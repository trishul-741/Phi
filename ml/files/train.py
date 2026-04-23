"""
Training loop for PhishGuardNet (v4).

v3 Changes (Anti-Overfitting):
  - FIX #1 (Data Leakage): create_dataloaders() returns selected_features internally.
  - FIX #3: Hard negative mining ratio increased to 0.5.
  - FIX #5: Label smoothing added to BCEWithLogitsLoss (epsilon=0.1).
  - FIX #7: Early stopping patience increased to 6.
  - Added: train/val gap monitoring.
  - Added: per-epoch weight norm tracking.

v4 Changes (GPU + correctness):
  - GPU info logging (device name, VRAM, AMP status) at startup.
  - LOW_VRAM_MODE banner printed when active.
  - Checkpoint paths use cfg.best_model_path / cfg.train_meta_path (no magic strings).
  - Progressive BERT unfreezing: layer 3 unfrozen at epoch 4, layer 2 at epoch 7.
    This gives BERT pretrained representations time to stabilise before the upper
    layers are allowed to fine-tune, reducing early-epoch overfitting.
  - Hard loss and full loss now tracked separately in the epoch log to make the
    discrepancy between optimizer target and monitored metric explicit.
  - GradScaler device string aligned with cfg.DEVICE for MPS/CPU compatibility.
"""

import os
import time
import logging
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.amp import autocast, GradScaler
from sklearn.metrics import roc_curve
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ml.config import cfg
from ml.preprocessing import build_dataframe
from ml.features import engineer_features
from ml.dataset import create_dataloaders
from ml.model import PhishGuardNet, count_parameters

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train")


# ══════════════════════════════════════════════════════════════════════
# Label-Smoothed BCE Loss
# ══════════════════════════════════════════════════════════════════════

class LabelSmoothingBCE(nn.Module):
    """
    Binary Cross-Entropy with label smoothing and optional pos_weight.

    WHY we removed AsymmetricLoss (gamma_neg=4):
    ──────────────────────────────────────────────
    AsymmetricLoss with gamma_neg=4 hyper-penalises easy NEGATIVE
    (legitimate) samples. In practice this gradient signal is dominated
    by the HARD negatives — legitimate sites that look suspicious.
    The model learns an extreme prior of "when in doubt, call it phishing",
    which is exactly the all-false-positive production behaviour we observe.

    Label smoothing (ε=0.1) already prevents overconfident predictions.
    pos_weight handles class imbalance.  Together they are sufficient and
    do not introduce directional bias.

    WHY we use ONE loss class for both train and val:
    ─────────────────────────────────────────────────
    Previously criterion (AsymmetricLoss) was used for val loss and
    criterion_none (plain BCE) for the train backward pass.  Optimising
    one objective while monitoring a *different* one means early stopping
    and checkpointing track the wrong signal.
    """

    def __init__(self, pos_weight: torch.Tensor = None,
                 smoothing: float = 0.1, reduction: str = "mean"):
        super().__init__()
        self.smoothing  = smoothing
        self.reduction  = reduction
        self.pos_weight = pos_weight

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        # Smooth: push labels away from hard 0/1
        targets_smooth = targets * (1 - self.smoothing) + 0.5 * self.smoothing
        loss = F.binary_cross_entropy_with_logits(
            logits, targets_smooth,
            pos_weight=self.pos_weight,
            reduction=self.reduction,
        )
        return loss


# ══════════════════════════════════════════════════════════════════════
# Early Stopping
# ══════════════════════════════════════════════════════════════════════

class EarlyStopping:
    """
    Monitor val loss; stop if no improvement for `patience` epochs.
    Patience=6 accounts for OneCycleLR's natural val loss fluctuations.
    """

    def __init__(self, patience: int = cfg.EARLY_STOP_PATIENCE, min_delta: float = 1e-4):
        self.patience    = patience
        self.min_delta   = min_delta
        self.counter     = 0
        self.best_loss   = float("inf")
        self.should_stop = False

    def __call__(self, val_loss: float) -> bool:
        if val_loss < self.best_loss - self.min_delta:
            self.best_loss = val_loss
            self.counter   = 0
        else:
            self.counter += 1
            if self.counter >= self.patience:
                self.should_stop = True
        return self.should_stop


# ══════════════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════════════

def save_checkpoint(model, optimizer, epoch, val_loss, optimal_threshold, path):
    torch.save({
        "epoch":                epoch,
        "model_state_dict":     model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "val_loss":             val_loss,
        "optimal_threshold":    optimal_threshold,
    }, path)
    logger.info(f"Checkpoint saved → {path}")


def compute_optimal_threshold(
    y_true: np.ndarray,
    y_probs: np.ndarray,
    max_fpr: float = 0.05,
) -> tuple:
    """
    Choose decision threshold via Youden's J within an FPR budget.

    FIX 1 — max_fpr raised from 0.005 → 0.05
    ──────────────────────────────────────────
    0.5% FPR was unreachable on most val sets. When unsatisfied, the code
    fell back to index 0 — the highest threshold on the ROC curve (~0.97),
    meaning the model almost never fired.  5% FPR is the standard operating
    point for URL/email phishing filters in production.

    FIX 2 — broken fallback replaced with best-J fallback
    ──────────────────────────────────────────────────────
    Previous fallback used index 0 (highest threshold). Now falls back to
    global Youden maximum — the statistically correct choice.

    FIX 3 — clip widened from (0.1, 0.95) → (0.25, 0.80)
    ───────────────────────────────────────────────────────
    Lower clip of 0.1 allowed aggressive thresholds that flagged everything.
    Upper clip of 0.80 prevents thresholds so high the model never fires.
    """
    fpr, tpr, thresholds = roc_curve(y_true, y_probs)
    j_scores   = tpr - fpr
    valid_mask = fpr <= max_fpr

    if valid_mask.any():
        best_idx = int(np.argmax(np.where(valid_mask, j_scores, -np.inf)))
    else:
        best_idx = int(np.argmax(j_scores))
        logger.warning(
            f"FPR budget {max_fpr:.1%} not achievable on val set; "
            f"using global Youden threshold (FPR={fpr[best_idx]:.3f})"
        )

    threshold = float(np.clip(thresholds[best_idx], 0.25, 0.80))
    return threshold, float(tpr[best_idx])


def _select_hard_samples(
    per_sample_loss: torch.Tensor,
    labels: torch.Tensor,
    ratio: float,
) -> torch.Tensor:
    """
    Mine hard samples symmetrically: top-ratio% hardest PHISHING and
    top-ratio% hardest LEGITIMATE samples are selected separately, then
    concatenated.

    WHY this matters
    ────────────────
    The original implementation selected the top-50% hardest samples
    regardless of class.  In an imbalanced dataset (more phishing than
    legitimate, or vice versa), the "hard" samples are dominated by one
    class — typically the hard-to-classify LEGITIMATE sites that look
    suspicious.  Repeatedly back-propping on those teaches the model an
    extreme paranoid prior: "every borderline site is phishing".

    Symmetric per-class mining keeps gradient contributions balanced and
    prevents the model from learning a directional bias.
    """
    selected = []
    for class_val in [0.0, 1.0]:
        mask = (labels >= 0.5) if class_val == 1.0 else (labels < 0.5)
        if mask.sum() == 0:
            continue
        k = max(1, int(mask.sum().item() * ratio))
        class_loss = per_sample_loss[mask]
        _, local_idx = torch.topk(class_loss, k)
        full_idx = torch.where(mask)[0][local_idx]
        selected.append(full_idx)
    if not selected:
        return torch.arange(len(labels), device=labels.device)
    return torch.cat(selected)
    """Track total L2 norm of model weights — rising norm = overfitting signal."""
    total = 0.0
    for p in model.parameters():
        if p.requires_grad:
            total += p.data.norm(2).item() ** 2
    return total ** 0.5


def log_gpu_info(device: torch.device):
    """Print GPU diagnostics at training startup."""
    if device.type == "cuda":
        props = torch.cuda.get_device_properties(0)
        vram_gb = props.total_memory / 1024 ** 3
        logger.info(f"GPU:       {props.name}")
        logger.info(f"VRAM:      {vram_gb:.1f} GB")
        logger.info(f"CUDA:      {torch.version.cuda}")
        logger.info(f"AMP:       {'enabled' if cfg.USE_AMP else 'disabled'}")
        if cfg.LOW_VRAM_MODE:
            logger.warning(
                f"LOW_VRAM_MODE active — BATCH_SIZE={cfg.BATCH_SIZE}, "
                f"MAX_TEXT_LENGTH={cfg.MAX_TEXT_LENGTH}"
            )
    else:
        logger.warning(f"Running on CPU — training will be very slow.")


def plot_training_curves(train_losses, val_losses, train_accs, val_accs,
                         thresholds, weight_norms):
    fig, axes = plt.subplots(1, 4, figsize=(26, 5))
    epochs_range = range(1, len(train_losses) + 1)

    axes[0].plot(epochs_range, train_losses, "o-", label="Train", color="#e74c3c")
    axes[0].plot(epochs_range, val_losses,   "o-", label="Val",   color="#2980b9")
    axes[0].set_title("Loss Curves", fontsize=14, fontweight="bold")
    axes[0].set_xlabel("Epoch"); axes[0].set_ylabel("Loss")
    axes[0].legend(); axes[0].grid(True, alpha=0.3)

    axes[1].plot(epochs_range, train_accs, "o-", label="Train", color="#e74c3c")
    axes[1].plot(epochs_range, val_accs,   "o-", label="Val",   color="#2980b9")
    axes[1].set_title("Accuracy Curves", fontsize=14, fontweight="bold")
    axes[1].set_xlabel("Epoch"); axes[1].set_ylabel("Accuracy")
    axes[1].legend(); axes[1].grid(True, alpha=0.3)

    axes[2].plot(epochs_range, thresholds, "o-", color="#27ae60", label="Optimal Threshold")
    axes[2].axhline(y=0.5, linestyle="--", color="gray", alpha=0.5, label="Default (0.5)")
    axes[2].set_title("Optimal Threshold (Youden's J)", fontsize=14, fontweight="bold")
    axes[2].set_xlabel("Epoch"); axes[2].set_ylabel("Threshold")
    axes[2].legend(); axes[2].grid(True, alpha=0.3)

    axes[3].plot(epochs_range, weight_norms, "o-", color="#8e44ad", label="Weight Norm")
    axes[3].set_title("Weight L2 Norm (Overfit Diagnostic)", fontsize=14, fontweight="bold")
    axes[3].set_xlabel("Epoch"); axes[3].set_ylabel("L2 Norm")
    axes[3].legend(); axes[3].grid(True, alpha=0.3)

    fig.tight_layout()
    path = os.path.join(cfg.CHECKPOINT_DIR, "training_curves.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Training curves saved → {path}")


# ══════════════════════════════════════════════════════════════════════
# Main Training Loop
# ══════════════════════════════════════════════════════════════════════

def train():
    print("DEBUG: Starting training function...")
    device = torch.device(cfg.DEVICE)
    
    print("DEBUG: Building dataframe...")
    df = build_dataframe()
    
    print("DEBUG: Engineering features...")
    df = engineer_features(df)
    device = torch.device(cfg.DEVICE)
    log_gpu_info(device)

    # ── Data Preparation ──────────────────────────────────────────────
    logger.info("Loading and preprocessing data...")
    df = build_dataframe()
    df = engineer_features(df)

    # create_dataloaders returns 5-tuple (always).
    train_loader, val_loader, scaler, pos_weight, selected_features = create_dataloaders(df)
    stat_feature_dim = len(selected_features)

    logger.info(f"Train batches: {len(train_loader)} | Val batches: {len(val_loader)}")
    logger.info(f"Using {stat_feature_dim} statistical features: {selected_features}")
    logger.info(f"Class pos_weight: {pos_weight.item():.4f}")

    # ── Model ─────────────────────────────────────────────────────────
    model      = PhishGuardNet(stat_feature_dim=stat_feature_dim).to(device)
    params_info = count_parameters(model)
    logger.info(f"Model — Total: {params_info['total']:,} | "
                f"Trainable: {params_info['trainable']:,} | "
                f"Frozen: {params_info['frozen']:,}")

    # ── Differential Learning Rates ───────────────────────────────────
    bert_params    = list(model.content_bert.bert.parameters())
    bert_param_ids = {id(p) for p in bert_params}
    head_params    = [p for p in model.parameters()
                      if id(p) not in bert_param_ids and p.requires_grad]
    trainable_bert = [p for p in bert_params if p.requires_grad]

    optimizer = torch.optim.AdamW([
        {"params": trainable_bert, "lr": cfg.BERT_LR},
        {"params": head_params,    "lr": cfg.HEAD_LR},
    ], weight_decay=cfg.WEIGHT_DECAY)

    # ── Unified Label-Smoothing BCE (train backward + val monitoring) ──
    # CRITICAL: both criterion and criterion_none use the SAME underlying
    # objective so early stopping and checkpointing track the correct signal.
    # pos_weight is moved to device here — it must match the labels tensor.
    criterion = LabelSmoothingBCE(
        pos_weight=pos_weight.to(device),
        smoothing=cfg.LABEL_SMOOTHING,
        reduction="mean",
    )
    criterion_none = LabelSmoothingBCE(
        pos_weight=pos_weight.to(device),
        smoothing=cfg.LABEL_SMOOTHING,
        reduction="none",
    )

    # ── Scheduler ─────────────────────────────────────────────────────
    total_steps = len(train_loader) * cfg.EPOCHS
    scheduler   = torch.optim.lr_scheduler.OneCycleLR(
        optimizer,
        max_lr=[cfg.BERT_LR * 10, cfg.HEAD_LR],
        total_steps=total_steps,
        pct_start=0.1,
        anneal_strategy="cos",
    )

    # ── AMP Scaler ────────────────────────────────────────────────────
    # Use "cuda" device string only when CUDA is available.
    amp_device  = "cuda" if device.type == "cuda" else "cpu"
    amp_scaler  = GradScaler(amp_device, enabled=cfg.USE_AMP)

    # ── Hard Negative Mining ──────────────────────────────────────────
    # HARD_NEG_RATIO now used as per-class ratio inside _select_hard_samples.
    # Reduced from 0.5 → cfg.HARD_NEG_RATIO (0.3 recommended in config).
    logger.info(f"Hard Sample Mining: top {cfg.HARD_NEG_RATIO*100:.0f}% "
                f"per class (symmetric pos+neg)")
    logger.info(f"Symmetric hard mining: {cfg.HARD_NEG_RATIO*100:.0f}% per class per batch")

    # ── Training State ────────────────────────────────────────────────
    early_stop     = EarlyStopping()
    best_val_loss  = float("inf")
    best_threshold = 0.5
    train_losses, val_losses = [], []
    train_accs, val_accs     = [], []
    epoch_thresholds         = []
    weight_norms             = []

    logger.info(f"\n{'='*65}")
    logger.info(f"  Starting training — {cfg.EPOCHS} epochs | BS={cfg.BATCH_SIZE} | "
                f"Dropout={cfg.DROPOUT} | LabelSmoothing={cfg.LABEL_SMOOTHING}")
    logger.info(f"  HardNegRatio={cfg.HARD_NEG_RATIO} | WeightDecay={cfg.WEIGHT_DECAY} | "
                f"Patience={cfg.EARLY_STOP_PATIENCE} | Device={device}")
    logger.info(f"{'='*65}\n")

    for epoch in range(1, cfg.EPOCHS + 1):
        epoch_start = time.time()

        # ── Progressive BERT Unfreezing ───────────────────────────────
        # Unfreeze upper BERT layers gradually so pretrained representations
        # stabilise before fine-tuning expands. Runs once per trigger epoch.
        if epoch == 4:
            model.content_bert.unfreeze_layer(cfg.BERT_FREEZE_LAYERS - 1)
            logger.info(f"Epoch {epoch}: Unfroze BERT layer {cfg.BERT_FREEZE_LAYERS - 1}")
        if epoch == 7:
            model.content_bert.unfreeze_layer(cfg.BERT_FREEZE_LAYERS - 2)
            logger.info(f"Epoch {epoch}: Unfroze BERT layer {cfg.BERT_FREEZE_LAYERS - 2}")

        # ── Train Phase ───────────────────────────────────────────────
        model.train()
        running_loss      = 0.0
        running_hard_loss = 0.0   # FIX: track optimizer target separately
        correct           = 0
        total             = 0

        for batch_idx, batch in enumerate(train_loader):
            input_ids      = batch["input_ids"].to(device, non_blocking=True)
            attention_mask = batch["attention_mask"].to(device, non_blocking=True)
            url_chars      = batch["url_chars"].to(device, non_blocking=True)
            stat_features  = batch["stat_features"].to(device, non_blocking=True)
            labels         = batch["label"].to(device, non_blocking=True)

            optimizer.zero_grad()

            with autocast(amp_device, enabled=cfg.USE_AMP):
                logits = model(input_ids, attention_mask, url_chars, stat_features).squeeze(1)

                # Per-sample loss for symmetric hard-sample selection
                per_sample_loss = criterion_none(logits, labels)

                # FIX: Mine hard positives and hard negatives separately.
                # Previously: top-50% regardless of class → dominated by
                # hard legitimate samples → trains the model to be paranoid.
                hard_idxs = _select_hard_samples(
                    per_sample_loss, labels, ratio=cfg.HARD_NEG_RATIO
                )
                hard_loss = per_sample_loss[hard_idxs].mean()

            amp_scaler.scale(hard_loss).backward()
            amp_scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=cfg.GRAD_CLIP_NORM)
            amp_scaler.step(optimizer)
            amp_scaler.update()
            scheduler.step()

            full_loss             = per_sample_loss.mean()
            running_loss         += full_loss.item() * labels.size(0)
            running_hard_loss    += hard_loss.item() * labels.size(0)

            with torch.no_grad():
                preds    = (torch.sigmoid(logits) >= 0.5).float()
                hard_lbl = (labels >= 0.5).float()
                correct += (preds == hard_lbl).sum().item()
                total   += labels.size(0)

            if (batch_idx + 1) % 50 == 0:
                logger.info(
                    f"  Epoch {epoch} | Batch {batch_idx+1}/{len(train_loader)} | "
                    f"Full Loss: {full_loss.item():.4f} | Hard Loss: {hard_loss.item():.4f}"
                )

        train_loss      = running_loss / total
        train_hard_loss = running_hard_loss / total   # what optimizer actually minimized
        train_acc       = correct / total
        train_losses.append(train_loss)
        train_accs.append(train_acc)

        # ── Validation Phase ──────────────────────────────────────────
        model.eval()
        val_running_loss = 0.0
        val_total        = 0
        all_val_labels   = []
        all_val_probs    = []

        with torch.no_grad():
            for batch in val_loader:
                input_ids      = batch["input_ids"].to(device, non_blocking=True)
                attention_mask = batch["attention_mask"].to(device, non_blocking=True)
                url_chars      = batch["url_chars"].to(device, non_blocking=True)
                stat_features  = batch["stat_features"].to(device, non_blocking=True)
                labels         = batch["label"].to(device, non_blocking=True)

                with autocast(amp_device, enabled=cfg.USE_AMP):
                    logits = model(input_ids, attention_mask, url_chars, stat_features).squeeze(1)
                    loss   = criterion(logits, labels)

                probs             = torch.sigmoid(logits)
                val_running_loss += loss.item() * labels.size(0)
                val_total        += labels.size(0)

                all_val_labels.extend(labels.cpu().numpy().tolist())
                all_val_probs.extend(probs.cpu().numpy().tolist())

        val_loss = val_running_loss / val_total
        val_losses.append(val_loss)

        # ── Youden's J: Optimal Threshold ─────────────────────────────
        y_true_np  = np.array(all_val_labels)
        y_probs_np = np.array(all_val_probs)

        optimal_threshold, j_stat = compute_optimal_threshold(y_true_np, y_probs_np)
        epoch_thresholds.append(optimal_threshold)

        val_preds       = (y_probs_np >= optimal_threshold).astype(float)
        val_acc         = float(np.mean(val_preds == (y_true_np >= 0.5).astype(float)))
        val_accs.append(val_acc)

        val_acc_default = float(np.mean(
            (y_probs_np >= 0.5).astype(float) == (y_true_np >= 0.5).astype(float)
        ))

        # ── Train/Val Gap Monitoring ──────────────────────────────────
        acc_gap  = train_acc - val_acc
        w_norm   = compute_weight_norm(model)
        weight_norms.append(w_norm)

        elapsed = time.time() - epoch_start
        logger.info(
            f"Epoch {epoch:>2}/{cfg.EPOCHS} | "
            f"Train Loss: {train_loss:.4f} (Hard: {train_hard_loss:.4f}) Acc: {train_acc:.4f} | "
            f"Val Loss: {val_loss:.4f} Acc@J: {val_acc:.4f} Acc@0.5: {val_acc_default:.4f} | "
            f"Threshold: {optimal_threshold:.4f} (J={j_stat:.4f}) | "
            f"Gap(Acc): {acc_gap:+.4f} | WNorm: {w_norm:.1f} | "
            f"Time: {elapsed:.1f}s"
        )

        if acc_gap > 0.05:
            logger.warning(
                f"  Overfit signal: train acc exceeds val acc by {acc_gap*100:.1f}%. "
                f"Consider increasing DROPOUT or WEIGHT_DECAY."
            )

        # ── Checkpoint best model ─────────────────────────────────────
        if val_loss < best_val_loss:
            best_val_loss  = val_loss
            best_threshold = optimal_threshold
            save_checkpoint(
                model, optimizer, epoch, val_loss, optimal_threshold,
                cfg.best_model_path,   # FIX: use config property, not magic string
            )

        # ── Early stopping ────────────────────────────────────────────
        if early_stop(val_loss):
            logger.info(
                f"Early stopping at epoch {epoch} "
                f"(patience={cfg.EARLY_STOP_PATIENCE}, best val loss={best_val_loss:.4f})"
            )
            break

    # ── Final Outputs ─────────────────────────────────────────────────
    plot_training_curves(
        train_losses, val_losses,
        train_accs, val_accs,
        epoch_thresholds, weight_norms,
    )

    torch.save({
        "selected_features": selected_features,
        "stat_feature_dim":  stat_feature_dim,
        "optimal_threshold": best_threshold,
    }, cfg.train_meta_path)   # FIX: use config property

    logger.info(f"\nTraining complete.")
    logger.info(f"   Best val loss:      {best_val_loss:.4f}")
    logger.info(f"   Optimal threshold:  {best_threshold:.4f}")
    logger.info(f"   Checkpoint:         {cfg.best_model_path}")

    return model


if __name__ == "__main__":
    train()

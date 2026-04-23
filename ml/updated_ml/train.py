"""
Training loop for the non-visual PhishGuard fusion classifier.

Key updates:
- saves scaler artifact for calibration / inference reuse
- metadata explicitly describes non-visual deployment path
- calibration split is held out from training and validation
"""

from __future__ import annotations

import logging
import os
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import classification_report, confusion_matrix, f1_score, fbeta_score, precision_score, recall_score
from torch.amp import GradScaler, autocast

from ml.config import cfg
from ml.dataset import create_dataloaders, save_scaler
from ml.features import engineer_features
from ml.model import PhishGuardNet, count_parameters
from ml.preprocessing import build_dataframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train")


class LabelSmoothingBCE(nn.Module):
    def __init__(self, pos_weight: torch.Tensor | None = None, smoothing: float = 0.1, reduction: str = "mean"):
        super().__init__()
        self.smoothing = smoothing
        self.reduction = reduction
        self.pos_weight = pos_weight

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        targets_smooth = targets * (1 - self.smoothing) + 0.5 * self.smoothing
        return F.binary_cross_entropy_with_logits(
            logits,
            targets_smooth,
            pos_weight=self.pos_weight,
            reduction=self.reduction,
        )


class EarlyStopping:
    def __init__(self, patience: int = cfg.EARLY_STOP_PATIENCE, min_delta: float = 1e-4):
        self.patience = patience
        self.min_delta = min_delta
        self.counter = 0
        self.best_score = -float("inf")
        self.should_stop = False

    def __call__(self, val_f2: float) -> bool:
        if val_f2 > self.best_score + self.min_delta:
            self.best_score = val_f2
            self.counter = 0
        else:
            self.counter += 1
            if self.counter >= self.patience:
                self.should_stop = True
        return self.should_stop


def save_checkpoint(model, optimizer, epoch, val_loss, optimal_threshold, path):
    torch.save(
        {
            "epoch": epoch,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "val_loss": val_loss,
            "optimal_threshold": optimal_threshold,
        },
        path,
    )


def compute_val_metrics(y_true: np.ndarray, y_probs: np.ndarray, threshold: float) -> dict:
    y_pred = (y_probs >= threshold).astype(int)
    y_bin = (y_true >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_bin, y_pred, labels=[0, 1]).ravel()
    prec = precision_score(y_bin, y_pred, zero_division=0.0)
    rec = recall_score(y_bin, y_pred, zero_division=0.0)
    f1 = f1_score(y_bin, y_pred, zero_division=0.0)
    f2 = fbeta_score(y_bin, y_pred, beta=2, zero_division=0.0)
    fpr = fp / max(fp + tn, 1)
    acc = (tp + tn) / max(tp + tn + fp + fn, 1)
    return {"precision": prec, "recall": rec, "f1": f1, "f2": f2, "fpr": fpr, "accuracy": acc,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn}


def search_optimal_threshold_fpr(
    y_true: np.ndarray,
    y_probs: np.ndarray,
    max_fpr: float = 0.03,
    sweep_start: float = 0.20,
    sweep_end: float = 0.70,
    sweep_step: float = 0.02,
) -> tuple[float, float, float]:
    y_bin = (y_true >= 0.5).astype(int)
    best_threshold = cfg.DECISION_THRESHOLD
    best_recall = 0.0
    best_fpr = 1.0

    for t in np.arange(sweep_start, sweep_end + sweep_step, sweep_step):
        y_pred = (y_probs >= t).astype(int)
        tn, fp, fn, tp = confusion_matrix(y_bin, y_pred, labels=[0, 1]).ravel()
        fpr_val = fp / max(fp + tn, 1)
        rec = tp / max(tp + fn, 1)
        if fpr_val <= max_fpr and rec > best_recall:
            best_threshold = float(t)
            best_recall = float(rec)
            best_fpr = float(fpr_val)

    if best_recall == 0.0:
        lowest_fpr = 1.0
        for t in np.arange(sweep_start, sweep_end + sweep_step, sweep_step):
            y_pred = (y_probs >= t).astype(int)
            tn, fp, fn, tp = confusion_matrix(y_bin, y_pred, labels=[0, 1]).ravel()
            fpr_val = fp / max(fp + tn, 1)
            rec = tp / max(tp + fn, 1)
            if fpr_val < lowest_fpr:
                lowest_fpr = fpr_val
                best_threshold = float(t)
                best_recall = float(rec)
                best_fpr = float(fpr_val)

    return best_threshold, best_recall, best_fpr


def _select_hard_samples(per_sample_loss: torch.Tensor, labels: torch.Tensor, ratio: float) -> torch.Tensor:
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
    return torch.cat(selected) if selected else torch.arange(len(labels), device=labels.device)


def compute_weight_norm(model: nn.Module) -> float:
    total = 0.0
    for p in model.parameters():
        if p.requires_grad:
            total += p.data.norm(2).item() ** 2
    return total ** 0.5


def plot_training_curves(train_losses, val_losses, train_accs, val_accs, thresholds, weight_norms):
    fig, axes = plt.subplots(1, 4, figsize=(26, 5))
    epochs = range(1, len(train_losses) + 1)
    plots = [
        (axes[0], train_losses, val_losses, "Loss Curves", "Loss"),
        (axes[1], train_accs, val_accs, "Accuracy Curves", "Accuracy"),
    ]
    for ax, a, b, title, ylabel in plots:
        ax.plot(epochs, a, "o-", label="Train")
        ax.plot(epochs, b, "o-", label="Val")
        ax.set_title(title)
        ax.set_xlabel("Epoch")
        ax.set_ylabel(ylabel)
        ax.legend()
        ax.grid(True, alpha=0.3)

    axes[2].plot(epochs, thresholds, "o-", label="Threshold")
    axes[2].axhline(y=0.5, linestyle="--", color="gray", alpha=0.5)
    axes[2].set_title("Optimal Threshold")
    axes[2].set_xlabel("Epoch")
    axes[2].set_ylabel("Threshold")
    axes[2].grid(True, alpha=0.3)

    axes[3].plot(epochs, weight_norms, "o-", label="Weight Norm")
    axes[3].set_title("Weight L2 Norm")
    axes[3].set_xlabel("Epoch")
    axes[3].set_ylabel("L2 Norm")
    axes[3].grid(True, alpha=0.3)

    fig.tight_layout()
    path = os.path.join(cfg.CHECKPOINT_DIR, "training_curves.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Training curves saved -> %s", path)


def train():
    device = torch.device(cfg.DEVICE)
    logger.info("Device: %s | AMP: %s", device, cfg.USE_AMP)

    df = engineer_features(build_dataframe())
    train_loader, val_loader, scaler, pos_weight, selected_features = create_dataloaders(df)
    save_scaler(scaler, cfg.scaler_path)
    stat_feature_dim = len(selected_features)
    logger.info("Saved scaler -> %s", cfg.scaler_path)
    logger.info("Selected %d statistical features", stat_feature_dim)

    # Reuse the class balance computed from the raw training split.
    # Deriving weights from the train loader would sample MixUp-softened labels,
    # which shifts the positive/negative ratio away from the real dataset.
    pos_weight_adjusted = (pos_weight / max(cfg.FP_PENALTY_WEIGHT, 1e-8)).clone().detach()
    logger.info(
        "Using train-split pos_weight %.4f adjusted to %.4f for FP control",
        float(pos_weight.item()),
        float(pos_weight_adjusted.item()),
    )

    model = PhishGuardNet(stat_feature_dim=stat_feature_dim).to(device)
    params_info = count_parameters(model)
    logger.info("Model params: %s", params_info)

    bert_layers = model.content_bert.bert.transformer.layer
    layers_0_to_2, layers_3_to_5 = [], []
    for i in range(3):
        layers_0_to_2.extend(list(bert_layers[i].parameters()))
    for i in range(3, min(6, len(bert_layers))):
        layers_3_to_5.extend(list(bert_layers[i].parameters()))

    bert_param_ids = {id(p) for p in model.content_bert.bert.parameters()}
    head_params = [p for p in model.parameters() if id(p) not in bert_param_ids and p.requires_grad]

    optimizer = torch.optim.AdamW(
        [
            {"params": layers_0_to_2, "lr": cfg.BERT_LR * 0.1},
            {"params": layers_3_to_5, "lr": cfg.BERT_LR * 0.3},
            {"params": head_params, "lr": cfg.HEAD_LR},
        ],
        weight_decay=cfg.WEIGHT_DECAY,
    )

    criterion = LabelSmoothingBCE(
        pos_weight=pos_weight_adjusted.to(device),
        smoothing=cfg.LABEL_SMOOTHING,
        reduction="mean",
    )
    criterion_none = LabelSmoothingBCE(
        pos_weight=pos_weight_adjusted.to(device),
        smoothing=cfg.LABEL_SMOOTHING,
        reduction="none",
    )

    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=0.5, patience=3, min_lr=1e-6
    )
    amp_device = "cuda" if device.type == "cuda" else "cpu"
    amp_scaler = GradScaler(amp_device, enabled=cfg.USE_AMP)
    early_stop = EarlyStopping()

    best_val_f2 = -float("inf")
    best_threshold = cfg.DECISION_THRESHOLD
    train_losses, val_losses, train_accs, val_accs, thresholds, weight_norms = [], [], [], [], [], []

    for epoch in range(1, cfg.EPOCHS + 1):
        start = time.time()
        model.train()
        running_loss = 0.0
        running_hard_loss = 0.0
        correct = 0
        total = 0

        for batch in train_loader:
            input_ids = batch["input_ids"].to(device, non_blocking=True)
            attention_mask = batch["attention_mask"].to(device, non_blocking=True)
            url_chars = batch["url_chars"].to(device, non_blocking=True)
            stat_features = batch["stat_features"].to(device, non_blocking=True)
            labels = batch["label"].to(device, non_blocking=True)

            optimizer.zero_grad()
            with autocast(amp_device, enabled=cfg.USE_AMP):
                logits = model(input_ids, attention_mask, url_chars, stat_features).squeeze(1)
                per_sample_loss = criterion_none(logits, labels)
                hard_idxs = _select_hard_samples(per_sample_loss, labels, ratio=cfg.HARD_NEG_RATIO)
                hard_loss = per_sample_loss[hard_idxs].mean()

            amp_scaler.scale(hard_loss).backward()
            amp_scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            amp_scaler.step(optimizer)
            amp_scaler.update()

            full_loss = per_sample_loss.mean()
            running_loss += full_loss.item() * labels.size(0)
            running_hard_loss += hard_loss.item() * labels.size(0)

            with torch.no_grad():
                preds = (torch.sigmoid(logits) >= 0.5).float()
                hard_lbl = (labels >= 0.5).float()
                correct += (preds == hard_lbl).sum().item()
                total += labels.size(0)

        train_loss = running_loss / max(total, 1)
        train_acc = correct / max(total, 1)
        train_losses.append(train_loss)
        train_accs.append(train_acc)

        model.eval()
        val_running_loss = 0.0
        val_total = 0
        all_val_labels, all_val_probs = [], []

        with torch.no_grad():
            for batch in val_loader:
                input_ids = batch["input_ids"].to(device, non_blocking=True)
                attention_mask = batch["attention_mask"].to(device, non_blocking=True)
                url_chars = batch["url_chars"].to(device, non_blocking=True)
                stat_features = batch["stat_features"].to(device, non_blocking=True)
                labels = batch["label"].to(device, non_blocking=True)

                with autocast(amp_device, enabled=cfg.USE_AMP):
                    logits = model(input_ids, attention_mask, url_chars, stat_features).squeeze(1)
                    loss = criterion(logits, labels)

                probs = torch.sigmoid(logits)
                val_running_loss += loss.item() * labels.size(0)
                val_total += labels.size(0)
                all_val_labels.extend(labels.cpu().numpy().tolist())
                all_val_probs.extend(probs.cpu().numpy().tolist())

        y_true_np = np.array(all_val_labels)
        y_probs_np = np.array(all_val_probs)
        val_loss = val_running_loss / max(val_total, 1)
        threshold, sweep_recall, sweep_fpr = search_optimal_threshold_fpr(y_true_np, y_probs_np, max_fpr=0.03)
        metrics = compute_val_metrics(y_true_np, y_probs_np, threshold)

        scheduler.step(metrics["f2"])
        train_losses.append(train_loss) if False else None
        val_losses.append(val_loss)
        val_accs.append(metrics["accuracy"])
        thresholds.append(threshold)
        weight_norms.append(compute_weight_norm(model))

        logger.info(
            "Epoch %02d | Train loss %.4f acc %.4f | Val loss %.4f | P %.4f R %.4f F1 %.4f F2 %.4f FPR %.4f | Th %.4f | time %.1fs",
            epoch, train_loss, train_acc, val_loss, metrics["precision"], metrics["recall"],
            metrics["f1"], metrics["f2"], metrics["fpr"], threshold, time.time() - start,
        )

        if metrics["f2"] > best_val_f2:
            best_val_f2 = metrics["f2"]
            best_threshold = threshold
            save_checkpoint(model, optimizer, epoch, val_loss, threshold, cfg.best_model_path)
            logger.info("Saved best checkpoint -> %s", cfg.best_model_path)

        if early_stop(metrics["f2"]):
            logger.info("Early stopping triggered at epoch %d", epoch)
            break

    plot_training_curves(train_losses[:len(val_losses)], val_losses, train_accs[:len(val_accs)], val_accs, thresholds, weight_norms)

    torch.save(
        {
            "selected_features": selected_features,
            "stat_feature_dim": stat_feature_dim,
            "optimal_threshold": best_threshold,
            "best_val_f2": best_val_f2,
            "decision_threshold": cfg.DECISION_THRESHOLD,
            "fp_penalty_weight": cfg.FP_PENALTY_WEIGHT,
            "scaler_path": cfg.scaler_path,
            "architecture": "non_visual_multimodal_fusion",
        },
        cfg.train_meta_path,
    )

    report = classification_report(
        (y_true_np >= 0.5).astype(int),
        (y_probs_np >= best_threshold).astype(int),
        target_names=["legitimate", "phishing"],
        digits=4,
    )
    logger.info("Final classification report @ threshold %.4f\n%s", best_threshold, report)
    print(report)
    return model


if __name__ == "__main__":
    train()

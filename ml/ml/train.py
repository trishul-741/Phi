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
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    fbeta_score,
    precision_score,
    recall_score,
)
from torch.amp import GradScaler, autocast

from ml.config import cfg
from ml.dataset import create_dataloaders, save_scaler
from ml.features import engineer_features
from ml.model import PhishGuardNet, count_parameters
from ml.preprocessing import build_dataframe


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train")


def get_base_model(model: nn.Module) -> nn.Module:
    """Return original model if wrapped with DataParallel."""
    return model.module if isinstance(model, nn.DataParallel) else model


def log_gpu_info():
    logger.info("=" * 70)
    logger.info("GPU / DEVICE CHECK")
    logger.info("=" * 70)

    logger.info("cfg.DEVICE: %s", cfg.DEVICE)
    logger.info("CUDA available: %s", torch.cuda.is_available())
    logger.info("CUDA device count: %d", torch.cuda.device_count())

    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            logger.info(
                "GPU %d: %s | VRAM: %.2f GB",
                i,
                torch.cuda.get_device_name(i),
                props.total_memory / (1024 ** 3),
            )

        if torch.cuda.device_count() >= 2:
            logger.info("T4 x2 / Multi-GPU detected. DataParallel will be enabled.")
        else:
            logger.warning("Only 1 GPU detected. Training will use single GPU.")
    else:
        logger.warning("No CUDA GPU detected. Training will run on CPU and will be slow.")

    logger.info("AMP enabled: %s", cfg.USE_AMP)
    logger.info("=" * 70)


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
    os.makedirs(os.path.dirname(path), exist_ok=True)

    base_model = get_base_model(model)

    torch.save(
        {
            "epoch": epoch,
            "model_state_dict": base_model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "val_loss": val_loss,
            "optimal_threshold": optimal_threshold,
            "multi_gpu_used": isinstance(model, nn.DataParallel),
            "gpu_count": torch.cuda.device_count(),
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

    return {
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "f2": f2,
        "fpr": fpr,
        "accuracy": acc,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
    }


def search_optimal_threshold_fpr(
    y_true: np.ndarray,
    y_probs: np.ndarray,
    max_fpr: float = 0.005,
    sweep_start: float = 0.20,
    sweep_end: float = 0.95,
    sweep_step: float = 0.01,
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


def compute_weight_norm(model: nn.Module) -> float:
    base_model = get_base_model(model)

    total = 0.0
    for p in base_model.parameters():
        if p.requires_grad:
            total += p.data.norm(2).item() ** 2

    return total ** 0.5


def plot_training_curves(
    train_losses,
    val_losses,
    train_accs,
    val_accs,
    thresholds,
    weight_norms,
):
    fig, axes = plt.subplots(1, 4, figsize=(26, 5))
    epochs = range(1, len(train_losses) + 1)

    axes[0].plot(epochs, train_losses, "o-", label="Train")
    axes[0].plot(epochs, val_losses, "o-", label="Val")
    axes[0].set_title("Loss Curves")
    axes[0].set_xlabel("Epoch")
    axes[0].set_ylabel("Loss")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(epochs, train_accs, "o-", label="Train")
    axes[1].plot(epochs, val_accs, "o-", label="Val")
    axes[1].set_title("Accuracy Curves")
    axes[1].set_xlabel("Epoch")
    axes[1].set_ylabel("Accuracy")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

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

    os.makedirs(cfg.CHECKPOINT_DIR, exist_ok=True)
    path = os.path.join(cfg.CHECKPOINT_DIR, "training_curves.png")

    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    logger.info("Training curves saved -> %s", path)


def train():
    log_gpu_info()

    device = torch.device(cfg.DEVICE)
    amp_device = "cuda" if device.type == "cuda" else "cpu"

    logger.info("Loading and engineering dataset...")
    df = engineer_features(build_dataframe())

    logger.info("Creating dataloaders...")
    train_loader, val_loader, scaler, pos_weight, selected_features = create_dataloaders(df)

    os.makedirs(cfg.CHECKPOINT_DIR, exist_ok=True)

    save_scaler(scaler, cfg.scaler_path)
    logger.info("Saved scaler -> %s", cfg.scaler_path)

    stat_feature_dim = len(selected_features)
    logger.info("Selected %d statistical features", stat_feature_dim)
    logger.info("Selected features: %s", selected_features)

    pos_weight_adjusted = pos_weight.clone().detach().to(device)
    logger.info("Using class pos_weight: %.4f", float(pos_weight_adjusted.item()))

    logger.info("Building model...")
    model = PhishGuardNet(stat_feature_dim=stat_feature_dim).to(device)

    params_info = count_parameters(model)
    logger.info("Model params before DataParallel: %s", params_info)

    use_multi_gpu = torch.cuda.is_available() and torch.cuda.device_count() > 1

    if use_multi_gpu:
        logger.info("Wrapping model with torch.nn.DataParallel for %d GPUs", torch.cuda.device_count())
        model = torch.nn.DataParallel(model)
    else:
        logger.info("DataParallel not enabled.")

    base_model = get_base_model(model)

    bert_layers = base_model.content_bert.bert.transformer.layer

    layers_0_to_2 = []
    layers_3_to_5 = []

    for i in range(min(3, len(bert_layers))):
        layers_0_to_2.extend(list(bert_layers[i].parameters()))

    for i in range(3, min(6, len(bert_layers))):
        layers_3_to_5.extend(list(bert_layers[i].parameters()))

    bert_param_ids = {id(p) for p in base_model.content_bert.bert.parameters()}

    head_params = [
        p for p in base_model.parameters()
        if id(p) not in bert_param_ids and p.requires_grad
    ]

    layers_0_to_2 = [p for p in layers_0_to_2 if p.requires_grad]
    layers_3_to_5 = [p for p in layers_3_to_5 if p.requires_grad]

    param_groups = []

    if layers_0_to_2:
        param_groups.append({"params": layers_0_to_2, "lr": cfg.BERT_LR * 0.1})

    if layers_3_to_5:
        param_groups.append({"params": layers_3_to_5, "lr": cfg.BERT_LR * 0.3})

    if head_params:
        param_groups.append({"params": head_params, "lr": cfg.HEAD_LR})

    if not param_groups:
        raise RuntimeError("No trainable parameters found. Check model freezing settings.")

    optimizer = torch.optim.AdamW(param_groups, weight_decay=cfg.WEIGHT_DECAY)

    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight_adjusted)

    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="max",
        factor=0.5,
        patience=3,
        min_lr=1e-6,
    )

    amp_scaler = GradScaler(amp_device, enabled=cfg.USE_AMP)
    early_stop = EarlyStopping()

    best_val_f2 = -float("inf")
    best_threshold = cfg.DECISION_THRESHOLD

    train_losses = []
    val_losses = []
    train_accs = []
    val_accs = []
    thresholds = []
    weight_norms = []

    last_y_true_np = None
    last_y_probs_np = None

    logger.info("=" * 70)
    logger.info("STARTING TRAINING")
    logger.info("Epochs: %d | Batch size: %d | Device: %s", cfg.EPOCHS, cfg.BATCH_SIZE, device)
    logger.info("=" * 70)

    for epoch in range(1, cfg.EPOCHS + 1):
        start = time.time()

        model.train()

        running_loss = 0.0
        correct = 0
        total = 0

        for batch_idx, batch in enumerate(train_loader):
            input_ids = batch["input_ids"].to(device, non_blocking=True)
            attention_mask = batch["attention_mask"].to(device, non_blocking=True)
            url_chars = batch["url_chars"].to(device, non_blocking=True)
            stat_features = batch["stat_features"].to(device, non_blocking=True)

            labels = batch["label"].to(device, non_blocking=True).view(-1)

            optimizer.zero_grad(set_to_none=True)

            with autocast(amp_device, enabled=cfg.USE_AMP):
                logits = model(input_ids, attention_mask, url_chars, stat_features).view(-1)
                loss = criterion(logits, labels)

            amp_scaler.scale(loss).backward()
            amp_scaler.unscale_(optimizer)

            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)

            amp_scaler.step(optimizer)
            amp_scaler.update()

            running_loss += loss.item() * labels.size(0)

            with torch.no_grad():
                preds = (torch.sigmoid(logits) >= 0.5).float()
                hard_lbl = (labels >= 0.5).float()

                correct += (preds == hard_lbl).sum().item()
                total += labels.size(0)

            if (batch_idx + 1) % 50 == 0:
                logger.info(
                    "Epoch %02d | Batch %04d/%04d | Loss %.4f",
                    epoch,
                    batch_idx + 1,
                    len(train_loader),
                    loss.item(),
                )

        train_loss = running_loss / max(total, 1)
        train_acc = correct / max(total, 1)

        train_losses.append(train_loss)
        train_accs.append(train_acc)

        model.eval()

        val_running_loss = 0.0
        val_total = 0
        all_val_labels = []
        all_val_probs = []

        with torch.no_grad():
            for batch in val_loader:
                input_ids = batch["input_ids"].to(device, non_blocking=True)
                attention_mask = batch["attention_mask"].to(device, non_blocking=True)
                url_chars = batch["url_chars"].to(device, non_blocking=True)
                stat_features = batch["stat_features"].to(device, non_blocking=True)

                labels = batch["label"].to(device, non_blocking=True).view(-1)

                with autocast(amp_device, enabled=cfg.USE_AMP):
                    logits = model(input_ids, attention_mask, url_chars, stat_features).view(-1)
                    loss = criterion(logits, labels)

                probs = torch.sigmoid(logits)

                val_running_loss += loss.item() * labels.size(0)
                val_total += labels.size(0)

                all_val_labels.extend(labels.detach().cpu().numpy().tolist())
                all_val_probs.extend(probs.detach().cpu().numpy().tolist())

        y_true_np = np.array(all_val_labels)
        y_probs_np = np.array(all_val_probs)

        last_y_true_np = y_true_np
        last_y_probs_np = y_probs_np

        val_loss = val_running_loss / max(val_total, 1)

        threshold, sweep_recall, sweep_fpr = search_optimal_threshold_fpr(
            y_true_np,
            y_probs_np,
            max_fpr=0.005,
        )

        metrics = compute_val_metrics(y_true_np, y_probs_np, threshold)

        scheduler.step(metrics["f2"])

        val_losses.append(val_loss)
        val_accs.append(metrics["accuracy"])
        thresholds.append(threshold)
        weight_norms.append(compute_weight_norm(model))

        elapsed = time.time() - start

        logger.info(
            "Epoch %02d | Train loss %.4f acc %.4f | Val loss %.4f | "
            "P %.4f R %.4f F1 %.4f F2 %.4f FPR %.4f | "
            "Th %.4f | SweepRecall %.4f SweepFPR %.4f | Time %.1fs",
            epoch,
            train_loss,
            train_acc,
            val_loss,
            metrics["precision"],
            metrics["recall"],
            metrics["f1"],
            metrics["f2"],
            metrics["fpr"],
            threshold,
            sweep_recall,
            sweep_fpr,
            elapsed,
        )

        if metrics["f2"] > best_val_f2:
            best_val_f2 = metrics["f2"]
            best_threshold = threshold

            save_checkpoint(
                model,
                optimizer,
                epoch,
                val_loss,
                threshold,
                cfg.best_model_path,
            )

            logger.info("Saved best checkpoint -> %s", cfg.best_model_path)

        if early_stop(metrics["f2"]):
            logger.info("Early stopping triggered at epoch %d", epoch)
            break

    plot_training_curves(
        train_losses[: len(val_losses)],
        val_losses,
        train_accs[: len(val_accs)],
        val_accs,
        thresholds,
        weight_norms,
    )

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
            "multi_gpu_used": use_multi_gpu,
            "gpu_count": torch.cuda.device_count(),
        },
        cfg.train_meta_path,
    )

    logger.info("Saved training metadata -> %s", cfg.train_meta_path)

    if last_y_true_np is not None and last_y_probs_np is not None:
        report = classification_report(
            (last_y_true_np >= 0.5).astype(int),
            (last_y_probs_np >= best_threshold).astype(int),
            target_names=["legitimate", "phishing"],
            digits=4,
        )

        logger.info("Final classification report @ threshold %.4f\n%s", best_threshold, report)
        print(report)

    logger.info("=" * 70)
    logger.info("TRAINING COMPLETE")
    logger.info("Best F2: %.4f | Best threshold: %.4f", best_val_f2, best_threshold)
    logger.info("Best checkpoint: %s", cfg.best_model_path)
    logger.info("=" * 70)

    return model


if __name__ == "__main__":
    train()
"""
Evaluation for the non-visual PhishGuard model.

Uses:
- train-time selected features
- saved scaler artifact
- validation split only (calibration holdout excluded)
"""

from __future__ import annotations

import os
import logging

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import torch
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score, roc_curve
from torch.amp import autocast
from transformers import DistilBertTokenizer

from ml.config import cfg
from ml.dataset import PhishingMultiModalDataset, default_collate_fn, load_scaler, split_dataframe
from ml.features import engineer_features
from ml.model import PhishGuardNet
from ml.preprocessing import build_dataframe
from torch.utils.data import DataLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("evaluate")
sns.set_theme(style="whitegrid", font_scale=1.1)
_AMP_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def load_model(checkpoint_path: str, stat_feature_dim: int) -> PhishGuardNet:
    device = torch.device(cfg.DEVICE)
    model = PhishGuardNet(stat_feature_dim=stat_feature_dim).to(device)
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    logger.info("Loaded checkpoint from epoch %s", checkpoint["epoch"])
    return model


def build_val_loader(df, selected_features):
    _, val_df, _ = split_dataframe(df)
    tokenizer = DistilBertTokenizer.from_pretrained(cfg.BERT_MODEL)
    scaler = load_scaler(cfg.scaler_path)
    dataset = PhishingMultiModalDataset(val_df, selected_features, scaler, tokenizer, cfg.char_dict, is_train=False)
    return DataLoader(
        dataset,
        batch_size=cfg.BATCH_SIZE,
        shuffle=False,
        num_workers=cfg.NUM_WORKERS,
        persistent_workers=(cfg.NUM_WORKERS > 0),
        pin_memory=cfg.PIN_MEMORY,
        collate_fn=default_collate_fn,
    )


def run_inference(model, val_loader):
    device = torch.device(cfg.DEVICE)
    model.eval()
    all_labels, all_probs = [], []
    with torch.no_grad():
        for batch in val_loader:
            ids = batch["input_ids"].to(device, non_blocking=True)
            mask = batch["attention_mask"].to(device, non_blocking=True)
            chars = batch["url_chars"].to(device, non_blocking=True)
            stats = batch["stat_features"].to(device, non_blocking=True)
            labels = batch["label"]
            with autocast(_AMP_DEVICE, enabled=cfg.USE_AMP):
                logits = model(ids, mask, chars, stats).squeeze(1)
            all_probs.extend(torch.sigmoid(logits).cpu().numpy().tolist())
            all_labels.extend(labels.numpy().tolist())
    return np.array(all_labels), np.array(all_probs)


def plot_confusion_matrix(y_true, y_pred):
    cm = confusion_matrix(y_true, y_pred)
    fig, ax = plt.subplots(figsize=(7, 6))
    sns.heatmap(cm, annot=True, fmt=",d", cmap="Blues", xticklabels=["Legitimate", "Phishing"],
                yticklabels=["Legitimate", "Phishing"], ax=ax, linewidths=0.5)
    ax.set_title("Confusion Matrix")
    path = os.path.join(cfg.EVAL_DIR, "confusion_matrix.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_roc_curve(y_true, y_probs):
    fpr, tpr, _ = roc_curve(y_true, y_probs)
    auc = roc_auc_score(y_true, y_probs)
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.plot(fpr, tpr, linewidth=2.5, label=f"AUC={auc:.4f}")
    ax.plot([0, 1], [0, 1], "k--", alpha=0.4)
    ax.legend(loc="lower right")
    path = os.path.join(cfg.EVAL_DIR, "roc_curve.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return auc


def evaluate():
    meta = torch.load(cfg.train_meta_path, weights_only=False)
    selected_features = meta["selected_features"]
    stat_feature_dim = meta["stat_feature_dim"]
    optimal_threshold = meta.get("optimal_threshold", cfg.DECISION_THRESHOLD)

    df = engineer_features(build_dataframe())
    val_loader = build_val_loader(df, selected_features)
    model = load_model(cfg.best_model_path, stat_feature_dim)
    y_true, y_probs = run_inference(model, val_loader)
    y_pred = (y_probs >= optimal_threshold).astype(int)

    acc = accuracy_score(y_true, y_pred)
    prec = precision_score(y_true, y_pred, zero_division=0)
    rec = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    auc = roc_auc_score(y_true, y_probs)

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    fpr_metric = fp / (fp + tn + 1e-8)
    fnr_metric = fn / (fn + tp + 1e-8)

    print(f"Threshold: {optimal_threshold:.4f}")
    print(f"Accuracy: {acc:.4f}")
    print(f"Precision: {prec:.4f}")
    print(f"Recall: {rec:.4f}")
    print(f"F1: {f1:.4f}")
    print(f"AUC: {auc:.4f}")
    print(f"FPR: {fpr_metric:.4f}")
    print(f"FNR: {fnr_metric:.4f}\n")
    print(classification_report(y_true, y_pred, target_names=["Legitimate", "Phishing"]))

    plot_confusion_matrix(y_true, y_pred)
    plot_roc_curve(y_true, y_probs)


if __name__ == "__main__":
    evaluate()

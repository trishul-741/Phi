"""
Rigorous evaluation module for PhishGuardNet (v4).

v4 Fixes (all were runtime crashes or incorrect measurements):

  FIX 1 — 5-tuple unpack:
    create_dataloaders() returns 5 values in v3+.
    Original code unpacked only 4, causing a ValueError at runtime.

  FIX 2 — AMP autocast in inference:
    The model was trained with AMP (float16 activations). Running inference
    without autocast causes a dtype mismatch crash on CUDA. Wrapped inference
    call with the same autocast context used in train.py and evaluate.py.

  FIX 3 — Accurate latency via cuda.synchronize():
    CUDA kernels are dispatched asynchronously. Without synchronize() before
    stopping the timer, perf_counter() measures kernel dispatch time only —
    10-20x lower than actual GPU computation time. Latency is now gated with
    synchronize() on both sides of the timed region.

  FIX 4 — Checkpoint/meta paths via cfg properties:
    Replaced hardcoded "best_model.pt" / "train_meta.pt" strings with
    cfg.best_model_path and cfg.train_meta_path.

  FIX 5 — AMP device string:
    "cuda" was hardcoded as the autocast device. Now uses _AMP_DEVICE
    derived from cfg.DEVICE so it works on CPU/MPS fallback without errors.
"""

import os
import time
import numpy as np
import torch
from torch.amp import autocast
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score, roc_curve
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from ml.model import PhishGuardNet
from ml.config import cfg
from ml.preprocessing import build_dataframe
from ml.features import engineer_features
from ml.dataset import create_dataloaders

# AMP device string — must match train.py
_AMP_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def plot_confusion_matrix(y_true, y_pred):
    cm = confusion_matrix(y_true, y_pred)
    plt.figure(figsize=(8, 6))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues",
                xticklabels=["Legitimate", "Phishing"],
                yticklabels=["Legitimate", "Phishing"])
    plt.ylabel("Actual")
    plt.xlabel("Predicted")
    plt.title("PhishGuard Confusion Matrix (Rigorous)")
    out_path = os.path.join(cfg.EVAL_DIR, "confusion_matrix_rigorous.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[Testing] Saved {out_path}")


def plot_roc_curve(y_true, y_probs):
    fpr, tpr, _ = roc_curve(y_true, y_probs)
    auc = roc_auc_score(y_true, y_probs)
    plt.figure(figsize=(8, 6))
    plt.plot(fpr, tpr, label=f"ROC Curve (AUC = {auc:.4f})", color="darkorange", lw=2)
    plt.plot([0, 1], [0, 1], color="navy", lw=2, linestyle="--")
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.title("Receiver Operating Characteristic (Rigorous)")
    plt.legend(loc="lower right")
    out_path = os.path.join(cfg.EVAL_DIR, "roc_curve_rigorous.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[Testing] Saved {out_path}")


def rigorous_evaluation():
    device = torch.device(cfg.DEVICE)
    print(f"[Testing] Running rigorous evaluation on {device}...")

    # ── Load training metadata ────────────────────────────────────────
    if not os.path.exists(cfg.train_meta_path):
        raise FileNotFoundError(
            f"train_meta.pt not found at {cfg.train_meta_path}. Run train.py first."
        )

    meta = torch.load(cfg.train_meta_path, map_location=device, weights_only=False)
    selected_features = meta["selected_features"]
    stat_feature_dim  = meta["stat_feature_dim"]
    optimal_threshold = meta.get("optimal_threshold", 0.5)
    print(f"[Testing] Using optimal threshold: {optimal_threshold:.4f} (from saved training/calibration metadata)")

    # ── Load model ────────────────────────────────────────────────────
    if not os.path.exists(cfg.best_model_path):
        raise FileNotFoundError(
            f"best_model.pt not found at {cfg.best_model_path}. Run train.py first."
        )

    model = PhishGuardNet(stat_feature_dim=stat_feature_dim).to(device)
    checkpoint = torch.load(cfg.best_model_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    # ── Build validation loader ───────────────────────────────────────
    print("[Testing] Loading validation dataset from core pipeline...")
    df = build_dataframe()
    df = engineer_features(df)

    # FIX 1: create_dataloaders returns 5 values — must unpack all 5.
    # Original code unpacked 4 → ValueError at runtime.
    _, val_loader, _, _, _ = create_dataloaders(df, feature_names=selected_features)

    y_true  = []
    y_pred  = []
    y_probs = []
    latencies = []

    print("[Testing] Commencing bulk inference...")
    with torch.no_grad():
        for batch in val_loader:
            input_ids      = batch["input_ids"].to(device, non_blocking=True)
            attention_mask = batch["attention_mask"].to(device, non_blocking=True)
            url_chars      = batch["url_chars"].to(device, non_blocking=True)
            stat_features  = batch["stat_features"].to(device, non_blocking=True)
            labels         = batch["label"].to(device)

            # FIX 3: cuda.synchronize() gates the timer on both sides.
            # Without it, CUDA's async dispatch means perf_counter() measures
            # kernel launch time only — giving 10-20x underestimates on GPU.
            if device.type == "cuda":
                torch.cuda.synchronize()
            start_time = time.perf_counter()

            # FIX 2: wrap inference with the same autocast context used in training.
            # Without this, AMP-trained models crash with a dtype mismatch on CUDA.
            with autocast(_AMP_DEVICE, enabled=cfg.USE_AMP):
                outputs = model(input_ids, attention_mask, url_chars, stat_features)

            if device.type == "cuda":
                torch.cuda.synchronize()
            end_time = time.perf_counter()

            # Per-URL latency in milliseconds
            batch_latency = ((end_time - start_time) / input_ids.size(0)) * 1000
            latencies.append(batch_latency)

            probs = torch.sigmoid(outputs).squeeze(1).cpu().numpy()
            preds = (probs > optimal_threshold).astype(int)

            y_probs.extend(probs.tolist())
            y_pred.extend(preds.tolist())
            y_true.extend(labels.cpu().numpy().tolist())

    # ── 1. Statistical Report ─────────────────────────────────────────
    print("\n" + "=" * 55)
    print("        STATISTICAL PERFORMANCE REPORT")
    print("=" * 55)
    print(classification_report(y_true, y_pred,
                                target_names=["Legitimate", "Phishing"], digits=4))

    auc_score = roc_auc_score(y_true, y_probs)
    print(f"ROC-AUC Score: {auc_score:.4f}")

    # ── 2. Security Metrics ───────────────────────────────────────────
    cm = confusion_matrix(y_true, y_pred)
    tn, fp, fn, tp = cm.ravel()

    false_positive_rate = fp / (fp + tn + 1e-8)
    false_negative_rate = fn / (fn + tp + 1e-8)

    print("\n" + "=" * 55)
    print("        CRITICAL SECURITY METRICS")
    print("=" * 55)
    print(f"False Positive Rate (Blocked Safe Sites): {false_positive_rate*100:.2f}%")
    print(f"False Negative Rate (Missed Attacks):     {false_negative_rate*100:.2f}%")

    if false_negative_rate > 0.05:
        print("WARNING: High FNR — model is letting too many threats through.")
    if false_positive_rate > 0.05:
        print("WARNING: High FPR — users will experience alert fatigue.")

    # ── 3. Latency Metrics ────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("        LATENCY & THROUGHPUT")
    print("        (inference only — network/crawler excluded)")
    print("=" * 55)
    avg_latency = np.mean(latencies)
    p50_latency = np.percentile(latencies, 50)
    p95_latency = np.percentile(latencies, 95)
    p99_latency = np.percentile(latencies, 99)

    print(f"Average latency per URL:   {avg_latency:.2f} ms")
    print(f"p50 latency:               {p50_latency:.2f} ms")
    print(f"p95 latency:               {p95_latency:.2f} ms")
    print(f"p99 latency:               {p99_latency:.2f} ms")
    print(f"Device:                    {device} | AMP: {cfg.USE_AMP}")

    if avg_latency > 100:
        print("WARNING: Inference is slow. Consider ONNX export or TorchScript for production.")

    # ── Visuals ───────────────────────────────────────────────────────
    plot_confusion_matrix(y_true, y_pred)
    plot_roc_curve(y_true, y_probs)
    print("\n[Testing] Rigorous evaluation complete.")


if __name__ == "__main__":
    rigorous_evaluation()

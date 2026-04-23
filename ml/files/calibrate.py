"""
Post-training production calibration for PhishGuard (v5).

WHY calibration is mandatory for a phishing detector
─────────────────────────────────────────────────────
The model is trained and threshold-tuned on a dataset where ~50% of samples
are phishing (balanced or near-balanced splits).  Real-world web traffic is
overwhelmingly legitimate — typically 95–99% of URLs seen in production are
benign.  A threshold calibrated at 50/50 base rate will generate catastrophic
false positive rates when deployed against 98% legitimate traffic.

This is not a model quality problem — it is a base rate mismatch.  Even a
perfect 99% accurate model calibrated at 50/50 will flag ~50% of legitimate
pages when the real base rate is 2% phishing.

This module provides two calibration approaches:
  1. Empirical threshold search on a production-representative holdout set.
     Recommended when you have ≥500 labelled production samples.
  2. Platt scaling — fits a logistic regression on the model's raw logits
     to produce calibrated probabilities.  Use when your holdout is small
     (~100–500 samples) or you want reliable probability estimates, not just
     a better threshold.

Usage
─────
    # After training, collect a production-representative sample:
    python -m ml.calibrate \
        --holdout-dir  ./data/production_holdout \
        --checkpoint   ./ml/outputs/checkpoints/best_model.pt \
        --meta         ./ml/outputs/checkpoints/train_meta.pt \
        --method       threshold \
        --target-fpr   0.01

    # The calibrated threshold is written back into train_meta.pt so
    # the inference pipeline picks it up automatically.
"""

import os
import argparse
import logging
import json
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from sklearn.metrics import roc_curve, precision_recall_curve, classification_report
from sklearn.linear_model import LogisticRegression
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ml.config import cfg
from ml.preprocessing import build_dataframe
from ml.features import engineer_features
from ml.dataset import PhishingMultiModalDataset, default_collate_fn, _tokenize_smart
from ml.model import PhishGuardNet

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("calibrate")


# ══════════════════════════════════════════════════════════════════════
# Inference helpers
# ══════════════════════════════════════════════════════════════════════

def collect_logits(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Run the model in eval mode over a DataLoader and return
    (logits, labels) as numpy arrays.
    """
    model.eval()
    all_logits, all_labels = [], []
    with torch.no_grad():
        for batch in loader:
            ids   = batch["input_ids"].to(device)
            mask  = batch["attention_mask"].to(device)
            chars = batch["url_chars"].to(device)
            stats = batch["stat_features"].to(device)
            logits = model(ids, mask, chars, stats).squeeze(1)
            all_logits.extend(logits.cpu().numpy().tolist())
            all_labels.extend(batch["label"].cpu().numpy().tolist())
    return np.array(all_logits), np.array(all_labels)


# ══════════════════════════════════════════════════════════════════════
# Method 1 — empirical threshold search
# ══════════════════════════════════════════════════════════════════════

def calibrate_threshold(
    logits: np.ndarray,
    labels: np.ndarray,
    target_fpr: float = 0.01,
) -> dict:
    """
    Find the decision threshold that achieves ≤ target_fpr on the
    production-representative holdout set.

    Returns a dict with keys:
        threshold, fpr, tpr, precision, f1, target_fpr
    """
    probs = 1 / (1 + np.exp(-logits))   # sigmoid
    fpr_arr, tpr_arr, thresholds = roc_curve(labels, probs)

    # Youden's J within FPR budget
    j_scores   = tpr_arr - fpr_arr
    valid_mask = fpr_arr <= target_fpr

    if valid_mask.any():
        best_idx = int(np.argmax(np.where(valid_mask, j_scores, -np.inf)))
    else:
        # Budget not achievable — use global Youden maximum
        best_idx = int(np.argmax(j_scores))
        logger.warning(
            f"Target FPR {target_fpr:.1%} not achievable on holdout set. "
            f"Using global Youden maximum (FPR={fpr_arr[best_idx]:.3f}). "
            f"Consider adding more legitimate samples to the holdout."
        )

    threshold = float(np.clip(thresholds[best_idx], 0.25, 0.80))
    preds = (probs >= threshold).astype(int)

    # Precision at this threshold
    tp = int(((preds == 1) & (labels == 1)).sum())
    fp = int(((preds == 1) & (labels == 0)).sum())
    fn = int(((preds == 0) & (labels == 1)).sum())
    precision = tp / max(tp + fp, 1)
    recall    = float(tpr_arr[best_idx])
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)

    result = {
        "threshold":  threshold,
        "fpr":        float(fpr_arr[best_idx]),
        "tpr":        recall,
        "precision":  precision,
        "f1":         f1,
        "target_fpr": target_fpr,
    }

    logger.info(
        f"\n{'─'*55}\n"
        f"  Calibrated threshold : {threshold:.4f}\n"
        f"  FPR (false alarm rate): {result['fpr']:.3%}\n"
        f"  TPR (detection rate)  : {result['tpr']:.3%}\n"
        f"  Precision             : {precision:.3%}\n"
        f"  F1                    : {f1:.4f}\n"
        f"  Target FPR            : {target_fpr:.1%}\n"
        f"{'─'*55}"
    )
    return result


# ══════════════════════════════════════════════════════════════════════
# Method 2 — Platt scaling
# ══════════════════════════════════════════════════════════════════════

def platt_scale(
    logits: np.ndarray,
    labels: np.ndarray,
    target_fpr: float = 0.01,
) -> dict:
    """
    Fit a logistic regression on raw logits to produce calibrated
    probabilities, then find a threshold on those probabilities.

    Platt scaling is more reliable than raw threshold search when the
    holdout set is small or the logit distribution is skewed.

    Returns:
        dict with keys: platt_a, platt_b, threshold, fpr, tpr, precision, f1
    """
    lr = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
    lr.fit(logits.reshape(-1, 1), labels)

    cal_probs = lr.predict_proba(logits.reshape(-1, 1))[:, 1]
    a = float(lr.coef_[0][0])
    b = float(lr.intercept_[0])
    logger.info(f"Platt scaling: a={a:.4f}, b={b:.4f}")
    logger.info("  Calibrated probability = σ(a·logit + b)")

    # Now find threshold on calibrated probabilities
    fpr_arr, tpr_arr, thresholds = roc_curve(labels, cal_probs)
    j_scores   = tpr_arr - fpr_arr
    valid_mask = fpr_arr <= target_fpr

    if valid_mask.any():
        best_idx = int(np.argmax(np.where(valid_mask, j_scores, -np.inf)))
    else:
        best_idx = int(np.argmax(j_scores))
        logger.warning(f"Target FPR {target_fpr:.1%} not achievable after Platt scaling.")

    threshold = float(np.clip(thresholds[best_idx], 0.25, 0.80))
    preds     = (cal_probs >= threshold).astype(int)
    tp = int(((preds == 1) & (labels == 1)).sum())
    fp = int(((preds == 1) & (labels == 0)).sum())
    precision = tp / max(tp + fp, 1)
    recall    = float(tpr_arr[best_idx])
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)

    result = {
        "platt_a":    a,
        "platt_b":    b,
        "threshold":  threshold,
        "fpr":        float(fpr_arr[best_idx]),
        "tpr":        recall,
        "precision":  precision,
        "f1":         f1,
        "target_fpr": target_fpr,
    }

    logger.info(
        f"\n{'─'*55}\n"
        f"  Platt-scaled threshold: {threshold:.4f}\n"
        f"  FPR                   : {result['fpr']:.3%}\n"
        f"  TPR                   : {result['tpr']:.3%}\n"
        f"  Precision             : {precision:.3%}\n"
        f"  F1                    : {f1:.4f}\n"
        f"{'─'*55}"
    )
    return result


# ══════════════════════════════════════════════════════════════════════
# Diagnostic plots
# ══════════════════════════════════════════════════════════════════════

def plot_calibration_report(
    logits: np.ndarray,
    labels: np.ndarray,
    result: dict,
    method: str,
    out_dir: str,
):
    """
    Save three diagnostic plots:
      1. ROC curve with calibrated operating point marked
      2. Score distribution (legitimate vs phishing histograms)
      3. Precision–Recall curve
    """
    probs = 1 / (1 + np.exp(-logits))
    if "platt_a" in result:
        from sklearn.linear_model import LogisticRegression as LR
        lr = LR(C=1.0, solver="lbfgs", max_iter=1000)
        lr.fit(logits.reshape(-1, 1), labels)
        probs = lr.predict_proba(logits.reshape(-1, 1))[:, 1]

    threshold = result["threshold"]
    fpr_arr, tpr_arr, _ = roc_curve(labels, probs)
    pre_arr, rec_arr, _ = precision_recall_curve(labels, probs)

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    import seaborn as sns
    sns.set_theme(style="whitegrid")

    # ROC
    axes[0].plot(fpr_arr, tpr_arr, color="#2980b9", lw=2, label="ROC curve")
    axes[0].scatter([result["fpr"]], [result["tpr"]],
                    color="#e74c3c", zorder=5, s=120,
                    label=f"Operating point\n(FPR={result['fpr']:.3%}, TPR={result['tpr']:.3%})")
    axes[0].plot([0, 1], [0, 1], "k--", alpha=0.4)
    axes[0].set_title("ROC Curve — Production Holdout", fontweight="bold")
    axes[0].set_xlabel("False Positive Rate")
    axes[0].set_ylabel("True Positive Rate")
    axes[0].legend(fontsize=9)

    # Score distribution
    phish_probs = probs[labels == 1]
    legit_probs = probs[labels == 0]
    axes[1].hist(legit_probs, bins=50, alpha=0.6, color="#2ecc71",
                 label=f"Legitimate (n={len(legit_probs):,})", density=True)
    axes[1].hist(phish_probs, bins=50, alpha=0.6, color="#e74c3c",
                 label=f"Phishing (n={len(phish_probs):,})", density=True)
    axes[1].axvline(threshold, color="black", lw=1.5, linestyle="--",
                    label=f"Threshold = {threshold:.3f}")
    axes[1].set_title("Score Distribution", fontweight="bold")
    axes[1].set_xlabel("Predicted Probability")
    axes[1].legend(fontsize=9)

    # Precision–Recall
    axes[2].plot(rec_arr, pre_arr, color="#8e44ad", lw=2)
    axes[2].set_title("Precision–Recall Curve", fontweight="bold")
    axes[2].set_xlabel("Recall (TPR)")
    axes[2].set_ylabel("Precision")

    fig.suptitle(
        f"Calibration Report — {method} | threshold={threshold:.4f} | "
        f"FPR={result['fpr']:.3%} | F1={result['f1']:.4f}",
        fontsize=13, fontweight="bold",
    )
    fig.tight_layout()
    path = os.path.join(out_dir, f"calibration_{method}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Calibration plot saved → {path}")


# ══════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════

def run_calibration(
    checkpoint_path: str,
    meta_path: str,
    target_fpr: float = 0.01,
    method: str = "threshold",
    batch_size: int = 64,
):
    """
    Load model from checkpoint, collect logits on a production-representative
    holdout set, calibrate the threshold, and write it back to meta_path.

    The holdout set is built from MongoDB using the same build_dataframe()
    pipeline.  For best results, ensure your MongoDB contains a
    production-representative mix (>90% legitimate) BEFORE calling this.
    If your MongoDB is still training-distribution, set up a separate
    holdout collection and point MONGO_URI / DB_NAME / COLLECTION_NAME to it.
    """
    device = torch.device(cfg.DEVICE)

    # ── Load meta ──────────────────────────────────────────────────────
    meta = torch.load(meta_path, map_location="cpu", weights_only=False)
    selected_features = meta["selected_features"]
    stat_feature_dim  = meta["stat_feature_dim"]
    logger.info(f"Loaded meta: {stat_feature_dim} features: {selected_features}")

    # ── Load model ─────────────────────────────────────────────────────
    ckpt  = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    model = PhishGuardNet(stat_feature_dim=stat_feature_dim).to(device)
    model.load_state_dict(ckpt["model_state_dict"])
    logger.info(f"Loaded checkpoint from epoch {ckpt['epoch']} "
                f"(val_loss={ckpt['val_loss']:.4f})")

    # ── Build holdout set ──────────────────────────────────────────────
    logger.info("Building holdout DataFrame from MongoDB...")
    df = build_dataframe()
    df = engineer_features(df)

    phish_ratio = (df["label"] == 1).mean()
    logger.info(f"Holdout base rate: {phish_ratio:.1%} phishing")
    if phish_ratio > 0.50:
        logger.warning(
            "Holdout set is majority phishing — this is NOT representative "
            "of production traffic. Calibrated threshold will be too aggressive. "
            "Use a holdout with >80% legitimate samples."
        )

    # ── Build DataLoader using training scaler ─────────────────────────
    from transformers import DistilBertTokenizer
    from sklearn.preprocessing import StandardScaler
    tokenizer = DistilBertTokenizer.from_pretrained(cfg.BERT_MODEL)
    scaler    = StandardScaler()
    scaler.fit(df[selected_features].values)   # fit on holdout (standalone use)

    dataset = PhishingMultiModalDataset(
        df, selected_features, scaler, tokenizer, cfg.char_dict,
        is_train=False,
    )
    loader = DataLoader(
        dataset, batch_size=batch_size, shuffle=False,
        num_workers=cfg.NUM_WORKERS, pin_memory=cfg.PIN_MEMORY,
        collate_fn=default_collate_fn,
    )

    # ── Collect logits ─────────────────────────────────────────────────
    logger.info("Collecting logits on holdout set...")
    logits, labels = collect_logits(model, loader, device)
    logger.info(f"Holdout: {len(labels):,} samples, "
                f"{int(labels.sum()):,} phishing, "
                f"{int((labels==0).sum()):,} legitimate")

    # ── Calibrate ─────────────────────────────────────────────────────
    if method == "platt":
        result = platt_scale(logits, labels, target_fpr=target_fpr)
    else:
        result = calibrate_threshold(logits, labels, target_fpr=target_fpr)

    # ── Plot ───────────────────────────────────────────────────────────
    plot_calibration_report(logits, labels, result, method, cfg.EVAL_DIR)

    # ── Write calibrated threshold back to meta ────────────────────────
    meta["optimal_threshold"]   = result["threshold"]
    meta["calibration_method"]  = method
    meta["calibration_fpr"]     = result["fpr"]
    meta["calibration_tpr"]     = result["tpr"]
    meta["calibration_target_fpr"] = target_fpr
    if "platt_a" in result:
        meta["platt_a"] = result["platt_a"]
        meta["platt_b"] = result["platt_b"]

    torch.save(meta, meta_path)
    logger.info(f"Calibrated meta written → {meta_path}")

    # ── JSON summary ───────────────────────────────────────────────────
    summary_path = os.path.join(cfg.EVAL_DIR, "calibration_result.json")
    with open(summary_path, "w") as f:
        json.dump({k: float(v) if isinstance(v, (float, np.floating)) else v
                   for k, v in result.items()}, f, indent=2)
    logger.info(f"Calibration summary → {summary_path}")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PhishGuard post-training calibration")
    parser.add_argument("--checkpoint", default=cfg.best_model_path)
    parser.add_argument("--meta",       default=cfg.train_meta_path)
    parser.add_argument("--method",     default="threshold",
                        choices=["threshold", "platt"],
                        help="Calibration method: empirical threshold or Platt scaling")
    parser.add_argument("--target-fpr", type=float, default=0.01,
                        help="Maximum acceptable false positive rate (default: 1%%)")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    run_calibration(
        checkpoint_path=args.checkpoint,
        meta_path=args.meta,
        target_fpr=args.target_fpr,
        method=args.method,
        batch_size=args.batch_size,
    )

"""
Post-training calibration for the non-visual PhishGuard model.

Key updates:
- uses held-out calibration split only
- reuses saved scaler from training
- persists chosen calibrator + recommended threshold for production inference
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pickle

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from torch.utils.data import DataLoader
from transformers import DistilBertTokenizer

from ml.config import cfg
from ml.dataset import PhishingMultiModalDataset, default_collate_fn, load_scaler, split_dataframe
from ml.features import engineer_features
from ml.model import PhishGuardNet
from ml.preprocessing import build_dataframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("calibrate")


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def collect_logits(model, loader, device):
    model.eval()
    all_logits, all_labels = [], []
    with torch.no_grad():
        for batch in loader:
            ids = batch["input_ids"].to(device)
            mask = batch["attention_mask"].to(device)
            chars = batch["url_chars"].to(device)
            stats = batch["stat_features"].to(device)
            logits = model(ids, mask, chars, stats).squeeze(1)
            all_logits.extend(logits.cpu().numpy().tolist())
            all_labels.extend(batch["label"].cpu().numpy().tolist())
    return np.array(all_logits), np.array(all_labels)


def fit_platt_scaler(logits: np.ndarray, labels: np.ndarray) -> LogisticRegression:
    lr = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
    lr.fit(logits.reshape(-1, 1), labels.astype(int))
    return lr


def fit_isotonic_scaler(logits: np.ndarray, labels: np.ndarray) -> IsotonicRegression:
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    iso.fit(_sigmoid(logits), labels.astype(int))
    return iso


def platt_predict(lr: LogisticRegression, logits: np.ndarray) -> np.ndarray:
    return lr.predict_proba(logits.reshape(-1, 1))[:, 1]


def isotonic_predict(iso: IsotonicRegression, logits: np.ndarray) -> np.ndarray:
    return iso.predict(_sigmoid(logits))


def plot_calibration_curves(labels, raw_probs, platt_probs, isotonic_probs, out_dir, n_bins: int = 10):
    fig, axes = plt.subplots(1, 3, figsize=(20, 6))
    configs = [("Raw", raw_probs), ("Platt", platt_probs), ("Isotonic", isotonic_probs)]
    labels_int = (labels >= 0.5).astype(int)

    for ax, (name, probs) in zip(axes, configs):
        frac_pos, mean_pred = calibration_curve(labels_int, probs, n_bins=n_bins, strategy="uniform")
        ax.plot([0, 1], [0, 1], "k--", alpha=0.4)
        ax.plot(mean_pred, frac_pos, "o-")
        ax.set_title(name)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "calibration_curves.png")
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _compute_metrics_at_threshold(y_true: np.ndarray, y_probs: np.ndarray, threshold: float) -> dict:
    y_pred = (y_probs >= threshold).astype(int)
    y_bin = (y_true >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_bin, y_pred, labels=[0, 1]).ravel()
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    fpr = fp / max(fp + tn, 1)
    fnr = fn / max(fn + tp, 1)
    return {
        "threshold": threshold, "precision": precision, "recall": recall,
        "f1": f1, "fpr": fpr, "fnr": fnr, "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn),
    }


def sweep_thresholds(y_true, y_probs, sweep_start: float = 0.10, sweep_end: float = 0.90, sweep_step: float = 0.01):
    return [_compute_metrics_at_threshold(y_true, y_probs, round(t, 4))
            for t in np.arange(sweep_start, sweep_end + sweep_step / 2, sweep_step)]


def find_operating_points(sweep_results: list[dict], target_fpr: float) -> dict:
    under_budget = [r for r in sweep_results if r["fpr"] <= target_fpr]
    max_recall = max(under_budget, key=lambda r: r["recall"]) if under_budget else min(sweep_results, key=lambda r: r["fpr"])
    balanced = max(sweep_results, key=lambda r: r["f1"])
    high_precision_pool = [r for r in sweep_results if r["recall"] >= 0.85]
    high_precision = max(high_precision_pool, key=lambda r: r["precision"]) if high_precision_pool else max(sweep_results, key=lambda r: r["precision"])
    return {"max_recall": max_recall, "balanced": balanced, "high_precision": high_precision}


def save_calibration_artifacts(calibrator, calibrator_name, recommended_threshold, operating_points, metrics_at_threshold, meta_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    calibrator_path = cfg.calibrator_path
    with open(calibrator_path, "wb") as f:
        pickle.dump({"calibrator": calibrator, "calibrator_type": calibrator_name}, f)

    threshold_path = cfg.optimal_threshold_path
    with open(threshold_path, "w") as f:
        json.dump({
            "recommended_threshold": recommended_threshold,
            "calibrator_type": calibrator_name,
            "metrics_at_threshold": metrics_at_threshold,
            "operating_points": operating_points,
        }, f, indent=2)

    meta = torch.load(meta_path, map_location="cpu", weights_only=False) if os.path.exists(meta_path) else {}
    meta["optimal_threshold"] = recommended_threshold
    meta["calibration_method"] = calibrator_name
    meta["calibrator_path"] = calibrator_path
    meta["calibration_metrics"] = metrics_at_threshold
    meta["architecture"] = "non_visual_multimodal_fusion"
    torch.save(meta, meta_path)
    return {"calibrator_path": calibrator_path, "threshold_path": threshold_path, "meta_path": meta_path}


def build_calibration_loader(df, selected_features):
    _, _, calib_df = split_dataframe(df)
    tokenizer = DistilBertTokenizer.from_pretrained(cfg.BERT_MODEL)
    scaler = load_scaler(cfg.scaler_path)
    dataset = PhishingMultiModalDataset(calib_df, selected_features, scaler, tokenizer, cfg.char_dict, is_train=False)
    loader = DataLoader(
        dataset,
        batch_size=64,
        shuffle=False,
        num_workers=cfg.NUM_WORKERS,
        pin_memory=cfg.PIN_MEMORY,
        collate_fn=default_collate_fn,
    )
    return loader, calib_df


def run_calibration(checkpoint_path: str, meta_path: str, target_fpr: float = cfg.TARGET_FPR, batch_size: int = 64):
    device = torch.device(cfg.DEVICE)
    meta = torch.load(meta_path, map_location="cpu", weights_only=False)
    selected_features = meta["selected_features"]
    stat_feature_dim = meta["stat_feature_dim"]

    ckpt = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    model = PhishGuardNet(stat_feature_dim=stat_feature_dim).to(device)
    model.load_state_dict(ckpt["model_state_dict"])

    df = engineer_features(build_dataframe())
    loader, calib_df = build_calibration_loader(df, selected_features)
    logits, labels = collect_logits(model, loader, device)
    labels_int = (labels >= 0.5).astype(int)

    platt = fit_platt_scaler(logits, labels_int)
    isotonic = fit_isotonic_scaler(logits, labels_int)

    raw_probs = _sigmoid(logits)
    platt_probs = platt_predict(platt, logits)
    isotonic_probs = isotonic_predict(isotonic, logits)
    plot_calibration_curves(labels_int, raw_probs, platt_probs, isotonic_probs, cfg.EVAL_DIR)

    sweep_results = sweep_thresholds(labels_int, platt_probs)
    operating_points = find_operating_points(sweep_results, target_fpr=target_fpr)
    recommended = operating_points["max_recall"]
    threshold = recommended["threshold"]

    y_pred = (platt_probs >= threshold).astype(int)
    report = classification_report(labels_int, y_pred, target_names=["legitimate", "phishing"], digits=4)
    print(report)

    saved = save_calibration_artifacts(
        calibrator=platt,
        calibrator_name="platt",
        recommended_threshold=threshold,
        operating_points=operating_points,
        metrics_at_threshold=recommended,
        meta_path=meta_path,
        out_dir=cfg.EVAL_DIR,
    )
    logger.info("Calibration saved: %s", saved)
    return {"recommended_threshold": threshold, "operating_points": operating_points, "saved_paths": saved}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibrate the non-visual PhishGuard model")
    parser.add_argument("--checkpoint", default=cfg.best_model_path)
    parser.add_argument("--meta", default=cfg.train_meta_path)
    parser.add_argument("--target-fpr", type=float, default=cfg.TARGET_FPR)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    run_calibration(args.checkpoint, args.meta, args.target_fpr, args.batch_size)

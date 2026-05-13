"""
Production inference wrapper for the non-visual PhishGuard system.

Flow:
1. engineer features
2. run multimodal model
3. apply calibrator if available
4. apply safe filter
5. return final verdict + reason codes
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import torch
from transformers import DistilBertTokenizer

from ml.config import cfg
from ml.dataset import _tokenize_smart, load_scaler
from ml.features import engineer_features
from ml.model import PhishGuardNet
from ml.safe_filter import SafeFilter

logger = logging.getLogger("inference")


@dataclass
class InferenceArtifacts:
    model: PhishGuardNet
    tokenizer: DistilBertTokenizer
    scaler: Any
    selected_features: list[str]
    threshold: float
    calibrator: Any | None
    calibrator_type: str | None
    safeguard: SafeFilter


def _load_calibrator():
    try:
        with open(cfg.calibrator_path, "rb") as f:
            payload = pickle.load(f)
        return payload.get("calibrator"), payload.get("calibrator_type")
    except FileNotFoundError:
        return None, None


def _resolve_runtime_threshold(meta: dict[str, Any]) -> float:
    raw_threshold = meta.get("optimal_threshold", cfg.DECISION_THRESHOLD)
    try:
        threshold = float(raw_threshold)
    except (TypeError, ValueError):
        threshold = cfg.DECISION_THRESHOLD

    # The checked-in artifact currently carries a stale 0.2 threshold, which is
    # far more aggressive than the production-safe policy and causes safe pages
    # to escalate during Stage 2. We keep the configured floor authoritative so
    # old artifacts cannot silently lower production behavior.
    normalized = min(0.80, max(threshold, cfg.DECISION_THRESHOLD))
    if normalized != threshold:
        logger.warning(
            "Overriding artifact threshold %.3f with production floor %.3f",
            threshold,
            normalized,
        )
    return normalized


def load_artifacts() -> InferenceArtifacts:
    meta = torch.load(cfg.train_meta_path, map_location="cpu", weights_only=False)
    selected_features = meta["selected_features"]
    stat_feature_dim = meta["stat_feature_dim"]
    threshold = _resolve_runtime_threshold(meta)

    model = PhishGuardNet(stat_feature_dim=stat_feature_dim)
    ckpt = torch.load(cfg.best_model_path, map_location="cpu", weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    scaler = load_scaler(cfg.scaler_path)
    tokenizer = DistilBertTokenizer.from_pretrained(cfg.BERT_MODEL)
    calibrator, calibrator_type = _load_calibrator()
    safeguard = SafeFilter()

    return InferenceArtifacts(
        model=model,
        tokenizer=tokenizer,
        scaler=scaler,
        selected_features=selected_features,
        threshold=threshold,
        calibrator=calibrator,
        calibrator_type=calibrator_type,
        safeguard=safeguard,
    )


def _tokenize_text(text: str, tokenizer):
    encoded = _tokenize_smart(text or "", tokenizer, cfg.MAX_TEXT_LENGTH)
    return encoded["input_ids"], encoded["attention_mask"]


def _encode_url(url: str):
    url = (url or "").lower()
    out = torch.zeros((1, cfg.MAX_URL_LENGTH), dtype=torch.long)
    for i, c in enumerate(url[: cfg.MAX_URL_LENGTH]):
        out[0, i] = cfg.char_dict.get(c, 0)
    return out


def _apply_calibrator(calibrator, calibrator_type: str | None, raw_logit: float) -> float:
    raw_prob = 1.0 / (1.0 + np.exp(-raw_logit))
    if calibrator is None:
        return float(raw_prob)
    if calibrator_type == "platt":
        return float(calibrator.predict_proba(np.array([[raw_logit]]))[:, 1][0])
    return float(calibrator.predict(np.array([raw_prob]))[0])


def predict_url(url: str, text_clean: str, text_raw: str, artifacts: InferenceArtifacts | None = None) -> dict:
    artifacts = artifacts or load_artifacts()
    df = pd.DataFrame([{
        "url": url,
        "label": 0,
        "label_str": "unknown",
        "source": "inference",
        "minio_txt_key": "",
        "text_raw": text_raw or text_clean or "",
        "text_clean": text_clean or "",
    }])
    df = engineer_features(df)
    row = df.iloc[0]

    input_ids, attention_mask = _tokenize_text(row["text_clean"], artifacts.tokenizer)
    url_chars = _encode_url(row["url"])
    stat_array = artifacts.scaler.transform(df[artifacts.selected_features].values).astype(np.float32)
    stat_features = torch.tensor(stat_array, dtype=torch.float32)

    with torch.no_grad():
        raw_logit = float(artifacts.model(input_ids, attention_mask, url_chars, stat_features).squeeze().item())

    raw_score = float(1.0 / (1.0 + np.exp(-raw_logit)))
    calibrated_score = _apply_calibrator(artifacts.calibrator, artifacts.calibrator_type, raw_logit)
    final_score, filter_reason = artifacts.safeguard.predict(url, calibrated_score)
    verdict = "malicious" if final_score >= artifacts.threshold else "legitimate"

    signals = []
    for feat in ["brand_impersonation_score", "subdomain_depth", "has_password_field",
                 "title_mismatch", "external_link_ratio", "form_action_density",
                 "has_hidden_iframe"]:
        if feat in row and float(row[feat]) > 0:
            signals.append({"name": feat, "value": float(row[feat])})

    return {
        "url": url,
        "verdict": verdict,
        "raw_score": raw_score,
        "calibrated_score": calibrated_score,
        "final_score": float(final_score),
        "threshold": float(artifacts.threshold),
        "signals": signals,
        "filter_reason": filter_reason,
        "calibrator_type": artifacts.calibrator_type or "none",
        "architecture": "non_visual_multimodal_fusion",
    }


if __name__ == "__main__":
    artifacts = load_artifacts()
    sample = predict_url(
        url="http://paypal.security-check.evil-example.com/login",
        text_clean="verify your paypal account password now",
        text_raw="<html><title>PayPal Security Verification</title><form action='http://evil-example.com/post'><input type='password'></form></html>",
        artifacts=artifacts,
    )
    print(json.dumps(sample, indent=2))

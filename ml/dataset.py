"""
Dataset + DataLoader utilities for the non-visual PhishGuard pipeline.

Key updates:
- explicit train/val/calibration split helper
- shared scaler persistence/loading hooks
- create_dataloaders still returns the original 5-tuple for compatibility
"""

from __future__ import annotations

import pickle
import random

import numpy as np
import pandas as pd
import torch
from sklearn.model_selection import StratifiedShuffleSplit
from torch.utils.data import DataLoader, Dataset
from transformers import DistilBertTokenizer

from ml.config import cfg
from ml.features import fit_scaler, select_features


_HOMOGLYPHS = {
    "o": "0", "l": "1", "i": "1", "a": "@", "e": "3", "s": "5", "t": "7", "b": "6", "g": "9",
}

_SYNONYM_MAP = {
    "verify": ["confirm", "validate", "authenticate"],
    "account": ["profile", "membership", "subscription"],
    "password": ["passcode", "passkey", "credentials"],
    "login": ["sign-in", "log-in", "signin"],
    "update": ["upgrade", "renew", "refresh"],
    "security": ["protection", "safety", "defense"],
    "suspend": ["restrict", "disable", "freeze"],
    "unusual": ["suspicious", "abnormal", "irregular"],
    "confirm": ["verify", "validate", "approve"],
}


def save_scaler(scaler, path: str = None) -> str:
    path = path or cfg.scaler_path
    with open(path, "wb") as f:
        pickle.dump(scaler, f)
    return path


def load_scaler(path: str = None):
    path = path or cfg.scaler_path
    with open(path, "rb") as f:
        return pickle.load(f)


def split_dataframe(
    df: pd.DataFrame,
    val_split: float = cfg.VAL_SPLIT,
    calibration_split: float = cfg.CALIBRATION_SPLIT,
    seed: int = cfg.RANDOM_SEED,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Create train / validation / calibration splits.

    Strategy:
    1. Hold out calibration split from full data.
    2. Split remaining data into train / validation.

    Returns:
        train_df, val_df, calib_df
    """
    outer = StratifiedShuffleSplit(n_splits=1, test_size=calibration_split, random_state=seed)
    model_idx, calib_idx = next(outer.split(df, df["label"]))
    model_df = df.iloc[model_idx].reset_index(drop=True)
    calib_df = df.iloc[calib_idx].reset_index(drop=True)

    inner = StratifiedShuffleSplit(n_splits=1, test_size=val_split, random_state=seed)
    train_idx, val_idx = next(inner.split(model_df, model_df["label"]))
    train_df = model_df.iloc[train_idx].reset_index(drop=True)
    val_df = model_df.iloc[val_idx].reset_index(drop=True)
    return train_df, val_df, calib_df


def _typosquatting_augment(url: str) -> str:
    try:
        if "://" in url:
            prefix, rest = url.split("://", 1)
            domain, path = (rest.split("/", 1) if "/" in rest else (rest, ""))
            path = "/" + path if path else ""
            prefix = prefix + "://"
        else:
            domain, path = (url.split("/", 1) if "/" in url else (url, ""))
            path = "/" + path if path else ""
            prefix = ""

        if len(domain) < 3:
            return url

        mutation = random.choice(["swap", "insert", "delete", "homoglyph"])
        if mutation == "swap" and len(domain) >= 2:
            idx = random.randint(0, len(domain) - 2)
            domain = domain[:idx] + domain[idx + 1] + domain[idx] + domain[idx + 2:]
        elif mutation == "insert":
            idx = random.randint(1, len(domain) - 1)
            domain = domain[:idx] + random.choice("abcdefghijklmnopqrstuvwxyz") + domain[idx:]
        elif mutation == "delete" and len(domain) > 3:
            idx = random.randint(1, len(domain) - 2)
            domain = domain[:idx] + domain[idx + 1:]
        elif mutation == "homoglyph":
            replaceable = [(i, c) for i, c in enumerate(domain) if c in _HOMOGLYPHS]
            if replaceable:
                idx, char = random.choice(replaceable)
                domain = domain[:idx] + _HOMOGLYPHS[char] + domain[idx + 1:]
        return prefix + domain + path
    except Exception:
        return url


def _synonym_replace(text: str, max_replacements: int = 3) -> str:
    words = text.split()
    if not words:
        return text

    candidates = []
    for i, word in enumerate(words):
        clean_word = word.lower().strip(".,!?;:'\"()[]{}")
        if clean_word in _SYNONYM_MAP:
            candidates.append((i, clean_word))

    if not candidates:
        return text

    to_replace = random.sample(candidates, min(max_replacements, len(candidates)))
    for idx, clean_word in to_replace:
        synonym = random.choice(_SYNONYM_MAP[clean_word])
        original = words[idx]
        leading, trailing, stripped = "", "", original
        while stripped and not stripped[0].isalnum():
            leading += stripped[0]
            stripped = stripped[1:]
        while stripped and not stripped[-1].isalnum():
            trailing = stripped[-1] + trailing
            stripped = stripped[:-1]
        if stripped.isupper():
            synonym = synonym.upper()
        elif stripped and stripped[0].isupper():
            synonym = synonym.capitalize()
        words[idx] = leading + synonym + trailing
    return " ".join(words)


def _tokenize_smart(text: str, tokenizer, max_len: int) -> dict:
    """
    Head + tail tokenisation for long documents.
    Compatible with Colab/Transformers setups where prepare_for_model
    is not exposed on the tokenizer object.
    """
    HEAD_TOKENS = 128

    # Tokenize without special tokens first
    token_ids = tokenizer.encode(
        text,
        add_special_tokens=False,
        truncation=True,
        max_length=10000,
    )

    # Short text: normal tokenizer path
    if len(token_ids) <= max_len - 2:
        return tokenizer(
            text,
            max_length=max_len,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )

    # Long text: stitch head + tail manually
    tail_len = max_len - HEAD_TOKENS - 2   # reserve CLS + SEP
    head_ids = token_ids[:HEAD_TOKENS]
    tail_ids = token_ids[-tail_len:]
    combined = head_ids + tail_ids

    cls_id = tokenizer.cls_token_id
    sep_id = tokenizer.sep_token_id
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else 0

    input_ids = [cls_id] + combined + [sep_id]
    attention_mask = [1] * len(input_ids)

    # Pad to max_len
    pad_needed = max_len - len(input_ids)
    if pad_needed > 0:
        input_ids += [pad_id] * pad_needed
        attention_mask += [0] * pad_needed
    else:
        input_ids = input_ids[:max_len]
        attention_mask = attention_mask[:max_len]

    return {
        "input_ids": torch.tensor([input_ids], dtype=torch.long),
        "attention_mask": torch.tensor([attention_mask], dtype=torch.long),
    }


class PhishingMultiModalDataset(Dataset):
    def __init__(
        self,
        df: pd.DataFrame,
        feature_names: list[str],
        scaler,
        tokenizer: DistilBertTokenizer,
        char_dict: dict,
        max_text_len: int = cfg.MAX_TEXT_LENGTH,
        max_url_len: int = cfg.MAX_URL_LENGTH,
        is_train: bool = False,
    ):
        self.df = df.reset_index(drop=True)
        self.feature_names = feature_names
        self.scaler = scaler
        self.tokenizer = tokenizer
        self.char_dict = char_dict
        self.max_text_len = max_text_len
        self.max_url_len = max_url_len
        self.is_train = is_train
        self.stat_matrix = self.scaler.transform(self.df[self.feature_names].values).astype(np.float32)

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        text = row["text_clean"] if isinstance(row["text_clean"], str) else ""
        if self.is_train and random.random() < cfg.SYNONYM_AUG_PROB:
            text = _synonym_replace(text)
        inputs = _tokenize_smart(text, self.tokenizer, self.max_text_len)

        url = row["url"].lower() if isinstance(row["url"], str) else ""
        if self.is_train and random.random() < cfg.TYPO_AUG_PROB:
            url = _typosquatting_augment(url)

        url_tensor = torch.zeros(self.max_url_len, dtype=torch.long)
        for i, char in enumerate(url[: self.max_url_len]):
            url_tensor[i] = self.char_dict.get(char, 0)

        return {
            "input_ids": inputs["input_ids"].squeeze(0),
            "attention_mask": inputs["attention_mask"].squeeze(0),
            "url_chars": url_tensor,
            "stat_features": torch.tensor(self.stat_matrix[idx], dtype=torch.float32),
            "label": torch.tensor(row["label"], dtype=torch.float32),
        }


def mixup_collate_fn(batch, alpha: float = cfg.MIXUP_ALPHA):
    input_ids = torch.stack([b["input_ids"] for b in batch])
    attention_mask = torch.stack([b["attention_mask"] for b in batch])
    url_chars = torch.stack([b["url_chars"] for b in batch])
    stat_features = torch.stack([b["stat_features"] for b in batch])
    labels = torch.stack([b["label"] for b in batch])

    if alpha > 0 and random.random() < 0.5:
        lam = float(np.random.beta(alpha, alpha))
        idx = torch.randperm(len(batch))
        stat_features = lam * stat_features + (1 - lam) * stat_features[idx]
        labels = lam * labels + (1 - lam) * labels[idx]

    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "url_chars": url_chars,
        "stat_features": stat_features,
        "label": labels,
    }


def default_collate_fn(batch):
    return {
        "input_ids": torch.stack([b["input_ids"] for b in batch]),
        "attention_mask": torch.stack([b["attention_mask"] for b in batch]),
        "url_chars": torch.stack([b["url_chars"] for b in batch]),
        "stat_features": torch.stack([b["stat_features"] for b in batch]),
        "label": torch.stack([b["label"] for b in batch]),
    }


def create_dataloaders(
    df: pd.DataFrame,
    feature_names: list[str] | None = None,
    scaler=None,
    val_split: float = cfg.VAL_SPLIT,
    batch_size: int = cfg.BATCH_SIZE,
    seed: int = cfg.RANDOM_SEED,
):
    tokenizer = DistilBertTokenizer.from_pretrained(cfg.BERT_MODEL)
    char_dict = cfg.char_dict

    # Keep calibration split out of training/eval by design.
    train_df, val_df, _ = split_dataframe(
        df, val_split=val_split, calibration_split=cfg.CALIBRATION_SPLIT, seed=seed
    )

    if feature_names is None:
        feature_names = select_features(train_df)
    if scaler is None:
        scaler = fit_scaler(train_df, feature_names)

    n_pos = (train_df["label"] == 1).sum()
    n_neg = (train_df["label"] == 0).sum()
    pos_weight = torch.tensor([n_neg / max(n_pos, 1)], dtype=torch.float32)

    train_dataset = PhishingMultiModalDataset(train_df, feature_names, scaler, tokenizer, char_dict, is_train=True)
    val_dataset = PhishingMultiModalDataset(val_df, feature_names, scaler, tokenizer, char_dict, is_train=False)

    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=cfg.NUM_WORKERS,
        persistent_workers=(cfg.NUM_WORKERS > 0),
        pin_memory=cfg.PIN_MEMORY,
        drop_last=True,
        collate_fn=mixup_collate_fn,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=cfg.NUM_WORKERS,
        persistent_workers=(cfg.NUM_WORKERS > 0),
        pin_memory=cfg.PIN_MEMORY,
        collate_fn=default_collate_fn,
    )

    return train_loader, val_loader, scaler, pos_weight, feature_names

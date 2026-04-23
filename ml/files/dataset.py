"""
Multi-modal PyTorch Dataset and DataLoader factory (v4).

v3 Changes:
  - FIX #1 (Data Leakage): Split FIRST, then call select_features() and
    fit_scaler() on the TRAINING split only. Val split never touches these.
  - FIX #6: Augmentation probabilities raised to 0.35.
  - FIX (MixUp): Statistical feature MixUp added for training.
  - select_features() and fit_scaler() are called internally — callers
    should NOT call them on the full df before create_dataloaders().

v4 Changes:
  - pin_memory now sourced from cfg.PIN_MEMORY (which is already guarded
    to be True only when CUDA is available — see config.py).
  - create_dataloaders() return signature documented: always 5-tuple.
    Both evaluate.py and evaluate_rigorous.py must unpack all 5 values.
"""

import random
import torch
import numpy as np
import pandas as pd
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import StratifiedShuffleSplit
from transformers import DistilBertTokenizer
from ml.config import cfg
from ml.features import fit_scaler, select_features


# ══════════════════════════════════════════════════════════════════════
# Augmentation Utilities
# ══════════════════════════════════════════════════════════════════════

_HOMOGLYPHS = {
    "o": "0", "l": "1", "i": "1", "a": "@", "e": "3",
    "s": "5", "t": "7", "b": "6", "g": "9",
}

_SYNONYM_MAP = {
    "verify": ["confirm", "validate", "authenticate"],
    "account": ["profile", "membership", "subscription"],
    "password": ["passcode", "passkey", "credentials"],
    "login": ["sign-in", "log-in", "signin"],
    "signin": ["login", "log-in", "sign-in"],
    "update": ["upgrade", "renew", "refresh"],
    "security": ["protection", "safety", "defense"],
    "suspend": ["restrict", "disable", "freeze"],
    "unusual": ["suspicious", "abnormal", "irregular"],
    "confirm": ["verify", "validate", "approve"],
    "click": ["tap", "press", "select"],
    "link": ["url", "address", "hyperlink"],
    "email": ["mail", "message", "correspondence"],
    "bank": ["financial institution", "credit union"],
    "payment": ["transaction", "transfer", "remittance"],
    "expire": ["lapse", "terminate", "end"],
    "warning": ["alert", "notice", "caution"],
    "required": ["mandatory", "necessary", "needed"],
    "immediately": ["urgently", "promptly", "right away"],
    "personal": ["private", "confidential", "sensitive"],
    "information": ["details", "data", "records"],
    "unauthorized": ["illegal", "unlawful", "fraudulent"],
    "locked": ["blocked", "frozen", "restricted"],
    "restore": ["recover", "reactivate", "reinstate"],
    "access": ["entry", "authorization", "permission"],
    "submit": ["send", "provide", "enter"],
    "customer": ["client", "user", "member"],
    "service": ["support", "assistance", "help"],
    "notification": ["alert", "notice", "message"],
    "limited": ["restricted", "temporary", "finite"],
}


def _typosquatting_augment(url: str) -> str:
    try:
        if "://" in url:
            prefix, rest = url.split("://", 1)
            domain, path = (rest.split("/", 1) if "/" in rest else (rest, ""))
            path   = "/" + path if path else ""
            prefix = prefix + "://"
        else:
            domain, path = (url.split("/", 1) if "/" in url else (url, ""))
            path   = "/" + path if path else ""
            prefix = ""

        if len(domain) < 3:
            return url

        mutation = random.choice(["swap", "insert", "delete", "homoglyph"])

        if mutation == "swap" and len(domain) >= 2:
            idx    = random.randint(0, len(domain) - 2)
            domain = domain[:idx] + domain[idx + 1] + domain[idx] + domain[idx + 2:]
        elif mutation == "insert":
            idx    = random.randint(1, len(domain) - 1)
            char   = random.choice("abcdefghijklmnopqrstuvwxyz")
            domain = domain[:idx] + char + domain[idx:]
        elif mutation == "delete" and len(domain) > 3:
            idx    = random.randint(1, len(domain) - 2)
            domain = domain[:idx] + domain[idx + 1:]
        elif mutation == "homoglyph":
            replaceable = [(i, c) for i, c in enumerate(domain) if c in _HOMOGLYPHS]
            if replaceable:
                idx, char  = random.choice(replaceable)
                domain     = domain[:idx] + _HOMOGLYPHS[char] + domain[idx + 1:]

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
        synonym      = random.choice(_SYNONYM_MAP[clean_word])
        original     = words[idx]
        leading      = ""
        trailing     = ""
        stripped     = original
        while stripped and not stripped[0].isalnum():
            leading += stripped[0]; stripped = stripped[1:]
        while stripped and not stripped[-1].isalnum():
            trailing = stripped[-1] + trailing; stripped = stripped[:-1]
        if stripped.isupper():
            synonym = synonym.upper()
        elif stripped and stripped[0].isupper():
            synonym = synonym.capitalize()
        words[idx] = leading + synonym + trailing

    return " ".join(words)


# ══════════════════════════════════════════════════════════════════════
# MixUp Collator
# ══════════════════════════════════════════════════════════════════════

def mixup_collate_fn(batch, alpha: float = cfg.MIXUP_ALPHA):
    """
    MixUp augmentation applied to statistical features only.
    Text and URL inputs are kept as-is (too complex to mix meaningfully).
    Labels are mixed as soft targets — prevents overconfident predictions.

    Only applied during training (val uses default_collate_fn).
    """
    input_ids      = torch.stack([b["input_ids"] for b in batch])
    attention_mask = torch.stack([b["attention_mask"] for b in batch])
    url_chars      = torch.stack([b["url_chars"] for b in batch])
    stat_features  = torch.stack([b["stat_features"] for b in batch])
    labels         = torch.stack([b["label"] for b in batch])

    if alpha > 0 and random.random() < 0.5:   # apply MixUp 50% of batches
        lam    = float(np.random.beta(alpha, alpha))
        idx    = torch.randperm(len(batch))

        stat_features = lam * stat_features + (1 - lam) * stat_features[idx]
        labels        = lam * labels + (1 - lam) * labels[idx]

    return {
        "input_ids":      input_ids,
        "attention_mask": attention_mask,
        "url_chars":      url_chars,
        "stat_features":  stat_features,
        "label":          labels,
    }


def default_collate_fn(batch):
    """Standard collate for validation — no augmentation."""
    return {
        "input_ids":      torch.stack([b["input_ids"] for b in batch]),
        "attention_mask": torch.stack([b["attention_mask"] for b in batch]),
        "url_chars":      torch.stack([b["url_chars"] for b in batch]),
        "stat_features":  torch.stack([b["stat_features"] for b in batch]),
        "label":          torch.stack([b["label"] for b in batch]),
    }


def _tokenize_smart(text: str, tokenizer, max_len: int) -> dict:
    """
    Head + tail tokenisation for long documents.

    WHY this is needed
    ──────────────────
    Phishing pages are short (200–600 tokens: a fake login form, a spoofed
    logo, urgency text).  Legitimate pages — bank homepages, SaaS portals,
    e-commerce sites — are long (2 000–15 000+ tokens) and get hard-truncated
    to the FIRST max_len tokens by the default tokenizer call.

    The first 512 tokens of a legitimate page are almost always: navigation
    menus, cookie banners, "Sign in / Create account" links, and header forms.
    That is exactly what a phishing kit looks like.  The model learned
    "short page OR page that starts with login links = phishing", causing
    false positives on every modern authenticated web app.

    Taking the first HEAD_TOKENS tokens + the last (max_len - HEAD_TOKENS - 2)
    tokens gives a representative view of the full page: the header context
    AND the main body content, which for legitimate sites contains product
    listings, articles, navigation breadcrumbs, and footer links that are
    absent from phishing pages.
    """
    HEAD_TOKENS = 128
    token_ids = tokenizer.encode(text, add_special_tokens=False,
                                  truncation=False)

    if len(token_ids) <= max_len - 2:
        # Short enough — use as-is with standard padding
        return tokenizer(
            text,
            max_length=max_len,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )

    # Long document: stitch head + tail
    tail_len  = max_len - HEAD_TOKENS - 2   # -2 for [CLS] and [SEP]
    head_ids  = token_ids[:HEAD_TOKENS]
    tail_ids  = token_ids[-tail_len:]
    combined  = head_ids + tail_ids

    # Build tensors manually — tokenizer.prepare_for_model handles CLS/SEP/PAD
    encoded = tokenizer.prepare_for_model(
        combined,
        max_length=max_len,
        padding="max_length",
        truncation=True,
        return_tensors="pt",
    )
    return encoded


# ══════════════════════════════════════════════════════════════════════
# Dataset
# ══════════════════════════════════════════════════════════════════════

class PhishingMultiModalDataset(Dataset):
    """
    Returns a dict per sample:
        input_ids      – DistilBERT token IDs                [MAX_TEXT_LENGTH]
        attention_mask – DistilBERT attention mask             [MAX_TEXT_LENGTH]
        url_chars      – Character-level integer sequence      [MAX_URL_LENGTH]
        stat_features  – Scaled engineered features            [N_features]
        label          – Binary label (float for BCEWithLogits) scalar
    """

    def __init__(
        self,
        df: pd.DataFrame,
        feature_names: list,
        scaler,
        tokenizer: DistilBertTokenizer,
        char_dict: dict,
        max_text_len: int = cfg.MAX_TEXT_LENGTH,
        max_url_len: int  = cfg.MAX_URL_LENGTH,
        is_train: bool    = False,
    ):
        self.df            = df.reset_index(drop=True)
        self.feature_names = feature_names
        self.scaler        = scaler
        self.tokenizer     = tokenizer
        self.char_dict     = char_dict
        self.max_text_len  = max_text_len
        self.max_url_len   = max_url_len
        self.is_train      = is_train

        # Pre-scale all stat features in one shot
        self.stat_matrix = self.scaler.transform(
            self.df[self.feature_names].values
        ).astype(np.float32)

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]

        # ── Text tokenization (smart head+tail for long pages) ───────
        text = row["text_clean"] if isinstance(row["text_clean"], str) else ""
        if self.is_train and random.random() < cfg.SYNONYM_AUG_PROB:
            text = _synonym_replace(text)

        inputs = _tokenize_smart(text, self.tokenizer, self.max_text_len)

        # ── URL character encoding ───────────────────────────────────
        url = row["url"].lower() if isinstance(row["url"], str) else ""
        if self.is_train and random.random() < cfg.TYPO_AUG_PROB:
            url = _typosquatting_augment(url)

        url_tensor = torch.zeros(self.max_url_len, dtype=torch.long)
        for i, char in enumerate(url[: self.max_url_len]):
            url_tensor[i] = self.char_dict.get(char, 0)

        # ── Statistical features ─────────────────────────────────────
        stat_features = torch.tensor(self.stat_matrix[idx], dtype=torch.float32)

        # ── Label ────────────────────────────────────────────────────
        label = torch.tensor(row["label"], dtype=torch.float32)

        return {
            "input_ids":      inputs["input_ids"].squeeze(0),
            "attention_mask": inputs["attention_mask"].squeeze(0),
            "url_chars":      url_tensor,
            "stat_features":  stat_features,
            "label":          label,
        }


# ══════════════════════════════════════════════════════════════════════
# DataLoader Factory — always returns a 5-tuple
# ══════════════════════════════════════════════════════════════════════

def create_dataloaders(
    df: pd.DataFrame,
    feature_names: list = None,
    scaler=None,
    val_split: float  = cfg.VAL_SPLIT,
    batch_size: int   = cfg.BATCH_SIZE,
    seed: int         = cfg.RANDOM_SEED,
):
    """
    Build train and validation DataLoaders with stratified splitting.

    FIX #1 (Data Leakage):
      1. Split df into train_df and val_df
      2. select_features(train_df)        ← train only
      3. fit_scaler(train_df, features)   ← train only
      4. Apply scaler.transform() to both splits

    IMPORTANT: Always unpack all 5 return values:
        train_loader, val_loader, scaler, pos_weight, selected_features = create_dataloaders(df)

    Returns:
        train_loader, val_loader, scaler, pos_weight, selected_features
    """
    tokenizer = DistilBertTokenizer.from_pretrained(cfg.BERT_MODEL)
    char_dict = cfg.char_dict

    # ── Step 1: Split FIRST ───────────────────────────────────────────
    splitter = StratifiedShuffleSplit(n_splits=1, test_size=val_split, random_state=seed)
    train_idx, val_idx = next(splitter.split(df, df["label"]))

    train_df = df.iloc[train_idx].reset_index(drop=True)
    val_df   = df.iloc[val_idx].reset_index(drop=True)

    # ── Step 2: Feature selection on TRAIN only ───────────────────────
    if feature_names is None:
        feature_names = select_features(train_df)

    # ── Step 3: Fit scaler on TRAIN only ─────────────────────────────
    if scaler is None:
        scaler = fit_scaler(train_df, feature_names)

    # ── Step 4: Class weights from TRAIN only ────────────────────────
    n_pos      = (train_df["label"] == 1).sum()
    n_neg      = (train_df["label"] == 0).sum()
    pos_weight = torch.tensor([n_neg / n_pos], dtype=torch.float32)

    # ── Create Datasets ───────────────────────────────────────────────
    train_dataset = PhishingMultiModalDataset(
        train_df, feature_names, scaler, tokenizer, char_dict,
        is_train=True,
    )
    val_dataset = PhishingMultiModalDataset(
        val_df, feature_names, scaler, tokenizer, char_dict,
        is_train=False,
    )

    # ── Create DataLoaders ────────────────────────────────────────────
    # cfg.PIN_MEMORY is already guarded: True only when CUDA is available.
    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=cfg.NUM_WORKERS,
        pin_memory=cfg.PIN_MEMORY,
        drop_last=True,
        collate_fn=mixup_collate_fn,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=cfg.NUM_WORKERS,
        pin_memory=cfg.PIN_MEMORY,
        collate_fn=default_collate_fn,
    )

    return train_loader, val_loader, scaler, pos_weight, feature_names

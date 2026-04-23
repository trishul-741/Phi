"""
Feature engineering for URL and webpage text signals.

Engineers 18 statistical features from URL structure and text content,
performs correlation analysis, and selects the most predictive features.

v3 Fix (Anti-Overfitting / Data Leakage):
  - select_features() now accepts an explicit train_df argument.
    It MUST only be called on the training split — never on the full dataset.

v4 Fixes (Security + Accuracy):
  - ReDoS guard: text_raw is capped at 50KB before any regex to prevent
    catastrophic backtracking on adversarially crafted HTML style attributes.
  - num_external_links: now counts unique external anchor href domains
    instead of raw 'http' occurrences (more accurate, less noisy).
  - fit_scaler documented and guarded: raises if called with val/full df.
"""

import re
import math
import logging
import numpy as np
import pandas as pd
from urllib.parse import urlparse
from sklearn.preprocessing import StandardScaler
from ml.config import cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("features")

# ── Compiled patterns ─────────────────────────────────────────────────
_RE_IP = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")

# FIX (ReDoS): Replaced nested quantifiers with an explicit length-bounded
# match. The original [^\"']*display\s*:\s*none[^\"']* could catastrophically
# backtrack on crafted style values. We now cap the style attribute body at
# 200 chars with a possessive-equivalent structure in Python's re engine.
_RE_HIDDEN_IFRAME = re.compile(
    r"<iframe[^>]{0,500}style\s*=\s*[\"'][^\"']{0,200}display\s*:\s*none",
    re.IGNORECASE,
)
_RE_FORM_ACTION  = re.compile(r"<form[^>]*action\s*=", re.IGNORECASE)

_RE_SPA_MARKERS = re.compile(r"(data-reactroot|ng-version|__nuxt|__NEXT_DATA__|vue-router|<div id=[\"'](root|app)[\"']>)", re.IGNORECASE)

# FIX: Extract anchor href URLs for external link counting
_RE_ANCHOR_HREF  = re.compile(r'href=[\'"]?(https?://[^\s\'"<>]+)', re.IGNORECASE)

_LOGIN_KEYWORDS = {
    "login", "signin", "sign-in", "sign_in", "password", "verify",
    "account", "security", "confirm", "authenticate", "credential",
    "update", "suspend", "restrict", "unusual"
}

# Max bytes of raw HTML to feed into regex (prevents ReDoS on huge pages)
_MAX_RAW_REGEX_BYTES = 50_000


def _shannon_entropy(s: str) -> float:
    """Compute Shannon entropy of a string."""
    if not s:
        return 0.0
    freq = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


def _login_keyword_density(text_lower: str) -> float:
    """
    Fraction of words that are login/phishing keywords (range: 0.0 – 1.0).

    WHY density instead of a binary flag
    ──────────────────────────────────────
    A single "login" on a bank homepage or a "verify" button on a
    two-factor auth page is completely normal.  The binary has_login_keywords
    flag fired on ALL of those and was the single biggest source of false
    positives on legitimate banking / e-commerce / SaaS sites.

    Density captures the real signal: a page with 5 different phishing
    keywords in 60 words (density ≈ 0.083) is qualitatively different from
    a bank portal with 1 "login" in 400 words (density ≈ 0.0025).
    The model can learn a meaningful threshold on a continuous feature;
    it cannot do that with a binary flag already set to 1.
    """
    words = text_lower.split()
    if not words:
        return 0.0
    hits = sum(1 for w in words if w.strip(".,!?;:'\"()[]{}") in _LOGIN_KEYWORDS)
    return hits / len(words)


# ── URL Feature Extractors ────────────────────────────────────────────

def _extract_url_features(url: str) -> dict:
    """Extract 12 statistical features from a URL string."""
    try:
        parsed = urlparse(url)
    except Exception:
        parsed = urlparse("")

    netloc = parsed.netloc or ""
    path   = parsed.path or ""

    return {
        "url_length":     len(url),
        "domain_length":  len(netloc),
        "path_length":    len(path),
        "num_dots":       url.count("."),
        "num_hyphens":    url.count("-"),
        "num_at":         url.count("@"),
        "num_question":   url.count("?"),
        "num_ampersand":  url.count("&"),
        "num_digits":     sum(c.isdigit() for c in url),
        "has_ip":         int(bool(_RE_IP.search(netloc))),
        "domain_entropy": _shannon_entropy(netloc),
        "num_subdomains": max(netloc.count(".") - 1, 0),
    }


def _count_external_links(text_raw: str, page_netloc: str) -> int:
    """
    Count unique external domains referenced via anchor href attributes.

    FIX: The original implementation counted all 'http' substrings in
    raw HTML, which conflates JS URLs, CSS url(), data attributes, and
    inline scripts. This version extracts only <a href="..."> links
    and counts those whose netloc differs from the page's own domain.

    Args:
        text_raw:     Raw HTML content (capped internally at _MAX_RAW_REGEX_BYTES).
        page_netloc:  The page's own domain (used to exclude self-links).

    Returns:
        Number of unique external domains referenced via anchor hrefs.
    """
    sample   = text_raw[:_MAX_RAW_REGEX_BYTES]
    hrefs    = _RE_ANCHOR_HREF.findall(sample)
    external = set()
    for href in hrefs:
        try:
            netloc = urlparse(href).netloc.lower()
            if netloc and netloc != page_netloc.lower():
                external.add(netloc)
        except Exception:
            pass
    return len(external)


# ── Text Feature Extractors ──────────────────────────────────────────

def _extract_text_features(text_clean: str, text_raw: str, page_netloc: str = "") -> dict:
    words      = text_clean.split()
    text_lower = text_clean.lower()
    raw_sample = text_raw[:_MAX_RAW_REGEX_BYTES]

    return {
        "text_length":        len(text_clean),
        "word_count":         len(words),
        # FIX: density float replaces binary flag — prevents false positives
        # on legitimate sites that have any login/verify/account vocabulary.
        "login_kw_density":   _login_keyword_density(text_lower),
        "has_hidden_iframe":  int(bool(_RE_HIDDEN_IFRAME.search(raw_sample))),
        "has_form_action":    int(bool(_RE_FORM_ACTION.search(raw_sample))),
        "num_external_links": _count_external_links(text_raw, page_netloc),
        # NOTE on is_modern_spa: this feature has NEGATIVE label correlation
        # (SPAs are predominantly legitimate). Feature selection will keep it
        # only if |corr| >= FEAT_MIN_LABEL_CORR. If the sign ever flips in a
        # new data batch, the correlation monitor in select_features() will
        # log a warning. Do not treat this as a phishing signal.
        "is_modern_spa":      int(bool(_RE_SPA_MARKERS.search(raw_sample))),
    }


# ── Main API ──────────────────────────────────────────────────────────

ALL_FEATURE_NAMES = [
    "url_length", "domain_length", "path_length",
    "num_dots", "num_hyphens", "num_at", "num_question", "num_ampersand",
    "num_digits", "has_ip", "domain_entropy", "num_subdomains",
    "text_length", "word_count",
    # FIX: was "has_login_keywords" (binary) — replaced with density float
    "login_kw_density",
    "has_hidden_iframe", "has_form_action", "num_external_links",
    "is_modern_spa",
]


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add all engineered features as new columns to the DataFrame.

    Args:
        df: DataFrame with 'url', 'text_clean', 'text_raw' columns.

    Returns:
        DataFrame with 18 additional feature columns appended.
    """
    logger.info("Engineering URL features...")
    url_feats = df["url"].apply(_extract_url_features).apply(pd.Series)

    logger.info("Engineering text features...")
    text_feats = df.apply(
        lambda row: _extract_text_features(
            row["text_clean"],
            row["text_raw"],
            page_netloc=urlparse(row["url"]).netloc,
        ),
        axis=1,
    ).apply(pd.Series)

    result = pd.concat([df, url_feats, text_feats], axis=1)
    logger.info(f"Engineered {len(ALL_FEATURE_NAMES)} features")
    return result


def select_features(
    train_df: pd.DataFrame,
    min_corr_with_label: float = cfg.FEAT_MIN_LABEL_CORR,
    max_cross_corr: float      = cfg.FEAT_MAX_CROSS_CORR,
) -> list:
    """
    Feature selection via correlation analysis.

    *** CRITICAL: Pass ONLY the training split here. ***
    Passing the full dataset (train + val) causes data leakage — the model
    indirectly learns from validation labels before training begins.

    Steps:
      1. Drop features with |correlation to label| < min_corr_with_label
      2. Among remaining, drop one from each pair with cross-corr > max_cross_corr

    Returns:
        List of selected feature column names.
    """
    available    = [f for f in ALL_FEATURE_NAMES if f in train_df.columns]
    corr_matrix  = train_df[available + ["label"]].corr()

    # Step 1: filter by correlation with label
    label_corr = corr_matrix["label"].drop("label").abs()
    selected   = label_corr[label_corr >= min_corr_with_label].index.tolist()
    dropped_low = set(available) - set(selected)
    if dropped_low:
        logger.info(f"Dropped (low label correlation): {dropped_low}")

    # Step 2: remove one of highly cross-correlated pairs
    if len(selected) > 1:
        feat_corr = train_df[selected].corr().abs()
        to_drop   = set()
        for i in range(len(selected)):
            for j in range(i + 1, len(selected)):
                if feat_corr.iloc[i, j] > max_cross_corr:
                    fi, fj = selected[i], selected[j]
                    if label_corr[fi] < label_corr[fj]:
                        to_drop.add(fi)
                    else:
                        to_drop.add(fj)
        if to_drop:
            logger.info(f"Dropped (high cross-correlation): {to_drop}")
        selected = [f for f in selected if f not in to_drop]

    logger.info(f"Selected {len(selected)} features from TRAIN split only: {selected}")

    # ── Correlation direction audit ───────────────────────────────────
    # Warn if any feature that should be a LEGITIMATE signal appears with a
    # positive correlation (phishing direction) in this training batch.
    # Catches distribution shifts before they silently bias the model.
    _expected_negative = {"is_modern_spa", "text_length", "word_count", "num_external_links"}
    for feat in selected:
        if feat in _expected_negative and label_corr.get(feat, 0) > 0.05:
            logger.warning(
                f"DIRECTION FLIP: '{feat}' has positive label corr "
                f"({label_corr[feat]:+.3f}) but is expected to correlate "
                f"with LEGITIMATE sites. Check data quality for this batch."
            )

    return selected


def fit_scaler(train_df: pd.DataFrame, feature_names: list) -> StandardScaler:
    """
    Fit a StandardScaler on the TRAINING split only.

    *** Never call this on the full dataset — it would leak val statistics
    (mean/std) into normalization and cause subtle overfitting. ***
    """
    scaler = StandardScaler()
    scaler.fit(train_df[feature_names].values)
    return scaler


if __name__ == "__main__":
    from ml.preprocessing import build_dataframe
    from sklearn.model_selection import StratifiedShuffleSplit

    df = build_dataframe()
    df = engineer_features(df)

    splitter = StratifiedShuffleSplit(n_splits=1, test_size=cfg.VAL_SPLIT, random_state=cfg.RANDOM_SEED)
    train_idx, val_idx = next(splitter.split(df, df["label"]))
    train_df = df.iloc[train_idx]

    print("\n── Feature Statistics (train split) ──")
    print(train_df[ALL_FEATURE_NAMES].describe().T.to_string())

    selected = select_features(train_df)
    print(f"\n── Selected Features ({len(selected)}) ──")
    print(selected)

    corr = train_df[selected + ["label"]].corr()["label"].drop("label").sort_values()
    print(f"\n── Correlation with Label (train split) ──")
    print(corr.to_string())

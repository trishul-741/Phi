"""
Feature engineering for URL and webpage text signals.

Updated for the non-visual implementation plan:
- no screenshot / visual dependency
- shared registered-domain parsing via tldextract
- feature set focused on textual, lexical, and structural risk signals
"""

from __future__ import annotations

import logging
import math
import re
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import tldextract
from sklearn.preprocessing import StandardScaler

from ml.config import cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("features")

_RE_IP = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")
_RE_HIDDEN_IFRAME = re.compile(
    r"<iframe[^>]{0,500}style\s*=\s*[\"'][^\"']{0,200}display\s*:\s*none",
    re.IGNORECASE,
)
_RE_FORM_ACTION = re.compile(r"<form[^>]*action\s*=", re.IGNORECASE)
_RE_PASSWORD = re.compile(r'<input[^>]+type\s*=\s*[\'"]?password\b', re.IGNORECASE)
_RE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_RE_SUBMIT = re.compile(r'<(?:button[^>]+type\s*=\s*[\'"]?submit\b|input[^>]+type\s*=\s*[\'"]?submit\b)', re.IGNORECASE)
_RE_HIDDEN_INPUT = re.compile(r'<input[^>]+type\s*=\s*[\'"]?hidden\b', re.IGNORECASE)
_RE_IFRAME = re.compile(r"<iframe\b", re.IGNORECASE)
_RE_SPA_MARKERS = re.compile(
    r"(data-reactroot|ng-version|__nuxt|__NEXT_DATA__|vue-router|<div id=[\"'](root|app)[\"']>)",
    re.IGNORECASE,
)
_RE_ANCHOR_HREF = re.compile(
    r'<a\b[^>]*\bhref\s*=\s*(?:["\']([^"\']+)["\']|([^\s\'">]+))',
    re.IGNORECASE,
)

_LOGIN_KEYWORDS = {
    "login", "signin", "sign-in", "sign_in", "password", "verify",
    "account", "security", "confirm", "authenticate", "credential",
    "update", "suspend", "restrict", "unusual",
}

SAFE_DOMAINS = {
    "google.com", "googleapis.com", "cloudflare.com", "jquery.com",
    "bootstrapcdn.com", "gstatic.com", "facebook.net", "twitter.com",
    "analytics.google.com",
}

TOP_BRANDS = {
    "paypal", "apple", "microsoft", "google", "amazon",
    "netflix", "chase", "wellsfargo", "facebook", "instagram",
    "bankofamerica", "linkedin", "dhl", "fedex",
}

_MAX_RAW_REGEX_BYTES = 50_000
_TLD = tldextract.TLDExtract(suffix_list_urls=None)


def _extract_registered_domain(netloc: str) -> str:
    host = (netloc or "").split(":")[0].lower().strip(".")
    if not host:
        return ""
    extracted = _TLD(host)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}"
    return extracted.domain or host


_SAFE_REGISTERED_DOMAINS = {_extract_registered_domain(domain) for domain in SAFE_DOMAINS}


def _subdomain_labels(netloc: str) -> list[str]:
    host = (netloc or "").split(":")[0].lower().strip(".")
    if not host:
        return []
    extracted = _TLD(host)
    subs = [p for p in extracted.subdomain.split(".") if p and p != "www"]
    return subs


def _subdomain_depth(netloc: str) -> int:
    return len(_subdomain_labels(netloc))


def _joined_alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((v / n) * math.log2(v / n) for v in freq.values())


def _login_keyword_density(text_lower: str) -> float:
    words = text_lower.split()
    if not words:
        return 0.0
    hits = sum(1 for w in words if w.strip(".,!?;:'\"()[]{}") in _LOGIN_KEYWORDS)
    return hits / len(words)


def _brand_impersonation_score(url: str, netloc: str) -> int:
    reg_domain = _extract_registered_domain(netloc)
    reg_sld = reg_domain.split(".")[0] if reg_domain else ""
    parsed = urlparse(url)
    search_area = " ".join(_subdomain_labels(netloc)) + " " + (parsed.path or "").lower()
    return sum(1 for brand in TOP_BRANDS if brand != reg_sld and brand in search_area)


def _title_mismatch(raw_html: str, page_netloc: str) -> int:
    match = _RE_TITLE.search(raw_html[:_MAX_RAW_REGEX_BYTES])
    if not match:
        return 0
    title = re.sub(r"\s+", " ", match.group(1).lower()).strip()
    reg_domain = _extract_registered_domain(page_netloc)
    reg_root = reg_domain.split(".")[0] if reg_domain else ""
    reg_tokens = set(re.split(r"[\W_]+", reg_root)) if reg_root else set()
    title_tokens = set(re.split(r"[\W_]+", title))
    reg_joined = _joined_alnum(reg_root)
    title_joined = _joined_alnum(title)
    title_tokens.discard("")
    reg_tokens.discard("")
    if reg_joined and reg_joined in title_joined:
        return 0
    if not reg_tokens or not title_tokens:
        return 0
    return int(reg_tokens.isdisjoint(title_tokens))


def _domain_title_token_overlap(raw_html: str, page_netloc: str) -> float:
    match = _RE_TITLE.search(raw_html[:_MAX_RAW_REGEX_BYTES])
    if not match:
        return 0.0
    title = match.group(1).lower()
    reg_domain = _extract_registered_domain(page_netloc)
    reg_root = reg_domain.split(".")[0] if reg_domain else ""
    reg_tokens = {t for t in re.split(r"[\W_]+", reg_root) if t}
    title_tokens = {t for t in re.split(r"[\W_]+", title) if t}
    if _joined_alnum(reg_root) and _joined_alnum(reg_root) in _joined_alnum(title):
        return 1.0
    if not reg_tokens or not title_tokens:
        return 0.0
    return len(reg_tokens & title_tokens) / max(len(reg_tokens), 1)


def _same_domain_form_action_ratio(raw_html: str, page_netloc: str) -> float:
    sample = raw_html[:_MAX_RAW_REGEX_BYTES]
    actions = re.findall(r'<form[^>]+action\s*=\s*[\'"]([^\'"]+)', sample, re.IGNORECASE)
    if not actions:
        return 0.0
    page_reg = _extract_registered_domain(page_netloc)
    same = 0
    for action in actions:
        try:
            action_netloc = urlparse(action).netloc
            if not action_netloc:
                same += 1  # relative path
                continue
            if _extract_registered_domain(action_netloc) == page_reg:
                same += 1
        except Exception:
            continue
    return same / max(len(actions), 1)


def _external_link_ratio(text_raw: str, page_netloc: str) -> float:
    sample = text_raw[:_MAX_RAW_REGEX_BYTES]
    hrefs = [quoted or bare for quoted, bare in _RE_ANCHOR_HREF.findall(sample)]
    if not hrefs:
        return 0.0

    page_reg = _extract_registered_domain(page_netloc)
    total_anchor_links = 0
    external_links = 0
    for href in hrefs:
        href = href.strip()
        if not href:
            continue
        href_lower = href.lower()
        if href_lower.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue

        total_anchor_links += 1
        try:
            netloc = urlparse(href).netloc.lower()
            if not netloc:
                continue
            reg = _extract_registered_domain(netloc)
            if not reg or reg == page_reg:
                continue
            if reg in _SAFE_REGISTERED_DOMAINS:
                continue
            external_links += 1
        except Exception:
            pass
    if total_anchor_links == 0:
        return 0.0
    return min(external_links / total_anchor_links, 1.0)


def _extract_url_features(url: str) -> dict:
    try:
        parsed = urlparse(url)
    except Exception:
        parsed = urlparse("")
    netloc = parsed.netloc or ""
    path = parsed.path or ""
    return {
        "url_length": len(url),
        "domain_length": len(netloc),
        "path_length": len(path),
        "num_dots": url.count("."),
        "num_hyphens": url.count("-"),
        "num_at": url.count("@"),
        "num_question": url.count("?"),
        "num_ampersand": url.count("&"),
        "num_digits": sum(c.isdigit() for c in url),
        "has_ip": int(bool(_RE_IP.search(netloc))),
        "domain_entropy": _shannon_entropy(netloc),
        "num_subdomains": max((netloc.split(":")[0].count(".")) - 1, 0),
        "subdomain_depth": _subdomain_depth(netloc),
        "brand_impersonation_score": _brand_impersonation_score(url, netloc),
    }


def _extract_text_features(text_clean: str, text_raw: str, page_netloc: str = "") -> dict:
    words = text_clean.split()
    word_count = len(words)
    text_lower = text_clean.lower()
    raw_sample = text_raw[:_MAX_RAW_REGEX_BYTES]
    password_fields = len(_RE_PASSWORD.findall(raw_sample))
    return {
        "text_length": len(text_clean),
        "word_count": word_count,
        "login_kw_density": _login_keyword_density(text_lower),
        "has_hidden_iframe": int(bool(_RE_HIDDEN_IFRAME.search(raw_sample))),
        "form_action_density": len(_RE_FORM_ACTION.findall(raw_sample)) / max(word_count, 1),
        "external_link_ratio": _external_link_ratio(text_raw, page_netloc),
        "is_modern_spa": int(bool(_RE_SPA_MARKERS.search(raw_sample))),
        "has_password_field": int(password_fields > 0),
        "num_password_fields": password_fields,
        "title_mismatch": _title_mismatch(raw_sample, page_netloc),
        "same_domain_form_action_ratio": _same_domain_form_action_ratio(raw_sample, page_netloc),
        "num_iframes": len(_RE_IFRAME.findall(raw_sample)),
        "num_hidden_inputs": len(_RE_HIDDEN_INPUT.findall(raw_sample)),
        "submit_button_count": len(_RE_SUBMIT.findall(raw_sample)),
        "domain_title_token_overlap": _domain_title_token_overlap(raw_sample, page_netloc),
    }


ALL_FEATURE_NAMES = [
    "url_length", "domain_length", "path_length", "num_dots", "num_hyphens",
    "num_at", "num_question", "num_ampersand", "num_digits", "has_ip",
    "domain_entropy", "num_subdomains", "subdomain_depth", "brand_impersonation_score",
    "text_length", "word_count", "login_kw_density", "has_hidden_iframe",
    "form_action_density", "external_link_ratio", "is_modern_spa",
    "has_password_field", "num_password_fields", "title_mismatch",
    "same_domain_form_action_ratio", "num_iframes", "num_hidden_inputs",
    "submit_button_count", "domain_title_token_overlap",
]


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
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
    logger.info("Engineered %d features", len(ALL_FEATURE_NAMES))
    return result


def select_features(
    train_df: pd.DataFrame,
    min_corr_with_label: float = cfg.FEAT_MIN_LABEL_CORR,
    max_cross_corr: float = cfg.FEAT_MAX_CROSS_CORR,
) -> list[str]:
    available = [f for f in ALL_FEATURE_NAMES if f in train_df.columns]
    corr_matrix = train_df[available + ["label"]].corr(numeric_only=True)
    label_corr = corr_matrix["label"].drop("label").abs()
    selected = label_corr[label_corr >= min_corr_with_label].index.tolist()
    dropped_low = sorted(set(available) - set(selected))
    if dropped_low:
        logger.info("Dropped low-correlation features: %s", dropped_low)

    if len(selected) > 1:
        feat_corr = train_df[selected].corr(numeric_only=True).abs()
        to_drop = set()
        for i in range(len(selected)):
            for j in range(i + 1, len(selected)):
                if feat_corr.iloc[i, j] > max_cross_corr:
                    fi, fj = selected[i], selected[j]
                    to_drop.add(fi if label_corr[fi] < label_corr[fj] else fj)
        selected = [f for f in selected if f not in to_drop]
        if to_drop:
            logger.info("Dropped cross-correlated features: %s", sorted(to_drop))

    logger.info("Selected %d features: %s", len(selected), selected)
    return selected


def fit_scaler(train_df: pd.DataFrame, feature_names: list[str]) -> StandardScaler:
    scaler = StandardScaler()
    scaler.fit(train_df[feature_names].values)
    return scaler


if __name__ == "__main__":
    from sklearn.model_selection import StratifiedShuffleSplit
    from ml.preprocessing import build_dataframe

    df = engineer_features(build_dataframe())
    splitter = StratifiedShuffleSplit(n_splits=1, test_size=cfg.VAL_SPLIT, random_state=cfg.RANDOM_SEED)
    train_idx, _ = next(splitter.split(df, df["label"]))
    train_df = df.iloc[train_idx].reset_index(drop=True)
    selected = select_features(train_df)
    print(train_df[selected].describe().T.to_string())

"""
Data loading and text cleaning utilities.

Loads records from MongoDB, reads text content from local disk,
cleans HTML residue, and constructs a pandas DataFrame ready for
feature engineering and model training.

v4 Fixes (Security):
  - Path traversal guard on minio_txt_key — a crafted key like ../../etc/passwd
    from a compromised MongoDB record can no longer escape LOCAL_DATASET_DIR.
  - MONGO_URI env var documented to support auth credentials.
  - Added empty-label guard to prevent silent mislabeling.
"""

import os
import re
import logging
import pandas as pd
from pymongo import MongoClient
from tqdm import tqdm
from ml.config import cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("preprocessing")

# ── Compiled regex patterns for cleaning ──────────────────────────────
_RE_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_RE_HTML_TAGS    = re.compile(r"<[^>]+>")
_RE_MULTI_SPACE  = re.compile(r"\s+")
_RE_HTML_ENTITIES = re.compile(r"&[a-zA-Z]+;|&#\d+;")

# Resolved base for path traversal checks (resolved once at import time)
_DATASET_BASE = os.path.realpath(cfg.LOCAL_DATASET_DIR)


def clean_text(raw: str) -> str:
    """
    Strip residual HTML tags, collapse whitespace, lowercase.
    The text files from the crawler are already mostly plain-text
    (BeautifulSoup .get_text()), but some HTML debris may remain.
    """
    # Prevent regex from freezing on gigantically obfuscated malware JS
    if len(raw) > 500_000:
        raw = raw[:500_000]
        
    text = _RE_SCRIPT_STYLE.sub(" ", raw)
    text = _RE_HTML_TAGS.sub(" ", text)
    text = _RE_HTML_ENTITIES.sub(" ", text)
    # split/join is significantly faster than \s+ regex
    text = " ".join(text.split())
    return text.lower()


def load_records_from_mongo() -> list:
    """
    Fetch all successful scan records from MongoDB.

    MONGO_URI should include credentials in production:
        mongodb://user:pass@host:27017/phish_guard?authSource=admin
    Set via environment variable MONGO_URI.

    Works around pymongo 4.16 $exists bug by fetching all success
    records and filtering in Python.
    """
    logger.info("Connecting to MongoDB...")
    client = MongoClient(cfg.MONGO_URI, serverSelectionTimeoutMS=5000)
    db     = client[cfg.DB_NAME]
    collection = db[cfg.COLLECTION_NAME]

    logger.info("Fetching success records...")
    all_success = list(collection.find({"status": "success"}))
    logger.info(f"Total success records in MongoDB: {len(all_success)}")

    # Filter to only records that have minio_txt_key (workaround for $exists bug)
    records = [r for r in all_success if r.get("minio_txt_key")]
    logger.info(f"Records with minio_txt_key: {len(records)}")

    client.close()
    return records


def _safe_local_path(txt_key: str) -> str | None:
    """
    Resolve the local path for a txt_key and verify it stays within
    LOCAL_DATASET_DIR. Returns None if path traversal is detected.

    This guards against a compromised or injected MongoDB record
    supplying a key like '../../etc/passwd' to read arbitrary files.
    """
    candidate = os.path.realpath(os.path.join(cfg.LOCAL_DATASET_DIR, txt_key))
    if not candidate.startswith(_DATASET_BASE + os.sep) and candidate != _DATASET_BASE:
        logger.warning(f"Path traversal blocked for key: {txt_key!r}")
        return None
    return candidate


def read_text_content(txt_key: str) -> str | None:
    """
    Read text content from the local dataset directory.
    Returns None if the file doesn't exist or the path is unsafe.
    """
    local_path = _safe_local_path(txt_key)
    if local_path is None:
        return None
    if not os.path.exists(local_path):
        return None
    try:
        with open(local_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None


def build_dataframe() -> pd.DataFrame:
    """
    Kaggle-aware DataFrame builder. 
    Uses metadata.csv if MONGO is unreachable or if IS_KAGGLE is True.
    """
    if cfg.IS_KAGGLE or not os.getenv("USE_MONGO", "false").lower() == "true":
        logger.info(f"Kaggle Mode: Loading metadata from {cfg.METADATA_CSV}")
        if not os.path.exists(cfg.METADATA_CSV):
            raise FileNotFoundError(f"Metadata file not found at {cfg.METADATA_CSV}")
        records_df = pd.read_csv(cfg.METADATA_CSV)
        records = records_df.to_dict('records')
    else:
        records = load_records_from_mongo()

    rows = []
    skipped = 0

    for rec in tqdm(records, desc="Loading text files"):
        txt_key = rec.get("minio_txt_key", "")
        raw_text = read_text_content(txt_key)

        if raw_text is None or len(raw_text.strip()) < 100:
            skipped += 1
            continue

        label_str = rec.get("label", "")
        if not label_str:
            skipped += 1
            continue

        rows.append({
            "url":           rec["url"],
            "label":         1 if label_str == "phishing" else 0,
            "label_str":     label_str,
            "source":        rec.get("source", "unknown"),
            "minio_txt_key": txt_key,
            "text_raw":      raw_text,
            "text_clean":    clean_text(raw_text),
        })

    df = pd.DataFrame(rows)
    logger.info(f"Built DataFrame: {len(df)} samples ({skipped} skipped)")
    return df


if __name__ == "__main__":
    df = build_dataframe()
    print(f"\nDataFrame shape: {df.shape}")
    print(f"\nColumn types:\n{df.dtypes}")
    print(f"\nLabel distribution:\n{df['label'].value_counts()}")
    print(f"\nSample record:\n{df.iloc[0]}")

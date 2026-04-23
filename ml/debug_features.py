"""
Inspect engineered features for a single URL/text sample.

Example:
    python -m ml.debug_features ^
        --url "https://paypal.example.com/login" ^
        --text-clean "verify your account now" ^
        --text-raw "<html><title>PayPal Login</title>...</html>"
"""

from __future__ import annotations

import argparse
import json

import pandas as pd

from ml.features import ALL_FEATURE_NAMES, engineer_features


def _to_builtin(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def main():
    parser = argparse.ArgumentParser(description="Print the engineered feature vector for a single sample")
    parser.add_argument("--url", required=True, help="Page URL")
    parser.add_argument("--text-clean", default="", help="Cleaned visible text")
    parser.add_argument("--text-raw", default="", help="Raw HTML/text source")
    args = parser.parse_args()

    df = pd.DataFrame([{
        "url": args.url,
        "label": 0,
        "label_str": "debug",
        "source": "debug_cli",
        "minio_txt_key": "",
        "text_clean": args.text_clean or "",
        "text_raw": args.text_raw or args.text_clean or "",
    }])
    row = engineer_features(df).iloc[0]

    payload = {
        name: _to_builtin(row[name])
        for name in ALL_FEATURE_NAMES
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

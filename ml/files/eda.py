"""
Exploratory Data Analysis for the PhishGuard dataset.

Generates visual plots for class distribution, URL lengths,
text token counts, lexical character frequencies, and feature correlations.
All plots are saved to ml/outputs/eda/.

v4 Fix:
  - select_features() is now called on the TRAIN split only, consistent
    with dataset.py and features.py. The original eda.py called it on the
    full df, which is a data leakage issue and inconsistent with v3 changes
    made to the rest of the pipeline.
  - Correlation plots use train split features to match what the model sees.
"""

import os
import re
import logging
import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedShuffleSplit
import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
from ml.config import cfg
from ml.preprocessing import build_dataframe
from ml.features import engineer_features, select_features, ALL_FEATURE_NAMES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eda")

# ── Verify feature list is in sync with features.py ──────────────────
# If this assertion fails, ALL_FEATURE_NAMES in features.py was changed
# without updating eda.py. Fix: import ALL_FEATURE_NAMES rather than
# hardcoding it here.
assert "login_kw_density" in ALL_FEATURE_NAMES, (
    "ALL_FEATURE_NAMES does not contain 'login_kw_density'. "
    "Check that features.py has been updated (has_login_keywords was renamed)."
)
assert "has_login_keywords" not in ALL_FEATURE_NAMES, (
    "'has_login_keywords' still in ALL_FEATURE_NAMES — should be 'login_kw_density'. "
    "Update features.py."
)

# ── Global style ──────────────────────────────────────────────────────
sns.set_theme(style="whitegrid", palette="muted", font_scale=1.1)
COLORS = {"phishing": "#e74c3c", "legitimate": "#2ecc71"}


def _save(fig, name: str):
    path = os.path.join(cfg.EDA_DIR, f"{name}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Saved: {path}")


def plot_class_distribution(df: pd.DataFrame):
    """Bar plot of phishing vs legitimate counts."""
    fig, ax = plt.subplots(figsize=(8, 5))
    counts  = df["label_str"].value_counts()
    bars    = ax.bar(counts.index, counts.values,
                     color=[COLORS.get(l, "#95a5a6") for l in counts.index],
                     edgecolor="white", linewidth=1.2)
    for bar, val in zip(bars, counts.values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 200,
                f"{val:,}", ha="center", va="bottom", fontweight="bold", fontsize=13)
    ax.set_title("Class Distribution", fontsize=16, fontweight="bold")
    ax.set_ylabel("Count")
    ax.set_xlabel("Label")
    _save(fig, "01_class_distribution")


def plot_url_length_distribution(df: pd.DataFrame):
    """Overlaid histograms of URL lengths by class."""
    fig, ax = plt.subplots(figsize=(10, 5))
    for label_str, color in COLORS.items():
        subset = df[df["label_str"] == label_str]["url"].str.len()
        ax.hist(subset, bins=80, alpha=0.6, label=label_str, color=color, edgecolor="white")
    ax.set_title("URL Length Distribution by Class", fontsize=16, fontweight="bold")
    ax.set_xlabel("URL Length (characters)")
    ax.set_ylabel("Frequency")
    ax.legend()
    ax.set_xlim(0, df["url"].str.len().quantile(0.99))
    _save(fig, "02_url_length_distribution")


def plot_text_token_distribution(df: pd.DataFrame):
    """Histograms of whitespace-tokenized word counts by class."""
    df = df.copy()
    df["_word_count"] = df["text_clean"].str.split().str.len()

    fig, ax = plt.subplots(figsize=(10, 5))
    for label_str, color in COLORS.items():
        subset = df[df["label_str"] == label_str]["_word_count"]
        ax.hist(subset, bins=80, alpha=0.6, label=label_str, color=color, edgecolor="white")
    ax.set_title("Text Word Count Distribution by Class", fontsize=16, fontweight="bold")
    ax.set_xlabel("Word Count")
    ax.set_ylabel("Frequency")
    ax.legend()
    ax.set_xlim(0, df["_word_count"].quantile(0.99))
    _save(fig, "03_text_token_distribution")


def plot_char_frequency(df: pd.DataFrame):
    """Heatmap of special character frequencies (per-URL average) by class."""
    special_chars = ["@", "-", ".", "/", "?", "=", "%", "~", "!", "_", "&"]
    data = {}
    for label_str in ["phishing", "legitimate"]:
        subset = df[df["label_str"] == label_str]["url"]
        row = {}
        for ch in special_chars:
            row[ch] = subset.str.count(re.escape(ch)).mean()
        data[label_str] = row

    heat_df = pd.DataFrame(data).T
    fig, ax  = plt.subplots(figsize=(12, 3.5))
    sns.heatmap(heat_df, annot=True, fmt=".2f", cmap="YlOrRd", ax=ax,
                linewidths=0.5, cbar_kws={"label": "Avg Count per URL"})
    ax.set_title("Lexical Character Frequency by Class", fontsize=16, fontweight="bold")
    ax.set_ylabel("")
    _save(fig, "04_char_frequency_heatmap")


def plot_feature_correlation(train_df: pd.DataFrame, selected_features: list):
    """
    Heatmap of correlations among selected features + label.

    FIX: Uses train_df only (not full df) to match the feature selection
    contract. Passing the full df would mix val labels into correlation
    computation, inconsistent with the rest of the v3+ pipeline.
    """
    cols = selected_features + ["label"]
    corr = train_df[cols].corr()

    fig, ax = plt.subplots(figsize=(14, 11))
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)
    sns.heatmap(corr, mask=mask, annot=True, fmt=".2f", cmap="RdBu_r",
                center=0, ax=ax, linewidths=0.5, square=True,
                cbar_kws={"shrink": 0.8})
    ax.set_title("Feature Correlation Matrix (train split)", fontsize=16, fontweight="bold")
    _save(fig, "05_feature_correlation")


def plot_label_correlation_bar(train_df: pd.DataFrame, feature_names: list):
    """
    Horizontal bar chart of each feature's correlation with label.
    FIX: Uses train_df only.
    """
    available = [f for f in feature_names if f in train_df.columns]
    corr = train_df[available + ["label"]].corr()["label"].drop("label").sort_values()

    fig, ax = plt.subplots(figsize=(10, max(6, len(corr) * 0.4)))
    colors  = ["#e74c3c" if v < 0 else "#2ecc71" for v in corr.values]
    ax.barh(corr.index, corr.values, color=colors, edgecolor="white")
    ax.axvline(0, color="gray", linewidth=0.8)
    ax.set_title("Feature Correlation with Label (train split, 1=phishing)",
                 fontsize=16, fontweight="bold")
    ax.set_xlabel("Pearson Correlation")
    _save(fig, "06_label_correlation_bar")


def print_summary_stats(df: pd.DataFrame):
    """Print summary statistics to console."""
    print("\n" + "=" * 60)
    print("            DATASET SUMMARY STATISTICS")
    print("=" * 60)
    print(f"  Total samples:      {len(df):,}")
    print(f"  Phishing:           {(df['label'] == 1).sum():,}")
    print(f"  Legitimate:         {(df['label'] == 0).sum():,}")
    print(f"  Imbalance ratio:    {(df['label'] == 1).sum() / max((df['label'] == 0).sum(), 1):.2f}")
    print(f"  Sources:            {df['source'].unique().tolist()}")
    print(f"\n  URL length   — mean: {df['url'].str.len().mean():.1f}, "
          f"std: {df['url'].str.len().std():.1f}, "
          f"max: {df['url'].str.len().max()}")
    wc = df["text_clean"].str.split().str.len()
    print(f"  Word count   — mean: {wc.mean():.1f}, "
          f"std: {wc.std():.1f}, "
          f"max: {wc.max()}")
    print("=" * 60)


# ── Entry Point ───────────────────────────────────────────────────────

def run_eda():
    """Run the full EDA pipeline."""

    logger.info("Step 1/6: Building DataFrame...")
    df = build_dataframe()

    logger.info("Step 2/6: Engineering features...")
    df = engineer_features(df)

    # FIX: Split first, then select features on train split only.
    logger.info("Step 3/6: Splitting and selecting features (train split only)...")
    splitter = StratifiedShuffleSplit(
        n_splits=1, test_size=cfg.VAL_SPLIT, random_state=cfg.RANDOM_SEED
    )
    train_idx, _ = next(splitter.split(df, df["label"]))
    train_df      = df.iloc[train_idx].reset_index(drop=True)
    selected      = select_features(train_df)

    print_summary_stats(df)

    logger.info("Step 4/6: Generating distribution plots...")
    plot_class_distribution(df)
    plot_url_length_distribution(df)
    plot_text_token_distribution(df)

    logger.info("Step 5/6: Generating character frequency heatmap...")
    plot_char_frequency(df)

    logger.info("Step 6/6: Generating correlation plots (train split)...")
    plot_feature_correlation(train_df, selected)
    plot_label_correlation_bar(train_df, ALL_FEATURE_NAMES)

    logger.info(f"EDA complete. All plots saved to: {cfg.EDA_DIR}")


if __name__ == "__main__":
    run_eda()

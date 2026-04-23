"""
Inference script for PhishGuardNet.
Accepts a single URL via command line.
Uses Playwright to dynamically load the webpage and extract text content.
Tokenizes text, encodes URL chars, extracts statistical features,
and predicts Phishing vs Legitimate using the trained PhishGuardNet model.
"""

import os
import sys
import argparse
import pickle
import numpy as np
import pandas as pd
import torch
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from transformers import DistilBertTokenizer

from ml.config import cfg
from ml.features import engineer_features
from ml.model import PhishGuardNet


def clean_html(html_content: str) -> str:
    """Extract legible text from raw HTML using BeautifulSoup."""
    if not html_content or not isinstance(html_content, str):
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    # Remove script and style elements
    for script in soup(["script", "style", "meta", "noscript"]):
        script.extract()
    text = soup.get_text(separator=" ")
    # Collapse whitespace
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    return " ".join(chunk for chunk in chunks if chunk)


def fetch_webpage_content(url: str, timeout_ms: int = 15000) -> str:
    """Dynamically load URL using Playwright and extract HTML content."""
    print(f"[*] Loading URL using Playwright: {url}")
    # Ensure scheme exists for Playwright
    if not url.startswith("http://") and not url.startswith("https://"):
        fetch_url = "http://" + url
    else:
        fetch_url = url

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            # Wait until there are no network connections for at least 500 ms.
            page.goto(fetch_url, timeout=timeout_ms, wait_until="networkidle")
            
            html_content = page.content()
            browser.close()
            print("[+] Webpage loaded successfully.")
            return html_content
    except PlaywrightTimeoutError:
        print("[-] Warning: Webpage load timed out. Processing URL-only features.")
        return ""
    except Exception as e:
        print(f"[-] Warning: Unreachable domain or error ({e}). Processing URL-only features.")
        return ""


def main():
    parser = argparse.ArgumentParser(description="Evaluate a single URL with PhishGuardNet.")
    parser.add_argument("url", type=str, help="The URL to classify (e.g., https://example.com)")
    args = parser.parse_args()

    device = torch.device(cfg.DEVICE)
    print(f"[*] Inference Device: {device}")

    # ── 1. Fetch and process content ─────────────────────────────────────────
    html_content = fetch_webpage_content(args.url)
    text_clean = clean_html(html_content)

    # ── 2. Create single-row DataFrame and engineer features ─────────────────
    print("[*] Extracting statistical features...")
    df = pd.DataFrame([{"url": args.url, "text_clean": text_clean, "text_raw": html_content}])
    
    # engineer_features computes all 18 features vector-wise
    df = engineer_features(df)

    # ── 3. Load pre-trained meta and scaler ──────────────────────────────────
    meta_path = os.path.join(cfg.CHECKPOINT_DIR, "train_meta.pt")
    scaler_path = os.path.join(cfg.CHECKPOINT_DIR, "scaler.pkl")
    model_path = os.path.join(cfg.CHECKPOINT_DIR, "best_model.pt")

    if not os.path.exists(meta_path) or not os.path.exists(scaler_path) or not os.path.exists(model_path):
        print("\n[!] Error: Missing model checkpoints, train_meta, or scaler.")
        print("Please ensure the training pipeline has fully run and the scaler script executed.")
        sys.exit(1)

    meta = torch.load(meta_path, map_location="cpu", weights_only=False)
    selected_features = meta["selected_features"]
    stat_feature_dim = meta["stat_feature_dim"]

    with open(scaler_path, "rb") as f:
        scaler = pickle.load(f)

    # Scale the selected statistical features
    stat_raw = df[selected_features].values
    stat_scaled = scaler.transform(stat_raw).astype(np.float32)
    stat_tensor = torch.tensor(stat_scaled, dtype=torch.float32).to(device)

    # ── 4. Encode URL into characters ────────────────────────────────────────
    url_lower = args.url.lower()
    url_tensor = torch.zeros(cfg.MAX_URL_LENGTH, dtype=torch.long)
    for i, char in enumerate(url_lower[: cfg.MAX_URL_LENGTH]):
        url_tensor[i] = cfg.char_dict.get(char, 0)
    url_tensor = url_tensor.unsqueeze(0).to(device)  # Add batch dimension

    # ── 5. Tokenize text using DistilBERT ────────────────────────────────────
    print("[*] Tokenizing text...")
    tokenizer = DistilBertTokenizer.from_pretrained(cfg.BERT_MODEL)
    text_inputs = tokenizer(
        text_clean,
        max_length=cfg.MAX_TEXT_LENGTH,
        padding="max_length",
        truncation=True,
        return_tensors="pt"
    )
    input_ids = text_inputs["input_ids"].to(device)
    attention_mask = text_inputs["attention_mask"].to(device)

    # ── 6. Load Model and Predict ────────────────────────────────────────────
    print("[*] Loading PhishGuardNet...")
    model = PhishGuardNet(stat_feature_dim=stat_feature_dim).to(device)
    checkpoint = torch.load(model_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    print("[*] Running inference...")
    with torch.no_grad():
        logits = model(input_ids, attention_mask, url_tensor, stat_tensor).squeeze(1)
        prob = torch.sigmoid(logits).item()

    # ── 7. Output Result ─────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("                PHISHGUARD RESULT")
    print("=" * 50)
    print(f"URL: {args.url}")
    print("-" * 50)
    
    cutoff = 0.5
    is_phishing = prob >= cutoff
    
    if is_phishing:
        # ANSI Red text for Phishing
        print(f"Classification: \033[91m\033[1mPHISHING\033[0m")
    else:
        # ANSI Green text for Legitimate
        print(f"Classification: \033[92m\033[1mLEGITIMATE\033[0m")
        
    print(f"Confidence:     {prob * 100:.2f}%")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()

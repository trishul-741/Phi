import os
import torch
import pandas as pd
from ml.config import cfg
from ml.features import engineer_features

def debug_features():
    print("Loading test metadata...")
    meta_path = os.path.join(cfg.CHECKPOINT_DIR, "train_meta.pt")
    meta = torch.load(meta_path, map_location="cpu", weights_only=False)
    selected_features = meta["selected_features"]
    print(f"Selected features ({len(selected_features)}): {selected_features}")
    
    # Let's run feature extraction on the test URLs
    test_data = [
        {"url": "https://unsplash.com/", "text_clean": "beautiful free images pictures", "text_raw": "<html><title>Unsplash</title><a href='https://unsplash.com/'>Link</a></html>"},
        {"url": "https://www.linkedin.com/feed/", "text_clean": "linkedin login register", "text_raw": "<html><title>LinkedIn</title><form action='https://linkedin.com/login'></form></html>"},
    ]
    df = pd.DataFrame(test_data)
    df_engineered = engineer_features(df)
    
    print("\nFeature values for Unsplash:")
    for f in selected_features:
        if f in df_engineered:
            print(f"  {f}: {df_engineered[f].iloc[0]}")
            
    print("\nFeature values for LinkedIn:")
    for f in selected_features:
        if f in df_engineered:
            print(f"  {f}: {df_engineered[f].iloc[1]}")

if __name__ == "__main__":
    debug_features()

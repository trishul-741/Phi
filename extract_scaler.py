import os
import pickle
import numpy as np
import pandas as pd
from ml.config import cfg

def debug_scaler():
    meta_path = os.path.join(cfg.CHECKPOINT_DIR, "train_meta.pt")
    import torch
    meta = torch.load(meta_path, map_location="cpu", weights_only=False)
    features = meta["selected_features"]
    
    scaler_path = os.path.join(cfg.CHECKPOINT_DIR, "scaler.pkl")
    with open(scaler_path, "rb") as f:
        scaler = pickle.load(f)
        
    print("Scaler parameter inspection:")
    for i, fname in enumerate(features):
        print(f"  {fname:<20} Mean: {scaler.mean_[i]:>10.4f} Scale: {scaler.scale_[i]:>10.4f}")

if __name__ == "__main__":
    debug_scaler()

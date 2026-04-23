import os
import torch
import platform
from dataclasses import dataclass, field
from typing import List

@dataclass
class Config:
    # ── Updated Kaggle Path ──────────────────────────────────────────
    IS_KAGGLE: bool = os.path.exists("/kaggle/working")
    
    # Updated to your specific dataset path
    KAGGLE_DATA_ROOT: str = "/kaggle/input/datasets/trishulg/phishguard-v4-production-data/local_dataset"

    # ── Paths ──────────────────────────────────────────────────────────
    MONGO_URI: str          = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
    
    LOCAL_DATASET_DIR: str  = field(init=False)
    METADATA_CSV: str       = field(init=False)
    
    OUTPUT_DIR: str         = "./ml/outputs"
    EDA_DIR: str            = "./ml/outputs/eda"
    CHECKPOINT_DIR: str     = "./ml/outputs/checkpoints"
    EVAL_DIR: str           = "./ml/outputs/eval"
    BEST_MODEL_NAME: str    = "best_model.pt"

    # ── Constants ─────────────────────────────────────────────────────
    DB_NAME: str            = "phish_guard"
    COLLECTION_NAME: str    = "scans"
    VAL_SPLIT: float        = 0.20
    RANDOM_SEED: int        = 42
    BERT_MODEL: str         = "distilbert-base-uncased"
    MAX_TEXT_LENGTH: int    = 512
    MAX_URL_LENGTH: int     = 200
    CHAR_VOCAB: str         = "abcdefghijklmnopqrstuvwxyz0123456789-,;.!?:'\"/\\|_@#$%^&*~`+-=<>()[]{}"
    
    # Training Hyperparameters
    BATCH_SIZE: int         = 32
    EPOCHS: int             = 30
    DROPOUT: float          = 0.4
    WEIGHT_DECAY: float     = 0.05
    EARLY_STOP_PATIENCE: int = 6
    LABEL_SMOOTHING: float  = 0.1
    BERT_FREEZE_LAYERS: int = 4
    
    DEVICE: str             = "cuda" if torch.cuda.is_available() else "cpu"
    USE_AMP: bool           = torch.cuda.is_available()
    PIN_MEMORY: bool        = torch.cuda.is_available()
    NUM_WORKERS: int        = 0
    
    FEAT_MIN_LABEL_CORR: float  = 0.02
    FEAT_MAX_CROSS_CORR: float  = 0.90
    LOW_VRAM_MODE: bool     = os.getenv("LOW_VRAM_MODE", "false").lower() == "true"

    def __post_init__(self):
        # Resolve paths based on environment
        if self.IS_KAGGLE:
            self.LOCAL_DATASET_DIR = self.KAGGLE_DATA_ROOT
            self.METADATA_CSV      = os.path.join(self.KAGGLE_DATA_ROOT, "metadata.csv")
        else:
            self.LOCAL_DATASET_DIR = "./local_dataset"
            self.METADATA_CSV      = "./local_dataset/metadata.csv"

        # Create writable output directories in /kaggle/working
        for d in [self.OUTPUT_DIR, self.EDA_DIR, self.CHECKPOINT_DIR, self.EVAL_DIR]:
            os.makedirs(d, exist_ok=True)

        if self.LOW_VRAM_MODE:
            self.BATCH_SIZE = 8
            self.MAX_TEXT_LENGTH = 256

        if platform.system() == "Windows":
            self.NUM_WORKERS = 0

    @property
    def best_model_path(self) -> str:
        return os.path.join(self.CHECKPOINT_DIR, self.BEST_MODEL_NAME)

    @property
    def train_meta_path(self) -> str:
        return os.path.join(self.CHECKPOINT_DIR, "train_meta.pt")

    @property
    def char_dict(self):
        return {c: i + 1 for i, c in enumerate(self.CHAR_VOCAB)}

    @property
    def char_vocab_size(self):
        return len(self.CHAR_VOCAB) + 1

cfg = Config()
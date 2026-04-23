"""
Central configuration for the non-visual PhishGuard pipeline.

Model A / visual branches have been removed from the implementation plan.
The production path is now:
    text/content + lexical URL + statistical features -> fusion classifier
"""

import os
import platform
import torch
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    IS_KAGGLE: bool = os.path.exists("/kaggle/working")
    KAGGLE_DATA_ROOT: str = "/kaggle/input/datasets/trishulg/phishguard-v4-production-data/local_dataset"

    # Paths
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
    LOCAL_DATASET_DIR: str = field(init=False)
    METADATA_CSV: str = field(init=False)

    OUTPUT_DIR: str = "./ml/outputs"
    EDA_DIR: str = "./ml/outputs/eda"
    CHECKPOINT_DIR: str = "./ml/outputs/checkpoints"
    EVAL_DIR: str = "./ml/outputs/eval"
    BEST_MODEL_NAME: str = "best_model.pt"
    SCALER_NAME: str = "scaler.pkl"

    # Dataset + split policy
    DB_NAME: str = "phish_guard"
    COLLECTION_NAME: str = "scans"
    VAL_SPLIT: float = 0.20
    CALIBRATION_SPLIT: float = 0.10
    RANDOM_SEED: int = 42

    # Core model config
    BERT_MODEL: str = "distilbert-base-uncased"
    MAX_TEXT_LENGTH: int = 512
    MAX_URL_LENGTH: int = 200
    CHAR_VOCAB: str = "abcdefghijklmnopqrstuvwxyz0123456789-,;.!?:'\"/\\|_@#$%^&*~`+-=<>()[]{}"

    # Training
    BATCH_SIZE: int = 32
    EPOCHS: int = 30
    DROPOUT: float = 0.4
    WEIGHT_DECAY: float = 0.05
    EARLY_STOP_PATIENCE: int = 6
    LABEL_SMOOTHING: float = 0.1
    USE_FOCAL_LOSS: bool = False
    BERT_FREEZE_LAYERS: int = 4
    BERT_LR: float = 2e-5
    HEAD_LR: float = 1e-4
    HARD_NEG_RATIO: float = 0.3
    MIXUP_ALPHA: float = 0.2
    SYNONYM_AUG_PROB: float = 0.10
    TYPO_AUG_PROB: float = 0.10

    # Architecture
    BERT_PROJ_DIM: int = 256
    CHAR_EMBED_DIM: int = 32
    CHAR_CNN_FILTERS: int = 64
    CHAR_CNN_KERNELS: List[int] = field(default_factory=lambda: [3, 4, 5])
    LSTM_HIDDEN: int = 128
    LSTM_LAYERS: int = 1
    CNN_PROJ_DIM: int = 256
    STAT_HIDDEN_DIM: int = 64
    STAT_OUT_DIM: int = 32
    CROSS_ATTN_DIM: int = 128
    CROSS_ATTN_HEADS: int = 4
    FUSION_HIDDEN: int = 256
    FUSION_MID: int = 128

    # Runtime
    DEVICE: str = "cuda" if torch.cuda.is_available() else "cpu"
    USE_AMP: bool = torch.cuda.is_available()
    PIN_MEMORY: bool = torch.cuda.is_available()
    NUM_WORKERS: int = 2
    LOW_VRAM_MODE: bool = os.getenv("LOW_VRAM_MODE", "false").lower() == "true"

    # Feature selection
    FEAT_MIN_LABEL_CORR: float = 0.08
    FEAT_MAX_CROSS_CORR: float = 0.80

    # Decision / production policy
    # Production floor chosen from observed safe-site conflict scans:
    # 0.72 is the smallest clean cutoff above the current worst false-positive
    # conflict score (~0.705) in local device history.
    DECISION_THRESHOLD: float = 0.72
    FP_PENALTY_WEIGHT: float = 2.0
    TARGET_FPR: float = 0.05

    def __post_init__(self):
        if self.IS_KAGGLE:
            self.LOCAL_DATASET_DIR = self.KAGGLE_DATA_ROOT
            self.METADATA_CSV = os.path.join(self.KAGGLE_DATA_ROOT, "metadata.csv")
        else:
            self.LOCAL_DATASET_DIR = "./local_dataset"
            self.METADATA_CSV = "./local_dataset/metadata.csv"

        for d in [self.OUTPUT_DIR, self.EDA_DIR, self.CHECKPOINT_DIR, self.EVAL_DIR]:
            os.makedirs(d, exist_ok=True)

        if self.LOW_VRAM_MODE:
            self.BATCH_SIZE = 8
            self.MAX_TEXT_LENGTH = 256

        if platform.system() == "Windows":
            self.NUM_WORKERS = 2

    @property
    def best_model_path(self) -> str:
        return os.path.join(self.CHECKPOINT_DIR, self.BEST_MODEL_NAME)

    @property
    def train_meta_path(self) -> str:
        return os.path.join(self.CHECKPOINT_DIR, "train_meta.pt")

    @property
    def scaler_path(self) -> str:
        return os.path.join(self.CHECKPOINT_DIR, self.SCALER_NAME)

    @property
    def calibrator_path(self) -> str:
        return os.path.join(self.EVAL_DIR, "calibrator.pkl")

    @property
    def optimal_threshold_path(self) -> str:
        return os.path.join(self.EVAL_DIR, "optimal_threshold.json")

    @property
    def char_dict(self):
        return {c: i + 1 for i, c in enumerate(self.CHAR_VOCAB)}

    @property
    def char_vocab_size(self):
        return len(self.CHAR_VOCAB) + 1


cfg = Config()

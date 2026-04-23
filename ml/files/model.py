"""
Multi-modal PhishGuard model architecture (v4).

v3 Changes:
  - Dropout increased to cfg.DROPOUT (0.4)
  - StochasticDepth on cross-attention residual
  - Attention Dropout on MultiheadAttention
  - BERT freeze increased to 4 layers
  - He initialization on non-BERT linear layers
  - Fusion MLP: extra dropout between layers

v4 Fixes:
  - CRITICAL FIX: _init_weights() now SKIPS all submodules inside ContentBERT.
    The original implementation called nn.init.kaiming_normal_ on ALL Linear
    layers, including those inside DistilBertModel. This destroyed the pretrained
    HuggingFace weights, making the content branch functionally equivalent to a
    random encoder and negating transfer learning entirely.
    Fix: named_modules() is used; any module whose name contains "content_bert"
    is skipped. Only the char-CNN, stat-FF, fusion MLP, and projection heads
    get He initialization.
  - FUSION_MID updated 64→128 (less aggressive bottleneck — see config.py).
  - Progressive unfreezing support: unfreeze_bert_layer(i) method added for
    use in training callbacks (freeze 4 layers initially, gradually unfreeze).
"""

import torch
import torch.nn as nn
from transformers import DistilBertModel
from ml.config import cfg


# ══════════════════════════════════════════════════════════════════════
# Stochastic Depth (DropPath)
# ══════════════════════════════════════════════════════════════════════

class StochasticDepth(nn.Module):
    """
    Stochastic Depth (DropPath) regularization.
    During training, randomly drops entire residual paths with probability p.
    At inference, scales the output by (1 - p) for consistency.
    """
    def __init__(self, drop_prob: float = 0.1):
        super().__init__()
        self.drop_prob = drop_prob

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if not self.training or self.drop_prob == 0.0:
            return x
        keep_prob     = 1 - self.drop_prob
        shape         = (x.shape[0],) + (1,) * (x.ndim - 1)
        random_tensor = torch.rand(shape, dtype=x.dtype, device=x.device)
        random_tensor = torch.floor(random_tensor + keep_prob)
        return x * random_tensor / keep_prob


# ══════════════════════════════════════════════════════════════════════
# Branch 1: ContentBERT
# ══════════════════════════════════════════════════════════════════════

class ContentBERT(nn.Module):
    """
    DistilBERT branch for webpage text content.
    Freezes cfg.BERT_FREEZE_LAYERS (4 of 6) transformer blocks.

    v5 Fix — weighted mean pooling replaces CLS-only pooling
    ──────────────────────────────────────────────────────────
    CLS token pooling works well when the entire sequence fits in 512
    tokens.  After the head+tail tokenisation fix in dataset.py, the
    input is now a stitched representation: first 128 tokens from the
    page header + last 382 tokens from the page body.  The CLS token
    attends over both halves, but because DistilBERT was pretrained on
    contiguous text, the cross-segment attention signal is weak for the
    tail portion.

    Attention-weighted mean pooling aggregates ALL non-padding token
    representations, giving the tail portion equal weight.  This is
    especially important for legitimate long pages where the main content
    (articles, product listings, breadcrumbs) lives in the tail.
    Phishing pages are uniformly short, so their CLS and mean-pool
    representations are nearly identical — no regression for phishing.
    """

    def __init__(self):
        super().__init__()
        self.bert = DistilBertModel.from_pretrained(cfg.BERT_MODEL)

        # Freeze embedding layer
        for param in self.bert.embeddings.parameters():
            param.requires_grad = False

        # Freeze first N transformer blocks
        for i in range(cfg.BERT_FREEZE_LAYERS):
            for param in self.bert.transformer.layer[i].parameters():
                param.requires_grad = False

        self.proj = nn.Sequential(
            nn.Linear(self.bert.config.dim, cfg.BERT_PROJ_DIM),
            nn.LayerNorm(cfg.BERT_PROJ_DIM),
            nn.ReLU(inplace=True),
            nn.Dropout(cfg.DROPOUT),
        )

    @staticmethod
    def _mean_pool(last_hidden_state: torch.Tensor,
                   attention_mask: torch.Tensor) -> torch.Tensor:
        """
        Compute attention-mask-weighted mean of token embeddings.
        Padding positions (mask=0) are excluded from the mean.
        """
        mask_expanded = attention_mask.unsqueeze(-1).float()        # (B, L, 1)
        sum_hidden    = (last_hidden_state * mask_expanded).sum(1)  # (B, D)
        count         = mask_expanded.sum(1).clamp(min=1e-9)        # (B, 1)
        return sum_hidden / count                                    # (B, D)

    def forward(self, input_ids, attention_mask):
        output = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        # Weighted mean over all non-padding tokens instead of CLS only
        pooled = self._mean_pool(output.last_hidden_state, attention_mask)
        return self.proj(pooled)

    def unfreeze_layer(self, layer_idx: int):
        """
        Unfreeze a specific transformer layer for progressive fine-tuning.
        Call from training loop: model.content_bert.unfreeze_layer(3) at epoch 3,
        then unfreeze_layer(2) at epoch 6 to gradually expand the learning signal.
        """
        if 0 <= layer_idx < len(self.bert.transformer.layer):
            for param in self.bert.transformer.layer[layer_idx].parameters():
                param.requires_grad = True


# ══════════════════════════════════════════════════════════════════════
# Branch 2: LexicalCharCNN + BiLSTM
# ══════════════════════════════════════════════════════════════════════

class LexicalCharCNN(nn.Module):
    """
    Character-level CNN with Bi-Directional LSTM for URL lexical analysis.
    """

    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(
            num_embeddings=cfg.char_vocab_size,
            embedding_dim=cfg.CHAR_EMBED_DIM,
            padding_idx=0,
        )

        self.convs = nn.ModuleList([
            nn.Sequential(
                nn.Conv1d(cfg.CHAR_EMBED_DIM, cfg.CHAR_CNN_FILTERS, kernel_size=k, padding=k // 2),
                nn.BatchNorm1d(cfg.CHAR_CNN_FILTERS),
                nn.ReLU(inplace=True),
            )
            for k in cfg.CHAR_CNN_KERNELS
        ])

        total_filters = cfg.CHAR_CNN_FILTERS * len(cfg.CHAR_CNN_KERNELS)

        self.bilstm = nn.LSTM(
            input_size=total_filters,
            hidden_size=cfg.LSTM_HIDDEN,
            num_layers=cfg.LSTM_LAYERS,
            batch_first=True,
            bidirectional=True,
            dropout=cfg.DROPOUT if cfg.LSTM_LAYERS > 1 else 0.0,
        )

        self.proj = nn.Sequential(
            nn.Linear(2 * cfg.LSTM_HIDDEN, cfg.CNN_PROJ_DIM),
            nn.LayerNorm(cfg.CNN_PROJ_DIM),
            nn.ReLU(inplace=True),
            nn.Dropout(cfg.DROPOUT),
        )

    def forward(self, url_chars):
        x = self.embedding(url_chars)
        x = x.permute(0, 2, 1)

        conv_outs = [conv(x) for conv in self.convs]
        min_len   = min(c.size(2) for c in conv_outs)
        conv_outs = [c[:, :, :min_len] for c in conv_outs]
        x         = torch.cat(conv_outs, dim=1).permute(0, 2, 1)

        _, (h_n, _) = self.bilstm(x)
        h_forward   = h_n[-2, :, :]
        h_backward  = h_n[-1, :, :]
        hidden      = torch.cat([h_forward, h_backward], dim=1)

        return self.proj(hidden)


# ══════════════════════════════════════════════════════════════════════
# Branch 3: StatFF
# ══════════════════════════════════════════════════════════════════════

class StatFF(nn.Module):
    """
    Feed-forward branch for engineered statistical / heuristic features.
    """

    def __init__(self, input_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, cfg.STAT_HIDDEN_DIM),
            nn.BatchNorm1d(cfg.STAT_HIDDEN_DIM),
            nn.ReLU(inplace=True),
            nn.Dropout(cfg.DROPOUT),
            nn.Linear(cfg.STAT_HIDDEN_DIM, cfg.STAT_OUT_DIM),
            nn.LayerNorm(cfg.STAT_OUT_DIM),
            nn.ReLU(inplace=True),
            nn.Dropout(cfg.DROPOUT * 0.5),
        )

    def forward(self, stat_features):
        return self.net(stat_features)


# ══════════════════════════════════════════════════════════════════════
# Fusion: Multi-Head Cross-Attention
# ══════════════════════════════════════════════════════════════════════

class CrossAttentionFusion(nn.Module):
    """
    Multi-Head Cross-Attention fusion block.
    StochasticDepth on residual connection for regularization.
    """

    def __init__(self):
        super().__init__()
        d = cfg.CROSS_ATTN_DIM

        self.proj_bert = nn.Linear(cfg.BERT_PROJ_DIM, d)
        self.proj_cnn  = nn.Linear(cfg.CNN_PROJ_DIM,  d)
        self.proj_stat = nn.Linear(cfg.STAT_OUT_DIM,   d)

        self.attn = nn.MultiheadAttention(
            embed_dim=d,
            num_heads=cfg.CROSS_ATTN_HEADS,
            dropout=cfg.DROPOUT,
            batch_first=True,
        )
        self.layer_norm  = nn.LayerNorm(d)
        self.dropout     = nn.Dropout(cfg.DROPOUT)
        self.stoch_depth = StochasticDepth(drop_prob=0.1)

    def forward(self, bert_out, cnn_out, stat_out):
        t_bert = self.proj_bert(bert_out)
        t_cnn  = self.proj_cnn(cnn_out)
        t_stat = self.proj_stat(stat_out)

        # Stack as sequence of 3 modality tokens: (B, 3, D)
        tokens      = torch.stack([t_bert, t_cnn, t_stat], dim=1)

        # Pre-Norm: normalize before attention
        tokens_norm = self.layer_norm(tokens)
        attn_out, _ = self.attn(tokens_norm, tokens_norm, tokens_norm)

        tokens = tokens + self.stoch_depth(self.dropout(attn_out))

        return tokens.reshape(tokens.size(0), -1)   # (B, 3*D)


# ══════════════════════════════════════════════════════════════════════
# PhishGuardNet — Full Model
# ══════════════════════════════════════════════════════════════════════

class PhishGuardNet(nn.Module):
    """
    Fusion Meta-Learner combining ContentBERT + LexicalCharCNN + StatFF
    via Multi-Head Cross-Attention.

    v4 Fix: _init_weights() skips ContentBERT to preserve pretrained weights.

    v5 Fix — modality confidence gates
    ─────────────────────────────────────
    Cross-attention treats all three branches as equally reliable per sample.
    In practice they are not: BERT is weak on near-empty SPA pages; char-CNN
    is uninformative on normal-word legitimate domains.  Per-branch learned
    scalar gates (σ(Linear(branch_out))) let the fusion suppress unreliable
    branches on a per-sample basis without hard-switching any branch off.
    Gates are initialised near 1.0 (bias=2.0) so training starts from the
    current behaviour and only diverges when the data supports it.

    v5 Fix — mean pooling in ContentBERT (see ContentBERT docstring)
    """

    def __init__(self, stat_feature_dim: int):
        super().__init__()
        self.content_bert = ContentBERT()
        self.lexical_cnn  = LexicalCharCNN()
        self.stat_ff      = StatFF(stat_feature_dim)
        self.cross_attn   = CrossAttentionFusion()

        # Per-branch confidence gates — scalar weight in [0, 1] per sample
        self.gate_bert = nn.Sequential(nn.Linear(cfg.BERT_PROJ_DIM, 1), nn.Sigmoid())
        self.gate_cnn  = nn.Sequential(nn.Linear(cfg.CNN_PROJ_DIM,  1), nn.Sigmoid())
        self.gate_stat = nn.Sequential(nn.Linear(cfg.STAT_OUT_DIM,  1), nn.Sigmoid())

        fusion_in = 3 * cfg.CROSS_ATTN_DIM

        self.fusion = nn.Sequential(
            nn.Linear(fusion_in, cfg.FUSION_HIDDEN),
            nn.BatchNorm1d(cfg.FUSION_HIDDEN),
            nn.ReLU(inplace=True),
            nn.Dropout(cfg.DROPOUT),
            nn.Linear(cfg.FUSION_HIDDEN, cfg.FUSION_MID),
            nn.ReLU(inplace=True),
            nn.Dropout(cfg.DROPOUT * 0.5),
            nn.Linear(cfg.FUSION_MID, 1),
        )

        self._init_weights()

    def _init_weights(self):
        """
        He init on all non-BERT Linear layers.
        Gate biases initialised to +2.0 so sigmoid ≈ 0.88 at startup —
        gates start open and close only when training data supports it.
        """
        for name, module in self.named_modules():
            if name.startswith("content_bert"):
                continue
            if isinstance(module, nn.Linear):
                nn.init.kaiming_normal_(module.weight, mode="fan_out", nonlinearity="relu")
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
            elif isinstance(module, (nn.BatchNorm1d, nn.LayerNorm)):
                nn.init.ones_(module.weight)
                nn.init.zeros_(module.bias)

        # Warm-start gates: bias → +2.0 so σ(2.0) ≈ 0.88
        for gate in [self.gate_bert, self.gate_cnn, self.gate_stat]:
            nn.init.constant_(gate[0].bias, 2.0)

    def forward(self, input_ids, attention_mask, url_chars, stat_features):
        bert_out = self.content_bert(input_ids, attention_mask)
        cnn_out  = self.lexical_cnn(url_chars)
        stat_out = self.stat_ff(stat_features)

        # Scale each branch by its learned confidence gate
        bert_out = bert_out * self.gate_bert(bert_out)
        cnn_out  = cnn_out  * self.gate_cnn(cnn_out)
        stat_out = stat_out * self.gate_stat(stat_out)

        fused = self.cross_attn(bert_out, cnn_out, stat_out)
        return self.fusion(fused)


def count_parameters(model: nn.Module) -> dict:
    total     = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    return {"total": total, "trainable": trainable, "frozen": total - trainable}


if __name__ == "__main__":
    model  = PhishGuardNet(stat_feature_dim=16)
    params = count_parameters(model)
    print(f"Total:      {params['total']:>12,}")
    print(f"Trainable:  {params['trainable']:>12,}")
    print(f"Frozen:     {params['frozen']:>12,}")

    B     = 4
    dummy = {
        "input_ids":      torch.randint(0, 30522, (B, cfg.MAX_TEXT_LENGTH)),
        "attention_mask": torch.ones(B, cfg.MAX_TEXT_LENGTH, dtype=torch.long),
        "url_chars":      torch.randint(0, cfg.char_vocab_size, (B, cfg.MAX_URL_LENGTH)),
        "stat_features":  torch.randn(B, 16),
    }
    out = model(**dummy)
    print(f"\nOutput shape:   {out.shape}")
    print(f"Sample logits:  {out.squeeze().tolist()}")

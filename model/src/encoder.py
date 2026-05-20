"""Two-stream encoder: mel (ResNet-18 adapted) + f0 (1D CNN) → L2-normalized embedding.

Shapes (defaults match configs/preproc.yaml + configs/model.yaml):

    mel  [B, 1, 80, 1000]   → ResNet-18 stem (1ch) → GAP → [B, 512]
    f0   [B, 2, ~334]       → 1D-CNN              → GAP → [B, 128]
    concat [B, 640] → Linear(640,512) GELU Dropout → Linear(512, D) → L2-norm
    embedding [B, D]
"""
from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision.models import resnet18


@dataclass
class EncoderConfig:
    embedding_dim: int = 256
    fusion_hidden: int = 512
    dropout: float = 0.1
    f0_in_channels: int = 2


class MelStream(nn.Module):
    """ResNet-18 with a 1-channel stem and no classification head."""

    def __init__(self):
        super().__init__()
        backbone = resnet18(weights=None)
        backbone.conv1 = nn.Conv2d(
            1, 64, kernel_size=7, stride=2, padding=3, bias=False
        )
        backbone.fc = nn.Identity()
        self.backbone = backbone
        self.out_dim = 512

    def forward(self, mel: torch.Tensor) -> torch.Tensor:
        # mel: [B, 1, n_mels, T]
        return self.backbone(mel)  # [B, 512]


class F0Stream(nn.Module):
    """Light 1D-CNN over [B, 2, T_f0]. ~250K params."""

    def __init__(self, in_channels: int = 2):
        super().__init__()

        def block(c_in, c_out, k, s=1, d=1):
            p = (k // 2) * d
            return nn.Sequential(
                nn.Conv1d(c_in, c_out, kernel_size=k, stride=s, padding=p, dilation=d),
                nn.BatchNorm1d(c_out),
                nn.GELU(),
            )

        self.net = nn.Sequential(
            block(in_channels, 32, k=7, s=2),
            block(32, 64, k=5, s=1),
            block(64, 96, k=5, s=2),
            block(96, 128, k=3, s=1, d=2),
            block(128, 128, k=3, s=2),
        )
        self.out_dim = 128

    def forward(self, f0: torch.Tensor) -> torch.Tensor:
        # f0: [B, 2, T]
        h = self.net(f0)            # [B, 128, T']
        return h.mean(dim=-1)       # GAP → [B, 128]


class TwoStreamEncoder(nn.Module):
    """Mel + F0 → L2-normalized embedding. Output is unit-norm on the hypersphere."""

    def __init__(self, cfg: EncoderConfig | None = None):
        super().__init__()
        cfg = cfg or EncoderConfig()
        self.cfg = cfg
        self.mel_stream = MelStream()
        self.f0_stream = F0Stream(in_channels=cfg.f0_in_channels)

        fused = self.mel_stream.out_dim + self.f0_stream.out_dim
        self.head = nn.Sequential(
            nn.Linear(fused, cfg.fusion_hidden),
            nn.GELU(),
            nn.Dropout(cfg.dropout),
            nn.Linear(cfg.fusion_hidden, cfg.embedding_dim),
        )

    @property
    def embedding_dim(self) -> int:
        return self.cfg.embedding_dim

    def forward(self, mel: torch.Tensor, f0: torch.Tensor) -> torch.Tensor:
        if mel.dim() == 3:
            mel = mel.unsqueeze(1)  # [B, n_mels, T] → [B, 1, n_mels, T]
        m = self.mel_stream(mel)
        p = self.f0_stream(f0)
        h = torch.cat([m, p], dim=1)
        z = self.head(h)
        return F.normalize(z, p=2, dim=1)

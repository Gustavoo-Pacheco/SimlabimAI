"""Sub-center ArcFace loss for song-identification training.

Thin wrapper over pytorch-metric-learning so the rest of the codebase can
treat the loss as a regular nn.Module (its learnable class prototypes go
into the optimizer alongside the encoder weights).
"""
from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
from pytorch_metric_learning.losses import SubCenterArcFaceLoss


@dataclass
class ArcFaceConfig:
    num_classes: int
    embedding_size: int = 256
    margin: float = 0.5
    scale: float = 30.0
    sub_centers: int = 3


class SongArcFaceLoss(nn.Module):
    """Wraps SubCenterArcFaceLoss. Forward: (embeddings, song_ids) → scalar."""

    def __init__(self, cfg: ArcFaceConfig):
        super().__init__()
        self.cfg = cfg
        self.loss_fn = SubCenterArcFaceLoss(
            num_classes=cfg.num_classes,
            embedding_size=cfg.embedding_size,
            margin=cfg.margin,
            scale=cfg.scale,
            sub_centers=cfg.sub_centers,
        )

    def forward(self, embeddings: torch.Tensor, song_ids: torch.Tensor) -> torch.Tensor:
        return self.loss_fn(embeddings, song_ids)

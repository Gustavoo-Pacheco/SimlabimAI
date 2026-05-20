"""Mel-level augmentation: SpecAugment + intra-class mixup."""
from __future__ import annotations

from dataclasses import dataclass

import torch
import torchaudio


@dataclass
class SpecAugmentConfig:
    time_mask_p: float = 0.7
    time_mask_count: int = 2
    time_mask_max: int = 30
    freq_mask_p: float = 0.7
    freq_mask_count: int = 2
    freq_mask_max: int = 20


class SpecAugmenter:
    """Applies time/freq masks to a log-mel tensor [n_mels, frames]."""

    def __init__(self, cfg: SpecAugmentConfig | None = None):
        cfg = cfg or SpecAugmentConfig()
        self.cfg = cfg
        self._time = torchaudio.transforms.TimeMasking(time_mask_param=cfg.time_mask_max)
        self._freq = torchaudio.transforms.FrequencyMasking(freq_mask_param=cfg.freq_mask_max)

    def __call__(self, mel: torch.Tensor) -> torch.Tensor:
        out = mel.clone()
        if torch.rand(()).item() < self.cfg.freq_mask_p:
            for _ in range(self.cfg.freq_mask_count):
                out = self._freq(out)
        if torch.rand(()).item() < self.cfg.time_mask_p:
            for _ in range(self.cfg.time_mask_count):
                out = self._time(out)
        return out


def intra_class_mixup(
    mels: torch.Tensor,
    f0s: torch.Tensor,
    song_ids: torch.Tensor,
    alpha: float = 0.2,
    p: float = 0.2,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Linearly mix each sample with a same-song partner in the batch.

    Labels remain unchanged because both endpoints share `song_id`. Samples
    whose batch has no same-song partner are passed through untouched.
    """
    if alpha <= 0 or p <= 0:
        return mels, f0s

    mels = mels.clone()
    f0s = f0s.clone()
    beta = torch.distributions.Beta(alpha, alpha)

    for i in range(mels.shape[0]):
        if torch.rand(()).item() >= p:
            continue
        same = (song_ids == song_ids[i]).nonzero(as_tuple=True)[0]
        same = same[same != i]
        if len(same) == 0:
            continue
        j = int(same[torch.randint(0, len(same), ()).item()].item())
        lam = float(beta.sample().item())
        mels[i] = lam * mels[i] + (1.0 - lam) * mels[j]
        f0s[i] = lam * f0s[i] + (1.0 - lam) * f0s[j]

    return mels, f0s

"""Deterministic preprocessing: trim, loudness normalize, crop.

Identical in train/val/test/inference — no randomness here unless explicitly
requested via `mode='random'` for crop.
"""
from __future__ import annotations

import numpy as np
import pyloudnorm as pyln
import torch
import torch.nn.functional as F


SAMPLE_RATE = 16000


def trim_by_confidence(
    waveform: torch.Tensor,
    confidence: torch.Tensor,
    frame_hop_ms: float,
    threshold: float = 0.5,
    margin_ms: float = 100.0,
) -> torch.Tensor:
    """Trim leading/trailing silence using a frame-level confidence signal.

    Returns the full waveform if no frame crosses the threshold (degenerate
    take — let downstream filtering / loss handle it).
    """
    above = confidence >= threshold
    if not above.any():
        return waveform

    above_int = above.to(torch.int32)
    first = int(torch.argmax(above_int).item())
    last = int(len(above) - 1 - torch.argmax(torch.flip(above_int, dims=[0])).item())

    hop_samples = int(round(frame_hop_ms * SAMPLE_RATE / 1000))
    margin_samples = int(round(margin_ms * SAMPLE_RATE / 1000))

    start = max(0, first * hop_samples - margin_samples)
    end = min(len(waveform), (last + 1) * hop_samples + margin_samples)
    return waveform[start:end]


def normalize_loudness(waveform: torch.Tensor, target_lufs: float = -23.0) -> torch.Tensor:
    """LUFS integrated loudness normalization (EBU R128).

    Falls back to a safe peak-normalize when pyloudnorm can't measure the
    audio (clip too short, silent, or DC-only). Output peak is hard-limited
    to 0.99 to prevent post-gain clipping.
    """
    audio = waveform.detach().cpu().numpy().astype(np.float64)
    duration_s = len(audio) / SAMPLE_RATE

    if duration_s < 0.5:
        peak = float(np.max(np.abs(audio)))
        if peak < 1e-6:
            return waveform
        return torch.from_numpy((audio * (0.5 / peak)).astype(np.float32))

    try:
        current = pyln.Meter(SAMPLE_RATE).integrated_loudness(audio)
    except ValueError:
        peak = float(np.max(np.abs(audio)))
        if peak < 1e-6:
            return waveform
        return torch.from_numpy((audio * (0.5 / peak)).astype(np.float32))

    if not np.isfinite(current):
        return waveform

    normalized = pyln.normalize.loudness(audio, current, target_lufs)
    peak = float(np.max(np.abs(normalized)))
    if peak > 0.99:
        normalized = normalized * (0.99 / peak)
    return torch.from_numpy(normalized.astype(np.float32))


def crop_or_pad(
    waveform: torch.Tensor,
    duration_samples: int,
    mode: str = "center",
) -> torch.Tensor:
    """Crop to fixed length, right-pad with zeros if shorter.

    mode: 'random' (uniform start, for training) or 'center' (deterministic).
    """
    n = len(waveform)
    if n >= duration_samples:
        if mode == "random":
            start = int(torch.randint(0, n - duration_samples + 1, ()).item())
        elif mode == "center":
            start = (n - duration_samples) // 2
        else:
            raise ValueError(f"unknown crop mode {mode!r}")
        return waveform[start : start + duration_samples]
    return F.pad(waveform, (0, duration_samples - n))

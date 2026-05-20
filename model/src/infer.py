"""Sliding-window inference: WAV → top-K songs.

Mirrors the runtime pipeline described in PLAN.md [11]: 10 s windows,
5 s hop, embed each window, query FAISS, aggregate scores per song via
sum-of-top-3 across windows.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from .enroll import Gallery
from .io import load_wav
from .preproc import SAMPLE_RATE, crop_or_pad, normalize_loudness, trim_by_confidence
from .representation import (
    MelConfig,
    MelExtractor,
    PestoConfig,
    PestoExtractor,
    coarse_confidence_for_trim,
    normalize_log_mel,
)


@dataclass
class InferenceResult:
    top: list[tuple[str, float]]  # [(song_slug, aggregated_score), ...]
    n_windows: int
    accepted: bool                # False iff best score < threshold
    threshold: float | None


def _windows(waveform: torch.Tensor, window_samples: int, hop_samples: int) -> list[torch.Tensor]:
    if len(waveform) <= window_samples:
        return [crop_or_pad(waveform, window_samples, mode="center")]
    out = []
    start = 0
    while start + window_samples <= len(waveform):
        out.append(waveform[start : start + window_samples])
        start += hop_samples
    return out


@torch.no_grad()
def infer_wav(
    wav_path: str | Path,
    *,
    model,
    gallery: Gallery,
    mel_cfg: MelConfig,
    pesto_cfg: PestoConfig,
    mel_mean: torch.Tensor | None,
    mel_std: torch.Tensor | None,
    window_s: float = 10.0,
    hop_s: float = 5.0,
    top_k_per_window: int = 3,
    top_n_return: int = 5,
    device: str = "cuda",
    target_lufs: float = -23.0,
    trim_step_size_ms: float = 50.0,
    trim_confidence_threshold: float = 0.5,
    trim_margin_ms: float = 100.0,
    threshold: float | None = None,
) -> InferenceResult:
    """Run the full inference pipeline on a single WAV file."""
    waveform = load_wav(wav_path)

    conf = coarse_confidence_for_trim(waveform, step_size_ms=trim_step_size_ms)
    waveform = trim_by_confidence(
        waveform, conf,
        frame_hop_ms=trim_step_size_ms,
        threshold=trim_confidence_threshold,
        margin_ms=trim_margin_ms,
    )
    waveform = normalize_loudness(waveform, target_lufs=target_lufs)

    window_samples = int(window_s * SAMPLE_RATE)
    hop_samples = int(hop_s * SAMPLE_RATE)
    chunks = _windows(waveform, window_samples, hop_samples)

    mel_extractor = MelExtractor(mel_cfg)
    pesto_extractor = PestoExtractor(pesto_cfg)

    model.eval()
    index = gallery.to_faiss()

    aggregated: dict[int, list[float]] = {}
    for chunk in chunks:
        mel = mel_extractor(chunk)
        if mel_mean is not None and mel_std is not None:
            mel = normalize_log_mel(mel, mel_mean, mel_std)
        f0 = pesto_extractor(chunk)
        mel_b = mel.unsqueeze(0).unsqueeze(0).to(device)   # [1, 1, n_mels, T]
        f0_b = f0.unsqueeze(0).to(device)                  # [1, 2, T_f0]
        embed = model(mel_b, f0_b).cpu().numpy().astype(np.float32)
        sims, idxs = index.search(embed, k=top_k_per_window)
        for sim, gallery_idx in zip(sims[0], idxs[0]):
            song_id = int(gallery.song_ids[gallery_idx])
            aggregated.setdefault(song_id, []).append(float(sim))

    # sum-of-top-k aggregator across windows
    scored: list[tuple[str, float]] = []
    for song_id, sims in aggregated.items():
        sims_sorted = sorted(sims, reverse=True)[:top_k_per_window]
        score = float(sum(sims_sorted))
        scored.append((gallery.id_to_slug[song_id], score))
    scored.sort(key=lambda pair: pair[1], reverse=True)

    top = scored[:top_n_return]
    accepted = True if (threshold is None or not top) else top[0][1] >= threshold
    return InferenceResult(top=top, n_windows=len(chunks), accepted=accepted, threshold=threshold)

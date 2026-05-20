"""Waveform-level data augmentation. Train-only.

All augs simulate a physical or channel transformation and must run on the
waveform before mel extraction. Set `leave_length_unchanged=True` on
TimeStretch so downstream tensor shapes stay stable.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np
import torch
from audiomentations import (
    AddBackgroundNoise,
    AddGaussianSNR,
    ApplyImpulseResponse,
    Compose,
    Gain,
    Mp3Compression,
    PitchShift,
    SevenBandParametricEQ,
    TimeStretch,
)


SAMPLE_RATE = 16000


def _try_build(cls, kwargs: dict, label: str) -> Any | None:
    try:
        return cls(**kwargs)
    except Exception as err:
        warnings.warn(f"skipping {label}: {err}")
        return None


def build_waveform_augmenter(cfg: dict) -> "WaveformAugmenter":
    """Compose the train-time waveform augmentation pipeline.

    Augs whose external resources (background noise, impulse responses) are
    missing get skipped with a warning rather than failing the run.
    """
    transforms: list[Any] = []

    if (g := cfg.get("gain")):
        transforms.append(Gain(
            min_gain_db=g["range_db"][0], max_gain_db=g["range_db"][1], p=g["p"]
        ))

    if (ps := cfg.get("pitch_shift")):
        transforms.append(PitchShift(
            min_semitones=ps["range_semitones"][0],
            max_semitones=ps["range_semitones"][1],
            p=ps["p"],
        ))

    if (ts := cfg.get("time_stretch")):
        transforms.append(TimeStretch(
            min_rate=ts["range_log"][0],
            max_rate=ts["range_log"][1],
            leave_length_unchanged=True,
            p=ts["p"],
        ))

    if (eq := cfg.get("eq")):
        t = _try_build(SevenBandParametricEQ, dict(
            min_gain_db=eq["range_db"][0],
            max_gain_db=eq["range_db"][1],
            p=eq["p"],
        ), "SevenBandParametricEQ")
        if t is not None:
            transforms.append(t)

    if (bn := cfg.get("background_noise")) and bn.get("path"):
        path = Path(bn["path"])
        if path.exists():
            transforms.append(AddBackgroundNoise(
                sounds_path=str(path),
                min_snr_db=bn["range_db"][0],
                max_snr_db=bn["range_db"][1],
                p=bn["p"],
            ))
        else:
            warnings.warn(
                f"background_noise path {path} does not exist — skipping"
            )

    if (gn := cfg.get("gaussian_snr")):
        transforms.append(AddGaussianSNR(
            min_snr_db=gn["range_db"][0], max_snr_db=gn["range_db"][1], p=gn["p"]
        ))

    if (ir := cfg.get("ir_reverb")) and ir.get("path"):
        path = Path(ir["path"])
        if path.exists():
            transforms.append(ApplyImpulseResponse(ir_path=str(path), p=ir["p"]))
        else:
            warnings.warn(f"ir_reverb path {path} does not exist — skipping")

    if (mp3 := cfg.get("mp3")):
        t = _try_build(Mp3Compression, dict(
            min_bitrate=mp3["bitrate_kbps"][0],
            max_bitrate=mp3["bitrate_kbps"][1],
            p=mp3["p"],
        ), "Mp3Compression")
        if t is not None:
            transforms.append(t)

    return WaveformAugmenter(Compose(transforms))


class WaveformAugmenter:
    def __init__(self, compose: Compose):
        self._compose = compose

    def __call__(self, waveform: torch.Tensor) -> torch.Tensor:
        audio = waveform.detach().cpu().numpy().astype(np.float32)
        augmented = self._compose(samples=audio, sample_rate=SAMPLE_RATE)
        return torch.from_numpy(augmented.astype(np.float32))

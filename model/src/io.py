"""WAV loading aligned with shared/wav.json invariants."""
from __future__ import annotations

import json
from pathlib import Path

import soundfile as sf
import torch

_SHARED = Path(__file__).resolve().parents[2] / "shared"
_WAV = json.loads((_SHARED / "wav.json").read_text())

EXPECTED_SR: int = _WAV["sampleRateHz"]
EXPECTED_CHANNELS: int = _WAV["channels"]


class WavLoadError(RuntimeError):
    pass


def load_wav(path: str | Path) -> torch.Tensor:
    """Return mono float32 tensor in [-1, 1], shape [num_samples].

    Validates sample rate and channel count against shared/wav.json. The
    collection/ pipeline guarantees both, so a mismatch is a real data
    integrity bug.
    """
    audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if sr != EXPECTED_SR:
        raise WavLoadError(f"{path}: sample rate {sr} != {EXPECTED_SR}")
    if audio.ndim == 2:
        if audio.shape[1] != EXPECTED_CHANNELS:
            raise WavLoadError(
                f"{path}: expected {EXPECTED_CHANNELS} channel(s), got shape {audio.shape}"
            )
        audio = audio[:, 0]
    return torch.from_numpy(audio)

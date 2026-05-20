"""Two-stream representation: log-mel-spectrogram + PESTO f0 contour."""
from __future__ import annotations

from dataclasses import dataclass

import torch
import torchaudio


SAMPLE_RATE = 16000


@dataclass
class MelConfig:
    n_fft: int = 400
    win_length: int = 400
    hop_length: int = 160
    n_mels: int = 128
    f_min: float = 50.0
    f_max: float = 8000.0
    mel_scale: str = "htk"
    power: float = 2.0


@dataclass
class PestoConfig:
    step_size_ms: float = 30.0
    confidence_threshold: float = 0.5
    median_subtract: bool = True


class MelExtractor:
    """Deterministic log-mel-spectrogram. No learnable params."""

    def __init__(self, cfg: MelConfig | None = None):
        cfg = cfg or MelConfig()
        self.cfg = cfg
        self._mel = torchaudio.transforms.MelSpectrogram(
            sample_rate=SAMPLE_RATE,
            n_fft=cfg.n_fft,
            win_length=cfg.win_length,
            hop_length=cfg.hop_length,
            n_mels=cfg.n_mels,
            f_min=cfg.f_min,
            f_max=cfg.f_max,
            mel_scale=cfg.mel_scale,
            power=cfg.power,
        )

    def __call__(self, waveform: torch.Tensor) -> torch.Tensor:
        """Waveform [T] or [1, T] → log-mel [n_mels, frames]."""
        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)
        mel = self._mel(waveform)
        mel = torch.log1p(mel)
        return mel.squeeze(0)


def normalize_log_mel(mel: torch.Tensor, mean: torch.Tensor, std: torch.Tensor) -> torch.Tensor:
    """Per-mel-bin standardization. mean/std are [n_mels]."""
    return (mel - mean.view(-1, 1)) / (std.view(-1, 1) + 1e-8)


class PestoExtractor:
    """Pitch + confidence via PESTO.

    Output is [2, frames]:
        row 0 = pitch in semitones (median-subtracted across high-confidence
                frames if cfg.median_subtract, low-confidence frames zeroed)
        row 1 = confidence in [0, 1]
    """

    def __init__(self, cfg: PestoConfig | None = None):
        cfg = cfg or PestoConfig()
        self.cfg = cfg
        import pesto  # imported lazily so smoke test errors are localized
        self._predict = pesto.predict

    def __call__(self, waveform: torch.Tensor) -> torch.Tensor:
        x = waveform.unsqueeze(0) if waveform.dim() == 1 else waveform
        _, pitch, confidence, _ = self._predict(
            x, sr=SAMPLE_RATE, step_size=self.cfg.step_size_ms
        )
        if pitch.dim() == 2:
            pitch = pitch.squeeze(0)
        if confidence.dim() == 2:
            confidence = confidence.squeeze(0)

        valid = confidence >= self.cfg.confidence_threshold
        if self.cfg.median_subtract and valid.any():
            median = torch.median(pitch[valid])
            pitch = pitch - median
        pitch = torch.where(valid, pitch, torch.zeros_like(pitch))

        return torch.stack([pitch, confidence], dim=0)


def coarse_confidence_for_trim(
    waveform: torch.Tensor, step_size_ms: float = 50.0
) -> torch.Tensor:
    """Run a coarse PESTO pass purely to get the confidence signal used by
    `preproc.trim_by_confidence`. Cheaper than the feature-extraction pass
    because the step is larger. Could be cached per take_id offline.
    """
    import pesto
    x = waveform.unsqueeze(0) if waveform.dim() == 1 else waveform
    _, _, confidence, _ = pesto.predict(x, sr=SAMPLE_RATE, step_size=step_size_ms)
    if confidence.dim() == 2:
        confidence = confidence.squeeze(0)
    return confidence

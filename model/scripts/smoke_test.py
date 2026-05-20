"""Smoke test for the Part 1 pipeline.

Runs every component on a synthetic waveform and prints intermediate shapes.
Validates that dependencies install correctly and the tensor shapes coming
out of this pipeline match what the CNN (Part 2) will expect.

Does not validate model quality — it's a wiring test.

Run from model/:
    .venv/bin/python scripts/smoke_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.augment_mel import SpecAugmenter, SpecAugmentConfig, intra_class_mixup
from src.augment_waveform import build_waveform_augmenter
from src.preproc import SAMPLE_RATE, crop_or_pad, normalize_loudness, trim_by_confidence
from src.representation import (
    MelConfig,
    MelExtractor,
    PestoConfig,
    PestoExtractor,
    coarse_confidence_for_trim,
)


def synth_waveform(duration_s: float = 7.0, freq_hz: float = 440.0) -> torch.Tensor:
    """Pitched signal with silent head and tail — exercises trim."""
    n = int(duration_s * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    body = 0.3 * np.sin(2 * np.pi * freq_hz * t * (1.0 + 0.05 * t))
    body[: int(0.5 * SAMPLE_RATE)] = 0.0
    body[-int(0.8 * SAMPLE_RATE) :] = 0.0
    return torch.from_numpy(body.astype(np.float32))


def main() -> None:
    cfg_path = ROOT / "configs" / "preproc.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())

    print("== Smoke test: preproc + representation + augmentation ==")
    print(f"config: {cfg_path}")
    print()

    wav = synth_waveform(duration_s=14.0)
    print(f"raw waveform                shape={tuple(wav.shape)} dur={len(wav)/SAMPLE_RATE:.2f}s")

    trim_cfg = cfg["trim"]
    conf = coarse_confidence_for_trim(wav, step_size_ms=trim_cfg["step_size_ms"])
    print(f"coarse PESTO confidence     shape={tuple(conf.shape)} max={float(conf.max()):.2f}")

    trimmed = trim_by_confidence(
        wav, conf,
        frame_hop_ms=trim_cfg["step_size_ms"],
        threshold=trim_cfg["confidence_threshold"],
        margin_ms=trim_cfg["margin_ms"],
    )
    print(f"after trim                  shape={tuple(trimmed.shape)} dur={len(trimmed)/SAMPLE_RATE:.2f}s")

    loud = normalize_loudness(trimmed, target_lufs=cfg["loudness"]["target_lufs"])
    print(f"after LUFS normalize        shape={tuple(loud.shape)} peak={float(loud.abs().max()):.3f}")

    duration_samples = int(cfg["crop"]["duration_s"] * SAMPLE_RATE)
    cropped = crop_or_pad(loud, duration_samples, mode=cfg["crop"]["train_mode"])
    print(f"after crop ({cfg['crop']['train_mode']} {cfg['crop']['duration_s']:.0f}s)  shape={tuple(cropped.shape)}")

    augmenter = build_waveform_augmenter(cfg["augment"]["waveform"])
    augmented = augmenter(cropped)
    print(f"after waveform aug          shape={tuple(augmented.shape)}")

    mel_extractor = MelExtractor(MelConfig(
        n_fft=cfg["mel"]["n_fft"],
        win_length=cfg["mel"]["win_length"],
        hop_length=cfg["mel"]["hop_length"],
        n_mels=cfg["mel"]["n_mels"],
        f_min=cfg["mel"]["f_min"],
        f_max=cfg["mel"]["f_max"],
        mel_scale=cfg["mel"]["mel_scale"],
        power=cfg["mel"]["power"],
    ))
    mel = mel_extractor(augmented)
    print(f"log-mel                     shape={tuple(mel.shape)} min={float(mel.min()):.3f} max={float(mel.max()):.3f}")

    sa = cfg["augment"]["mel"]["spec_augment"]
    spec_aug = SpecAugmenter(SpecAugmentConfig(
        time_mask_p=sa["time_mask"]["p"],
        time_mask_count=sa["time_mask"]["count"],
        time_mask_max=sa["time_mask"]["max_width"],
        freq_mask_p=sa["freq_mask"]["p"],
        freq_mask_count=sa["freq_mask"]["count"],
        freq_mask_max=sa["freq_mask"]["max_width"],
    ))
    mel_aug = spec_aug(mel)
    print(f"after SpecAugment           shape={tuple(mel_aug.shape)}")

    pesto = PestoExtractor(PestoConfig(
        step_size_ms=cfg["pesto"]["step_size_ms"],
        confidence_threshold=cfg["pesto"]["confidence_threshold"],
        median_subtract=cfg["pesto"]["median_subtract"],
    ))
    f0 = pesto(augmented)
    print(f"f0 stream (pitch, conf)     shape={tuple(f0.shape)} pitch_range=({float(f0[0].min()):.2f}, {float(f0[0].max()):.2f})")

    # exercise intra-class mixup on a fake batch of 4
    mels_b = torch.stack([mel_aug, mel_aug.flip(-1), mel_aug, mel_aug.flip(-1)])
    f0_b = torch.stack([f0, f0.flip(-1), f0, f0.flip(-1)])
    song_ids = torch.tensor([0, 0, 1, 1])
    mu = cfg["augment"]["mel"]["mixup_intra_class"]
    mels_m, f0_m = intra_class_mixup(mels_b, f0_b, song_ids, alpha=mu["alpha"], p=1.0)
    print(f"after intra-class mixup     mels={tuple(mels_m.shape)} f0={tuple(f0_m.shape)}")

    print()
    print("== OK ==")


if __name__ == "__main__":
    main()

"""Dump augmented samples to disk for visual + audio inspection.

For each selected take, writes one folder under `--out` containing:
  - original.wav            post-trim + LUFS + center-crop, no aug
  - original_mel.png        baseline log-mel
  - original_f0.png         baseline PESTO pitch + confidence
  - augKK.wav               waveform after waveform-augs (KK = 00..N-1)
  - augKK_mel.png           log-mel of augKK.wav (before SpecAugment)
  - augKK_mel_specaug.png   log-mel after SpecAugment
  - augKK_f0.png            PESTO output on augKK.wav

This is the sanity-check artifact mentioned at the end of PLAN.md. Not used
during training — purely for human inspection. Output dir is gitignored.

Run from model/:
    .venv/bin/python scripts/dump_augmented_samples.py
    .venv/bin/python scripts/dump_augmented_samples.py --num-takes 3 --augs-per-take 5
    .venv/bin/python scripts/dump_augmented_samples.py --take-ids <uuid1> <uuid2>
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
import torch
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.augment_mel import SpecAugmenter, SpecAugmentConfig
from src.augment_waveform import build_waveform_augmenter
from src.io import load_wav
from src.preproc import SAMPLE_RATE, crop_or_pad, normalize_loudness, trim_by_confidence
from src.representation import (
    MelConfig,
    MelExtractor,
    PestoConfig,
    PestoExtractor,
    coarse_confidence_for_trim,
)


def save_wav(waveform: torch.Tensor, path: Path) -> None:
    sf.write(str(path), waveform.numpy(), SAMPLE_RATE, subtype="PCM_16")


def save_mel(mel: torch.Tensor, path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.imshow(mel.numpy(), origin="lower", aspect="auto", interpolation="nearest", cmap="magma")
    ax.set_title(title)
    ax.set_xlabel("frame (~10 ms)")
    ax.set_ylabel("mel bin")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def save_f0(f0: torch.Tensor, path: Path, title: str) -> None:
    pitch = f0[0].numpy()
    confidence = f0[1].numpy()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 4), sharex=True)
    ax1.plot(pitch, color="C0", linewidth=1.0)
    ax1.set_ylabel("semitones\n(median-subtracted)")
    ax1.set_title(title)
    ax1.grid(alpha=0.3)
    ax2.plot(confidence, color="C1", linewidth=1.0)
    ax2.set_ylabel("confidence")
    ax2.set_xlabel("PESTO frame")
    ax2.set_ylim(0, 1)
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def deterministic_baseline(
    wav: torch.Tensor, cfg: dict, duration_samples: int
) -> torch.Tensor:
    trim_cfg = cfg["trim"]
    conf = coarse_confidence_for_trim(wav, step_size_ms=trim_cfg["step_size_ms"])
    wav = trim_by_confidence(
        wav,
        conf,
        frame_hop_ms=trim_cfg["step_size_ms"],
        threshold=trim_cfg["confidence_threshold"],
        margin_ms=trim_cfg["margin_ms"],
    )
    wav = normalize_loudness(wav, target_lufs=cfg["loudness"]["target_lufs"])
    wav = crop_or_pad(wav, duration_samples, mode="center")
    return wav


def load_rows(manifest: Path, statuses: set[str]) -> list[dict]:
    rows: list[dict] = []
    with manifest.open() as f:
        for r in csv.DictReader(f):
            if r["status"] in statuses:
                rows.append(r)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path,
                    default=ROOT.parent / "dataset" / "data" / "manifest.csv")
    ap.add_argument("--audio-root", type=Path,
                    default=ROOT.parent / "dataset" / "data")
    ap.add_argument("--num-takes", type=int, default=5)
    ap.add_argument("--augs-per-take", type=int, default=10)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "augmented_samples")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--take-ids", nargs="*", default=None,
                    help="specific take_ids to dump; overrides --num-takes")
    ap.add_argument("--status", nargs="+", default=["approved"],
                    help="manifest statuses to include (default: approved)")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    if not args.manifest.exists():
        sys.exit(f"manifest not found at {args.manifest} — run dataset/export.py first")

    cfg = yaml.safe_load((ROOT / "configs" / "preproc.yaml").read_text())
    duration_samples = int(cfg["crop"]["duration_s"] * SAMPLE_RATE)

    rows = load_rows(args.manifest, set(args.status))
    if not rows:
        sys.exit(f"no takes with status {args.status} in {args.manifest}")

    if args.take_ids:
        wanted = set(args.take_ids)
        rows = [r for r in rows if r["take_id"] in wanted]
        if not rows:
            sys.exit(f"none of the requested take_ids found in manifest")
    else:
        np.random.shuffle(rows)
        rows = rows[: args.num_takes]

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"Dumping {args.augs_per_take} augs for {len(rows)} take(s) → {args.out}")

    mel_keys = ("n_fft", "win_length", "hop_length", "n_mels",
                "f_min", "f_max", "mel_scale", "power")
    mel_extractor = MelExtractor(MelConfig(**{k: cfg["mel"][k] for k in mel_keys}))
    pesto = PestoExtractor(PestoConfig(
        step_size_ms=cfg["pesto"]["step_size_ms"],
        confidence_threshold=cfg["pesto"]["confidence_threshold"],
        median_subtract=cfg["pesto"]["median_subtract"],
    ))
    waveform_aug = build_waveform_augmenter(cfg["augment"]["waveform"])
    sa = cfg["augment"]["mel"]["spec_augment"]
    spec_aug = SpecAugmenter(SpecAugmentConfig(
        time_mask_p=sa["time_mask"]["p"],
        time_mask_count=sa["time_mask"]["count"],
        time_mask_max=sa["time_mask"]["max_width"],
        freq_mask_p=sa["freq_mask"]["p"],
        freq_mask_count=sa["freq_mask"]["count"],
        freq_mask_max=sa["freq_mask"]["max_width"],
    ))

    for row in rows:
        take_id = row["take_id"]
        song_slug = row["song_slug"]
        style = row["style"]
        audio_path = args.audio_root / row["storage_key"]
        out_dir = args.out / f"{song_slug}__{style}__{take_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"  {song_slug} / {style} / {take_id}")

        wav = load_wav(audio_path)
        baseline = deterministic_baseline(wav, cfg, duration_samples)
        baseline_mel = mel_extractor(baseline)
        baseline_f0 = pesto(baseline)

        save_wav(baseline, out_dir / "original.wav")
        save_mel(baseline_mel, out_dir / "original_mel.png",
                 f"{take_id[:8]} | baseline log-mel")
        save_f0(baseline_f0, out_dir / "original_f0.png",
                f"{take_id[:8]} | baseline f0")

        for k in range(args.augs_per_take):
            aug_wav = waveform_aug(baseline)
            aug_mel = mel_extractor(aug_wav)
            aug_mel_spec = spec_aug(aug_mel)
            aug_f0 = pesto(aug_wav)

            tag = f"aug{k:02d}"
            save_wav(aug_wav, out_dir / f"{tag}.wav")
            save_mel(aug_mel, out_dir / f"{tag}_mel.png",
                     f"{take_id[:8]} | {tag} | post waveform-aug")
            save_mel(aug_mel_spec, out_dir / f"{tag}_mel_specaug.png",
                     f"{take_id[:8]} | {tag} | post SpecAugment")
            save_f0(aug_f0, out_dir / f"{tag}_f0.png",
                    f"{take_id[:8]} | {tag} | f0")

    print(f"\nDone. Open {args.out}/<song>__<style>__<take>/ to inspect.")


if __name__ == "__main__":
    main()

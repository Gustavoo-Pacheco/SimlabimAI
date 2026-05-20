"""Compute per-bin mean/std of the log-mel over the TRAIN split.

No augmentation. Center crop only. Output saved to data/stats.json and
loaded by the Dataset at training/eval time.

Run from model/:
    .venv/bin/python scripts/compute_mel_stats.py
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import torch
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.io import load_wav
from src.preproc import SAMPLE_RATE, crop_or_pad, normalize_loudness, trim_by_confidence
from src.representation import MelConfig, MelExtractor, coarse_confidence_for_trim
from src.splits import load_splits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path,
                    default=ROOT.parent / "dataset" / "data" / "manifest.csv")
    ap.add_argument("--audio-root", type=Path,
                    default=ROOT.parent / "dataset" / "data")
    ap.add_argument("--splits", type=Path, default=ROOT / "data" / "splits.json")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "stats.json")
    ap.add_argument("--status", nargs="+", default=["approved", "pending"])
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "configs" / "preproc.yaml").read_text())
    duration_samples = int(cfg["crop"]["duration_s"] * SAMPLE_RATE)
    trim_cfg = cfg["trim"]

    splits = load_splits(args.splits)
    train_slugs = set(splits.train)

    rows = []
    with args.manifest.open() as f:
        for r in csv.DictReader(f):
            if r["status"] in set(args.status) and r["song_slug"] in train_slugs:
                rows.append(r)

    if not rows:
        sys.exit("no train takes found — check splits.json and manifest")

    print(f"computing stats over {len(rows)} train takes...")
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

    n_mels = cfg["mel"]["n_mels"]
    sum_x = torch.zeros(n_mels, dtype=torch.float64)
    sum_x2 = torch.zeros(n_mels, dtype=torch.float64)
    count = 0

    for i, r in enumerate(rows):
        path = args.audio_root / r["storage_key"]
        wav = load_wav(path)
        conf = coarse_confidence_for_trim(wav, step_size_ms=trim_cfg["step_size_ms"])
        wav = trim_by_confidence(
            wav, conf,
            frame_hop_ms=trim_cfg["step_size_ms"],
            threshold=trim_cfg["confidence_threshold"],
            margin_ms=trim_cfg["margin_ms"],
        )
        wav = normalize_loudness(wav, target_lufs=cfg["loudness"]["target_lufs"])
        wav = crop_or_pad(wav, duration_samples, mode="center")
        mel = mel_extractor(wav).to(torch.float64)
        sum_x += mel.sum(dim=1)
        sum_x2 += (mel * mel).sum(dim=1)
        count += mel.shape[1]
        if (i + 1) % 5 == 0 or i + 1 == len(rows):
            print(f"  {i+1}/{len(rows)}")

    mean = (sum_x / count).tolist()
    var = (sum_x2 / count) - torch.tensor(mean) ** 2
    std = torch.sqrt(var.clamp_min(0.0)).tolist()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "n_mels": n_mels,
        "mean": mean,
        "std": std,
        "frames_aggregated": count,
        "takes": len(rows),
    }, indent=2))
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()

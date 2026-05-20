"""Torch Dataset that ties preproc + representation + augmentation together.

Reads the CSV manifest produced by `dataset/export.py`. One row per approved
take. Yields a dict with mel, f0, song_id, style, take_id.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import torch
from torch.utils.data import Dataset

from .augment_mel import SpecAugmenter
from .augment_waveform import WaveformAugmenter
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
class ManifestRow:
    take_id: str
    song_slug: str
    style: str
    audio_path: Path


def load_manifest(
    manifest_csv: Path,
    audio_root: Path,
    statuses: tuple[str, ...] = ("approved",),
) -> list[ManifestRow]:
    """Parse manifest.csv from `dataset/export.py`. Filter by status.

    `audio_root` is the directory under which `storage_key` resolves —
    typically `dataset/data/` (since storage_key starts with `raw_audio/...`).
    """
    rows: list[ManifestRow] = []
    with manifest_csv.open() as f:
        for r in csv.DictReader(f):
            if r["status"] not in statuses:
                continue
            rows.append(ManifestRow(
                take_id=r["take_id"],
                song_slug=r["song_slug"],
                style=r["style"],
                audio_path=audio_root / r["storage_key"],
            ))
    return rows


def build_song_id_map(manifest: list[ManifestRow]) -> dict[str, int]:
    """Stable slug→int mapping. Sorted alphabetically for determinism."""
    slugs = sorted({r.song_slug for r in manifest})
    return {slug: idx for idx, slug in enumerate(slugs)}


class TakesDataset(Dataset):
    """One sample = one take, fully preprocessed and (optionally) augmented.

    Returns:
        mel:     [n_mels, frames]   log-mel (normalized iff stats provided)
        f0:      [2, frames_pesto]  pitch + confidence (PESTO)
        song_id: int                stable index into the song catalogue
        style:   str                'cantar' | 'cantarolar' | 'assobiar'
        take_id: str                the original take uuid
    """

    def __init__(
        self,
        manifest: list[ManifestRow],
        song_slug_to_id: dict[str, int],
        *,
        train: bool,
        mel_cfg: MelConfig | None = None,
        pesto_cfg: PestoConfig | None = None,
        waveform_augmenter: WaveformAugmenter | None = None,
        spec_augmenter: SpecAugmenter | None = None,
        mel_stats_path: Path | None = None,
        crop_duration_s: float = 5.0,
        trim_step_size_ms: float = 50.0,
        trim_confidence_threshold: float = 0.5,
        trim_margin_ms: float = 100.0,
        target_lufs: float = -23.0,
    ):
        self.manifest = manifest
        self.song_slug_to_id = song_slug_to_id
        self.train = train
        self.mel = MelExtractor(mel_cfg)
        self.pesto = PestoExtractor(pesto_cfg)
        self.waveform_aug = waveform_augmenter
        self.spec_aug = spec_augmenter
        self.duration_samples = int(crop_duration_s * SAMPLE_RATE)
        self.trim_step_size_ms = trim_step_size_ms
        self.trim_confidence_threshold = trim_confidence_threshold
        self.trim_margin_ms = trim_margin_ms
        self.target_lufs = target_lufs

        if mel_stats_path and mel_stats_path.exists():
            stats = json.loads(mel_stats_path.read_text())
            self.mel_mean = torch.tensor(stats["mean"], dtype=torch.float32)
            self.mel_std = torch.tensor(stats["std"], dtype=torch.float32)
        else:
            self.mel_mean = None
            self.mel_std = None

    def __len__(self) -> int:
        return len(self.manifest)

    def __getitem__(self, idx: int) -> dict:
        row = self.manifest[idx]

        waveform = load_wav(row.audio_path)

        confidence = coarse_confidence_for_trim(
            waveform, step_size_ms=self.trim_step_size_ms
        )
        waveform = trim_by_confidence(
            waveform,
            confidence,
            frame_hop_ms=self.trim_step_size_ms,
            threshold=self.trim_confidence_threshold,
            margin_ms=self.trim_margin_ms,
        )

        waveform = normalize_loudness(waveform, target_lufs=self.target_lufs)

        mode = "random" if self.train else "center"
        waveform = crop_or_pad(waveform, self.duration_samples, mode=mode)

        if self.train and self.waveform_aug is not None:
            waveform = self.waveform_aug(waveform)

        mel = self.mel(waveform)
        if self.train and self.spec_aug is not None:
            mel = self.spec_aug(mel)
        if self.mel_mean is not None:
            mel = normalize_log_mel(mel, self.mel_mean, self.mel_std)

        f0 = self.pesto(waveform)

        return {
            "mel": mel,
            "f0": f0,
            "song_id": self.song_slug_to_id[row.song_slug],
            "style": row.style,
            "take_id": row.take_id,
        }

"""Shared helpers: slugification, manifest I/O, paths."""
from __future__ import annotations

import csv
import json
import pathlib
import re
import threading

from unidecode import unidecode

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
AUDIO_DIR = DATA_DIR / "raw_audio"
MANIFEST = DATA_DIR / "manifest.csv"
PROVENANCE = DATA_DIR / "provenance.csv"
SONGS_DIR = ROOT / "songs"

# Mirrors dataset/export.py column order exactly so downstream tools can read both.
MANIFEST_COLUMNS = [
    "take_id",
    "song_slug",
    "song_title",
    "song_author",
    "style",
    "duration_s",
    "audio_sha256",
    "storage_key",
    "status",
    "created_at",
]

# Extra columns kept in a sidecar so we don't break manifest compatibility.
PROVENANCE_COLUMNS = [
    "take_id",
    "source",
    "video_id",
    "video_title",
    "video_url",
    "video_duration_s",
    "query",
    "clip_start_s",
    "clip_dur_s",
]

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(s: str, max_len: int = 64) -> str:
    """Match shared/slugs.json: ^[a-z0-9-]+$, length 1..64."""
    s = unidecode(s or "").lower()
    s = _SLUG_RE.sub("-", s).strip("-")
    if not s:
        s = "untitled"
    return s[:max_len].rstrip("-") or "untitled"


def load_seen_video_ids() -> set[str]:
    if not PROVENANCE.exists():
        return set()
    with PROVENANCE.open() as f:
        return {row["video_id"] for row in csv.DictReader(f) if row.get("video_id")}


class CsvAppender:
    """Thread-safe append-only CSV writer that writes a header if file is new."""

    def __init__(self, path: pathlib.Path, columns: list[str]) -> None:
        self.path = path
        self.columns = columns
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with self.path.open("w", newline="") as f:
                csv.DictWriter(f, fieldnames=columns).writeheader()

    def append(self, row: dict) -> None:
        with self._lock, self.path.open("a", newline="") as f:
            csv.DictWriter(f, fieldnames=self.columns).writerow(
                {k: row.get(k, "") for k in self.columns}
            )


def read_songs(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return json.load(f)

"""Train/val/test splits by song slug.

Split unit is **song**, not take — songs in val/test are disjoint from train,
so the encoder must generalize to unseen songs (face-recognition style).

Within val/test, each song's takes are deterministically partitioned into
gallery (enroll) and query (probe) by hashing the take_id.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Splits:
    seed: int
    train: list[str]
    val: list[str]
    test: list[str]

    def as_dict(self) -> dict:
        return {
            "seed": self.seed,
            "train": self.train,
            "val": self.val,
            "test": self.test,
        }


def make_splits(
    song_slugs: list[str],
    ratios: tuple[float, float, float] = (0.7, 0.15, 0.15),
    seed: int = 0,
) -> Splits:
    """Random song-level split with fixed seed."""
    assert abs(sum(ratios) - 1.0) < 1e-6, "ratios must sum to 1"
    slugs = sorted(set(song_slugs))
    rng = random.Random(seed)
    rng.shuffle(slugs)
    n = len(slugs)
    n_train = int(round(n * ratios[0]))
    n_val = int(round(n * ratios[1]))
    return Splits(
        seed=seed,
        train=sorted(slugs[:n_train]),
        val=sorted(slugs[n_train : n_train + n_val]),
        test=sorted(slugs[n_train + n_val :]),
    )


def save_splits(splits: Splits, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(splits.as_dict(), indent=2))


def load_splits(path: Path) -> Splits:
    d = json.loads(path.read_text())
    return Splits(seed=d["seed"], train=d["train"], val=d["val"], test=d["test"])


def is_gallery_take(take_id: str, seed: int = 0) -> bool:
    """Deterministically assign a take to gallery (True) or query (False).

    50/50 partition stable across runs — depends only on take_id + seed.
    """
    digest = hashlib.sha256(f"{seed}|{take_id}".encode()).digest()
    return digest[0] < 128

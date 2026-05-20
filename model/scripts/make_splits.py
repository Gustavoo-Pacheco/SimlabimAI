"""Generate train/val/test splits by song from the manifest.

Run from model/:
    .venv/bin/python scripts/make_splits.py
    .venv/bin/python scripts/make_splits.py --seed 1 --ratios 0.7 0.15 0.15
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.splits import make_splits, save_splits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path,
                    default=ROOT.parent / "dataset" / "data" / "manifest.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "splits.json")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ratios", nargs=3, type=float, default=[0.7, 0.15, 0.15])
    ap.add_argument("--status", nargs="+", default=["approved", "pending"],
                    help="manifest statuses to include")
    args = ap.parse_args()

    if not args.manifest.exists():
        sys.exit(f"manifest not found: {args.manifest}")

    slugs: list[str] = []
    with args.manifest.open() as f:
        for r in csv.DictReader(f):
            if r["status"] in set(args.status):
                slugs.append(r["song_slug"])

    if not slugs:
        sys.exit(f"no rows with status in {args.status}")

    splits = make_splits(slugs, ratios=tuple(args.ratios), seed=args.seed)
    save_splits(splits, args.out)

    print(f"songs total: {len(set(slugs))}")
    print(f"train: {len(splits.train)} songs")
    print(f"val:   {len(splits.val)} songs")
    print(f"test:  {len(splits.test)} songs")
    print(f"written to {args.out}")


if __name__ == "__main__":
    main()

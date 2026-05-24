"""
verify.py — re-hash every WAV referenced in manifest.csv and flag drift.

    .venv/bin/python scripts/verify.py
"""
from __future__ import annotations

import csv
import hashlib
import pathlib
import sys

from _common import MANIFEST, ROOT


def sha256_of_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not MANIFEST.exists():
        print(f"no manifest at {MANIFEST}", file=sys.stderr)
        return 2
    bad = missing = ok = 0
    with MANIFEST.open() as f:
        for row in csv.DictReader(f):
            p = ROOT / "data" / row["storage_key"]
            if not p.exists():
                missing += 1
                print(f"MISSING {row['storage_key']}")
                continue
            if sha256_of_file(p) != row["audio_sha256"]:
                bad += 1
                print(f"HASH MISMATCH {row['storage_key']}")
            else:
                ok += 1
    print(f"\nok={ok} missing={missing} mismatched={bad}")
    return 0 if (bad == 0 and missing == 0) else 1


if __name__ == "__main__":
    sys.exit(main())

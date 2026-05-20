"""
export.py — pull the dataset out of Supabase into ./data/.

Produces:
    data/manifest.csv                              # one row per exported take
    data/raw_audio/<song-slug>/<take-uuid>.wav     # the audio bytes

Idempotent: re-running only fetches takes whose WAV is missing or whose on-disk
SHA-256 disagrees with the DB. Safe to run after every collection batch.

Run from dataset/:
    .venv/bin/python export.py
    .venv/bin/python export.py --limit 5         # smoke test
    .venv/bin/python export.py --include-rejected
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import pathlib
import sys
import tempfile
import time
from dataclasses import dataclass

import psycopg
import requests
from dotenv import load_dotenv

# ─── config ─────────────────────────────────────────────────────────────────

HERE = pathlib.Path(__file__).parent
load_dotenv(HERE / ".env")

DATABASE_URL = os.environ["DATABASE_URL"]
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
BUCKET = os.environ["SUPABASE_BUCKET"]

DATA_DIR = HERE / "data"
AUDIO_DIR = DATA_DIR / "raw_audio"
MANIFEST = DATA_DIR / "manifest.csv"

# Stream downloads in 64 KB chunks. Big enough to keep syscall overhead low,
# small enough that a 40 MB WAV never sits whole in Python memory.
CHUNK_BYTES = 64 * 1024

# Columns written to manifest.csv — order is the on-disk order.
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


@dataclass
class TakeRow:
    take_id: str
    song_slug: str
    song_title: str
    song_author: str
    style: str
    duration_s: float | None
    audio_sha256: str
    storage_key: str
    status: str
    created_at: int

    def as_manifest_dict(self) -> dict:
        return {k: getattr(self, k) for k in MANIFEST_COLUMNS}


# ─── helpers ────────────────────────────────────────────────────────────────


def sha256_of_file(path: pathlib.Path) -> str:
    """Hash a file in 1 MB chunks — never loads it whole into memory."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_object(storage_key: str, dest: pathlib.Path) -> None:
    """
    GET {SUPABASE_URL}/storage/v1/object/{bucket}/{key} → write to `dest`.

    Streams the response body straight to disk and writes via a temp file so a
    crash mid-download never leaves a corrupted file at the final path.
    """
    # Private buckets must be read through the "authenticated" route — the
    # public /object/{bucket}/{key} path returns 400 for non-public buckets.
    url = f"{SUPABASE_URL}/storage/v1/object/authenticated/{BUCKET}/{storage_key}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY,
    }

    dest.parent.mkdir(parents=True, exist_ok=True)

    # NamedTemporaryFile in the same dir → os.replace() is atomic on POSIX.
    fd, tmp_path = tempfile.mkstemp(prefix=".part-", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as tmp, requests.get(
            url, headers=headers, stream=True, timeout=60
        ) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=CHUNK_BYTES):
                tmp.write(chunk)
        os.replace(tmp_path, dest)
    except BaseException:
        # On any failure, clean up the temp file. Don't leak partials.
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def fetch_takes(conn: psycopg.Connection, include_rejected: bool, limit: int | None):
    """
    Yield TakeRow instances using a server-side (named) cursor.

    A named cursor keeps the result set on the database server and ships rows
    in batches as Python iterates. The whole result never has to fit in RAM,
    which is the only sane default for any "export everything" query.
    """
    where = "" if include_rejected else "WHERE t.status <> 'rejected'"
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    sql = f"""
        SELECT
            t.id           AS take_id,
            s.slug         AS song_slug,
            s.title        AS song_title,
            s.author       AS song_author,
            t.style,
            t.duration_s,
            t.audio_sha256,
            t.storage_key,
            t.status,
            t.created_at
        FROM takes t
        JOIN songs s ON s.id = t.song_id
        {where}
        ORDER BY t.created_at
        {limit_clause};
    """
    with conn.cursor(name="export_cursor") as cur:
        cur.itersize = 200  # rows per network roundtrip
        cur.execute(sql)
        for row in cur:
            yield TakeRow(*row)


def atomic_write_manifest(rows: list[dict]) -> None:
    """Write to a sibling temp file, then rename. Readers never see a partial CSV."""
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(MANIFEST.suffix + ".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, MANIFEST)


# ─── main ───────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--include-rejected",
        action="store_true",
        help="export takes with status='rejected' too (default: skip them)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap number of rows for a smoke test",
    )
    ap.add_argument(
        "--reverify",
        action="store_true",
        help="re-hash files even if they already exist on disk",
    )
    args = ap.parse_args()

    t0 = time.monotonic()
    counts = {
        "rows": 0,
        "downloaded": 0,
        "skipped_existing": 0,
        "hash_mismatch": 0,
        "download_failed": 0,
    }
    manifest_rows: list[dict] = []

    with psycopg.connect(DATABASE_URL) as conn:
        print(f"connected to {conn.info.host} db={conn.info.dbname}")
        for row in fetch_takes(conn, args.include_rejected, args.limit):
            counts["rows"] += 1
            # Mirror the storage key as the on-disk path. One column, two
            # meanings, no remapping later.
            dest = DATA_DIR / row.storage_key

            need_download = True
            if dest.exists():
                if args.reverify or sha256_of_file(dest) != row.audio_sha256:
                    if not args.reverify:
                        # On-disk bytes disagree with the DB. The DB hash is
                        # the source of truth (server-computed at upload).
                        # Re-download to make them agree.
                        print(f"  hash mismatch on existing file, re-downloading: "
                              f"{row.storage_key}")
                        dest.unlink()
                    else:
                        # --reverify: caller wants a fresh check; if hash
                        # already matches just skip.
                        if sha256_of_file(dest) == row.audio_sha256:
                            counts["skipped_existing"] += 1
                            manifest_rows.append(row.as_manifest_dict())
                            continue
                        dest.unlink()
                else:
                    counts["skipped_existing"] += 1
                    manifest_rows.append(row.as_manifest_dict())
                    continue

            try:
                download_object(row.storage_key, dest)
            except requests.HTTPError as e:
                counts["download_failed"] += 1
                print(f"  download failed for {row.storage_key}: {e}")
                continue

            actual = sha256_of_file(dest)
            if actual != row.audio_sha256:
                counts["hash_mismatch"] += 1
                print(
                    f"  HASH MISMATCH {row.storage_key}\n"
                    f"    db={row.audio_sha256}\n"
                    f"    disk={actual}\n"
                    f"  deleting; row will NOT be added to manifest"
                )
                dest.unlink()
                continue

            counts["downloaded"] += 1
            manifest_rows.append(row.as_manifest_dict())

    atomic_write_manifest(manifest_rows)

    elapsed = time.monotonic() - t0
    print()
    print("── summary ──")
    for k, v in counts.items():
        print(f"  {k:<20} {v}")
    print(f"  manifest_rows        {len(manifest_rows)}")
    print(f"  manifest             {MANIFEST.relative_to(HERE)}")
    print(f"  elapsed              {elapsed:.1f}s")

    # Non-zero exit if anything went wrong, so this script can be wired into
    # CI later without lying about success.
    bad = counts["hash_mismatch"] + counts["download_failed"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

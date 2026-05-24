"""
discover.py — build songs/songs_br.json and songs/songs_en.json from Last.fm.

Uses geo.getTopTracks (free, just needs LASTFM_API_KEY in .env). 'Top tracks' is a
proxy for 'most listened' which is in turn a decent proxy for 'most covered' —
classics with millions of listeners overwhelmingly have many YouTube covers.

    .venv/bin/python scripts/discover.py
    .venv/bin/python scripts/discover.py --per-country 500 --en-country "united states"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

from _common import ROOT, SONGS_DIR, slugify

LASTFM = "https://ws.audioscrobbler.com/2.0/"
PAGE_SIZE = 200  # Last.fm caps geo.getTopTracks at ~200/page


def fetch_top_tracks(api_key: str, country: str, target: int) -> list[dict]:
    """Pull `target` unique (title, author) tracks for a country, dedup by slug."""
    out: list[dict] = []
    seen: set[str] = set()
    page = 1
    while len(out) < target:
        r = requests.get(
            LASTFM,
            params={
                "method": "geo.gettoptracks",
                "country": country,
                "api_key": api_key,
                "format": "json",
                "limit": PAGE_SIZE,
                "page": page,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        tracks = (data.get("tracks") or {}).get("track") or []
        if not tracks:
            break
        for t in tracks:
            title = (t.get("name") or "").strip()
            author = ((t.get("artist") or {}).get("name") or "").strip()
            if not title or not author:
                continue
            slug = slugify(title)
            if slug in seen:
                continue
            seen.add(slug)
            out.append({
                "title": title,
                "author": author,
                "author_slug": slugify(author),
                "slug": slug,
                "listeners": int(t.get("listeners") or 0),
                "lastfm_url": t.get("url", ""),
            })
            if len(out) >= target:
                break
        page += 1
        time.sleep(0.25)  # be nice to last.fm
        if page > 50:  # safety stop
            break
    return out


def main() -> int:
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("LASTFM_API_KEY", "").strip()
    if not api_key:
        print("ERROR: LASTFM_API_KEY missing. Copy .env.example to .env and fill it.",
              file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--per-country", type=int, default=500)
    ap.add_argument("--br-country", default="brazil")
    ap.add_argument("--en-country", default="united states")
    args = ap.parse_args()

    SONGS_DIR.mkdir(parents=True, exist_ok=True)

    for tag, country, path in (
        ("BR", args.br_country, SONGS_DIR / "songs_br.json"),
        ("EN", args.en_country, SONGS_DIR / "songs_en.json"),
    ):
        print(f"[{tag}] fetching top tracks for {country!r} (target={args.per_country})")
        songs = fetch_top_tracks(api_key, country, args.per_country)
        path.write_text(json.dumps(songs, indent=2, ensure_ascii=False))
        print(f"[{tag}] wrote {len(songs)} songs -> {path.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

# imported_dataset/

YouTube-sourced supplementary dataset. Mirrors `dataset/data/`'s layout so both
can be consumed by the same training pipeline.

```
imported_dataset/
├── songs/
│   ├── songs_br.json          # 500 Brazilian top tracks (Last.fm)
│   └── songs_en.json          # 500 US top tracks (Last.fm)
├── scripts/
│   ├── discover.py            # build the songs/*.json
│   ├── download.py            # search YouTube + extract 16k mono PCM-16 clips
│   └── verify.py              # re-hash every WAV against the manifest
└── data/
    ├── manifest.csv           # same 10 columns as dataset/data/manifest.csv
    ├── provenance.csv         # sidecar: video_id, url, query, clip window
    └── raw_audio/<slug>/<uuid>.wav
```

## Differences vs `dataset/`

| | `dataset/` (collection app) | `imported_dataset/` (YouTube) |
|---|---|---|
| Source | crowdsourced a cappella vocals | published cover videos |
| Voice + instruments | vocal only | vocal + backing instruments |
| Length | a few seconds, user-controlled | configurable clip (default: 30s starting at 0:30) |
| `style` | `cantar` / `cantarolar` / `assobiar` | always `cantar` |
| `status` | `pending` / `approved` / `rejected` | `approved` |
| `song_author` | slug typed by contributor | slug of Last.fm artist |

The two manifests share the same 10 columns and the same `raw_audio/{slug}/{uuid}.wav`
key shape, so merging them is just a `cat`.

## Setup

```bash
cd imported_dataset
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
brew install ffmpeg              # macOS — ffmpeg must be on PATH
cp .env.example .env             # then paste your LASTFM_API_KEY
```

Get a Last.fm key at <https://www.last.fm/api/account/create> (instant, no review).

## Run

```bash
# 1. Build the song lists (~5 s, hits Last.fm)
.venv/bin/python scripts/discover.py

# 2. Smoke test on 5 songs × 3 covers
.venv/bin/python scripts/download.py --limit 5

# 3. Full run — 1000 songs × 3 covers, ~1–2 h on a fast connection
.venv/bin/python scripts/download.py --workers 16

# 4. Verify integrity
.venv/bin/python scripts/verify.py
```

Re-running `download.py` is safe — it skips video IDs already present in
`provenance.csv`.

## Clip length — how to expand later

Default is 30 s starting at 0:30. To pull a different window:

```bash
.venv/bin/python scripts/download.py --clip-start-s 30 --clip-dur-s 60
```

Each invocation creates *new* takes (new UUIDs); the original 30 s clips remain
on disk. If you instead want to *replace* the clips, delete `data/raw_audio/`,
`data/manifest.csv`, and `data/provenance.csv` first.

## Knobs

| Flag | Default | Notes |
|---|---|---|
| `--covers` | 3 | covers per song |
| `--workers` | 12 | parallel ffmpeg downloads; raise for fast connections |
| `--clip-start-s` | 30 | seconds to skip from the start of each video |
| `--clip-dur-s` | 30 | seconds of audio per clip |
| `--limit N` | — | only process first N songs (smoke test) |
| `--songs PATH` | both BR + EN | repeatable; pick a single JSON if you want |

## Why search ranks ≈ "most covered"

We use Last.fm `geo.getTopTracks` (sorted by listeners). For most popular songs,
high listener count strongly correlates with cover abundance on YouTube. The
download step searches `"<title> <author> cover"` and filters to videos
90–600 s long, which excludes Shorts/clips/compilations and leaves real covers.

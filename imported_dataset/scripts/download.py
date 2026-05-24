"""
download.py — for each song, find N YouTube covers, extract a clip to 16 kHz mono
PCM-16 WAV, and append to data/manifest.csv (+ data/provenance.csv).

Idempotent and resumable: video IDs already in provenance.csv are skipped.

Examples:
    .venv/bin/python scripts/download.py                       # both BR + EN, 3 covers each
    .venv/bin/python scripts/download.py --songs songs/songs_br.json
    .venv/bin/python scripts/download.py --covers 3 --workers 16
    .venv/bin/python scripts/download.py --clip-start-s 30 --clip-dur-s 30
    .venv/bin/python scripts/download.py --limit 5             # smoke test
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import re

import yt_dlp
from tqdm import tqdm
from unidecode import unidecode

from _common import (
    AUDIO_DIR,
    CsvAppender,
    MANIFEST,
    MANIFEST_COLUMNS,
    PROVENANCE,
    PROVENANCE_COLUMNS,
    SONGS_DIR,
    load_seen_video_ids,
    read_songs,
)

# ── tunables ────────────────────────────────────────────────────────────────
SEARCH_FETCH = 25            # over-fetch: most won't pass the a cappella filter
MIN_DURATION_S = 45          # a cappella covers are often short
MAX_DURATION_S = 600         # > 10min is probably a compilation
DEFAULT_COVERS_PER_SONG = 3
DEFAULT_WORKERS = 12
SAMPLE_RATE_HZ = 16000

# Title keywords that flag a recording as a cappella / voice-only. Case-folded
# match. If you ever want to relax to "any cover", drop this filter.
ACAPELLA_KEYWORDS = (
    "acapella", "a cappella", "a capella", "acapela", "a-cappella",
    "no instruments", "vocals only", "vocal only", "voice only",
    "só voz", "so voz", "só vocal", "so vocal", "sem instrumentos",
)


def is_acapella(title: str) -> bool:
    t = (title or "").lower()
    return any(kw in t for kw in ACAPELLA_KEYWORDS)


_NORM_RE = re.compile(r"[^a-z0-9]+")


def _norm(s: str) -> str:
    return _NORM_RE.sub(" ", unidecode(s or "").lower()).strip()


# Separadores comuns em nomes de duplas/grupos: "Henrique & Juliano",
# "Ícaro e Gilmar", "Diego e Victor Hugo", "Marcos and Belutti", "X feat Y", "X / Y"
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:&|/|\+|,|\bfeat\.?\b|\bft\.?\b|\bft\b|\b[ey]\b|\band\b)\s*",
    re.IGNORECASE,
)


def artist_tokens(artist: str) -> list[str]:
    """Tokens significativos do(s) nome(s) do artista, prontos pra busca em
    título normalizado. Quebra duplas em partes e descarta tokens <=2 chars."""
    parts = _ARTIST_SPLIT_RE.split(artist or "")
    out: list[str] = []
    for p in parts:
        for tok in _norm(p).split():
            if len(tok) > 2:
                out.append(tok)
    return out


def title_matches_song(video_title: str, song_title: str) -> bool:
    """Rígido: o título da música precisa aparecer como substring contígua no
    título do vídeo. Token-overlap solto causou falsos positivos como
    'Piel Morena' batendo busca por 'Morena'."""
    vt = _norm(video_title)
    st = _norm(song_title)
    return not st or st in vt


def artist_present_in_title(video_title: str, artist: str) -> bool:
    """Pelo menos UM token significativo do artista (ou das partes da dupla)
    precisa aparecer no título do vídeo. Sem isso pegamos a versão do artista
    errado da mesma música — 'Sonho de Amor' do Natanzinho cai pra versão do
    Zezé Di Camargo, etc."""
    toks = artist_tokens(artist)
    if not toks:
        return True
    vt = _norm(video_title)
    return any(t in vt for t in toks)


# Strong signals that *someone else* is performing the song (i.e. it's a cover,
# not the original artist's own a-cappella stem upload).
COVER_HINTS = ("cover", "covered by", "cover by", "cantando", "performs", "sings")


def looks_like_cover_not_original(video_title: str, artist: str) -> bool:
    """Reject quando o artista original parece ser o intérprete (sem 'cover'
    no título). Aceita se o nome NÃO aparece, ou aparece junto de 'cover'."""
    vt = _norm(video_title)
    toks = artist_tokens(artist)
    if not toks:
        return True
    artist_present = any(t in vt for t in toks)
    cover_hint = any(h in vt for h in COVER_HINTS)
    if artist_present and not cover_hint:
        return False
    return True

# Silence yt-dlp inside threads.
YDL_OPTS_SEARCH = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",   # cheap: don't resolve each video
    "skip_download": True,
    "default_search": "ytsearch",
    "noplaylist": True,
}
YDL_OPTS_RESOLVE = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "format": "bestaudio/best",
    "noplaylist": True,
}


@dataclass
class Candidate:
    video_id: str
    title: str
    duration_s: float
    url: str


@dataclass
class Job:
    song_slug: str
    song_title: str
    song_author: str
    author_slug: str
    query: str
    candidate: Candidate


# ── search ──────────────────────────────────────────────────────────────────


def search_candidates(query: str, fetch: int,
                      song_title: str, artist: str,
                      require_acapella: bool = True,
                      require_cover_not_original: bool = True,
                      ) -> list[Candidate]:
    """Return candidates filtered by:
      - duration in [MIN_DURATION_S, MAX_DURATION_S]
      - a-cappella keyword in title (if require_acapella)
      - song title actually appears in video title (kills wrong-song hits)
      - original artist is NOT the performer (if require_cover_not_original)
    """
    with yt_dlp.YoutubeDL(YDL_OPTS_SEARCH) as ydl:
        info = ydl.extract_info(f"ytsearch{fetch}:{query}", download=False)
    entries = (info or {}).get("entries") or []
    out: list[Candidate] = []
    for e in entries:
        if not e:
            continue
        vid = e.get("id")
        dur = e.get("duration")
        if not vid or not dur:
            continue
        if dur < MIN_DURATION_S or dur > MAX_DURATION_S:
            continue
        title = e.get("title") or ""
        if require_acapella and not is_acapella(title):
            continue
        if not title_matches_song(title, song_title):
            continue
        if not artist_present_in_title(title, artist):
            continue
        if require_cover_not_original and not looks_like_cover_not_original(title, artist):
            continue
        out.append(Candidate(
            video_id=vid,
            title=title,
            duration_s=float(dur),
            url=e.get("url") or f"https://www.youtube.com/watch?v={vid}",
        ))
    return out


# ── extract ─────────────────────────────────────────────────────────────────


def resolve_stream_url(video_id: str) -> str | None:
    """Get a direct audio stream URL from yt-dlp (with auth tokens baked in)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS_RESOLVE) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    return (info or {}).get("url")


def extract_clip(stream_url: str, dest: pathlib.Path,
                 start_s: float, dur_s: float) -> bool:
    """Run ffmpeg to pull [start_s, start_s+dur_s] as 16 kHz mono PCM-16 WAV.

    Atomic: writes to a sibling temp file then renames. -ss before -i lets ffmpeg
    HTTP-range-seek so we don't download the whole video.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".part-", suffix=".wav", dir=dest.parent)
    os.close(fd)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start_s}",
        "-i", stream_url,
        "-t", f"{dur_s}",
        "-vn",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE_HZ),
        "-acodec", "pcm_s16le",
        tmp_path,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=180,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)
        return False
    # Sanity: ffmpeg can succeed but produce a near-empty file if the stream
    # ended before start_s — drop anything implausibly small.
    if os.path.getsize(tmp_path) < 8192:
        os.unlink(tmp_path)
        return False
    os.replace(tmp_path, dest)
    return True


def sha256_of_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── per-job worker ──────────────────────────────────────────────────────────


def process_job(job: Job, clip_start_s: float, clip_dur_s: float,
                ) -> tuple[dict | None, dict | None, str | None]:
    """Return (manifest_row, provenance_row, error). Either rows OR error, not both."""
    stream_url = resolve_stream_url(job.candidate.video_id)
    if not stream_url:
        return None, None, "resolve_failed"

    take_id = str(uuid.uuid4())
    storage_key = f"raw_audio/{job.song_slug}/{take_id}.wav"
    dest = AUDIO_DIR.parent / storage_key

    if not extract_clip(stream_url, dest, clip_start_s, clip_dur_s):
        return None, None, "ffmpeg_failed"

    audio_sha = sha256_of_file(dest)
    duration_s = round(clip_dur_s, 4)
    created_at = int(time.time() * 1000)

    manifest_row = {
        "take_id": take_id,
        "song_slug": job.song_slug,
        "song_title": job.song_title,
        "song_author": job.author_slug,   # match dataset/ convention (slug, not display)
        "style": "cantar",
        "duration_s": duration_s,
        "audio_sha256": audio_sha,
        "storage_key": storage_key,
        "status": "approved",
        "created_at": created_at,
    }
    provenance_row = {
        "take_id": take_id,
        "source": "youtube",
        "video_id": job.candidate.video_id,
        "video_title": job.candidate.title,
        "video_url": f"https://www.youtube.com/watch?v={job.candidate.video_id}",
        "video_duration_s": job.candidate.duration_s,
        "query": job.query,
        "clip_start_s": clip_start_s,
        "clip_dur_s": clip_dur_s,
    }
    return manifest_row, provenance_row, None


# ── orchestration ───────────────────────────────────────────────────────────


def build_jobs(songs: list[dict], covers: int, seen_video_ids: set[str]
               ) -> tuple[list[Job], int]:
    """Search Last.fm-derived songs on YouTube and emit one Job per chosen cover.

    Search is sequential (cheap, ~1s each) so the heavy ffmpeg work is what
    parallelism actually accelerates.
    """
    # Try several query variants per song so we surface a-cappella uploads that
    # use different naming conventions (English "acapella", Portuguese "acapela",
    # "vocals only", etc.). Stop as soon as we have enough covers.
    # Phrase as "<title> cover acapella" — "cover" up front nudges YouTube to
    # rank fan covers above the original artist's own a-cappella stem uploads.
    query_variants = (
        '{title} {author} acapella cover',
        '{title} cover acapella',
        '{title} {author} a cappella cover',
        '{title} acapela cover',
        '{title} {author} covered acapella',
    )

    jobs: list[Job] = []
    skipped = 0
    for song in tqdm(songs, desc="search"):
        picked = 0
        picked_query = ""
        for tmpl in query_variants:
            if picked >= covers:
                break
            query = tmpl.format(title=song["title"], author=song["author"])
            try:
                candidates = search_candidates(
                    query, SEARCH_FETCH,
                    song_title=song["title"], artist=song["author"],
                    require_acapella=True, require_cover_not_original=True,
                )
            except Exception:
                candidates = []
            for cand in candidates:
                if cand.video_id in seen_video_ids:
                    continue
                seen_video_ids.add(cand.video_id)
                jobs.append(Job(
                    song_slug=song["slug"],
                    song_title=song["title"],
                    song_author=song["author"],
                    author_slug=song.get("author_slug", ""),
                    query=query,
                    candidate=cand,
                ))
                picked += 1
                picked_query = query
                if picked >= covers:
                    break
        if picked == 0:
            skipped += 1
    return jobs, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--songs", action="append", type=pathlib.Path,
                    help="path to a songs JSON; repeatable. Default: songs_br + songs_en.")
    ap.add_argument("--covers", type=int, default=DEFAULT_COVERS_PER_SONG)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--clip-start-s", type=float, default=30.0,
                    help="seconds to skip from the start of each video")
    ap.add_argument("--clip-dur-s", type=float, default=30.0,
                    help="clip length to extract (knob for future expansion)")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap number of songs (smoke test)")
    args = ap.parse_args()

    if args.songs:
        song_paths = args.songs
    else:
        song_paths = [SONGS_DIR / "songs_br.json", SONGS_DIR / "songs_en.json"]
    for p in song_paths:
        if not p.exists():
            print(f"ERROR: {p} missing. Run scripts/discover.py first.", file=sys.stderr)
            return 2

    songs: list[dict] = []
    for p in song_paths:
        songs.extend(read_songs(p))
    if args.limit:
        songs = songs[: args.limit]

    seen_video_ids = load_seen_video_ids()
    print(f"loaded {len(songs)} songs, {len(seen_video_ids)} videos already imported")

    jobs, skipped = build_jobs(songs, args.covers, seen_video_ids)
    print(f"queued {len(jobs)} download jobs (songs with no candidates: {skipped})")

    manifest = CsvAppender(MANIFEST, MANIFEST_COLUMNS)
    provenance = CsvAppender(PROVENANCE, PROVENANCE_COLUMNS)

    ok = fail = 0
    err_counts: dict[str, int] = {}
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(process_job, j, args.clip_start_s, args.clip_dur_s)
                for j in jobs]
        for fut in tqdm(as_completed(futs), total=len(futs), desc="download"):
            m_row, p_row, err = fut.result()
            if err:
                fail += 1
                err_counts[err] = err_counts.get(err, 0) + 1
                continue
            manifest.append(m_row)
            provenance.append(p_row)
            ok += 1

    print()
    print("── summary ──")
    print(f"  jobs                 {len(jobs)}")
    print(f"  succeeded            {ok}")
    print(f"  failed               {fail}")
    for reason, n in sorted(err_counts.items(), key=lambda kv: -kv[1]):
        print(f"    {reason:<18} {n}")
    print(f"  manifest             {MANIFEST}")
    print(f"  provenance           {PROVENANCE}")
    print(f"  elapsed              {time.monotonic() - t0:.1f}s")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

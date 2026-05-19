# SimlabimAI — Context

## What this is

A song-recognition system. The end goal — **Simsalabim** — listens to a microphone and identifies the song the user is singing, humming, or whistling. To train it, we need a dataset that does not currently exist: short vocal performances of popular songs, recorded by ordinary people on whatever device they have.

This repo holds every stage of that work:

| Folder | Role |
|---|---|
| `collection/` | Browser tool that crowdsources vocal samples. Deployed today. |
| `dataset/` | Tools to export, inspect, and package the collected audio into training-ready manifests. |
| `model/` | Notebooks + scripts for training and evaluating the recognition model. |
| `Simsalabim/` | The final app that consumes the trained model. Not built yet. |
| `shared/` | Canonical JSON (song list, style enum, slug rules) read by all of the above. |

## Why a web app for collection

Contributors record on different devices — laptops, phones, tablets — and the recordings need to land in a single shared database. A browser tool is the only practical way to do that without forcing every contributor to install software. Open a URL on any device, record, upload, done.

The audio pipeline (16 kHz mono PCM-16 WAV via `OfflineAudioContext`, all client-side) is the load-bearing piece. Everything else — metadata, storage, the model itself — is built around that audio.

## Stack — current

| Concern | Choice |
|---|---|
| Web app | **Next.js 15** on **Vercel** |
| Database | **Supabase Postgres** |
| Audio storage | **Supabase Storage** (private bucket, signed upload URLs) |
| Package manager | **npm** |
| Python tooling | per-folder venvs (`dataset/.venv-stats/`, `model/.venv/`) |

The choice rationale: Supabase gives us a free-tier Postgres + object store with one signup and one set of env vars. Postgres beats SQLite-at-the-edge for the dataset because we want real SQL ergonomics for analysis from `dataset/` and `model/`.

## The dataset

### Shape in Supabase Storage

```
audio/                              # bucket name
└── raw_audio/
    └── <song-slug>/
        └── <take-uuid>.wav         # 16 kHz mono PCM-16
```

UUIDs (not sequential `take_N`) — concurrent uploads from different devices would race on sequential numbering.

### Shape in Postgres

```
songs
├── id            serial primary key
├── slug          text unique not null         # 'hotel-california'
├── title         text not null                # 'Hotel California'
├── author        text not null default 'unknown'
└── created_at    bigint (unix ms)

takes
├── id            text primary key (uuid)
├── song_id       integer references songs(id)
├── storage_key   text not null unique         # 'raw_audio/hotel-california/<uuid>.wav'
├── duration_s    real                         # parsed from WAV header server-side
├── style         text not null                # 'cantar' | 'cantarolar' | 'assobiar'
├── audio_sha256  text not null
├── user_agent    text
├── status        text default 'pending'       # 'pending' | 'approved' | 'rejected'
├── review_note   text
├── reviewed_at   bigint
└── created_at    bigint (unix ms)
```

The `songs.author` field is upserted-but-never-downgraded: a real author value never gets replaced by `'unknown'`. First real contributor wins; everyone agreeing on the same author is a no-op.

### Style field — UI labels

Stored as a slug; rendered in the UI with the Portuguese label below.

| Stored value | UI label              |
|--------------|-----------------------|
| `cantar`     | Cantar (com letra)    |
| `cantarolar` | Cantarolar (sem letra)|
| `assobiar`   | Assobiar              |

## Recording pipeline

```
mic
  → MediaRecorder         (webm/mp4, browser-chosen)
  → AudioContext.decodeAudioData
  → OfflineAudioContext(channels=1, sampleRate=16000)
  → Float32 → Int16 PCM → WAV header
  → Blob (audio/wav)
  → fetch(PUT, signed_upload_url, body=blob)
  → POST /api/takes { song, author, style, storage_key }
```

See `collection/CLAUDE.md` for implementation-level notes (WAV header bytes, sample clipping, mono mix, server-side validation).

## Roles & access

- **MVP**: open link, no auth. Optional `INVITE_CODE` env var is reserved for a v2 invite-gate.
- **Admin**: Supabase Studio's Table Editor for `takes`, Storage browser for the bucket. No separate admin UI.
- **Identity**: there is no contributor identity field on `takes`. Earlier drafts had a `contributor` slug; it was removed because it didn't pull its weight and added a friction point in the UI.

## Open decisions

| Decision | Default |
|---|---|
| Take review workflow | All uploads `status = 'pending'`; flip manually |
| Multi-take dedup | Reject duplicate `(song_id, audio_sha256)` |
| Public dataset license | Undecided. Contributors see a consent line before recording. |
| Model architecture | TBD — work starts in `model/` |

## Non-goals

- Public, anonymous, sign-up-free *training data downloads* (the dataset is private until license is decided)
- Real-time playback or social/discovery features in `collection/`
- Native mobile apps (a PWA-style web app covers iOS + Android)
- Multi-language UI

## References

- Repo manual: `CLAUDE.md` (root) and `collection/CLAUDE.md` (site-specific)
- Next.js App Router: https://nextjs.org/docs/app
- Vercel project config: https://vercel.com/docs/projects/overview
- Supabase JS SDK: https://supabase.com/docs/reference/javascript
- Supabase Storage signed URLs: https://supabase.com/docs/guides/storage/uploads/standard-uploads
- Drizzle on Postgres: https://orm.drizzle.team/docs/get-started-postgresql
- MediaRecorder + Web Audio API: https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder

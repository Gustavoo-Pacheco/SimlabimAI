# SimlabimAI — Context

## What this is

A browser tool for crowdsourcing a vocal dataset. Contributors pick a song, record a 5–30s sample of themselves singing or humming the melody, tag the song's author, and submit. The aggregated WAVs are a machine-learning dataset.

## Why a web app

Contributors record on different devices — laptops, phones, tablets — and the recordings need to land in a single shared database. A browser tool is the only practical way to do that without forcing every contributor to install software. Open a URL on any device, record, upload, done.

The audio pipeline (16 kHz mono PCM-16 WAV via `OfflineAudioContext`, all client-side) is the load-bearing piece. Everything else — auth, metadata, storage — is conventional CRUD around that audio.

## Why Cloudflare

| Concern | Cloudflare answer |
|---|---|
| Audio storage | **R2** — S3-compatible, **zero egress fees**. |
| Metadata DB | **D1** — SQLite at the edge, 5 GB free tier, fits the dataset comfortably. |
| Hosting | **Pages + Workers** — 100k req/day free, unlimited static. OpenNext adapter handles Next.js. |
| Bill | Realistically $0/month at current scale. |

Cost is the load-bearing reason. Vendor lock-in is bounded: R2 is S3-compatible, D1 is plain SQLite.

## The dataset

### Shape in R2

```
raw_audio/
└── <song-slug>/
    └── <take-uuid>.wav      # 16 kHz mono PCM-16
```

UUIDs (not sequential `take_N`) — concurrent uploads from different devices would race on sequential numbering.

### Shape in D1

```
songs
├── id            integer primary key
├── slug          text unique not null         # 'meteoro', 'palacios'
├── title         text                         # 'Meteoro' (display)
├── author        text                         # 'paralamas-do-sucesso' or 'unknown'
└── created_at    integer (unix ms)

takes
├── id            text primary key (uuid)
├── song_id       integer references songs(id)
├── contributor   text not null                # 'gustavo', 'pri'
├── r2_key        text not null unique         # 'raw_audio/meteoro/<uuid>.wav'
├── duration_s    real                         # parsed from WAV header server-side
├── style         text not null                # 'cantar' | 'cantarolar' | 'assobiar'
├── audio_sha256  text not null                # SHA-256 of WAV bytes, computed server-side
├── user_agent    text                         # browser UA string, captured client-side
├── status        text default 'pending'       # 'pending' | 'approved' | 'rejected'
├── review_note   text                         # nullable; reason when status flips
├── reviewed_at   integer                      # nullable; unix ms
└── created_at    integer (unix ms)
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
  → fetch(PUT, signed_url, body=blob)
  → POST /api/takes { song, author, contributor, r2_key }
```

See `CLAUDE.md` → "Recording pipeline" for the implementation-level notes (WAV header bytes, sample clipping, mono mix).

## Roles & access

- **MVP**: shared invite code via env var (`INVITE_CODE`). Anyone with the link + code can record.
- **Identity**: free-text `contributor` slug typed by the user. Stored in `localStorage` for return visits. Not authenticated.
- **Admin**: Drizzle Studio against the local D1, or the Cloudflare dashboard query console against prod. No separate admin UI.

## Open decisions

| Decision | Default |
|---|---|
| R2 storage class | Standard |
| Take review workflow | All uploads `status = 'pending'`; flip manually |
| Multi-take dedup | None — accept duplicates |
| Public dataset license | Undecided. Contributors see a consent line before recording. |

## Non-goals

- Public, anonymous, sign-up-free uploads
- Real-time playback or social/discovery features
- Native mobile apps (a PWA-style web app covers iOS + Android)
- Multi-language UI

## References

- Operating manual for this build: `CLAUDE.md`
- OpenNext for Cloudflare: https://opennext.js.org/cloudflare
- Drizzle on D1: https://orm.drizzle.team/docs/get-started-sqlite#cloudflare-d1
- R2 + S3 SDK: https://developers.cloudflare.com/r2/api/s3/presigned-urls/
- Next.js App Router: https://nextjs.org/docs/app
- MediaRecorder + Web Audio API: https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder

# collection/ — Build Manual

Next.js site that crowdsources humming/singing samples. Contributors open a URL, record a short vocal sample, and upload. The aggregated WAVs are the training set for `model/`.

See `../context.md` for product rationale and `../CLAUDE.md` for repo-wide invariants. This file is the build manual for *this* subfolder only.

## Stack

- **Next.js 15** (App Router) on **Vercel**. Vercel project's **Root Directory** must point to `collection/`.
- **Supabase Postgres** for metadata (via `postgres` driver + Drizzle ORM `drizzle-orm/pg-core`).
- **Supabase Storage** for audio blobs. Browser uploads directly via **signed upload URLs** (no server proxying).
- **Tailwind v4** for styling.

No Cloudflare, no R2, no D1, no wrangler. If you see references to any of those in old docs or comments, treat them as stale and remove.

## Recording pipeline (already built — don't break)

```
mic
  → MediaRecorder                       (webm/mp4, browser-chosen container)
  → AudioContext.decodeAudioData        → AudioBuffer at device SR
  → OfflineAudioContext(1, _, 16000)    → mono AudioBuffer at 16 kHz
  → Float32Array → Int16 PCM → WAV header bytes
  → Blob (audio/wav)
  → fetch(PUT, signed_upload_url, body=blob)   → upload directly to Supabase Storage
  → POST /api/takes { song, author, style, storage_key }
```

Notes:
- Mono mix from stereo via `(ch0 + ch1) * 0.5`.
- WAV header is 44 bytes: `RIFF` / size / `WAVE` / `fmt ` (PCM, 1 ch, 16000 Hz, 16-bit) / `data`.
- Clip samples to `[-1, 1]` before Int16 conversion: `s < 0 ? s * 0x8000 : s * 0x7fff`.
- Live audio-level meter via `AnalyserNode.getByteTimeDomainData`.
- `navigator.userAgent` is sent with the POST body so the server can store it on the row.

Implementation lives in `components/Recorder.tsx` and `lib/wav.ts`.

## Server-side validation (every `POST /api/takes`)

Before writing the row:
- HEAD the Supabase Storage object — must exist.
- Object size: 8 KB ≤ size ≤ 12 MB (allows up to ~6 min mono 16 kHz; raised from initial 5 MB).
- Slug fields (`song`, `author`) match `^[a-z0-9-]+$`, length 1–64.
- `style` is exactly one of `'cantar' | 'cantarolar' | 'assobiar'`.
- Reject duplicate `(song_id, audio_sha256)` (replay/dedup).
- `duration_s` is parsed from the WAV header **server-side**. Never trust a client-reported number.
- Stream the object once to compute `audio_sha256` (SHA-256 of the bytes). Store it on the row.
- `user_agent` is captured but never used in any decision — store as-is, max length 512.

## DB schema (truth lives in `lib/db/schema.ts`)

```
songs
├── id            serial primary key
├── slug          text unique not null         # 'hotel-california'
├── title         text not null                # 'Hotel California' (display)
├── author        text not null default 'unknown'
└── created_at    bigint (unix ms)

takes
├── id            text primary key (uuid)
├── song_id       integer references songs(id)
├── storage_key   text not null unique         # 'raw_audio/hotel-california/<uuid>.wav'
├── duration_s    real                         # parsed from WAV header server-side
├── style         text not null                # 'cantar' | 'cantarolar' | 'assobiar'
├── audio_sha256  text not null                # SHA-256 of WAV bytes, server-computed
├── user_agent    text
├── status        text default 'pending'       # 'pending' | 'approved' | 'rejected'
├── review_note   text
├── reviewed_at   bigint
└── created_at    bigint (unix ms)
```

There is **no `contributor` column** — it was removed in a recent commit. Don't add it back without checking in.

## Folder layout

```
collection/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                       # recorder UI
│   ├── globals.css
│   └── api/
│       ├── songs/route.ts             # GET → list songs
│       ├── upload-url/route.ts        # POST → { upload_url, take_id, storage_key }
│       └── takes/route.ts             # POST → write row
├── components/
│   ├── Recorder.tsx                   # full client pipeline
│   └── SongPicker.tsx
├── lib/
│   ├── db/schema.ts                   # Drizzle (Postgres)
│   ├── db/index.ts                    # postgres-js client
│   ├── storage.ts                     # Supabase signed-URL helper
│   ├── slugs.ts                       # slug validation
│   ├── wav.ts                         # client-side encode + server-side parse
│   └── upsert-author.ts               # the 'unknown' rule
├── drizzle/                           # migrations + seed.sql
├── scripts/seed.ts                    # tsx scripts/seed.ts → seeds songs table
├── drizzle.config.ts
├── next.config.ts
├── postcss.config.mjs
├── tsconfig.json                      # paths: "@/*" → "./*" (relative to this file)
├── package.json
├── package-lock.json
└── README.md                          # human-facing setup (Supabase + Vercel)
```

## Env vars (`.env.local`)

```
NEXT_PUBLIC_SUPABASE_URL=
SUPABASE_SECRET_KEY=          # service_role, starts with sb_secret_...
SUPABASE_BUCKET=audio
DATABASE_URL=                 # Supabase pooled connection string
# INVITE_CODE=                # reserved for v2 invite-gate
```

## Commands (all run from `collection/`)

```bash
npm install
npm run dev                    # http://localhost:3000
npm run build                  # next build
npm run start                  # production preview
npm run lint
```

**Schema + seed data**: managed by hand in Supabase Studio's SQL editor. There is no migration tool, no `drizzle-kit`, no seed script. Keep `lib/db/schema.ts` in sync with the real DB schema so typed queries don't lie. If schema changes get frequent enough that this hurts, reinstall `drizzle-kit` and reintroduce `drizzle.config.ts`.

## Workflow rules

- **Don't add auth before checking in.** MVP is invite-link + (optional) `INVITE_CODE`. Real auth only after explicit go-ahead.
- **Don't change the slug regex** without updating `lib/slugs.ts` AND any consumer in `../dataset/` or `../model/` that parses storage keys.
- **Scope**: this subfolder ends at "audio in Supabase Storage, metadata in Postgres." Nothing else belongs here.
- **No server-side audio processing beyond parsing the WAV header.** The browser produces the correct format; the server just signs URLs, parses the header, hashes the bytes, and writes the row.

## Out of scope (for this subfolder)

- Public sign-up
- Moderation UI (use Supabase Studio's Table Editor)
- i18n (Portuguese only)
- Native mobile apps (PWA suffices)

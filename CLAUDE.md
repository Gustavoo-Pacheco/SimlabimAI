# SimlabimAI — Operating Manual

Browser-based tool for crowdsourcing a humming/singing dataset. Contributors on any device open a URL, record short vocal samples, and upload them to a shared database. The aggregated WAVs are a machine-learning dataset.

See `context.md` for the product/data rationale. This file is the build manual.

## State of the world

Greenfield. Only `CLAUDE.md` and `context.md` exist. Build the Next.js app from scratch.

## Stack

- **Next.js 15** (App Router) deployed via **`@opennextjs/cloudflare`** → **Cloudflare Pages**
- **Cloudflare R2** for audio blobs. Browser uploads directly via **pre-signed PUT URLs** (no Worker proxying).
- **Cloudflare D1** (SQLite) for metadata.
- **Drizzle ORM** (`drizzle-orm/d1`) — edge-compatible.
- **R2 signing**: `@aws-sdk/client-s3` + `@aws-sdk/s3-request-presigner` (R2 is S3-compatible, both packages work on Workers).

## Critical contracts — do not break

1. **Audio format**: 16 kHz mono PCM-16 WAV. The resample happens **client-side** via `OfflineAudioContext`. Non-negotiable.
2. **Slug pattern** for `song_id`, `author`, `contributor`: `^[a-z0-9-]+$`, length 1–64. Validate on the server too (browser is not the trust boundary).
3. **R2 key shape**: `raw_audio/<song-slug>/<take-uuid>.wav`. Use UUIDs (not `take_N`) — sequential numbering races on concurrent uploads.
4. **Author = "unknown"**: when a contributor leaves author blank, store `"unknown"`. A real value already stored on a song must **never** be overwritten by `"unknown"`. Always upsert: `songs.author = COALESCE(NULLIF(:new, 'unknown'), songs.author, :new)`.
5. **Take immutability**: once a row is in `takes`, its `r2_key` and audio bytes are immutable. Edits = new take + soft-delete previous (`status = 'rejected'`).

## Recording pipeline (build this)

```
mic
  → MediaRecorder                       (webm/mp4, browser-chosen container)
  → AudioContext.decodeAudioData        → AudioBuffer at device SR
  → OfflineAudioContext(1, _, 16000)    → mono AudioBuffer at 16 kHz
  → Float32Array → Int16 PCM → WAV header bytes
  → Blob (audio/wav)
  → fetch(PUT, signed_url, body=blob)   → upload directly to R2
  → POST /api/takes { song, author, contributor, style, r2_key }
```

Notes:
- Mono mix from stereo via `(ch0 + ch1) * 0.5`.
- WAV header is 44 bytes: `RIFF` / size / `WAVE` / `fmt ` chunk (PCM, 1 channel, 16000 Hz, 16-bit) / `data` chunk.
- Clip samples to `[-1, 1]` before Int16 conversion: `s < 0 ? s * 0x8000 : s * 0x7fff`.
- Show a live audio-level meter using `AnalyserNode.getByteTimeDomainData` during recording.
- Capture `navigator.userAgent` and submit it with the POST body so the server can store it on the row.

## UI labels (Portuguese)

The `style` field is stored as a slug and rendered with a friendly label. Wire the UI control as a 3-option radio/segmented control using exactly these labels:

| Stored value | UI label              |
|--------------|-----------------------|
| `cantar`     | Cantar (com letra)    |
| `cantarolar` | Cantarolar (sem letra)|
| `assobiar`   | Assobiar              |

## Edge runtime constraints

You're deploying to Cloudflare Workers via OpenNext. Hard limits to plan around:

- **No Node native modules.** Anything pulling in `fs`, `child_process`, `node-gyp` will break the build. Specifically: do not add `better-sqlite3`, `sqlite3`, `pg`, `sharp`, `bcrypt` (use `bcryptjs` if needed).
- **No server-side audio processing.** The browser produces the correct WAV; the server just signs URLs and writes metadata.
- **Always export `runtime`** on route handlers if mixing: `export const runtime = "edge"`.
- **Worker request body limit**: 100 MB. Irrelevant if uploads go straight to R2 (which they should). Don't proxy audio through a Worker.

## Validation rules (server-side, every `POST /api/takes`)

Before writing the row:
- HEAD the R2 object — must exist.
- Object size: 8 KB ≤ size ≤ 5 MB (10s mono 16k ≈ 320 KB; allow 30s + headroom).
- All slug fields (`song`, `author`, `contributor`) match `^[a-z0-9-]+$`, length 1–64.
- `style` is exactly one of `'cantar' | 'cantarolar' | 'assobiar'`. Reject anything else.
- Reject duplicate `(song_id, contributor)` submitted within 5 seconds (replay protection).
- Trust nothing from the client beyond what's validated. Parse `duration_s` from the WAV header server-side; do not trust a client-reported number.
- Stream the R2 object once to compute `audio_sha256` (SHA-256 of the bytes). Store that hash on the row. Cheap, and gives you free dedup + integrity checks later.
- `user_agent` is captured but never used for any decision — store as-is, max length 512.

## File layout (target)

```
/
├── app/
│   ├── page.tsx                       # recorder UI
│   ├── api/upload-url/route.ts        # POST → { upload_url, take_id, r2_key }
│   └── api/takes/route.ts             # POST → write D1 row
├── components/
│   └── Recorder.tsx                   # client component, the full pipeline above
├── lib/
│   ├── db/schema.ts                   # Drizzle
│   ├── db/index.ts                    # D1 client
│   ├── r2.ts                          # presign helper
│   └── slugs.ts                       # shared validation
├── drizzle/                           # migrations
├── wrangler.toml                      # R2 + D1 bindings
└── CLAUDE.md / context.md             # this and its sibling
```

## Commands (target)

```bash
pnpm dev                       # next dev (Node preview; doesn't hit R2/D1)
pnpm wrangler:dev              # wrangler dev with R2 + D1 bound locally (real edge runtime)
pnpm db:generate               # drizzle-kit generate
pnpm db:migrate:local          # apply migrations to local D1
pnpm db:migrate:prod           # apply migrations to remote D1
pnpm build                     # opennext build
pnpm deploy                    # wrangler pages deploy .open-next/...
```

## Workflow rules

- **Don't add auth before checking in with the user.** MVP uses a shared invite code (`INVITE_CODE` env var). Real auth (magic link, Clerk) only after explicit go-ahead.
- **Scope**: the web app's responsibility ends at "audio in R2, metadata in D1." Nothing else belongs in this repo.
- **Don't pin npm packages that need Node runtime** without first testing under `wrangler dev`.
- **Don't change the slug regex** without updating both the client validator (`lib/slugs.ts`) and the server validator.

## Out of scope

- Public sign-up (closed beta)
- Moderation UI (use Drizzle Studio / D1 dashboard)
- i18n (Portuguese-only labels)
- Native mobile apps (PWA suffices)

## Reading order for a fresh session

1. `context.md` — what we're building and why
2. This file — how to build it
3. The relevant Cloudflare docs in the References block of `context.md`

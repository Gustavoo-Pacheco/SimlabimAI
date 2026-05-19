# SimlabimAI — Repo Manual

Song-recognition system. The end goal is **Simsalabim**, an app that listens to a microphone and identifies the song being sung, hummed, or whistled. This repo holds every piece of work that leads to it.

See `context.md` for the product/data rationale. This file tells Claude (and humans) how the repo is organized and what the cross-cutting rules are.

## Repo layout

```
/
├── collection/    # Next.js site for crowdsourcing vocal samples (the only thing deployed today)
├── dataset/       # Export, EDA, and packaging tools for the dataset produced by collection/
├── model/         # Research notebooks, training scripts, evaluation (Python)
├── Simsalabim/    # Final recognition app (scaffold — not built yet)
├── shared/        # Canonical song list, slug rules, style enum (JSON, TS + Python both read it)
├── CLAUDE.md      # This file
├── context.md     # Product rationale and data shape
└── README.md      # Human-facing entry point
```

Each subfolder has its own `README.md` (and `collection/` has its own `CLAUDE.md` with build-level detail).

## Stack — current state

| Concern | Choice |
|---|---|
| Web app | **Next.js 15** (App Router), deployed on **Vercel** |
| Database | **Supabase Postgres** (via `postgres` driver + Drizzle ORM) |
| Audio storage | **Supabase Storage** (private bucket, signed upload URLs) |
| Package manager | **npm** (lockfile in `collection/package-lock.json`) |
| Python (dataset/model) | venvs scoped to each folder (`dataset/.venv-stats/`, `model/.venv/`) |

**Vercel "Root Directory" must be set to `collection`** in the project settings. The repo root is not a Next.js app and will not build.

## Cross-cutting invariants — never break these

Every value below has a single source of truth in `shared/*.json`. Don't re-hardcode any of them in a subfolder.

1. **Audio format** (`shared/wav.json`): 16 kHz mono PCM-16 WAV, 44-byte header. The browser-side resample via `OfflineAudioContext` produces this; anything downstream that touches audio must preserve it.
2. **Slug pattern** (`shared/slugs.json`): `^[a-z0-9-]+$`, length 1–64, applied to `song.slug` and `songs.author`. Validate server-side too — the browser is not the trust boundary.
3. **Storage key shape** (`shared/storage.json`): `raw_audio/{songSlug}/{takeUuid}.wav`. UUIDs (not sequential `take_N`) — concurrent uploads race on sequential numbering.
4. **`author = "unknown"` rule** (`shared/authors.json` + `shared/AUTHOR-RULE.md`): when a contributor leaves author blank, store the `unknownSentinel`. A real author already on a song must **never** be overwritten by the sentinel. Implemented via `COALESCE(NULLIF(excluded.author, ${UNKNOWN}), songs.author, excluded.author)`.
5. **Take immutability**: once a row is in `takes`, its `storage_key` and audio bytes are immutable. Edits = new take + soft-delete previous (`status = 'rejected'`).
6. **Style enum** (`shared/styles.json`): exactly one of `'cantar' | 'cantarolar' | 'assobiar'`. Anything else is rejected server-side.
7. **Size and duration bounds** (`shared/limits.json`): audio 8 KB–40 MB, user-agent ≤ 512 chars, recording ≤ 20 min (1200 s).

These apply across the whole repo: `collection/` writes the data, `dataset/` exports it, `model/` trains on it, `Simsalabim/` consumes the model. Drift in any of them and the system breaks.

## Where to look for what

| Question | Where |
|---|---|
| How is the recorder UI built? | `collection/CLAUDE.md` and `collection/components/Recorder.tsx` |
| What's the DB schema? | `collection/lib/db/schema.ts` |
| How does upload signing work? | `collection/lib/storage.ts` and `collection/app/api/upload-url/route.ts` |
| How do I run EDA on the dataset? | `dataset/README.md` |
| How do I train the model? | `model/README.md` (TBD) |
| What's the song catalogue / style enum? | Currently duplicated in `collection/`. Target: `shared/*.json` (TBD) |

## Workflow rules

- **Don't add auth without checking in.** MVP relies on obscurity + (optional) `INVITE_CODE` env var. Real auth (magic link, Clerk) only after explicit go-ahead.
- **Scope per folder**: `collection/` owns data collection, full stop. `dataset/` owns export/packaging. `model/` owns training. `Simsalabim/` owns inference. Don't blur lines.
- **Don't change the slug regex** without updating both `collection/lib/slugs.ts` and any consumer in `dataset/` or `model/` that parses storage keys.
- **Run everything from its subfolder**, not the repo root. `npm run dev` only works from `collection/`. `stats.py` only works from `dataset/`.

## Out of scope (repo-wide)

- Public sign-up (closed beta)
- i18n (Portuguese-only UI labels)
- Native mobile apps (PWA suffices)
- Moderation UI (use Supabase Studio's Table Editor)

## Reading order for a fresh session

1. `context.md` — what we're building and why
2. This file — how the repo is organized
3. The relevant subfolder's `README.md` / `CLAUDE.md` for the area you're touching

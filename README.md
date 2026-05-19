# SimlabimAI

A song-recognition system. The end goal — **Simsalabim** — identifies songs from someone singing, humming, or whistling them. Building it requires a dataset that doesn't exist yet, so most of the work today is collecting one.

## Repo layout

| Folder | What it is | Status |
|---|---|---|
| [`collection/`](./collection/README.md) | Browser tool for crowdsourcing vocal samples (Next.js + Supabase, on Vercel) | Live |
| [`dataset/`](./dataset/README.md) | Export / EDA / packaging tools for the collected audio | Bootstrap |
| [`model/`](./model/README.md) | Notebooks + training + evaluation for the recognition model | Not started |
| [`Simsalabim/`](./Simsalabim/README.md) | The final inference app | Not started |
| [`shared/`](./shared/README.md) | Canonical JSON shared across all of the above (song list, style enum, slug rules) | Scaffold |

## Getting started

The only runnable thing today is the data-collection site. See [`collection/README.md`](./collection/README.md) for setup. Short version:

```bash
cd collection
npm install
cp .env.example .env.local   # fill in Supabase + DATABASE_URL
npm run db:push
npm run db:seed
npm run dev
```

## Background

- [`context.md`](./context.md) — what we're building and why
- [`CLAUDE.md`](./CLAUDE.md) — repo-wide invariants and how the folders relate

## Deployment

`collection/` deploys to Vercel. The Vercel project's **Root Directory** must be set to `collection` (the repo root is not a Next.js app).

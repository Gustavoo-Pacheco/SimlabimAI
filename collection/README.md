# SimlabimAI

Browser-based tool for crowdsourcing a humming/singing dataset. See `context.md`
for the rationale and `CLAUDE.md` for the build contract.

## Stack

Next.js 15 (App Router) on Vercel · Supabase Postgres · Supabase Storage ·
Drizzle ORM · Tailwind v4.

## One-time setup

Install dependencies:

```bash
npm install
```

### 1. Create a Supabase project

1. Sign up at https://supabase.com (no card required for the Free plan).
2. **New project** → pick a region close to you, set a strong DB password
   (letters and numbers only — avoids URL-encoding headaches later).
3. Wait ~1 minute for provisioning.

### 2. Get credentials

In the Supabase dashboard for your project:

- **Settings → API Keys**
  - Copy **Project URL** → `NEXT_PUBLIC_SUPABASE_URL`
  - Copy the **secret** key (formerly `service_role`, starts with `sb_secret_…`)
    → `SUPABASE_SECRET_KEY`
- **Settings → Database → Connection string → Transaction pooler**
  - Copy the URL, replace `[YOUR-PASSWORD]` with your DB password
    → `DATABASE_URL`

Copy `.env.example` to `.env.local` and paste the values in.

### 3. Create the storage bucket

In Supabase Studio → **Storage** → **New bucket**:

- Name: **`audio`** (or whatever `SUPABASE_BUCKET` is set to)
- Public: **off** (private — uploads go via signed URLs)

### 4. Create the schema + seed

All database work happens in Supabase Studio → **SQL Editor**:

1. Run the schema DDL — `songs` and `takes` tables with their indexes,
   mirroring `lib/db/schema.ts`.
2. Insert seed songs by hand (or paste any `INSERT INTO songs ...`
   statement). New songs after that are added through the app's
   "Adicionar nova música" UI.

There is no `drizzle-kit`, no migrations folder, and no seed script.
Schema changes are done by hand in Supabase Studio; keep
`lib/db/schema.ts` in sync so typed queries don't lie.

## Develop

```bash
npm run dev
# → http://localhost:3000
```

End-to-end smoke test:

1. Open `http://localhost:3000`, fill in apelido, pick a song, pick a style,
   record ~5 seconds, **Enviar**.
2. In Supabase Studio → **Storage → audio**, you should see
   `raw_audio/<song-slug>/<uuid>.wav`.
3. **Table Editor → takes** — row present, `audio_sha256` populated,
   `duration_s` ≈ 5.

## Deploy to Vercel

```bash
# First time: install the Vercel CLI globally.
npm i -g vercel

# Link the local repo to a Vercel project (one time).
vercel link

# Push env vars to Vercel (you'll be prompted for each value).
vercel env add NEXT_PUBLIC_SUPABASE_URL
vercel env add SUPABASE_SECRET_KEY
vercel env add SUPABASE_BUCKET
vercel env add DATABASE_URL

# Deploy.
vercel deploy --prod
```

Alternative: connect the GitHub repo to Vercel via the web UI and set the same
four env vars under **Project Settings → Environment Variables**.

## Out of scope for v1

- Invite-code gate (`INVITE_CODE` env var is reserved for v2)
- Moderation UI (use Supabase Studio's Table Editor)
- Multi-language UI

# shared/

Canonical, language-agnostic values shared across `collection/`, `dataset/`, `model/`, and `Simsalabim/`. Plain JSON so both TypeScript and Python can consume the same source of truth.

| File | Contents |
|---|---|
| `slugs.json` | Slug regex (`^[a-z0-9-]+$`) and length bounds (1–64) for `song.slug` and `songs.author` |
| `styles.json` | The three vocal styles: `cantar`, `cantarolar`, `assobiar` |
| `storage.json` | Storage-key shape: `raw_audio/{songSlug}/{takeUuid}.wav` |
| `wav.json` | WAV format: 16 kHz, mono, 16-bit PCM, 44-byte header |
| `limits.json` | Audio size bounds (8 KB – 40 MB), user-agent max length, max recording duration |
| `authors.json` | The `unknownSentinel` string used to mark missing author info |
| `AUTHOR-RULE.md` | Prose explanation of the author-merge rule (never overwrite a real author with `unknown`) |

## How to consume

**TypeScript (`collection/`, `Simsalabim/`):** path alias `@shared/*` maps to `../shared/*`. Direct JSON import:

```ts
import slugs from "@shared/slugs.json";
const re = new RegExp(slugs.pattern);
```

**Python (`dataset/`, `model/`):**

```python
import json, pathlib
shared = pathlib.Path(__file__).parents[1] / "shared"
slugs = json.loads((shared / "slugs.json").read_text())
re = __import__("re").compile(slugs["pattern"])
```

## What does NOT live here

- **Song catalogue** — dynamic data in Postgres, not a contract.
- **UI labels** — presentation (each stage may render labels in its own language/idiom).
- **WAV parsing logic** — server-side only, stays in `collection/lib/wav.ts`.
- **The Drizzle `COALESCE` SQL expression** — implementation detail of `collection/`; the *rule* it implements lives in `AUTHOR-RULE.md`.

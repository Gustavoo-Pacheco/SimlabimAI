# Author-merge rule

A song's `author` field follows one rule across every stage of the pipeline:

> **A real author value is never overwritten by `"unknown"`. First real contributor wins.**

Concretely:

| Existing `songs.author` | Incoming value | Result |
|---|---|---|
| (row doesn't exist) | `"unknown"` | Insert with `"unknown"` |
| (row doesn't exist) | `"paralamas-do-sucesso"` | Insert with `"paralamas-do-sucesso"` |
| `"unknown"` | `"unknown"` | Keep `"unknown"` |
| `"unknown"` | `"paralamas-do-sucesso"` | **Update to `"paralamas-do-sucesso"`** |
| `"paralamas-do-sucesso"` | `"unknown"` | **Keep `"paralamas-do-sucesso"`** |
| `"paralamas-do-sucesso"` | `"chico-buarque"` | Update to `"chico-buarque"` (last real wins) |

The sentinel string is canonical: `unknownSentinel` in `shared/authors.json`. Don't hardcode `"unknown"` anywhere — import the constant.

## Implementation (collection/)

The rule is enforced in Postgres via `ON CONFLICT(slug) DO UPDATE`:

```sql
COALESCE(NULLIF(excluded.author, 'unknown'), songs.author, excluded.author)
```

Reading left to right:
1. If the incoming value is `'unknown'`, `NULLIF` returns `NULL`, and `COALESCE` skips it.
2. Otherwise prefer the existing `songs.author`.
3. Final fallback to the incoming value (covers the insert-from-empty case).

Lives in `collection/lib/upsert-author.ts`. This SQL is Drizzle-specific and intentionally not extracted into `shared/` — it's the implementation, not the contract.

## What other stages must do

- **`dataset/`** — when exporting, treat rows with `author = unknownSentinel` as "author missing." Don't drop them; the audio is still valid training data. Just don't write them into any author-keyed index.
- **`model/`** — same. Author is a label, not a feature.
- **`Simsalabim/`** — if it ever displays an author, render `unknownSentinel` as `"Desconhecido"` (or hide the field), not the literal string `"unknown"`.

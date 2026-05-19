# shared/

Canonical, language-agnostic values shared across `collection/`, `dataset/`, `model/`, and `Simsalabim/`.

Plain JSON so both TypeScript and Python can consume the same source of truth:

- `songs.json` — canonical song list (slug → display name) *(TBD)*
- `styles.json` — the three vocal styles: `cantar`, `cantarolar`, `assobiar` *(TBD)*
- `slug-rules.json` — slug regex (`^[a-z0-9-]+$`, length 1–64) and length bounds *(TBD)*

**Today**: empty scaffold. The song list and style enum still live duplicated inside `collection/`. Extracting them into this folder is a follow-up — it requires editing `collection/`'s imports, which is intentionally out of scope for the restructure commit.

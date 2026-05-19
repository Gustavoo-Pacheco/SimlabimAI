# dataset/

Tools for exporting, inspecting, and packaging the dataset produced by `collection/`.

- `stats.py` — EDA: minutes of audio collected per song. Outputs `stats.png`.
- `.venv-stats/` — Python venv for the stats scripts (gitignored).
- Export utilities (TBD) — pull rows from Postgres + objects from Supabase Storage into a training-ready manifest (`manifest.csv` + WAV paths).

The audio bytes themselves live in Supabase Storage, not in git. This folder holds the *tooling*, not the data.

## Run stats

```bash
.venv-stats/bin/python stats.py
```

# model/colab/ — Training on Google Colab

`Simsalabim_train.ipynb` is the end-to-end notebook: data → splits → stats → encoder → train → eval → infer. Open it in Colab and follow the cells top-to-bottom.

## One-time setup

1. **Upload the dataset to Drive.** Mirror the local layout:
   ```
   My Drive/SimlabimAI/dataset/data/manifest.csv
   My Drive/SimlabimAI/dataset/data/raw_audio/<song-slug>/<take-uuid>.wav
   ```
   `dataset/export.py` (run locally) produces both. Drag-and-drop the whole `dataset/data/` folder into Drive.

2. **Edit `REPO_URL`** in the notebook (section 3) to your fork/repo if you're not pulling from the canonical URL.

3. **Runtime → Change runtime type → GPU** (T4 is enough for the toy dataset; A100 for real training).

## What the notebook produces

All artifacts are written under `My Drive/SimlabimAI/model_artifacts/`:

| File | Purpose |
|---|---|
| `splits.json` | Frozen song-level train/val/test split (seed=0 by default). |
| `stats.json` | Per-bin mel mean/std computed over the train split. |
| `checkpoints/best_map.pt` | Encoder + ArcFace state at best val mAP@10. |
| `checkpoints/last.pt` | Latest epoch (for resume). |
| `val_gallery.npz` | FAISS-ready gallery built from val takes. |
| `eval_val.json` | Final retrieval metrics, broken down by style. |
| `history.json` | Per-epoch train_loss + val metrics. |
| `configs_resolved.json` | All hyperparameters as actually used. |

## Running the same pipeline locally

The notebook is just a driver — every cell calls into `model/src/` modules. To run the same flow on a workstation:

```bash
cd model
.venv/bin/python scripts/make_splits.py
.venv/bin/python scripts/compute_mel_stats.py
# then write your own short driver that mirrors sections 9–17 of the notebook
```

## Editing the code

When you change anything under `model/src/`, push to the repo and re-run section 3 of the notebook (`git pull`) — the import in section 3 picks up the new code without restarting the kernel (in most cases; if you change class signatures, restart the runtime).

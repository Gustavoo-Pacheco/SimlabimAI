# model/

Research notebooks, training scripts, and evaluation harnesses for the song-recognition model.

- Reads from `dataset/data/manifest.csv` produced by `dataset/export.py`.
- Outputs trained model artifacts consumed by `Simsalabim/` (the inference app).

Stack: **PyTorch**. The plan is in `PLAN.md`; this README only covers how to run what exists today.

## What's implemented (Part 1 of the plan)

Pre-processing, representation, and data augmentation — everything that feeds the CNN. No CNN, no loss, no training loop yet.

```
src/
├── io.py                 # WAV loading + shared/wav.json validation
├── preproc.py            # trim (PESTO-confidence), LUFS normalize, crop
├── representation.py     # log-mel + PESTO f0 (two-stream)
├── augment_waveform.py   # audiomentations Compose (pitch, stretch, noise, IR, EQ, codec)
├── augment_mel.py        # SpecAugment + intra-class mixup
└── dataset.py            # TakesDataset ties it all together
configs/preproc.yaml      # single source of truth for all hyperparameters
scripts/smoke_test.py     # validates wiring without a real dataset
```

## Setup

```bash
cd model
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

PESTO downloads its model weights on first use. Cache lives under `~/.cache/torch/`.

## Smoke test

Runs the full pipeline on a synthetic 7-second sine sweep with silent head/tail. Prints intermediate shapes — useful to verify dependencies and tensor flow.

```bash
.venv/bin/python scripts/smoke_test.py
```

Expected output ends with shapes around:

- `log-mel` ≈ `(128, 500)`
- `f0 stream` ≈ `(2, ~165)` (depends on PESTO step size)

If shapes match these, the pipeline is wired correctly.

## Using `TakesDataset` (once `dataset/` has exported a manifest)

```python
from pathlib import Path
from src.dataset import TakesDataset, load_manifest, build_song_id_map
from src.augment_waveform import build_waveform_augmenter
from src.augment_mel import SpecAugmenter
import yaml

cfg = yaml.safe_load(Path("configs/preproc.yaml").read_text())

manifest = load_manifest(
    manifest_csv=Path("../dataset/data/manifest.csv"),
    audio_root=Path("../dataset/data"),
)
slug_to_id = build_song_id_map(manifest)

train_ds = TakesDataset(
    manifest,
    slug_to_id,
    train=True,
    waveform_augmenter=build_waveform_augmenter(cfg["augment"]["waveform"]),
    spec_augmenter=SpecAugmenter(),
)
print(train_ds[0]["mel"].shape, train_ds[0]["f0"].shape)
```

## Conventions

- All hyperparameters live in `configs/preproc.yaml`. Don't hardcode them in `.py`.
- `src/` is a package — import as `from src.xxx import ...` after adding `model/` to `sys.path`.
- Augmentation runs only in training mode (`train=True`). Val/test/inference go through the deterministic path.
- Audio invariants (16 kHz mono PCM-16) are validated on load via `shared/wav.json` — a mismatch raises `WavLoadError`.

## Next (Part 2 of `PLAN.md`)

CNN architecture (two-stream: ResNet-ish over mel + 1D-CNN over f0), projection head, sub-center ArcFace loss, train/val/test split by song, training loop, enrollment to FAISS, sliding-window inference, retrieval metrics.

# model/

Research notebooks, training scripts, and evaluation harnesses for the song-recognition model.

- Reads from dataset manifests produced by `dataset/`.
- Outputs trained model artifacts consumed by `Simsalabim/` (the inference app).
- Notebooks live alongside `.py` exports so diffs stay readable in git.

Stack TBD — likely PyTorch or TF/Keras. Pin a Python venv here once chosen (`model/.venv/`, gitignored).

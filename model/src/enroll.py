"""Build a FAISS gallery of enrolled songs from a TakesDataset (eval mode).

Each take becomes one vector in the index — we do NOT average per song,
since the variance within a song (across styles and contributors) is the
recall signal we want at query time.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from .eval import embed_dataset


@dataclass
class Gallery:
    embeddings: np.ndarray   # [N, D] float32, L2-normalized
    song_ids: np.ndarray     # [N] int64
    take_ids: list[str]
    styles: list[str]
    id_to_slug: dict[int, str]

    @property
    def dim(self) -> int:
        return int(self.embeddings.shape[1])

    def to_faiss(self):
        import faiss
        index = faiss.IndexFlatIP(self.dim)
        index.add(self.embeddings)
        return index

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            path,
            embeddings=self.embeddings,
            song_ids=self.song_ids,
            take_ids=np.array(self.take_ids),
            styles=np.array(self.styles),
            id_to_slug_keys=np.array(list(self.id_to_slug.keys()), dtype=np.int64),
            id_to_slug_vals=np.array(list(self.id_to_slug.values())),
        )

    @classmethod
    def load(cls, path: Path) -> "Gallery":
        z = np.load(path, allow_pickle=False)
        id_to_slug = {int(k): str(v) for k, v in zip(z["id_to_slug_keys"], z["id_to_slug_vals"])}
        return cls(
            embeddings=z["embeddings"].astype(np.float32),
            song_ids=z["song_ids"].astype(np.int64),
            take_ids=list(z["take_ids"]),
            styles=list(z["styles"]),
            id_to_slug=id_to_slug,
        )


@torch.no_grad()
def build_gallery(
    model,
    dataset,
    id_to_slug: dict[int, str],
    device: str = "cuda",
    batch_size: int = 32,
) -> Gallery:
    """Run the encoder over `dataset` (must be train=False) and pack a Gallery."""
    bundle = embed_dataset(model, dataset, device=device, batch_size=batch_size)
    embeds = bundle["embeds"].numpy().astype(np.float32)
    # already L2-normalized by encoder, but enforce in case of float drift
    norms = np.linalg.norm(embeds, axis=1, keepdims=True).clip(min=1e-8)
    embeds = embeds / norms
    return Gallery(
        embeddings=embeds,
        song_ids=bundle["song_ids"].numpy().astype(np.int64),
        take_ids=list(bundle["take_ids"]),
        styles=list(bundle["styles"]),
        id_to_slug=dict(id_to_slug),
    )

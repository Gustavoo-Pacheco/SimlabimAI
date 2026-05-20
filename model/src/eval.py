"""Retrieval metrics: top-K accuracy, MRR, mAP@K.

Inputs are L2-normalized embeddings — cosine similarity is just matmul.
"""
from __future__ import annotations

from dataclasses import dataclass

import torch


@dataclass
class RetrievalMetrics:
    top1: float
    top5: float
    mrr: float
    map_at_10: float
    n_queries: int


def _cosine_topk(
    query: torch.Tensor, gallery: torch.Tensor, k: int
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return (values, indices) of top-k cosine similarity per query row."""
    sims = query @ gallery.T  # [Nq, Ng]
    return torch.topk(sims, k=min(k, gallery.shape[0]), dim=1)


def _average_precision(relevant: torch.Tensor) -> float:
    """AP over a boolean tensor of hits in rank order (length k)."""
    if not relevant.any():
        return 0.0
    cum_hits = torch.cumsum(relevant.float(), dim=0)
    ranks = torch.arange(1, relevant.numel() + 1, dtype=torch.float32)
    precisions = cum_hits / ranks
    return float((precisions * relevant.float()).sum().item() / relevant.float().sum().item())


def retrieval_metrics(
    query_embeds: torch.Tensor,
    query_song_ids: torch.Tensor,
    gallery_embeds: torch.Tensor,
    gallery_song_ids: torch.Tensor,
    k_for_map: int = 10,
) -> RetrievalMetrics:
    """Compute top-1, top-5, MRR, mAP@k_for_map. Same-take self-matches
    are NOT excluded here; the caller is responsible for splitting takes
    between gallery/query (see splits.is_gallery_take).
    """
    k = max(10, k_for_map)
    _, topk_idx = _cosine_topk(query_embeds, gallery_embeds, k=k)
    topk_songs = gallery_song_ids[topk_idx]                 # [Nq, k]
    hits = topk_songs == query_song_ids.unsqueeze(1)        # [Nq, k]

    top1 = float(hits[:, 0].float().mean().item())
    top5 = float(hits[:, :5].any(dim=1).float().mean().item())

    # MRR over the top-k window (queries with no hit contribute 0).
    rank_idx = torch.argmax(hits.int(), dim=1)
    has_any = hits.any(dim=1)
    reciprocals = torch.where(
        has_any,
        1.0 / (rank_idx.float() + 1.0),
        torch.zeros_like(rank_idx, dtype=torch.float32),
    )
    mrr = float(reciprocals.mean().item())

    aps = [_average_precision(hits[i, :k_for_map]) for i in range(hits.shape[0])]
    map_k = float(sum(aps) / len(aps)) if aps else 0.0

    return RetrievalMetrics(
        top1=top1, top5=top5, mrr=mrr, map_at_10=map_k, n_queries=hits.shape[0]
    )


@torch.no_grad()
def embed_dataset(model, dataset, device: str = "cuda", batch_size: int = 32) -> dict:
    """Run encoder over a dataset (no augmentation) and stack embeddings.

    Returns dict with keys: embeds [N, D], song_ids [N], styles list[str],
    take_ids list[str]. Caller decides how to partition into gallery/query.
    """
    from torch.utils.data import DataLoader

    model.eval()
    loader = DataLoader(
        dataset, batch_size=batch_size, shuffle=False,
        num_workers=0, collate_fn=_collate,
    )
    all_e, all_s, all_styles, all_tids = [], [], [], []
    for batch in loader:
        mel = batch["mel"].to(device)
        f0 = batch["f0"].to(device)
        z = model(mel, f0)
        all_e.append(z.cpu())
        all_s.append(batch["song_id"])
        all_styles.extend(batch["style"])
        all_tids.extend(batch["take_id"])
    return {
        "embeds": torch.cat(all_e, dim=0),
        "song_ids": torch.cat(all_s, dim=0),
        "styles": all_styles,
        "take_ids": all_tids,
    }


def _collate(items: list[dict]) -> dict:
    """Pads f0 to the longest in the batch; mel is fixed-length already."""
    mels = torch.stack([it["mel"] for it in items], dim=0)
    f0_max = max(it["f0"].shape[-1] for it in items)
    f0s = torch.zeros(len(items), items[0]["f0"].shape[0], f0_max, dtype=items[0]["f0"].dtype)
    for i, it in enumerate(items):
        f0s[i, :, : it["f0"].shape[-1]] = it["f0"]
    return {
        "mel": mels,
        "f0": f0s,
        "song_id": torch.tensor([it["song_id"] for it in items], dtype=torch.long),
        "style": [it["style"] for it in items],
        "take_id": [it["take_id"] for it in items],
    }

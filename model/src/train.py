"""Importable training helpers — used by the Colab notebook.

Design: small, composable functions instead of a giant CLI. The notebook
drives the epoch loop so users can inspect intermediate state easily.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import torch
from torch.utils.data import DataLoader

from .augment_mel import intra_class_mixup
from .eval import _collate, embed_dataset, retrieval_metrics


@dataclass
class TrainState:
    epoch: int = 0
    global_step: int = 0
    best_map: float = -1.0
    history: list[dict] = field(default_factory=list)


def make_loader(
    dataset, batch_size: int, *, shuffle: bool, num_workers: int = 2
) -> DataLoader:
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        collate_fn=_collate,
        pin_memory=True,
        drop_last=shuffle,  # drop tail only at train time
    )


def train_one_epoch(
    model,
    loss_fn,
    optimizer,
    loader: DataLoader,
    *,
    device: str = "cuda",
    scheduler=None,
    grad_clip: float = 5.0,
    use_amp: bool = True,
    mixup_alpha: float = 0.2,
    mixup_p: float = 0.2,
    log_every: int = 20,
    on_step: Callable[[dict], None] | None = None,
) -> dict:
    """Run one epoch. Returns {'loss': mean_loss, 'steps': n}."""
    model.train()
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp and device == "cuda")
    total, n = 0.0, 0

    for step, batch in enumerate(loader):
        mel = batch["mel"].to(device, non_blocking=True)
        f0 = batch["f0"].to(device, non_blocking=True)
        song_ids = batch["song_id"].to(device, non_blocking=True)

        if mixup_alpha > 0 and mixup_p > 0:
            mel, f0 = intra_class_mixup(mel, f0, song_ids, alpha=mixup_alpha, p=mixup_p)

        optimizer.zero_grad(set_to_none=True)
        with torch.amp.autocast("cuda", enabled=use_amp and device == "cuda"):
            embeds = model(mel, f0)
            loss = loss_fn(embeds, song_ids)

        scaler.scale(loss).backward()
        if grad_clip:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
        scaler.step(optimizer)
        scaler.update()
        if scheduler is not None:
            scheduler.step()

        loss_val = float(loss.detach().item())
        total += loss_val
        n += 1
        if on_step is not None:
            on_step({"step": step, "loss": loss_val})
        if log_every and (step % log_every == 0):
            print(f"  step {step:4d}  loss={loss_val:.4f}")

    return {"loss": total / max(1, n), "steps": n}


@torch.no_grad()
def evaluate_retrieval(
    model,
    eval_dataset,
    *,
    is_gallery_fn,
    device: str = "cuda",
    batch_size: int = 32,
    k_for_map: int = 10,
):
    """Split eval dataset into gallery/query by `is_gallery_fn(take_id)`,
    compute retrieval metrics."""
    bundle = embed_dataset(model, eval_dataset, device=device, batch_size=batch_size)
    is_g = torch.tensor(
        [is_gallery_fn(tid) for tid in bundle["take_ids"]], dtype=torch.bool
    )
    if not is_g.any() or is_g.all():
        # degenerate split — fall back to a random half
        idx = torch.arange(len(bundle["take_ids"]))
        is_g = (idx % 2 == 0)

    g_embeds = bundle["embeds"][is_g]
    g_songs = bundle["song_ids"][is_g]
    q_embeds = bundle["embeds"][~is_g]
    q_songs = bundle["song_ids"][~is_g]
    q_styles = [s for s, g in zip(bundle["styles"], is_g.tolist()) if not g]

    overall = retrieval_metrics(q_embeds, q_songs, g_embeds, g_songs, k_for_map=k_for_map)

    per_style: dict[str, dict] = {}
    for style in sorted(set(q_styles)):
        mask = torch.tensor([s == style for s in q_styles], dtype=torch.bool)
        if mask.sum() < 1:
            continue
        m = retrieval_metrics(
            q_embeds[mask], q_songs[mask], g_embeds, g_songs, k_for_map=k_for_map
        )
        per_style[style] = m.__dict__

    return {"overall": overall.__dict__, "per_style": per_style,
            "n_gallery": int(is_g.sum().item()), "n_query": int((~is_g).sum().item())}


def save_checkpoint(path: Path, *, model, loss_fn, optimizer, scheduler, state: TrainState):
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model": model.state_dict(),
        "loss_fn": loss_fn.state_dict(),
        "optimizer": optimizer.state_dict(),
        "scheduler": scheduler.state_dict() if scheduler is not None else None,
        "state": state.__dict__,
    }, path)


def load_checkpoint(path: Path, *, model, loss_fn=None, optimizer=None, scheduler=None) -> TrainState:
    ckpt = torch.load(path, map_location="cpu")
    model.load_state_dict(ckpt["model"])
    if loss_fn is not None and "loss_fn" in ckpt:
        loss_fn.load_state_dict(ckpt["loss_fn"])
    if optimizer is not None and "optimizer" in ckpt:
        optimizer.load_state_dict(ckpt["optimizer"])
    if scheduler is not None and ckpt.get("scheduler") is not None:
        scheduler.load_state_dict(ckpt["scheduler"])
    s = ckpt.get("state", {})
    return TrainState(**{k: s[k] for k in ("epoch", "global_step", "best_map", "history") if k in s})

"""Training loop for U-Net building segmentation on Apple-Silicon MPS.

Config is intentionally simple:
  * AdamW, lr 1e-3 with cosine annealing
  * BCE + Dice combined loss (see src.unet.model.BCEDiceLoss)
  * Random patches 256x256 from train scenes; augmentation = flips + rot90
  * Validation = stride patches from a random subset of train scenes (10%)
    OR from a held-out validation list passed in.

Saves:
  outputs/models/unet_best.pt    — state dict with best val F1
  outputs/models/unet_last.pt    — final epoch
  outputs/logs/unet_train.csv    — per-epoch metrics
"""
from __future__ import annotations
from pathlib import Path
import json
import time
import csv
from typing import Iterable

import torch
from torch.utils.data import DataLoader

from src.unet.model import build_unet, BCEDiceLoss, pixel_metrics
from src.unet.dataset import BuildingTileDataset


def get_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def train_loop(model: torch.nn.Module,
               train_loader: DataLoader,
               val_loader: DataLoader | None,
               *,
               epochs: int = 15,
               lr: float = 1e-3,
               weight_decay: float = 1e-4,
               device: torch.device | None = None,
               out_dir: str | Path = "outputs/models",
               log_path: str | Path = "outputs/logs/unet_train.csv",
               log: callable = print,
               ) -> dict:
    device = device or get_device()
    log(f"Device: {device}")
    model.to(device)

    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(optim, T_max=epochs)
    loss_fn = BCEDiceLoss(dice_weight=0.5)

    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(log_path); log_path.parent.mkdir(parents=True, exist_ok=True)
    best_path = out_dir / "unet_best.pt"
    last_path = out_dir / "unet_last.pt"

    fieldnames = ["epoch", "train_loss", "val_f1", "val_iou", "val_p", "val_r", "lr",
                  "epoch_time_s"]
    write_header = not log_path.exists()
    log_fh = open(log_path, "a", newline="")
    csvw = csv.DictWriter(log_fh, fieldnames=fieldnames)
    if write_header:
        csvw.writeheader()

    best_f1 = -1.0
    history = {"train_loss": [], "val_f1": [], "val_iou": []}

    for epoch in range(1, epochs + 1):
        t0 = time.time()
        # ---- train ----
        model.train()
        train_losses = []
        for step, (x, y) in enumerate(train_loader):
            x = x.to(device, non_blocking=True)
            y = y.to(device, non_blocking=True)
            optim.zero_grad()
            logits = model(x)
            loss = loss_fn(logits, y)
            loss.backward()
            optim.step()
            train_losses.append(float(loss.detach().cpu()))
            if (step + 1) % 50 == 0:
                log(f"  epoch {epoch} step {step+1}/{len(train_loader)} "
                    f"loss={sum(train_losses[-50:])/50:.4f}")
        train_loss = sum(train_losses) / max(1, len(train_losses))
        sched.step()

        # ---- val ----
        val_f1 = val_iou = val_p = val_r = float("nan")
        if val_loader is not None:
            model.eval()
            agg = {"tp": 0.0, "fp": 0.0, "fn": 0.0}
            with torch.no_grad():
                for x, y in val_loader:
                    x = x.to(device); y = y.to(device)
                    logits = model(x)
                    m = pixel_metrics(logits, y)
                    agg["tp"] += m["tp"]; agg["fp"] += m["fp"]; agg["fn"] += m["fn"]
            tp = agg["tp"]; fp = agg["fp"]; fn = agg["fn"]
            eps = 1e-6
            val_p = tp / (tp + fp + eps)
            val_r = tp / (tp + fn + eps)
            val_f1 = 2 * val_p * val_r / (val_p + val_r + eps)
            val_iou = tp / (tp + fp + fn + eps)

        cur_lr = sched.get_last_lr()[0]
        elapsed = time.time() - t0
        log(f"epoch {epoch}/{epochs}  train_loss={train_loss:.4f}  "
            f"val_F1={val_f1:.4f} val_IoU={val_iou:.4f} val_P={val_p:.3f} val_R={val_r:.3f}  "
            f"lr={cur_lr:.5f}  ({elapsed:.0f}s)")
        csvw.writerow({"epoch": epoch, "train_loss": round(train_loss, 5),
                       "val_f1": round(val_f1, 4), "val_iou": round(val_iou, 4),
                       "val_p": round(val_p, 4), "val_r": round(val_r, 4),
                       "lr": round(cur_lr, 6),
                       "epoch_time_s": round(elapsed, 1)})
        log_fh.flush()

        history["train_loss"].append(train_loss)
        history["val_f1"].append(val_f1)
        history["val_iou"].append(val_iou)

        # save
        torch.save(model.state_dict(), last_path)
        if val_loader is not None and val_f1 > best_f1:
            best_f1 = val_f1
            torch.save(model.state_dict(), best_path)
            log(f"  ✓ new best val F1 = {best_f1:.4f}, saved {best_path.name}")

    log_fh.close()
    return {"best_f1": best_f1, "last_path": str(last_path),
            "best_path": str(best_path) if best_f1 > 0 else None,
            "history": history}

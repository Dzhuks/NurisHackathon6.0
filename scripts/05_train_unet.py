"""Train a U-Net (EfficientNet-B0 encoder) on Overture-derived building masks.

Workflow:
  1. Load AOI scenes.geojson and aoi/overture/buildings_clipped.geojson.
  2. Split: 16 train scenes -> 14 for training, 2 randomly held out for
     internal validation. The 4 hold-out scenes are NEVER touched here.
  3. Build BuildingTileDataset for train and val.
  4. Train via src.unet.train.train_loop.

Quick smoke-test mode:
    python3 scripts/13_train_unet.py --smoke
        Trains 1 epoch on 1 scene with tiny batch — takes ~3 min, verifies
        MPS works end-to-end.

Full mode:
    python3 scripts/13_train_unet.py --epochs 15
"""
from pathlib import Path
import sys
import argparse
import random

import geopandas as gpd
from torch.utils.data import DataLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.unet.dataset import BuildingTileDataset, build_overture_lookup
from src.unet.model import build_unet
from src.unet.train import train_loop, get_device
from src.logging_config import setup_logger
log = setup_logger("05_train_unet")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--patch", type=int, default=256)
    ap.add_argument("--patches-per-tile", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--num-workers", type=int, default=4)
    ap.add_argument("--encoder", default="efficientnet-b0")
    ap.add_argument("--smoke", action="store_true",
                    help="Quick 1-epoch run on 1 scene to verify the pipeline")
    args = ap.parse_args()

    aoi = gpd.read_file(ROOT / "aoi" / "scenes.geojson")
    train_scenes = aoi[aoi["split"] == "train"]["scene_id"].tolist()
    log.info("Train scenes: %d", len(train_scenes))

    if args.smoke:
        train_scenes = train_scenes[:1]
        val_scenes = train_scenes
        args.epochs = 1
        args.patches_per_tile = 1
        log.info("SMOKE TEST: %s only, 1 epoch", train_scenes)
    else:
        random.seed(42)
        random.shuffle(train_scenes)
        n_val = max(1, len(train_scenes) // 8)   # ~12.5%
        val_scenes = train_scenes[:n_val]
        train_scenes = train_scenes[n_val:]
        log.info("Train: %d scenes, Internal val: %d scenes (%s)",
                 len(train_scenes), len(val_scenes), val_scenes)

    overture_per_scene = build_overture_lookup(
        ROOT / "aoi" / "overture" / "buildings_clipped.geojson")

    train_files = {sid: ROOT / aoi[aoi["scene_id"] == sid]["file"].iloc[0]
                   for sid in train_scenes}
    val_files = {sid: ROOT / aoi[aoi["scene_id"] == sid]["file"].iloc[0]
                 for sid in val_scenes}

    train_ds = BuildingTileDataset(
        scene_files=train_files,
        overture_per_scene=overture_per_scene,
        patch_size=args.patch,
        mode="random",
        patches_per_tile=args.patches_per_tile,
        augment=True,
        min_valid_frac=0.3,
    )
    val_ds = BuildingTileDataset(
        scene_files=val_files,
        overture_per_scene=overture_per_scene,
        patch_size=args.patch,
        mode="stride",
        augment=False,
        min_valid_frac=0.3,
    )
    log.info("Datasets: train=%d patches/epoch, val=%d patches",
             len(train_ds), len(val_ds))

    train_loader = DataLoader(train_ds, batch_size=args.batch,
                              shuffle=True, num_workers=args.num_workers,
                              pin_memory=False, persistent_workers=args.num_workers > 0)
    val_loader = DataLoader(val_ds, batch_size=args.batch,
                            shuffle=False, num_workers=args.num_workers,
                            pin_memory=False, persistent_workers=args.num_workers > 0)

    model = build_unet(encoder_name=args.encoder, in_channels=3, classes=1)
    log.info("Model: U-Net + %s encoder (params: %dM)",
             args.encoder, sum(p.numel() for p in model.parameters()) // 1_000_000)

    out_dir = ROOT / "outputs" / "models"
    log_path = ROOT / "outputs" / "logs" / "unet_train.csv"
    result = train_loop(
        model, train_loader, val_loader,
        epochs=args.epochs, lr=args.lr,
        device=get_device(),
        out_dir=out_dir, log_path=log_path,
        log=log.info,
    )
    log.info("DONE. Best F1: %.4f", result["best_f1"])
    log.info("Best path: %s", result["best_path"])
    log.info("Last path: %s", result["last_path"])


if __name__ == "__main__":
    main()

"""Thin wrapper around segmentation_models_pytorch (smp) U-Net.

Default config: EfficientNet-B0 encoder + standard U-Net decoder, single-class
binary output (building / non-building). ImageNet-pretrained encoder weights
are used by default — they help even though our domain (aerial RGB) is far
from natural photos because low-level features (edges, textures) transfer.
"""
from __future__ import annotations
import torch
import torch.nn as nn
import segmentation_models_pytorch as smp


def build_unet(encoder_name: str = "efficientnet-b0",
               encoder_weights: str | None = "imagenet",
               in_channels: int = 3,
               classes: int = 1) -> nn.Module:
    """Construct a U-Net model. Output is logits (apply sigmoid downstream)."""
    model = smp.Unet(
        encoder_name=encoder_name,
        encoder_weights=encoder_weights,
        in_channels=in_channels,
        classes=classes,
        activation=None,  # raw logits; loss applies sigmoid
    )
    return model


class BCEDiceLoss(nn.Module):
    """Combined BCE-with-logits + Dice loss.

    Dice term encourages full-shape coverage (good for segmentation),
    BCE term provides stable gradient at the per-pixel level.
    """
    def __init__(self, dice_weight: float = 0.5, smooth: float = 1.0):
        super().__init__()
        self.bce = nn.BCEWithLogitsLoss()
        self.dice_weight = dice_weight
        self.smooth = smooth

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        bce_loss = self.bce(logits, target)
        prob = torch.sigmoid(logits)
        intersection = (prob * target).sum(dim=(1, 2, 3))
        denom = prob.sum(dim=(1, 2, 3)) + target.sum(dim=(1, 2, 3))
        dice = 1.0 - (2.0 * intersection + self.smooth) / (denom + self.smooth)
        return bce_loss + self.dice_weight * dice.mean()


@torch.no_grad()
def pixel_metrics(logits: torch.Tensor, target: torch.Tensor,
                  thr: float = 0.5) -> dict:
    """Compute pixel-level F1, IoU, precision, recall on a batch."""
    pred = (torch.sigmoid(logits) >= thr).float()
    tp = (pred * target).sum().item()
    fp = (pred * (1 - target)).sum().item()
    fn = ((1 - pred) * target).sum().item()
    eps = 1e-6
    precision = tp / (tp + fp + eps)
    recall = tp / (tp + fn + eps)
    f1 = 2 * precision * recall / (precision + recall + eps)
    iou = tp / (tp + fp + fn + eps)
    return {"f1": f1, "iou": iou, "p": precision, "r": recall,
            "tp": tp, "fp": fp, "fn": fn}

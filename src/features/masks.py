"""RGB-only land-cover masks: vegetation, shadow, soil.

Why RGB-only: our input GeoTIFFs are RGB+alpha, no NIR available, so
NDVI is impossible. We use RGB-band indices documented in:

  Chen, Li, Li (2018) Remote Sensing 10:451 — Object-Based Features for
  House Detection from RGB High-Resolution Images. (vegetation +
  shadow color-invariant indices)

  Hossain & Chen (2024) Geomatica 76:100007 — sequential removal of
  non-buildings using RGB indices (ExG, VIgreen, NGBDI, DSBI).

All functions accept arrays in shape (H, W, 3), dtype uint8 or float.
Outputs are bool masks of the same (H, W) — True means "this class".

The user has indicated they will provide an additional vegetation
research paper; this module is structured to easily add a new index
function and combine via majority vote.
"""
from __future__ import annotations
import numpy as np
from skimage.filters import threshold_otsu
from skimage.morphology import binary_opening, binary_closing, disk


# ---- index calculations ----------------------------------------------------
def _to_float(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rgb_f = rgb.astype(np.float32)
    # Avoid divide-by-zero by adding tiny epsilon downstream
    return rgb_f[..., 0], rgb_f[..., 1], rgb_f[..., 2]


def color_invariance_v(rgb: np.ndarray) -> np.ndarray:
    """Vegetation color-invariance v = (4/π) * arctan((G-B)/(G+B+eps)).

    From Gevers & Smeulders (2000), used in Chen et al. 2018 §3.3.1.
    Independent of viewpoint, illumination intensity & direction.
    Higher values -> more vegetation-like.
    """
    R, G, B = _to_float(rgb)
    eps = 1e-6
    return (4.0 / np.pi) * np.arctan((G - B) / (G + B + eps))


def color_invariance_s(rgb: np.ndarray) -> np.ndarray:
    """Shadow color-invariance s, from Cretu & Payeur (2013), Chen 2018 §3.3.1.

    s = (4/π) * arctan( (I - sqrt(R^2+G^2+B^2)) / (I + sqrt(R^2+G^2+B^2)) )
    where I = (R+G+B)/3
    Higher values -> more shadow-like.
    """
    R, G, B = _to_float(rgb)
    I = (R + G + B) / 3.0
    rgb_norm = np.sqrt(R * R + G * G + B * B)
    eps = 1e-6
    return (4.0 / np.pi) * np.arctan((I - rgb_norm) / (I + rgb_norm + eps))


def excess_green(rgb: np.ndarray) -> np.ndarray:
    """ExG = 2G - R - B.  Higher -> greener. (Hossain 2024 Table 1)"""
    R, G, B = _to_float(rgb)
    return 2.0 * G - R - B


def vigreen(rgb: np.ndarray, a: float = 0.667) -> np.ndarray:
    """VIgreen = G / (G^a * B^(1-a)).  Hossain 2024 Table 1."""
    R, G, B = _to_float(rgb)
    eps = 1e-6
    return G / (np.power(G + eps, a) * np.power(B + eps, 1 - a))


def ngbdi(rgb: np.ndarray) -> np.ndarray:
    """NGBDI = (G-B)/(G+B).  Hossain 2024 Table 1."""
    R, G, B = _to_float(rgb)
    eps = 1e-6
    return (G - B) / (G + B + eps)


def dsbi(rgb: np.ndarray) -> np.ndarray:
    """DSBI = 0.5*(B-R) + 0.5*(B-G).  Difference Spectral Building Index.

    Hossain 2024 Table 1 (after Gu et al. 2018). High values mark
    blue-dominated artificial surfaces (some roof types, water).
    Inverse can pick up bare soil where R > B and G > B.
    """
    R, G, B = _to_float(rgb)
    return 0.5 * (B - R) + 0.5 * (B - G)


def _normalized_rgb(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Two-step RGB normalization from Marcial-Pablo et al. 2019 (Eq. 1, 2).

    Step 1: divide by 255 to get values in [0, 1].
    Step 2: r = Rn / (Rn+Gn+Bn), same for g, b.
    Returns (r, g, b) — fractional spectral components, summing to 1 per pixel.
    """
    R, G, B = _to_float(rgb)
    Rn = R / 255.0
    Gn = G / 255.0
    Bn = B / 255.0
    s = Rn + Gn + Bn + 1e-9
    return Rn / s, Gn / s, Bn / s


def cive(rgb: np.ndarray) -> np.ndarray:
    """CIVE — Color Index of Vegetation Extraction.

    From Kataoka et al. 2003, formula (after RGB normalization to r, g, b):
      CIVE = 0.441*r - 0.811*g + 0.385*b + 18.78745

    Lower values -> more vegetation. Marcial-Pablo et al. (2019) found CIVE
    second-best RGB-only vegetation index after ExG (86.17% vs 86.86%
    accuracy on UAV maize imagery).
    """
    r, g, b = _normalized_rgb(rgb)
    return 0.441 * r - 0.811 * g + 0.385 * b + 18.78745


def vig_normalized(rgb: np.ndarray) -> np.ndarray:
    """VIg (alternative formulation in Marcial-Pablo 2019, also called NGRDI).

    VIg = (G - R) / (G + R)
    Higher -> more vegetation. Less noise-prone than ExG when shadows present.
    """
    R, G, B = _to_float(rgb)
    eps = 1e-6
    return (G - R) / (G + R + eps)


# ---- masks ----------------------------------------------------------------
# Note: Chen 2018 / Hossain 2024 use Otsu, but they apply it after segmenting
# the image into homogeneous regions where the bimodal assumption holds.
# We work on raw pixels in heterogeneous urban scenes, so Otsu fails (it
# would pick an inadequate threshold when one class is rare). Instead, we
# use *physically interpretable* thresholds combined with multiple indices
# to be robust. Otsu is still available as `auto` mode for future use.

def vegetation_mask(rgb: np.ndarray, valid: np.ndarray | None = None,
                    exg_thr: float = 8.0,
                    v_thr: float = 0.05,
                    cive_thr: float = 18.78,
                    vig_thr: float = 0.0,
                    min_votes: int = 2,
                    morph_radius: int = 3) -> np.ndarray:
    """Binary vegetation mask via voting of 4 RGB-only indices.

    Per Marcial-Pablo et al. (2019), best RGB indices for vegetation are:
      ExG (Excess Green)         — high = vegetation
      CIVE                       — low  = vegetation
      VIg / NGRDI = (G-R)/(G+R)  — high = vegetation
    Plus Chen 2018:
      v color-invariance         — high = vegetation

    Each index votes; pixel is vegetation if at least `min_votes` agree.
    This ensemble is more robust than any single index, especially when
    shadows are present (which Marcial-Pablo 2019 §3.2 flags as the main
    failure mode for ExG alone).
    """
    exg = excess_green(rgb)
    v = color_invariance_v(rgb)
    civ = cive(rgb)
    vig = vig_normalized(rgb)

    votes = (
        (exg > exg_thr).astype(np.uint8) +
        (v > v_thr).astype(np.uint8) +
        (civ < cive_thr).astype(np.uint8) +
        (vig > vig_thr).astype(np.uint8)
    )
    mask = votes >= min_votes

    if valid is not None:
        mask &= valid
    if morph_radius > 0:
        sel = disk(morph_radius)
        mask = binary_opening(mask, sel)
        mask = binary_closing(mask, sel)
    return mask


def shadow_mask(rgb: np.ndarray, valid: np.ndarray | None = None,
                intensity_thr: float = 60.0,
                s_thr: float = 0.0,
                morph_radius: int = 3) -> np.ndarray:
    """Binary shadow mask: dark pixels with high color-invariance s.

      I < intensity_thr  AND  s > s_thr
    """
    R, G, B = _to_float(rgb)
    I = (R + G + B) / 3.0
    s = color_invariance_s(rgb)
    mask = (I < intensity_thr) & (s > s_thr)
    if valid is not None:
        mask &= valid
    if morph_radius > 0:
        sel = disk(morph_radius)
        mask = binary_opening(mask, sel)
        mask = binary_closing(mask, sel)
    return mask


def soil_mask(rgb: np.ndarray, valid: np.ndarray | None = None,
              morph_radius: int = 3) -> np.ndarray:
    """Bare-soil mask: warm surface (R>=G>B), low green excess, mid-bright."""
    R, G, B = _to_float(rgb)
    exg = excess_green(rgb)
    I = (R + G + B) / 3.0
    # R must be at least as large as G and clearly larger than B
    mask = (R >= G - 5) & (R > B + 8) & (G > B) & (exg < 5) & (I > 70) & (I < 200)
    if valid is not None:
        mask &= valid
    if morph_radius > 0:
        sel = disk(morph_radius)
        mask = binary_opening(mask, sel)
        mask = binary_closing(mask, sel)
    return mask


def composite_landcover(rgb: np.ndarray, valid: np.ndarray | None = None
                        ) -> dict:
    """Compute all 3 masks at once. Returns dict with bool arrays.

    Priority for non-overlapping classes (when needed):
      vegetation > shadow > soil
    """
    veg = vegetation_mask(rgb, valid=valid)
    sha = shadow_mask(rgb, valid=valid)
    soi = soil_mask(rgb, valid=valid)
    # Make non-overlapping: vegetation wins, then shadow, then soil
    sha = sha & ~veg
    soi = soi & ~veg & ~sha
    return {"vegetation": veg, "shadow": sha, "bare_soil": soi}

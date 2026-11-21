"""Plant health / RGB vegetation index (VARI) computation and preview rendering."""

from __future__ import annotations

from typing import Tuple
import numpy as np


def compute_plant_health_vari(ortho_rgba: np.ndarray) -> np.ndarray:
    """Compute Visible Atmospherically Resistant Index (VARI) from an RGBA orthomosaic.

    VARI = (G - R) / (G + R - B), clamped to [-1.0, 1.0].
    Invalid/nodata pixels (alpha == 0) are set to -9999.0.
    """
    r = ortho_rgba[..., 0].astype(np.float32)
    g = ortho_rgba[..., 1].astype(np.float32)
    b = ortho_rgba[..., 2].astype(np.float32)
    alpha = ortho_rgba[..., 3] if ortho_rgba.shape[2] == 4 else np.full(r.shape, 255, dtype=np.uint8)

    denom = g + r - b
    valid = (alpha > 0) & (np.abs(denom) > 1e-3)
    vari = np.full(r.shape, -9999.0, dtype=np.float32)
    vari[valid] = np.clip((g[valid] - r[valid]) / denom[valid], -1.0, 1.0)
    return vari


def render_plant_health_preview(vari: np.ndarray) -> np.ndarray:
    """Render a Red-Yellow-Green RGBA preview image from a VARI grid."""
    h, w = vari.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    valid = vari > -9998.0
    if not np.any(valid):
        return rgba

    # Normalize typical vegetation VARI range [-0.25, +0.35] -> [0, 1]
    t = np.clip((vari[valid] + 0.25) / 0.60, 0.0, 1.0)
    r = np.where(t < 0.5, 220.0, 220.0 * (1.0 - (t - 0.5) * 2.0))
    g = np.where(t < 0.5, 220.0 * (t * 2.0), 180.0 + 40.0 * ((t - 0.5) * 2.0))
    b = np.full_like(t, 40.0)

    rgba[valid, 0] = np.clip(r, 0, 255).astype(np.uint8)
    rgba[valid, 1] = np.clip(g, 0, 255).astype(np.uint8)
    rgba[valid, 2] = np.clip(b, 0, 255).astype(np.uint8)
    rgba[valid, 3] = 255
    return rgba

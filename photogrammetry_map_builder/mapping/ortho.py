"""Terrain-aware orthorectification and feather-blended mosaicking."""

from __future__ import annotations

from typing import Dict, List, Tuple
import cv2
import numpy as np
from tqdm import tqdm

from ..geometry.camera import image_footprint, project_world_to_image, scale_intrinsics
from ..models import CameraPose


def _sample_dsm_bilinear(
    dsm: np.ndarray,
    dsm_ox: float,
    dsm_oy: float,
    dsm_res: float,
    world_x: np.ndarray,
    world_y: np.ndarray,
) -> np.ndarray:
    """Bilinearly sample DSM elevation at world coordinates (world_x, world_y)."""
    h, w = dsm.shape
    fx = (world_x - dsm_ox) / dsm_res - 0.5
    fy = (dsm_oy - world_y) / dsm_res - 0.5
    fx = np.clip(fx, 0.0, w - 1.0001)
    fy = np.clip(fy, 0.0, h - 1.0001)

    x0 = np.floor(fx).astype(np.int32)
    y0 = np.floor(fy).astype(np.int32)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)

    dx = fx - x0
    dy = fy - y0

    v00 = dsm[y0, x0]
    v10 = dsm[y0, x1]
    v01 = dsm[y1, x0]
    v11 = dsm[y1, x1]

    return (
        v00 * (1.0 - dx) * (1.0 - dy)
        + v10 * dx * (1.0 - dy)
        + v01 * (1.0 - dx) * dy
        + v11 * dx * dy
    )


def build_orthomosaic(
    poses: Dict[str, CameraPose],
    images_rgb: Dict[str, np.ndarray],
    img_scale: float,
    dsm: np.ndarray,
    dsm_ox: float,
    dsm_oy: float,
    dsm_res: float,
    bounds_xy: Tuple[float, float, float, float],
    ortho_gsd_m: float = 0.05,
    show_progress: bool = True,
) -> Tuple[np.ndarray, float, float, float]:
    """Generate an RGBA uint8 orthomosaic by projecting onto the DSM.

    Returns
    -------
    (ortho_rgba, origin_x, origin_y, ortho_gsd_m)
    """
    min_x, min_y, max_x, max_y = bounds_xy
    width = max(2, int(np.ceil((max_x - min_x) / ortho_gsd_m)))
    height = max(2, int(np.ceil((max_y - min_y) / ortho_gsd_m)))
    origin_x = min_x
    origin_y = min_y + height * ortho_gsd_m

    accum_rgb = np.zeros((height, width, 3), dtype=np.float32)
    accum_w = np.zeros((height, width), dtype=np.float32)

    mean_z = float(np.nanmedian(dsm))
    items = list(poses.items())
    if show_progress:
        items = tqdm(items, desc="Orthorectifying & mosaicking", unit="img")

    for fname, pose_proc in items:
        img = images_rgb[fname]
        ih, iw = img.shape[:2]

        # Adapt intrinsics to the image resolution used for orthorectification
        scale_rel = img_scale / (pose_proc.intrinsics.width / (pose_proc.intrinsics.width / (iw / pose_proc.intrinsics.width)) if False else 1.0)
        # Compute exact ratio between current img width and pose_proc intrinsics width
        ratio = iw / float(pose_proc.intrinsics.width)
        pose = CameraPose(
            filename=pose_proc.filename,
            R_wc=pose_proc.R_wc,
            C_world=pose_proc.C_world,
            intrinsics=scale_intrinsics(pose_proc.intrinsics, ratio),
            refined=pose_proc.refined,
        )

        fp = image_footprint(pose, mean_z)
        fp_xs = [p[0] for p in fp]
        fp_ys = [p[1] for p in fp]
        # Pad slightly for terrain relief
        pad = 5.0
        c0 = max(0, int(np.floor((min(fp_xs) - pad - origin_x) / ortho_gsd_m)))
        c1 = min(width, int(np.ceil((max(fp_xs) + pad - origin_x) / ortho_gsd_m)))
        r0 = max(0, int(np.floor((origin_y - (max(fp_ys) + pad)) / ortho_gsd_m)))
        r1 = min(height, int(np.ceil((origin_y - (min(fp_ys) - pad)) / ortho_gsd_m)))

        if c1 <= c0 or r1 <= r0:
            continue

        xs = origin_x + (np.arange(c0, c1, dtype=np.float64) + 0.5) * ortho_gsd_m
        ys = origin_y - (np.arange(r0, r1, dtype=np.float64) + 0.5) * ortho_gsd_m
        gx, gy = np.meshgrid(xs, ys)
        gz = _sample_dsm_bilinear(dsm, dsm_ox, dsm_oy, dsm_res, gx, gy)

        pts_3d = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=-1)
        uv, z_cam = project_world_to_image(pose, pts_3d)

        sub_h, sub_w = gx.shape
        u_map = uv[:, 0].reshape(sub_h, sub_w).astype(np.float32)
        v_map = uv[:, 1].reshape(sub_h, sub_w).astype(np.float32)
        z_map = z_cam.reshape(sub_h, sub_w)

        valid = (
            (z_map > 1.0)
            & (u_map >= 1.0)
            & (u_map <= iw - 2.0)
            & (v_map >= 1.0)
            & (v_map <= ih - 2.0)
        )
        if not np.any(valid):
            continue

        warped = cv2.remap(
            img, u_map, v_map, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT
        )

        # Smooth nadir/center-weighted feathering to hide seamlines
        du = np.minimum(u_map, (iw - 1.0) - u_map) / (iw * 0.5)
        dv = np.minimum(v_map, (ih - 1.0) - v_map) / (ih * 0.5)
        w_patch = np.clip(np.minimum(du, dv), 0.0, 1.0).astype(np.float32)
        w_patch = np.where(valid, w_patch ** 2 + 1e-4, 0.0).astype(np.float32)

        accum_rgb[r0:r1, c0:c1] += warped.astype(np.float32) * w_patch[..., None]
        accum_w[r0:r1, c0:c1] += w_patch

    ortho_rgba = np.zeros((height, width, 4), dtype=np.uint8)
    mask = accum_w > 0.0
    ortho_rgba[mask, :3] = np.clip(
        accum_rgb[mask] / accum_w[mask, None], 0.0, 255.0
    ).astype(np.uint8)
    ortho_rgba[mask, 3] = 255

    return ortho_rgba, origin_x, origin_y, ortho_gsd_m

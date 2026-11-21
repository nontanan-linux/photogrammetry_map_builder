"""3D point cloud export (Open3D PLY) and Digital Surface Model (DSM) interpolation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple
import numpy as np
import open3d as o3d
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter, grey_opening


def save_point_cloud_ply(
    output_path: Path | str,
    points_3d: np.ndarray,
    colors_rgb: Optional[np.ndarray] = None,
) -> Path:
    """Save a 3D point cloud to PLY format using Open3D."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(np.asarray(points_3d, dtype=np.float64))
    if colors_rgb is not None and len(colors_rgb) == len(points_3d):
        cols = np.asarray(colors_rgb, dtype=np.float64)
        if cols.max() > 1.0:
            cols = cols / 255.0
        pcd.colors = o3d.utility.Vector3dVector(np.clip(cols, 0.0, 1.0))
    o3d.io.write_point_cloud(str(path), pcd)
    return path


def filter_point_cloud_outliers(
    points_3d: np.ndarray,
    colors_rgb: Optional[np.ndarray] = None,
    z_iqr_factor: float = 3.0,
) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """Filter elevation outliers using robust IQR bounds."""
    if len(points_3d) < 10:
        return points_3d, colors_rgb
    z = points_3d[:, 2]
    q1, q3 = np.percentile(z, [25.0, 75.0])
    iqr = max(q3 - q1, 2.0)
    mask = (z >= q1 - z_iqr_factor * iqr) & (z <= q3 + z_iqr_factor * iqr)
    if np.sum(mask) < 4:
        return points_3d, colors_rgb
    pts = points_3d[mask]
    cols = colors_rgb[mask] if colors_rgb is not None else None
    return pts, cols


def build_dsm_and_point_cloud(
    points_3d: np.ndarray,
    colors_rgb: Optional[np.ndarray],
    bounds_xy: Tuple[float, float, float, float],
    dsm_resolution_m: float = 0.25,
    fallback_ground_z: float = 0.0,
    ply_path: Optional[Path | str] = None,
    smooth_sigma_px: float = 1.0,
) -> Tuple[np.ndarray, float, float, float]:
    """Generate a regular-grid DSM (float32) from 3D points and optionally save PLY.

    Returns
    -------
    (dsm_grid, origin_x, origin_y, dsm_resolution_m)
        `dsm_grid` has shape `(H, W)` where row 0 is `origin_y` (top/north)
        and col 0 is `origin_x` (left/west).
    """
    min_x, min_y, max_x, max_y = bounds_xy
    width = max(2, int(np.ceil((max_x - min_x) / dsm_resolution_m)))
    height = max(2, int(np.ceil((max_y - min_y) / dsm_resolution_m)))
    origin_x = min_x
    origin_y = min_y + height * dsm_resolution_m

    pts, cols = filter_point_cloud_outliers(points_3d, colors_rgb)
    if ply_path is not None and len(pts) > 0:
        save_point_cloud_ply(ply_path, pts, cols)

    if len(pts) < 4:
        dsm = np.full((height, width), float(fallback_ground_z), dtype=np.float32)
        return dsm, origin_x, origin_y, dsm_resolution_m

    xs = origin_x + (np.arange(width, dtype=np.float64) + 0.5) * dsm_resolution_m
    ys = origin_y - (np.arange(height, dtype=np.float64) + 0.5) * dsm_resolution_m
    grid_x, grid_y = np.meshgrid(xs, ys)

    dsm_linear = griddata(pts[:, :2], pts[:, 2], (grid_x, grid_y), method="linear")
    nan_mask = np.isnan(dsm_linear)
    if np.any(nan_mask):
        dsm_nearest = griddata(pts[:, :2], pts[:, 2], (grid_x, grid_y), method="nearest")
        dsm_linear[nan_mask] = dsm_nearest[nan_mask]

    if smooth_sigma_px > 0.0:
        dsm_linear = gaussian_filter(dsm_linear, sigma=smooth_sigma_px)

    return dsm_linear.astype(np.float32), origin_x, origin_y, dsm_resolution_m


def build_dtm_from_dsm(
    dsm: np.ndarray,
    dsm_res: float,
    filter_window_m: float = 8.0,
    smooth_sigma_px: float = 1.5,
) -> np.ndarray:
    """Derive a Digital Terrain Model (DTM) from a DSM via morphological ground filtering."""
    win_px = max(3, int(round(filter_window_m / dsm_res)))
    if win_px % 2 == 0:
        win_px += 1
    dtm = grey_opening(dsm.astype(np.float32), size=(win_px, win_px))
    if smooth_sigma_px > 0.0:
        dtm = gaussian_filter(dtm, sigma=smooth_sigma_px)
    return np.minimum(dtm, dsm).astype(np.float32)


def build_3d_mesh_obj(
    output_path: Path | str,
    dsm: np.ndarray,
    dsm_ox: float,
    dsm_oy: float,
    dsm_res: float,
    ortho_rgba: Optional[np.ndarray] = None,
    ortho_ox: Optional[float] = None,
    ortho_oy: Optional[float] = None,
    ortho_gsd: Optional[float] = None,
) -> Path:
    """Build a 3D triangle mesh (.obj) from the DSM grid with optional orthomosaic vertex colors."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = dsm.shape

    xs = dsm_ox + (np.arange(w, dtype=np.float64) + 0.5) * dsm_res
    ys = dsm_oy - (np.arange(h, dtype=np.float64) + 0.5) * dsm_res
    gx, gy = np.meshgrid(xs, ys)
    verts = np.stack([gx.ravel(), gy.ravel(), dsm.ravel().astype(np.float64)], axis=-1)

    # Build grid triangles (2 per cell)
    r_idx, c_idx = np.meshgrid(np.arange(h - 1), np.arange(w - 1), indexing="ij")
    v00 = (r_idx * w + c_idx).ravel()
    v10 = v00 + 1
    v01 = v00 + w
    v11 = v01 + 1
    tris = np.concatenate(
        [np.stack([v00, v01, v10], axis=-1), np.stack([v10, v01, v11], axis=-1)],
        axis=0,
    )

    mesh = o3d.geometry.TriangleMesh()
    mesh.vertices = o3d.utility.Vector3dVector(verts)
    mesh.triangles = o3d.utility.Vector3iVector(tris)

    if (
        ortho_rgba is not None
        and ortho_ox is not None
        and ortho_oy is not None
        and ortho_gsd is not None
    ):
        oh, ow = ortho_rgba.shape[:2]
        oc = np.clip(np.round((gx.ravel() - ortho_ox) / ortho_gsd - 0.5).astype(np.int32), 0, ow - 1)
        orow = np.clip(np.round((ortho_oy - gy.ravel()) / ortho_gsd - 0.5).astype(np.int32), 0, oh - 1)
        vcols = ortho_rgba[orow, oc, :3].astype(np.float64) / 255.0
        mesh.vertex_colors = o3d.utility.Vector3dVector(vcols)

    mesh.compute_vertex_normals()
    o3d.io.write_triangle_mesh(str(path), mesh)
    return path


def render_elevation_preview(elev: np.ndarray) -> np.ndarray:
    """Render a terrain-colormapped RGBA preview image from a DSM/DTM grid."""
    h, w = elev.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    valid = np.isfinite(elev) & (elev > -9990.0)
    if not np.any(valid):
        return rgba

    vals = elev[valid]
    vmin, vmax = float(np.percentile(vals, 2.0)), float(np.percentile(vals, 98.0))
    span = max(vmax - vmin, 1e-3)
    t = np.clip((elev[valid] - vmin) / span, 0.0, 1.0)

    # Blue -> Cyan -> Green -> Yellow -> Red-Brown elevation ramp
    r = np.clip(np.where(t < 0.5, 40.0 + 80.0 * t, 120.0 + 135.0 * (t - 0.5) * 2.0), 0, 255)
    g = np.clip(np.where(t < 0.5, 100.0 + 140.0 * t * 2.0, 240.0 - 140.0 * (t - 0.5) * 2.0), 0, 255)
    b = np.clip(np.where(t < 0.5, 220.0 - 160.0 * t * 2.0, 60.0 - 40.0 * (t - 0.5) * 2.0), 0, 255)

    rgba[valid, 0] = r.astype(np.uint8)
    rgba[valid, 1] = g.astype(np.uint8)
    rgba[valid, 2] = b.astype(np.uint8)
    rgba[valid, 3] = 255
    return rgba

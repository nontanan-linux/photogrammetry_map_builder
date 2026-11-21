"""Camera geometry, DJI orientation conventions, projection, and undistortion."""

from __future__ import annotations

from typing import List, Tuple
import cv2
import numpy as np

from ..models import CameraIntrinsics, CameraPose, ImageMetadata


def dji_ypr_to_R_enu_cam(yaw_deg: float, pitch_deg: float, roll_deg: float) -> np.ndarray:
    """Convert DJI Gimbal/Flight Yaw-Pitch-Roll (deg, NED) to R_wc (camera -> ENU world)."""
    y, p, r = np.deg2rad([yaw_deg, pitch_deg, roll_deg])
    cy, sy = np.cos(y), np.sin(y)
    cp, sp = np.cos(p), np.sin(p)
    cr, sr = np.cos(r), np.sin(r)

    Rz = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    Ry = np.array([[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]], dtype=np.float64)
    Rx = np.array([[1.0, 0.0, 0.0], [0.0, cr, -sr], [0.0, sr, cr]], dtype=np.float64)

    R_ned_body = Rz @ Ry @ Rx
    # Body (Forward, Right, Down) <- Camera (Right, Down, Forward)
    C_body_cam = np.array(
        [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64
    )
    # NED (N, E, D) -> ENU (E, N, U)
    T_enu_ned = np.array(
        [[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, -1.0]], dtype=np.float64
    )
    return T_enu_ned @ R_ned_body @ C_body_cam


def scale_intrinsics(intr: CameraIntrinsics, scale: float) -> CameraIntrinsics:
    """Scale camera intrinsics for a resized image."""
    if scale == 1.0:
        return intr
    return CameraIntrinsics(
        width=int(round(intr.width * scale)),
        height=int(round(intr.height * scale)),
        fx=intr.fx * scale,
        fy=intr.fy * scale,
        cx=intr.cx * scale,
        cy=intr.cy * scale,
        dist_coeffs=intr.dist_coeffs,
        model=intr.model,
    )


def pose_from_metadata(meta: ImageMetadata, scale: float = 1.0) -> CameraPose:
    """Construct an initial CameraPose from ImageMetadata."""
    if meta.intrinsics is None:
        raise ValueError(f"Missing intrinsics in metadata for {meta.filename}")
    R_wc = dji_ypr_to_R_enu_cam(meta.gimbal_yaw, meta.gimbal_pitch, meta.gimbal_roll)
    C_world = np.array([meta.easting, meta.northing, meta.elevation], dtype=np.float64)
    return CameraPose(
        filename=meta.filename,
        R_wc=R_wc,
        C_world=C_world,
        intrinsics=scale_intrinsics(meta.intrinsics, scale),
        refined=False,
    )


def project_world_to_image(
    pose: CameraPose, points_3d: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """Project (N, 3) world points into pixel coordinates (N, 2) and camera-space Z (N,)."""
    pts = np.atleast_2d(points_3d).astype(np.float64)
    p_cam = (pts - pose.C_world[None, :]) @ pose.R_wc  # R_cw = R_wc.T -> (p - C) @ R_wc
    z = p_cam[:, 2]
    safe_z = np.where(np.abs(z) > 1e-6, z, 1e-6)
    u = pose.intrinsics.fx * (p_cam[:, 0] / safe_z) + pose.intrinsics.cx
    v = pose.intrinsics.fy * (p_cam[:, 1] / safe_z) + pose.intrinsics.cy
    return np.stack([u, v], axis=-1), z


def ray_ground_intersection(
    pose: CameraPose, pixels: np.ndarray, ground_z: float
) -> np.ndarray:
    """Intersect camera rays through `pixels` (N, 2) with horizontal plane Z = ground_z."""
    px = np.atleast_2d(pixels).astype(np.float64)
    x_norm = (px[:, 0] - pose.intrinsics.cx) / pose.intrinsics.fx
    y_norm = (px[:, 1] - pose.intrinsics.cy) / pose.intrinsics.fy
    rays_cam = np.stack([x_norm, y_norm, np.ones_like(x_norm)], axis=-1)
    rays_world = rays_cam @ pose.R_wc.T  # (N, 3)
    dz = rays_world[:, 2]
    # Avoid parallel rays
    valid_dz = np.where(np.abs(dz) > 1e-6, dz, -1e-6)
    t = (ground_z - pose.C_world[2]) / valid_dz
    return pose.C_world[None, :] + t[:, None] * rays_world


def image_footprint(pose: CameraPose, ground_z: float) -> List[Tuple[float, float]]:
    """Compute the 4 ground-plane corner coordinates (E, N) of the image."""
    w, h = pose.intrinsics.width, pose.intrinsics.height
    corners = np.array([[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]], dtype=np.float64)
    pts = ray_ground_intersection(pose, corners, ground_z)
    return [(float(p[0]), float(p[1])) for p in pts]


def undistort_image(
    img: np.ndarray, intr: CameraIntrinsics, target_scale: float = 1.0
) -> Tuple[np.ndarray, CameraIntrinsics]:
    """Resize (if target_scale != 1.0) and undistort an image using Brown-Conrady coeffs."""
    if target_scale != 1.0:
        new_w = int(round(intr.width * target_scale))
        new_h = int(round(intr.height * target_scale))
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        intr = scale_intrinsics(intr, target_scale)

    dist = intr.dist_array
    if np.allclose(dist, 0.0):
        return img, intr

    K = intr.K
    undist = cv2.undistort(img, K, dist, None, K)
    return undist, intr

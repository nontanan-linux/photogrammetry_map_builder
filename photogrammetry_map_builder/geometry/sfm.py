"""Structure-from-Motion tie-point matching and georeferenced bundle adjustment."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from tqdm import tqdm

from ..models import (
    BundleResult,
    CameraPose,
    GroundControlPoint,
    ImageMetadata,
)
from .camera import pose_from_metadata, project_world_to_image, ray_ground_intersection


class _UnionFind:
    def __init__(self) -> None:
        self.parent: Dict[Tuple[int, int], Tuple[int, int]] = {}

    def find(self, x: Tuple[int, int]) -> Tuple[int, int]:
        if x not in self.parent:
            self.parent[x] = x
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: Tuple[int, int], b: Tuple[int, int]) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _triangulate_dlt(
    poses: List[CameraPose], pts_2d: List[np.ndarray]
) -> Optional[np.ndarray]:
    """Triangulate a single 3D point from >=2 camera views using linear DLT."""
    if len(poses) < 2:
        return None
    rows = []
    for pose, uv in zip(poses, pts_2d):
        R_cw = pose.R_wc.T
        t_cw = -R_cw @ pose.C_world
        P = pose.intrinsics.K @ np.hstack([R_cw, t_cw[:, None]])
        u, v = float(uv[0]), float(uv[1])
        rows.append(u * P[2, :] - P[0, :])
        rows.append(v * P[2, :] - P[1, :])
    A = np.asarray(rows, dtype=np.float64)
    _, _, vt = np.linalg.svd(A)
    X_hom = vt[-1]
    if abs(X_hom[3]) < 1e-9:
        return None
    return X_hom[:3] / X_hom[3]


def _select_spatial_pairs(
    metas: List[ImageMetadata], max_neighbors: int = 6, max_dist_m: float = 90.0
) -> List[Tuple[int, int]]:
    """Select overlapping image pairs based on 2D UTM proximity."""
    coords = np.array([[m.easting, m.northing] for m in metas], dtype=np.float64)
    n = len(metas)
    pairs = set()
    for i in range(n):
        dists = np.linalg.norm(coords - coords[i], axis=1)
        order = np.argsort(dists)
        count = 0
        for j in order:
            if j == i:
                continue
            if dists[j] > max_dist_m and count >= 2:
                break
            a, b = (i, int(j)) if i < j else (int(j), i)
            pairs.add((a, b))
            count += 1
            if count >= max_neighbors:
                break
    return sorted(pairs)


def run_sfm_bundle(
    images_meta: List[ImageMetadata],
    undistorted_images: Dict[str, np.ndarray],
    proc_scale: float = 0.25,
    gcps: Optional[List[GroundControlPoint]] = None,
    estimate_ground_z: float = 0.0,
    max_features: int = 2500,
    max_bundle_tracks: int = 1200,
    max_pair_dist_m: float = 90.0,
    show_progress: bool = True,
) -> BundleResult:
    """Run SIFT tie-point matching, triangulation, and georeferenced bundle adjustment."""
    n_cams = len(images_meta)
    name_to_idx = {m.filename: i for i, m in enumerate(images_meta)}
    initial_poses = [pose_from_metadata(m, scale=proc_scale) for m in images_meta]

    # 1. Extract SIFT features
    sift = cv2.SIFT_create(nfeatures=max_features)
    keypoints_list: List[List[cv2.KeyPoint]] = []
    descriptors_list: List[Optional[np.ndarray]] = []

    iterator = images_meta
    if show_progress:
        iterator = tqdm(images_meta, desc="Extracting SIFT features", unit="img")
    for m in iterator:
        img = undistorted_images[m.filename]
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.ndim == 3 else img
        kps, desc = sift.detectAndCompute(gray, None)
        keypoints_list.append(kps)
        descriptors_list.append(desc)

    # 2. Match spatial pairs with ratio test + RANSAC Fundamental matrix
    pairs = _select_spatial_pairs(images_meta, max_neighbors=6, max_dist_m=max_pair_dist_m)
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    uf = _UnionFind()
    matched_pairs = 0

    pair_iter = pairs
    if show_progress:
        pair_iter = tqdm(pairs, desc="Matching image pairs", unit="pair")
    for i, j in pair_iter:
        d1, d2 = descriptors_list[i], descriptors_list[j]
        if d1 is None or d2 is None or len(d1) < 12 or len(d2) < 12:
            continue
        raw_matches = matcher.knnMatch(d1, d2, k=2)
        good = []
        for pair_m in raw_matches:
            if len(pair_m) == 2 and pair_m[0].distance < 0.72 * pair_m[1].distance:
                good.append(pair_m[0])
        if len(good) < 12:
            continue

        pts1 = np.float32([keypoints_list[i][m.queryIdx].pt for m in good])
        pts2 = np.float32([keypoints_list[j][m.trainIdx].pt for m in good])
        _, mask = cv2.findFundamentalMat(pts1, pts2, cv2.FM_RANSAC, 2.5, 0.99)
        if mask is None:
            continue
        inliers = [good[k] for k in range(len(good)) if mask[k, 0]]
        if len(inliers) < 10:
            continue
        matched_pairs += 1
        for m in inliers:
            uf.union((i, m.queryIdx), (j, m.trainIdx))

    # 3. Build multi-view tracks
    tracks_dict: Dict[Tuple[int, int], Dict[int, int]] = defaultdict(dict)
    for node in list(uf.parent.keys()):
        root = uf.find(node)
        cam_idx, kp_idx = node
        if cam_idx not in tracks_dict[root]:
            tracks_dict[root][cam_idx] = kp_idx

    raw_tracks = [obs for obs in tracks_dict.values() if len(obs) >= 2]
    # Prefer tracks with more observations
    raw_tracks.sort(key=lambda d: len(d), reverse=True)

    def triangulate_tracks(
        poses: List[CameraPose], max_reproj_px: float
    ) -> Tuple[List[Dict[int, np.ndarray]], np.ndarray]:
        valid_obs: List[Dict[int, np.ndarray]] = []
        pts3d: List[np.ndarray] = []
        z_min = estimate_ground_z - 50.0
        z_max = estimate_ground_z + 120.0
        for obs in raw_tracks:
            cam_indices = list(obs.keys())
            p_list = [poses[c] for c in cam_indices]
            uv_list = [
                np.array(keypoints_list[c][obs[c]].pt, dtype=np.float64)
                for c in cam_indices
            ]
            X = _triangulate_dlt(p_list, uv_list)
            if X is None or not (z_min <= X[2] <= z_max):
                continue
            ok = True
            for p, uv in zip(p_list, uv_list):
                proj, z = project_world_to_image(p, X[None, :])
                if z[0] <= 1.0 or np.linalg.norm(proj[0] - uv) > max_reproj_px:
                    ok = False
                    break
            if ok:
                valid_obs.append({c: uv for c, uv in zip(cam_indices, uv_list)})
                pts3d.append(X)
        if not pts3d:
            return [], np.zeros((0, 3), dtype=np.float64)
        return valid_obs, np.asarray(pts3d, dtype=np.float64)

    # Initial triangulation (loose threshold to accommodate raw IMU drift)
    valid_tracks, tie_pts_3d = triangulate_tracks(initial_poses, max_reproj_px=80.0)

    # Prepare GCP observations indexed by camera
    gcp_obs_list: List[Tuple[int, np.ndarray, np.ndarray]] = []
    if gcps:
        for g in gcps:
            X_gcp = np.array([g.x, g.y, g.z], dtype=np.float64)
            for obs in g.observations:
                if obs.image_filename in name_to_idx:
                    c_idx = name_to_idx[obs.image_filename]
                    uv_scaled = np.array(
                        [obs.pixel_x * proc_scale, obs.pixel_y * proc_scale],
                        dtype=np.float64,
                    )
                    gcp_obs_list.append((c_idx, X_gcp, uv_scaled))

    # 4. Bundle Adjustment (2-pass alternating pose optimization + re-triangulation)
    poses = [
        CameraPose(
            filename=p.filename,
            R_wc=p.R_wc.copy(),
            C_world=p.C_world.copy(),
            intrinsics=p.intrinsics,
            refined=False,
        )
        for p in initial_poses
    ]

    if len(valid_tracks) > 0 or len(gcp_obs_list) > 0:
        for pass_idx, (reproj_thresh, n_iter) in enumerate([(80.0, 25), (6.0, 35)]):
            if pass_idx > 0:
                valid_tracks, tie_pts_3d = triangulate_tracks(poses, max_reproj_px=reproj_thresh)

            # Subsample tracks for bundle speed while keeping high-multiplicity tracks
            n_bundle = min(len(valid_tracks), max_bundle_tracks)
            bundle_tracks = valid_tracks[:n_bundle]
            bundle_pts = tie_pts_3d[:n_bundle]

            # Flatten observations for vectorized residual evaluation
            obs_cam: List[int] = []
            obs_pt_idx: List[int] = []
            obs_uv: List[np.ndarray] = []
            for pt_i, tr in enumerate(bundle_tracks):
                for c_i, uv in tr.items():
                    obs_cam.append(c_i)
                    obs_pt_idx.append(pt_i)
                    obs_uv.append(uv)
            obs_cam_arr = np.asarray(obs_cam, dtype=np.int32)
            obs_pt_arr = np.asarray(obs_pt_idx, dtype=np.int32)
            obs_uv_arr = (
                np.asarray(obs_uv, dtype=np.float64)
                if obs_uv
                else np.zeros((0, 2), dtype=np.float64)
            )

            R_ref = [p.R_wc.copy() for p in poses]
            C_rtk = np.array(
                [[m.easting, m.northing, m.elevation] for m in images_meta],
                dtype=np.float64,
            )
            rtk_sigmas = np.array(
                [
                    [
                        max(0.03, m.rtk_std_lon * 2.0) if m.rtk_flag == 50 else 2.0,
                        max(0.03, m.rtk_std_lat * 2.0) if m.rtk_flag == 50 else 2.0,
                        max(0.05, m.rtk_std_hgt * 2.0) if m.rtk_flag == 50 else 4.0,
                    ]
                    for m in images_meta
                ],
                dtype=np.float64,
            )
            rot_sigma = np.deg2rad(5.0)
            fx_arr = np.array([p.intrinsics.fx for p in poses], dtype=np.float64)
            fy_arr = np.array([p.intrinsics.fy for p in poses], dtype=np.float64)
            cx_arr = np.array([p.intrinsics.cx for p in poses], dtype=np.float64)
            cy_arr = np.array([p.intrinsics.cy for p in poses], dtype=np.float64)

            def residuals(params: np.ndarray) -> np.ndarray:
                cam_params = params.reshape(n_cams, 6)
                rvecs = cam_params[:, :3]
                dCs = cam_params[:, 3:6]
                R_deltas = Rotation.from_rotvec(rvecs).as_matrix()
                R_cur = np.einsum("nij,njk->nik", R_ref, R_deltas)
                C_cur = np.array([poses[k].C_world for k in range(n_cams)]) + dCs

                res_parts = []

                # Tie-point reprojection
                if len(obs_cam_arr) > 0:
                    X = bundle_pts[obs_pt_arr]
                    diff = X - C_cur[obs_cam_arr]
                    p_cam = np.einsum("ni,nij->nj", diff, R_cur[obs_cam_arr])
                    z = np.where(np.abs(p_cam[:, 2]) > 1e-5, p_cam[:, 2], 1e-5)
                    u = fx_arr[obs_cam_arr] * (p_cam[:, 0] / z) + cx_arr[obs_cam_arr]
                    v = fy_arr[obs_cam_arr] * (p_cam[:, 1] / z) + cy_arr[obs_cam_arr]
                    reproj = np.stack([u, v], axis=-1) - obs_uv_arr
                    res_parts.append(reproj.ravel())

                # GCP 3D-2D reprojection (high weight)
                if gcp_obs_list:
                    g_res = []
                    for c_i, X_g, uv_g in gcp_obs_list:
                        p_cam = R_cur[c_i].T @ (X_g - C_cur[c_i])
                        z = p_cam[2] if abs(p_cam[2]) > 1e-5 else 1e-5
                        u = fx_arr[c_i] * (p_cam[0] / z) + cx_arr[c_i]
                        v = fy_arr[c_i] * (p_cam[1] / z) + cy_arr[c_i]
                        g_res.append(5.0 * (u - uv_g[0]))
                        g_res.append(5.0 * (v - uv_g[1]))
                    res_parts.append(np.asarray(g_res, dtype=np.float64))

                # RTK GPS prior
                res_parts.append(((C_cur - C_rtk) / rtk_sigmas).ravel())

                # Gimbal rotation prior
                res_parts.append((rvecs / rot_sigma).ravel())

                return np.concatenate(res_parts)

            x0 = np.zeros(n_cams * 6, dtype=np.float64)
            sol = least_squares(
                residuals, x0, method="trf", loss="soft_l1", f_scale=2.0, max_nfev=n_iter
            )
            cam_opt = sol.x.reshape(n_cams, 6)
            R_deltas = Rotation.from_rotvec(cam_opt[:, :3]).as_matrix()
            for k in range(n_cams):
                poses[k].R_wc = R_ref[k] @ R_deltas[k]
                poses[k].C_world = poses[k].C_world + cam_opt[k, 3:6]
                poses[k].refined = True

    # 5. Final triangulation & reprojection error statistics
    final_tracks, final_pts3d = triangulate_tracks(poses, max_reproj_px=5.0)
    all_errs: List[float] = []
    cam_errs: Dict[int, List[float]] = defaultdict(list)
    colors = np.zeros((len(final_pts3d), 3), dtype=np.uint8)

    for pt_i, (tr, X) in enumerate(zip(final_tracks, final_pts3d)):
        first_cam = next(iter(tr))
        uv0 = tr[first_cam]
        img0 = undistorted_images[images_meta[first_cam].filename]
        ix = int(np.clip(round(uv0[0]), 0, img0.shape[1] - 1))
        iy = int(np.clip(round(uv0[1]), 0, img0.shape[0] - 1))
        colors[pt_i] = img0[iy, ix, :3] if img0.ndim == 3 else img0[iy, ix]

        for c_i, uv in tr.items():
            proj, _ = project_world_to_image(poses[c_i], X[None, :])
            err = float(np.linalg.norm(proj[0] - uv))
            all_errs.append(err)
            cam_errs[c_i].append(err)

    for c_i, p in enumerate(poses):
        if cam_errs[c_i]:
            p.reprojection_rmse_px = float(np.sqrt(np.mean(np.square(cam_errs[c_i]))))

    mean_reproj = float(np.mean(all_errs)) if all_errs else 0.0

    # 6. Evaluate GCP residuals (in full-res pixels & 3D meters)
    gcp_residuals: List[Dict[str, object]] = []
    gcp_3d_sq_errs: List[float] = []
    if gcps:
        for g in gcps:
            X_g = np.array([g.x, g.y, g.z], dtype=np.float64)
            for obs in g.observations:
                if obs.image_filename not in name_to_idx:
                    continue
                c_i = name_to_idx[obs.image_filename]
                pose_proc = poses[c_i]
                proj_proc, _ = project_world_to_image(pose_proc, X_g[None, :])
                proj_full = proj_proc[0] / proc_scale
                obs_full = np.array([obs.pixel_x, obs.pixel_y], dtype=np.float64)
                reproj_px = float(np.linalg.norm(proj_full - obs_full))

                # Ground-plane 3D error at GCP elevation
                obs_proc = obs_full * proc_scale
                X_ray = ray_ground_intersection(pose_proc, obs_proc[None, :], g.z)[0]
                err_3d = float(np.linalg.norm(X_ray - X_g))
                gcp_3d_sq_errs.append(err_3d ** 2)
                gcp_residuals.append(
                    {
                        "gcp_id": g.gcp_id,
                        "image": obs.image_filename,
                        "reproj_err_px": round(reproj_px, 2),
                        "err_3d_m": round(err_3d, 4),
                    }
                )

    gcp_rmse_3d = (
        float(np.sqrt(np.mean(gcp_3d_sq_errs))) if gcp_3d_sq_errs else None
    )

    poses_dict = {p.filename: p for p in poses}
    return BundleResult(
        poses=poses_dict,
        points_3d=final_pts3d,
        point_colors=colors,
        mean_reprojection_error_px=mean_reproj,
        gcp_rmse_3d_m=gcp_rmse_3d,
        gcp_residuals=gcp_residuals,
        num_tie_points=len(final_pts3d),
        num_matched_pairs=matched_pairs,
    )

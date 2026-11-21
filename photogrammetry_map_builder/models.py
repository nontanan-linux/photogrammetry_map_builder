"""Data models for photogrammetry_map_builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class CameraIntrinsics:
    """Pinhole + Brown-Conrady camera intrinsics."""

    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    # Radial & tangential distortion: (k1, k2, p1, p2, k3)
    dist_coeffs: Tuple[float, float, float, float, float] = (0.0, 0.0, 0.0, 0.0, 0.0)
    model: str = "brown_conrady"

    @property
    def K(self) -> np.ndarray:
        """3x3 intrinsic camera matrix."""
        return np.array(
            [
                [self.fx, 0.0, self.cx],
                [0.0, self.fy, self.cy],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )

    @property
    def dist_array(self) -> np.ndarray:
        """OpenCV distortion vector (k1, k2, p1, p2, k3)."""
        return np.array(self.dist_coeffs, dtype=np.float64)


@dataclass
class ImageMetadata:
    """Parsed EXIF/XMP/GIS metadata for a single drone image."""

    path: Path
    filename: str
    lat: float
    lon: float
    abs_alt: float
    rel_alt: float
    gimbal_yaw: float
    gimbal_pitch: float
    gimbal_roll: float
    flight_yaw: float = 0.0
    flight_pitch: float = 0.0
    flight_roll: float = 0.0
    lrf_abs_alt: Optional[float] = None
    rtk_flag: int = 0
    rtk_std_lat: float = 1.0
    rtk_std_lon: float = 1.0
    rtk_std_hgt: float = 2.0
    timestamp: str = ""
    drone_model: str = ""
    intrinsics: Optional[CameraIntrinsics] = None
    # Projected coordinates in target CRS (e.g. UTM)
    easting: float = 0.0
    northing: float = 0.0
    elevation: float = 0.0
    target_epsg: int = 0


@dataclass
class MRKRecord:
    """Single exposure record from a DJI .MRK RTK file."""

    seq: int
    gps_tow: float
    gps_week: int
    north_offset_mm: float
    east_offset_mm: float
    down_offset_mm: float
    lat: float
    lon: float
    ellh: float
    std_n: float
    std_e: float
    std_v: float
    quality: int


@dataclass
class GCPObservation:
    """2D pixel observation of a Ground Control Point in a specific image."""

    image_filename: str
    pixel_x: float
    pixel_y: float


@dataclass
class GroundControlPoint:
    """3D Ground Control Point with optional 2D image observations."""

    gcp_id: str
    x: float
    y: float
    z: float
    crs: str = "EPSG:4326"
    observations: List[GCPObservation] = field(default_factory=list)


@dataclass
class CameraPose:
    """6-DoF camera pose in target projected ENU/world coordinates.

    R_wc transforms camera coordinates to world coordinates: p_world = R_wc @ p_cam + C_world.
    """

    filename: str
    R_wc: np.ndarray  # (3, 3)
    C_world: np.ndarray  # (3,) [Easting, Northing, Elevation]
    intrinsics: CameraIntrinsics
    refined: bool = False
    reprojection_rmse_px: Optional[float] = None


@dataclass
class BundleResult:
    """Result of tie-point matching and bundle adjustment."""

    poses: Dict[str, CameraPose]
    points_3d: np.ndarray  # (N, 3)
    point_colors: np.ndarray  # (N, 3) uint8 RGB
    mean_reprojection_error_px: float
    gcp_rmse_3d_m: Optional[float] = None
    gcp_residuals: List[Dict[str, object]] = field(default_factory=list)
    num_tie_points: int = 0
    num_matched_pairs: int = 0


@dataclass
class MapProducts:
    """Paths and summary metrics for generated mapping products."""

    output_dir: Path
    target_epsg: int
    orthomosaic_tif: Optional[Path] = None
    orthomosaic_preview_png: Optional[Path] = None
    dsm_tif: Optional[Path] = None
    dtm_tif: Optional[Path] = None
    plant_health_tif: Optional[Path] = None
    plant_health_preview_png: Optional[Path] = None
    point_cloud_ply: Optional[Path] = None
    model_3d_obj: Optional[Path] = None
    flight_geojson: Optional[Path] = None
    report_json: Optional[Path] = None
    report_md: Optional[Path] = None
    dashboard_html: Optional[Path] = None
    stats: Dict[str, object] = field(default_factory=dict)

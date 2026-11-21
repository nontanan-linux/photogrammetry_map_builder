"""GIS vector (GeoJSON) and QA report (JSON / Markdown) exporters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pyproj

from ..models import BundleResult, GroundControlPoint, ImageMetadata


def _to_wgs84_transformer(src_epsg: int) -> pyproj.Transformer:
    return pyproj.Transformer.from_crs(
        f"EPSG:{src_epsg}", "EPSG:4326", always_xy=True
    )


def export_flight_geojson(
    output_path: Path | str,
    images: List[ImageMetadata],
    src_epsg: int,
    gcps: Optional[List[GroundControlPoint]] = None,
    footprints: Optional[Dict[str, List[Tuple[float, float]]]] = None,
    map_bounds_utm: Optional[Tuple[float, float, float, float]] = None,
) -> Path:
    """Export camera stations, flight trajectory, footprints, GCPs, and map bounds as GeoJSON (WGS84)."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    to_wgs84 = _to_wgs84_transformer(src_epsg)

    features: List[Dict[str, object]] = []

    # 1. Flight trajectory LineString
    if len(images) >= 2:
        coords = [[img.lon, img.lat, img.abs_alt] for img in images]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "layer": "flight_trajectory",
                    "num_images": len(images),
                    "drone_model": images[0].drone_model,
                },
            }
        )

    # 2. Camera stations
    for img in images:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [img.lon, img.lat, img.abs_alt]},
                "properties": {
                    "layer": "camera_station",
                    "filename": img.filename,
                    "timestamp": img.timestamp,
                    "easting": round(img.easting, 3),
                    "northing": round(img.northing, 3),
                    "abs_alt": round(img.abs_alt, 3),
                    "rel_alt": round(img.rel_alt, 3),
                    "gimbal_yaw": img.gimbal_yaw,
                    "gimbal_pitch": img.gimbal_pitch,
                    "rtk_flag": img.rtk_flag,
                },
            }
        )

    # 3. Image footprints (if provided in UTM)
    if footprints:
        for fname, poly_xy in footprints.items():
            ring = []
            for x, y in poly_xy:
                lon, lat = to_wgs84.transform(x, y)
                ring.append([lon, lat])
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {"layer": "image_footprint", "filename": fname},
                }
            )

    # 4. Ground Control Points
    if gcps:
        for g in gcps:
            lon, lat = to_wgs84.transform(g.x, g.y)
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat, g.z]},
                    "properties": {
                        "layer": "gcp",
                        "gcp_id": g.gcp_id,
                        "x": round(g.x, 4),
                        "y": round(g.y, 4),
                        "z": round(g.z, 4),
                        "num_observations": len(g.observations),
                    },
                }
            )

    # 5. Map bounding box
    if map_bounds_utm is not None:
        min_x, min_y, max_x, max_y = map_bounds_utm
        corners = [
            (min_x, min_y),
            (max_x, min_y),
            (max_x, max_y),
            (min_x, max_y),
            (min_x, min_y),
        ]
        ring = [list(to_wgs84.transform(x, y)) for x, y in corners]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {"layer": "map_bounds", "epsg": src_epsg},
            }
        )

    geojson = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(geojson, indent=2), encoding="utf-8")
    return path


def export_report(
    output_dir: Path | str,
    stem: str,
    stats: Dict[str, object],
    bundle: Optional[BundleResult] = None,
) -> Tuple[Path, Path]:
    """Export processing QA report as JSON and Markdown."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{stem}_report.json"
    md_path = out / f"{stem}_report.md"

    payload = dict(stats)
    if bundle is not None:
        payload["bundle"] = {
            "num_matched_pairs": bundle.num_matched_pairs,
            "num_tie_points": bundle.num_tie_points,
            "mean_reprojection_error_px": round(bundle.mean_reprojection_error_px, 4),
            "gcp_rmse_3d_m": (
                round(bundle.gcp_rmse_3d_m, 4) if bundle.gcp_rmse_3d_m is not None else None
            ),
            "gcp_residuals": bundle.gcp_residuals,
        }

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# Photogrammetry Map Builder Report: `{stem}`",
        "",
        "## Survey & Processing Summary",
        "",
    ]
    for k, v in stats.items():
        lines.append(f"- **{k}**: `{v}`")

    if bundle is not None:
        lines.extend(
            [
                "",
                "## Bundle Adjustment & Tie Points",
                "",
                f"- **Matched image pairs**: {bundle.num_matched_pairs}",
                f"- **3D tie points**: {bundle.num_tie_points}",
                f"- **Mean reprojection error (px)**: {bundle.mean_reprojection_error_px:.3f}",
            ]
        )
        if bundle.gcp_rmse_3d_m is not None:
            lines.append(f"- **GCP 3D RMSE (m)**: {bundle.gcp_rmse_3d_m:.4f}")
        if bundle.gcp_residuals:
            lines.extend(
                [
                    "",
                    "### GCP Residuals",
                    "",
                    "| GCP ID | Image | Reproj Err (px) | 3D Err (m) |",
                    "| --- | --- | ---: | ---: |",
                ]
            )
            for r in bundle.gcp_residuals:
                lines.append(
                    f"| {r['gcp_id']} | {r['image']} | {r['reproj_err_px']:.2f} | {r['err_3d_m']:.4f} |"
                )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path

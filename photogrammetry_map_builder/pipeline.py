"""End-to-end drone photogrammetry and GIS map building pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np
from PIL import Image
from tqdm import tqdm

from .geometry.camera import image_footprint, pose_from_metadata, undistort_image
from .geometry.dense import (
    build_3d_mesh_obj,
    build_dsm_and_point_cloud,
    build_dtm_from_dsm,
    render_elevation_preview,
)
from .geometry.sfm import run_sfm_bundle
from .io.dashboard import export_dashboard_html
from .io.exif_xmp import load_dataset_metadata
from .io.gcp import load_gcp_file, transform_gcps
from .io.geotiff import write_geotiff
from .io.gis import export_flight_geojson, export_report
from .io.mrk import parse_mrk_file
from .mapping.ortho import build_orthomosaic
from .mapping.plant_health import compute_plant_health_vari, render_plant_health_preview
from .models import GroundControlPoint, ImageMetadata, MapProducts


@dataclass
class PipelineConfig:
    """Configuration for the photogrammetry mapping pipeline."""

    image_dir: Path
    output_dir: Path
    gcp_file: Optional[Path] = None
    mrk_file: Optional[Path] = None
    target_epsg: Optional[int] = None
    proc_scale: float = 0.25
    ortho_gsd_m: float = 0.05
    dsm_resolution_m: float = 0.25
    max_images: Optional[int] = None
    max_features: int = 2500
    max_pair_dist_m: float = 90.0
    project_name: str = "drone_map"
    show_progress: bool = True


class MapBuilder:
    """Orchestrates drone imagery + GIS ingestion, SfM/BA, DSM, and orthomosaic generation."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def run(self) -> MapProducts:
        cfg = self.config
        out_dir = Path(cfg.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # 1. Ingest imagery metadata
        metas: List[ImageMetadata] = load_dataset_metadata(
            cfg.image_dir,
            target_epsg=cfg.target_epsg,
            max_images=cfg.max_images,
        )
        epsg = metas[0].target_epsg

        # Optional MRK log
        mrk_records = parse_mrk_file(cfg.mrk_file) if cfg.mrk_file else []

        # Optional GCPs
        gcps: List[GroundControlPoint] = []
        if cfg.gcp_file is not None:
            raw_gcps = load_gcp_file(cfg.gcp_file)
            gcps = transform_gcps(raw_gcps, epsg)

        # Estimate fallback ground Z (prefer LRFTargetAbsAlt, then GCP Z, else abs_alt - rel_alt)
        lrf_alts = [m.lrf_abs_alt for m in metas if m.lrf_abs_alt is not None]
        if lrf_alts:
            ground_z = float(np.median(lrf_alts))
        elif gcps:
            ground_z = float(np.median([g.z for g in gcps]))
        else:
            ground_z = float(np.median([m.abs_alt - m.rel_alt for m in metas]))

        # 2. Load & undistort images at processing scale
        undist_imgs: Dict[str, np.ndarray] = {}
        iterator = metas
        if cfg.show_progress:
            iterator = tqdm(metas, desc="Loading & undistorting images", unit="img")
        for m in iterator:
            with Image.open(m.path) as pil_img:
                rgb = np.asarray(pil_img.convert("RGB"))
            assert m.intrinsics is not None
            u_img, _ = undistort_image(rgb, m.intrinsics, target_scale=cfg.proc_scale)
            undist_imgs[m.filename] = u_img

        # 3. Run SfM tie-point matching + georeferenced bundle adjustment
        bundle = run_sfm_bundle(
            images_meta=metas,
            undistorted_images=undist_imgs,
            proc_scale=cfg.proc_scale,
            gcps=gcps if gcps else None,
            estimate_ground_z=ground_z,
            max_features=cfg.max_features,
            max_pair_dist_m=cfg.max_pair_dist_m,
            show_progress=cfg.show_progress,
        )

        # 4. Compute footprints & map bounds in target UTM CRS
        footprints: Dict[str, List[Tuple[float, float]]] = {}
        all_xs: List[float] = []
        all_ys: List[float] = []
        for m in metas:
            pose = bundle.poses.get(m.filename) or pose_from_metadata(m, scale=cfg.proc_scale)
            fp = image_footprint(pose, ground_z)
            footprints[m.filename] = fp
            for x, y in fp:
                all_xs.append(x)
                all_ys.append(y)

        bounds_xy = (min(all_xs), min(all_ys), max(all_xs), max(all_ys))

        # Organized output subdirectories
        dir_ortho = out_dir / "01_orthophoto"
        dir_elev = out_dir / "02_elevation"
        dir_health = out_dir / "03_plant_health"
        dir_3d = out_dir / "04_3d_model"
        dir_gis = out_dir / "05_gis_vectors"
        dir_reports = out_dir / "06_reports"
        for d in (dir_ortho, dir_elev, dir_health, dir_3d, dir_gis, dir_reports):
            d.mkdir(parents=True, exist_ok=True)

        # 5. Build 3D point cloud (.ply) & DSM (.tif) + preview
        ply_path = dir_3d / f"{cfg.project_name}_pointcloud.ply"
        dsm_grid, dsm_ox, dsm_oy, dsm_res = build_dsm_and_point_cloud(
            points_3d=bundle.points_3d,
            colors_rgb=bundle.point_colors,
            bounds_xy=bounds_xy,
            dsm_resolution_m=cfg.dsm_resolution_m,
            fallback_ground_z=ground_z,
            ply_path=ply_path if len(bundle.points_3d) > 0 else None,
        )
        dsm_path = dir_elev / f"{cfg.project_name}_dsm.tif"
        write_geotiff(
            dsm_path,
            dsm_grid,
            origin_x=dsm_ox,
            origin_y=dsm_oy,
            pixel_size=dsm_res,
            epsg=epsg,
            nodata=-9999.0,
        )
        dsm_prev = Image.fromarray(render_elevation_preview(dsm_grid), mode="RGBA")
        dsm_prev.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        dsm_prev.save(dir_elev / f"{cfg.project_name}_dsm_preview.png")

        # 5b. Build DTM (ground-filtered Terrain Model) + preview
        dtm_grid = build_dtm_from_dsm(dsm_grid, dsm_res=dsm_res)
        dtm_path = dir_elev / f"{cfg.project_name}_dtm.tif"
        write_geotiff(
            dtm_path,
            dtm_grid,
            origin_x=dsm_ox,
            origin_y=dsm_oy,
            pixel_size=dsm_res,
            epsg=epsg,
            nodata=-9999.0,
        )
        dtm_prev = Image.fromarray(render_elevation_preview(dtm_grid), mode="RGBA")
        dtm_prev.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        dtm_prev.save(dir_elev / f"{cfg.project_name}_dtm_preview.png")

        # 6. Build Orthomosaic (.tif + preview .png)
        ortho_rgba, ortho_ox, ortho_oy, ortho_gsd = build_orthomosaic(
            poses=bundle.poses,
            images_rgb=undist_imgs,
            img_scale=cfg.proc_scale,
            dsm=dsm_grid,
            dsm_ox=dsm_ox,
            dsm_oy=dsm_oy,
            dsm_res=dsm_res,
            bounds_xy=bounds_xy,
            ortho_gsd_m=cfg.ortho_gsd_m,
            show_progress=cfg.show_progress,
        )
        ortho_path = dir_ortho / f"{cfg.project_name}_ortho.tif"
        write_geotiff(
            ortho_path,
            ortho_rgba,
            origin_x=ortho_ox,
            origin_y=ortho_oy,
            pixel_size=ortho_gsd,
            epsg=epsg,
        )

        # Save downsampled PNG preview (max 2048px)
        preview_path = dir_ortho / f"{cfg.project_name}_ortho_preview.png"
        pil_ortho = Image.fromarray(ortho_rgba, mode="RGBA")
        pil_ortho.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        pil_ortho.save(preview_path)

        # 6b. Plant Health (RGB VARI index + preview)
        vari_grid = compute_plant_health_vari(ortho_rgba)
        plant_health_path = dir_health / f"{cfg.project_name}_plant_health_vari.tif"
        write_geotiff(
            plant_health_path,
            vari_grid,
            origin_x=ortho_ox,
            origin_y=ortho_oy,
            pixel_size=ortho_gsd,
            epsg=epsg,
            nodata=-9999.0,
        )
        ph_preview_rgba = render_plant_health_preview(vari_grid)
        ph_preview_path = dir_health / f"{cfg.project_name}_plant_health_preview.png"
        pil_ph = Image.fromarray(ph_preview_rgba, mode="RGBA")
        pil_ph.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        pil_ph.save(ph_preview_path)

        # 6c. 3D Textured/Colored Mesh Model (.obj)
        model_3d_path = dir_3d / f"{cfg.project_name}_3d_model.obj"
        build_3d_mesh_obj(
            model_3d_path,
            dsm=dsm_grid,
            dsm_ox=dsm_ox,
            dsm_oy=dsm_oy,
            dsm_res=dsm_res,
            ortho_rgba=ortho_rgba,
            ortho_ox=ortho_ox,
            ortho_oy=ortho_oy,
            ortho_gsd=ortho_gsd,
        )

        # 7. Export GIS vector GeoJSON & QA Report
        geojson_path = dir_gis / f"{cfg.project_name}_flight.geojson"
        export_flight_geojson(
            geojson_path,
            images=metas,
            src_epsg=epsg,
            gcps=gcps if gcps else None,
            footprints=footprints,
            map_bounds_utm=bounds_xy,
        )
        geojson_data = json.loads(geojson_path.read_text(encoding="utf-8"))

        stats: Dict[str, object] = {
            "project_name": cfg.project_name,
            "num_images": len(metas),
            "num_mrk_records": len(mrk_records),
            "num_gcps": len(gcps),
            "target_epsg": epsg,
            "estimated_ground_z_m": round(ground_z, 3),
            "ortho_gsd_m": ortho_gsd,
            "ortho_size_px": [int(ortho_rgba.shape[1]), int(ortho_rgba.shape[0])],
            "dsm_resolution_m": dsm_res,
            "bounds_utm": [round(v, 3) for v in bounds_xy],
        }
        report_json, report_md = export_report(
            dir_reports, cfg.project_name, stats=stats, bundle=bundle
        )

        products = MapProducts(
            output_dir=out_dir,
            target_epsg=epsg,
            orthomosaic_tif=ortho_path,
            orthomosaic_preview_png=preview_path,
            dsm_tif=dsm_path,
            dtm_tif=dtm_path,
            plant_health_tif=plant_health_path,
            plant_health_preview_png=ph_preview_path,
            point_cloud_ply=ply_path if ply_path.exists() else None,
            model_3d_obj=model_3d_path if model_3d_path.exists() else None,
            flight_geojson=geojson_path,
            report_json=report_json,
            report_md=report_md,
            stats=stats,
        )
        products.dashboard_html = export_dashboard_html(
            products, geojson_data=geojson_data, bundle=bundle
        )
        return products


def build_map(
    image_dir: Path | str,
    output_dir: Path | str,
    gcp_file: Optional[Path | str] = None,
    mrk_file: Optional[Path | str] = None,
    **kwargs: object,
) -> MapProducts:
    """Convenience function to run the full photogrammetry mapping pipeline."""
    cfg = PipelineConfig(
        image_dir=Path(image_dir),
        output_dir=Path(output_dir),
        gcp_file=Path(gcp_file) if gcp_file else None,
        mrk_file=Path(mrk_file) if mrk_file else None,
        **kwargs,  # type: ignore[arg-type]
    )
    return MapBuilder(cfg).run()

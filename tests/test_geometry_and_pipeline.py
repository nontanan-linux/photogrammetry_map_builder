"""Geometry round-trip tests and end-to-end pipeline integration test."""

import json
from pathlib import Path
import numpy as np

from photogrammetry_map_builder import PipelineConfig, MapBuilder
from photogrammetry_map_builder.geometry.camera import (
    pose_from_metadata,
    project_world_to_image,
    ray_ground_intersection,
)
from photogrammetry_map_builder.io import load_image_metadata

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_RAW = REPO_ROOT / "resource" / "Module-Test-Data" / "Rawdata" / "DJI_202609300833_038_bua"
SAMPLE_GCP = REPO_ROOT / "resource" / "Module-Test-Data" / "GCP" / "gcp_Bua_final.txt"
SAMPLE_MRK = SAMPLE_RAW / "DJI_20260930083707_0002_D.MRK"


def test_camera_ray_projection_roundtrip():
    meta = load_image_metadata(SAMPLE_RAW / "DJI_20260930083705_0001_V.JPG")
    pose = pose_from_metadata(meta)
    pixels = np.array([[2640.0, 1978.0], [1000.0, 800.0], [4200.0, 3100.0]])
    pts_3d = ray_ground_intersection(pose, pixels, ground_z=-7.7)
    reproj, z = project_world_to_image(pose, pts_3d)
    assert np.all(z > 50.0)
    assert np.allclose(reproj, pixels, atol=1e-4)


def test_end_to_end_pipeline_subset(tmp_path: Path):
    cfg = PipelineConfig(
        image_dir=SAMPLE_RAW,
        output_dir=tmp_path / "out",
        gcp_file=SAMPLE_GCP,
        mrk_file=SAMPLE_MRK,
        proc_scale=0.2,
        ortho_gsd_m=0.10,
        dsm_resolution_m=0.50,
        max_images=6,
        max_features=1200,
        project_name="bua_test",
        show_progress=False,
    )
    products = MapBuilder(cfg).run()

    assert products.target_epsg == 32647
    assert products.dashboard_html and products.dashboard_html.exists()
    assert products.orthomosaic_tif and products.orthomosaic_tif.parent.name == "01_orthophoto"
    assert products.dsm_tif and products.dsm_tif.parent.name == "02_elevation"
    assert products.dtm_tif and products.dtm_tif.parent.name == "02_elevation"
    assert products.plant_health_tif and products.plant_health_tif.parent.name == "03_plant_health"
    assert products.point_cloud_ply and products.point_cloud_ply.parent.name == "04_3d_model"
    assert products.model_3d_obj and products.model_3d_obj.parent.name == "04_3d_model"
    assert products.flight_geojson and products.flight_geojson.parent.name == "05_gis_vectors"
    assert products.report_json and products.report_json.parent.name == "06_reports"
    assert products.report_md and products.report_md.exists()

    geojson = json.loads(products.flight_geojson.read_text(encoding="utf-8"))
    assert geojson["type"] == "FeatureCollection"
    layers = {f["properties"]["layer"] for f in geojson["features"]}
    assert {"flight_trajectory", "camera_station", "image_footprint", "gcp", "map_bounds"}.issubset(layers)

    report = json.loads(products.report_json.read_text(encoding="utf-8"))
    assert report["num_images"] == 6
    assert report["bundle"]["num_tie_points"] > 20
    assert report["bundle"]["mean_reprojection_error_px"] < 3.0

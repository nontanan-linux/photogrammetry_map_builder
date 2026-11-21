"""Unit tests for I/O modules (EXIF/XMP, MRK, GCP, GeoTIFF)."""

from pathlib import Path
import struct
import numpy as np
from PIL import Image

from photogrammetry_map_builder.io import (
    load_gcp_file,
    load_image_metadata,
    parse_mrk_file,
    transform_gcps,
    utm_epsg_from_lon_lat,
    write_geotiff,
)

PKG_ROOT = Path(__file__).resolve().parents[1]
RESOURCES_DIR = PKG_ROOT / "resources" / "Module-Test-Data"
if not RESOURCES_DIR.exists():
    RESOURCES_DIR = PKG_ROOT.parent / "resource" / "Module-Test-Data"

SAMPLE_RAW = RESOURCES_DIR / "Rawdata" / "DJI_202609300833_038_bua"
SAMPLE_GCP = RESOURCES_DIR / "GCP"


def test_utm_epsg_from_lon_lat():
    assert utm_epsg_from_lon_lat(100.955, 13.233) == 32647
    assert utm_epsg_from_lon_lat(-73.985, -33.45) == 32718


def test_load_image_metadata_dji_m4e():
    img_path = SAMPLE_RAW / "DJI_20260930083705_0001_V.JPG"
    meta = load_image_metadata(img_path)
    assert meta.target_epsg == 32647
    assert meta.rtk_flag == 50
    assert meta.drone_model == "DJI Matrice 4E"
    assert meta.intrinsics is not None
    assert meta.intrinsics.width == 5280
    assert meta.intrinsics.height == 3956
    assert 3700.0 < meta.intrinsics.fx < 3750.0
    assert meta.lrf_abs_alt is not None
    assert 711000.0 < meta.easting < 712500.0
    assert 1463000.0 < meta.northing < 1464500.0


def test_parse_mrk_file():
    mrk_path = SAMPLE_RAW / "DJI_20260930083707_0002_D.MRK"
    records = parse_mrk_file(mrk_path)
    assert len(records) == 99
    assert records[0].seq == 1
    assert records[0].gps_week == 2438
    assert records[0].quality == 50
    assert 13.23 < records[0].lat < 13.24


def test_load_and_transform_gcps():
    gcps_wgs = load_gcp_file(SAMPLE_GCP / "EPSG4326_Bua.txt")
    assert len(gcps_wgs) == 5
    gcps_utm_from_wgs = transform_gcps(gcps_wgs, 32647)

    gcps_odm = load_gcp_file(SAMPLE_GCP / "gcp_Bua_final.txt")
    assert len(gcps_odm) == 5
    total_obs = sum(len(g.observations) for g in gcps_odm)
    assert total_obs == 15

    # Verify gcp01 coordinates match between EPSG:4326 transform and UTM file
    g1_wgs = next(g for g in gcps_utm_from_wgs if g.gcp_id == "gcp01")
    g1_odm = next(g for g in gcps_odm if g.gcp_id == "gcp01")
    assert abs(g1_wgs.x - g1_odm.x) < 0.05
    assert abs(g1_wgs.y - g1_odm.y) < 0.05


def test_write_geotiff_rgb_and_dsm(tmp_path: Path):
    rgb = np.zeros((32, 48, 4), dtype=np.uint8)
    rgb[..., 0] = 120
    rgb[..., 3] = 255
    ortho_path = tmp_path / "test_ortho.tif"
    write_geotiff(ortho_path, rgb, origin_x=711800.0, origin_y=1463750.0, pixel_size=0.05, epsg=32647)

    assert ortho_path.exists()
    assert ortho_path.with_suffix(".tfw").exists()
    assert ortho_path.with_suffix(".prj").exists()
    header = ortho_path.read_bytes()[:4]
    assert header[:2] == b"II"
    assert struct.unpack("<H", header[2:4])[0] == 42
    with Image.open(ortho_path) as im:
        assert im.size == (48, 32)

    dsm = np.full((16, 24), -7.5, dtype=np.float32)
    dsm_path = tmp_path / "test_dsm.tif"
    write_geotiff(dsm_path, dsm, origin_x=711800.0, origin_y=1463750.0, pixel_size=0.25, epsg=32647, nodata=-9999.0)
    assert dsm_path.exists()

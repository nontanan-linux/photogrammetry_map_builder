"""EXIF and DJI XMP metadata extraction and CRS projection."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import math
from PIL import Image, ExifTags
import pyproj

from ..models import CameraIntrinsics, ImageMetadata


def utm_epsg_from_lon_lat(lon: float, lat: float) -> int:
    """Return the WGS 84 UTM EPSG code (326xx north / 327xx south) for lon/lat."""
    zone = int(math.floor((lon + 180.0) / 6.0) + 1)
    zone = max(1, min(60, zone))
    return (32600 + zone) if lat >= 0.0 else (32700 + zone)


def _dms_to_deg(dms: Tuple[float, float, float], ref: str) -> float:
    deg = float(dms[0]) + float(dms[1]) / 60.0 + float(dms[2]) / 3600.0
    if ref in ("S", "W"):
        deg = -deg
    return deg


def _parse_dewarp_data(
    raw: str, width: int, height: int
) -> Optional[Tuple[float, float, float, float, Tuple[float, float, float, float, float]]]:
    """Parse DJI DewarpData string: 'YYYY-MM-DD;fx,fy,cx_off,cy_off,k1,k2,p1,p2,k3'."""
    if not raw or ";" not in raw:
        return None
    try:
        _, params_str = raw.split(";", 1)
        vals = [float(v.strip()) for v in params_str.split(",") if v.strip()]
        if len(vals) < 9:
            return None
        fx, fy, cx_off, cy_off, k1, k2, p1, p2, k3 = vals[:9]
        cx = width / 2.0 + cx_off
        cy = height / 2.0 + cy_off
        return fx, fy, cx, cy, (k1, k2, p1, p2, k3)
    except (ValueError, TypeError):
        return None


def _extract_xmp_description(img: Image.Image) -> Dict[str, str]:
    if not hasattr(img, "getxmp"):
        return {}
    try:
        xmp = img.getxmp() or {}
        desc = xmp.get("xmpmeta", {}).get("RDF", {}).get("Description", {})
        if isinstance(desc, list) and desc:
            desc = desc[0]
        return desc if isinstance(desc, dict) else {}
    except Exception:
        return {}


def load_image_metadata(
    image_path: Path | str, target_epsg: Optional[int] = None
) -> ImageMetadata:
    """Read EXIF and DJI XMP metadata from a drone image and project to target CRS."""
    path = Path(image_path)
    with Image.open(path) as img:
        width, height = img.size
        exif = img.getexif()
        xmp = _extract_xmp_description(img)
        gps_ifd = exif.get_ifd(0x8825) if exif else {}
        exif_ifd = exif.get_ifd(0x8769) if exif else {}

    gps_named = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}

    # Coordinates: prefer XMP (high precision RTK) then EXIF GPS
    if "GpsLatitude" in xmp and "GpsLongitude" in xmp:
        lat = float(xmp["GpsLatitude"])
        lon = float(xmp["GpsLongitude"])
    elif "GPSLatitude" in gps_named and "GPSLongitude" in gps_named:
        lat = _dms_to_deg(gps_named["GPSLatitude"], str(gps_named.get("GPSLatitudeRef", "N")))
        lon = _dms_to_deg(gps_named["GPSLongitude"], str(gps_named.get("GPSLongitudeRef", "E")))
    else:
        raise ValueError(f"No GPS coordinates found in {path}")

    abs_alt = float(
        xmp.get("AbsoluteAltitude", gps_named.get("GPSAltitude", 0.0))
    )
    rel_alt = float(xmp.get("RelativeAltitude", abs_alt))
    lrf_abs_alt = float(xmp["LRFTargetAbsAlt"]) if "LRFTargetAbsAlt" in xmp else None

    gimbal_yaw = float(xmp.get("GimbalYawDegree", 0.0))
    gimbal_pitch = float(xmp.get("GimbalPitchDegree", -90.0))
    gimbal_roll = float(xmp.get("GimbalRollDegree", 0.0))
    flight_yaw = float(xmp.get("FlightYawDegree", 0.0))
    flight_pitch = float(xmp.get("FlightPitchDegree", 0.0))
    flight_roll = float(xmp.get("FlightRollDegree", 0.0))

    rtk_flag = int(float(xmp.get("RtkFlag", 0)))
    rtk_std_lat = float(xmp.get("RtkStdLat", 1.0))
    rtk_std_lon = float(xmp.get("RtkStdLon", 1.0))
    rtk_std_hgt = float(xmp.get("RtkStdHgt", 2.0))

    # Intrinsics: prefer DewarpData, fallback to CalibratedFocalLength, fallback to 35mm eq
    dewarp = _parse_dewarp_data(xmp.get("DewarpData", ""), width, height)
    if dewarp is not None:
        fx, fy, cx, cy, dist = dewarp
    elif "CalibratedFocalLength" in xmp:
        fx = fy = float(xmp["CalibratedFocalLength"])
        cx = float(xmp.get("CalibratedOpticalCenterX", width / 2.0))
        cy = float(xmp.get("CalibratedOpticalCenterY", height / 2.0))
        dist = (0.0, 0.0, 0.0, 0.0, 0.0)
    else:
        f35 = float(exif_ifd.get(41989, 24.0))
        fx = fy = (f35 / 36.0) * width
        cx, cy = width / 2.0, height / 2.0
        dist = (0.0, 0.0, 0.0, 0.0, 0.0)

    intrinsics = CameraIntrinsics(
        width=width, height=height, fx=fx, fy=fy, cx=cx, cy=cy, dist_coeffs=dist
    )

    epsg = target_epsg or utm_epsg_from_lon_lat(lon, lat)
    transformer = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    easting, northing = transformer.transform(lon, lat)

    return ImageMetadata(
        path=path,
        filename=path.name,
        lat=lat,
        lon=lon,
        abs_alt=abs_alt,
        rel_alt=rel_alt,
        gimbal_yaw=gimbal_yaw,
        gimbal_pitch=gimbal_pitch,
        gimbal_roll=gimbal_roll,
        flight_yaw=flight_yaw,
        flight_pitch=flight_pitch,
        flight_roll=flight_roll,
        lrf_abs_alt=lrf_abs_alt,
        rtk_flag=rtk_flag,
        rtk_std_lat=rtk_std_lat,
        rtk_std_lon=rtk_std_lon,
        rtk_std_hgt=rtk_std_hgt,
        timestamp=str(xmp.get("CreateDate", exif.get(306, "") if exif else "")),
        drone_model=str(xmp.get("ProductName", xmp.get("Model", ""))),
        intrinsics=intrinsics,
        easting=float(easting),
        northing=float(northing),
        elevation=abs_alt,
        target_epsg=epsg,
    )


def load_dataset_metadata(
    image_dir: Path | str,
    target_epsg: Optional[int] = None,
    max_images: Optional[int] = None,
    extensions: Tuple[str, ...] = (".jpg", ".jpeg", ".tif", ".tiff"),
) -> List[ImageMetadata]:
    """Load metadata for all drone images in a directory, sorted by filename."""
    img_dir = Path(image_dir)
    if not img_dir.is_dir():
        raise FileNotFoundError(f"Image directory not found: {img_dir}")

    paths = sorted(
        p for p in img_dir.iterdir() if p.is_file() and p.suffix.lower() in extensions
    )
    if max_images is not None:
        paths = paths[:max_images]
    if not paths:
        raise ValueError(f"No images found in {img_dir}")

    first = load_image_metadata(paths[0], target_epsg=target_epsg)
    resolved_epsg = target_epsg or first.target_epsg
    results = [first]
    for p in paths[1:]:
        results.append(load_image_metadata(p, target_epsg=resolved_epsg))
    return results

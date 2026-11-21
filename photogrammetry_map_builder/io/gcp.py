"""Ground Control Point (GCP) file parsers and CRS transformation."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List
import pyproj

from ..models import GCPObservation, GroundControlPoint


def load_gcp_file(gcp_path: Path | str) -> List[GroundControlPoint]:
    """Load GCPs from either ODM/Pix4D format or simple EPSG4326 format.

    Supported formats:
    1) ODM/Pix4D:
       Line 1: CRS string (e.g. '+proj=utm +zone=47 ...' or 'EPSG:4326')
       Lines 2+: X  Y  Z  px_x  px_y  image_filename  gcp_id
    2) Simple 4-column coordinate list:
       Line 1: CRS string (e.g. 'EPSG:4326')
       Lines 2+: gcp_id  lon_or_x  lat_or_y  z
    """
    path = Path(gcp_path)
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return []

    crs_str = lines[0]
    # Validate CRS string
    pyproj.CRS.from_user_input(crs_str)

    gcps: Dict[str, GroundControlPoint] = {}
    for ln in lines[1:]:
        parts = ln.split()
        if len(parts) >= 7:
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
            px_x, px_y = float(parts[3]), float(parts[4])
            img_name = parts[5]
            gcp_id = parts[6]
            if gcp_id not in gcps:
                gcps[gcp_id] = GroundControlPoint(gcp_id=gcp_id, x=x, y=y, z=z, crs=crs_str)
            gcps[gcp_id].observations.append(
                GCPObservation(image_filename=img_name, pixel_x=px_x, pixel_y=px_y)
            )
        elif len(parts) == 4:
            gcp_id = parts[0]
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            if gcp_id not in gcps:
                gcps[gcp_id] = GroundControlPoint(gcp_id=gcp_id, x=x, y=y, z=z, crs=crs_str)
        else:
            raise ValueError(f"Unrecognized GCP line format in {path}: {ln}")

    return list(gcps.values())


def transform_gcps(
    gcps: List[GroundControlPoint], target_epsg: int
) -> List[GroundControlPoint]:
    """Return a new list of GCPs transformed to `EPSG:{target_epsg}`."""
    target_crs = f"EPSG:{target_epsg}"
    transformed: List[GroundControlPoint] = []
    transformers: Dict[str, pyproj.Transformer] = {}

    for g in gcps:
        if g.crs not in transformers:
            transformers[g.crs] = pyproj.Transformer.from_crs(
                pyproj.CRS.from_user_input(g.crs),
                pyproj.CRS.from_epsg(target_epsg),
                always_xy=True,
            )
        tx, ty = transformers[g.crs].transform(g.x, g.y)
        transformed.append(
            GroundControlPoint(
                gcp_id=g.gcp_id,
                x=float(tx),
                y=float(ty),
                z=float(g.z),
                crs=target_crs,
                observations=list(g.observations),
            )
        )
    return transformed

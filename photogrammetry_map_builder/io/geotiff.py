"""Pure-Python GeoTIFF, World File (.tfw), and Projection (.prj) writer."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple
import struct
import numpy as np
import pyproj


# TIFF tag IDs
_TAG_IMAGE_WIDTH = 256
_TAG_IMAGE_LENGTH = 257
_TAG_BITS_PER_SAMPLE = 258
_TAG_COMPRESSION = 259
_TAG_PHOTOMETRIC = 262
_TAG_STRIP_OFFSETS = 273
_TAG_SAMPLES_PER_PIXEL = 277
_TAG_ROWS_PER_STRIP = 278
_TAG_STRIP_BYTE_COUNTS = 279
_TAG_PLANAR_CONFIG = 284
_TAG_SAMPLE_FORMAT = 339
_TAG_EXTRA_SAMPLES = 338
_TAG_MODEL_PIXEL_SCALE = 33550
_TAG_MODEL_TIEPOINT = 33922
_TAG_GEO_KEY_DIRECTORY = 34735
_TAG_GEO_ASCII_PARAMS = 34737
_TAG_GDAL_NODATA = 42113

# TIFF types
_TYPE_BYTE = 1
_TYPE_ASCII = 2
_TYPE_SHORT = 3
_TYPE_LONG = 4
_TYPE_DOUBLE = 12


def _pack_ifd_entry(tag: int, tiff_type: int, count: int, value_bytes: bytes) -> bytes:
    assert len(value_bytes) == 4
    return struct.pack("<HHII", tag, tiff_type, count, struct.unpack("<I", value_bytes)[0])


def _pack_inline_or_offset(
    tag: int, tiff_type: int, count: int, raw: bytes, data_blocks: List[bytes], next_offset: int
) -> Tuple[bytes, int]:
    if len(raw) <= 4:
        padded = raw.ljust(4, b"\x00")
        return _pack_ifd_entry(tag, tiff_type, count, padded), next_offset
    data_blocks.append(raw)
    if len(raw) % 2 == 1:
        data_blocks.append(b"\x00")
        pad = 1
    else:
        pad = 0
    entry = struct.pack("<HHII", tag, tiff_type, count, next_offset)
    return entry, next_offset + len(raw) + pad


def write_geotiff(
    output_path: Path | str,
    array: np.ndarray,
    origin_x: float,
    origin_y: float,
    pixel_size: float,
    epsg: int,
    nodata: Optional[float] = None,
    write_sidecars: bool = True,
) -> Path:
    """Write a 2D (float32/uint8) or 3D (H, W, C uint8) array as a standard GeoTIFF.

    Parameters
    ----------
    output_path:
        Destination `.tif` file path.
    array:
        Image array of shape `(H, W)` (single-band) or `(H, W, C)` with C in {3, 4}.
    origin_x, origin_y:
        World coordinates of the top-left corner of pixel (0, 0).
    pixel_size:
        Ground sample distance in meters (assumed square pixels).
    epsg:
        Projected EPSG code (e.g. 32647 for WGS 84 / UTM zone 47N).
    nodata:
        Optional nodata value (written to GDAL_NODATA tag 42113).
    write_sidecars:
        If True, also writes `.tfw` world file and `.prj` WKT file.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    arr = np.ascontiguousarray(array)
    if arr.ndim == 2:
        height, width = arr.shape
        channels = 1
    elif arr.ndim == 3 and arr.shape[2] in (3, 4):
        height, width, channels = arr.shape
    else:
        raise ValueError(f"Unsupported array shape for GeoTIFF: {arr.shape}")

    if arr.dtype == np.uint8:
        bps = 8
        sample_format = 1
    elif arr.dtype == np.float32:
        bps = 32
        sample_format = 3
    else:
        arr = arr.astype(np.float32)
        bps = 32
        sample_format = 3

    photometric = 2 if channels >= 3 else 1
    crs = pyproj.CRS.from_epsg(epsg)
    crs_name = (crs.name + "|").encode("ascii", errors="replace") + b"\x00"

    # Layout:
    # [0..8) TIFF Header: 'II', 42, ifd_offset=8
    # [8..8 + 2 + N*12 + 4) IFD
    # Extra tag payloads
    # Image pixel data (single strip for simplicity & universal compatibility)
    tags: List[Tuple[int, int, int, bytes]] = [
        (_TAG_IMAGE_WIDTH, _TYPE_LONG, 1, struct.pack("<I", width)),
        (_TAG_IMAGE_LENGTH, _TYPE_LONG, 1, struct.pack("<I", height)),
        (
            _TAG_BITS_PER_SAMPLE,
            _TYPE_SHORT,
            channels,
            struct.pack(f"<{channels}H", *([bps] * channels)),
        ),
        (_TAG_COMPRESSION, _TYPE_SHORT, 1, struct.pack("<H", 1)),
        (_TAG_PHOTOMETRIC, _TYPE_SHORT, 1, struct.pack("<H", photometric)),
        (_TAG_STRIP_OFFSETS, _TYPE_LONG, 1, b"\x00\x00\x00\x00"),  # placeholder
        (_TAG_SAMPLES_PER_PIXEL, _TYPE_SHORT, 1, struct.pack("<H", channels)),
        (_TAG_ROWS_PER_STRIP, _TYPE_LONG, 1, struct.pack("<I", height)),
        (
            _TAG_STRIP_BYTE_COUNTS,
            _TYPE_LONG,
            1,
            struct.pack("<I", arr.nbytes),
        ),
        (_TAG_PLANAR_CONFIG, _TYPE_SHORT, 1, struct.pack("<H", 1)),
        (
            _TAG_SAMPLE_FORMAT,
            _TYPE_SHORT,
            channels,
            struct.pack(f"<{channels}H", *([sample_format] * channels)),
        ),
    ]

    if channels == 4:
        tags.append((_TAG_EXTRA_SAMPLES, _TYPE_SHORT, 1, struct.pack("<H", 2)))

    # GeoTIFF tags
    tags.append(
        (
            _TAG_MODEL_PIXEL_SCALE,
            _TYPE_DOUBLE,
            3,
            struct.pack("<3d", float(pixel_size), float(pixel_size), 0.0),
        )
    )
    tags.append(
        (
            _TAG_MODEL_TIEPOINT,
            _TYPE_DOUBLE,
            6,
            struct.pack("<6d", 0.0, 0.0, 0.0, float(origin_x), float(origin_y), 0.0),
        )
    )
    geokeys = [
        1, 1, 0, 4,       # KeyDirectoryVersion, KeyRevision, MinorRevision, NumberOfKeys
        1024, 0, 1, 1,    # GTModelTypeGeoKey = ModelTypeProjected (1)
        1025, 0, 1, 1,    # GTRasterTypeGeoKey = RasterPixelIsArea (1)
        3072, 0, 1, epsg, # ProjectedCSTypeGeoKey
        3076, 0, 1, 9001, # ProjLinearUnitsGeoKey = Linear_Meter (9001)
    ]
    tags.append(
        (
            _TAG_GEO_KEY_DIRECTORY,
            _TYPE_SHORT,
            len(geokeys),
            struct.pack(f"<{len(geokeys)}H", *geokeys),
        )
    )
    tags.append((_TAG_GEO_ASCII_PARAMS, _TYPE_ASCII, len(crs_name), crs_name))

    if nodata is not None:
        nd_bytes = f"{nodata}\x00".encode("ascii")
        tags.append((_TAG_GDAL_NODATA, _TYPE_ASCII, len(nd_bytes), nd_bytes))

    # TIFF requires tags sorted ascending by tag ID
    tags.sort(key=lambda t: t[0])

    ifd_offset = 8
    ifd_size = 2 + len(tags) * 12 + 4
    next_offset = ifd_offset + ifd_size

    data_blocks: List[bytes] = []
    ifd_entries: List[bytes] = []
    strip_offset_entry_idx = -1

    for idx, (tag, ttype, count, raw) in enumerate(tags):
        if tag == _TAG_STRIP_OFFSETS:
            strip_offset_entry_idx = idx
        entry, next_offset = _pack_inline_or_offset(
            tag, ttype, count, raw, data_blocks, next_offset
        )
        ifd_entries.append(entry)

    # Pixel data starts right after extra tag blocks
    pixel_data_offset = next_offset
    ifd_entries[strip_offset_entry_idx] = struct.pack(
        "<HHII", _TAG_STRIP_OFFSETS, _TYPE_LONG, 1, pixel_data_offset
    )

    with path.open("wb") as f:
        f.write(struct.pack("<2sHI", b"II", 42, ifd_offset))
        f.write(struct.pack("<H", len(tags)))
        for entry in ifd_entries:
            f.write(entry)
        f.write(struct.pack("<I", 0))  # next IFD offset = 0
        for blk in data_blocks:
            f.write(blk)
        f.write(arr.tobytes())

    if write_sidecars:
        # Esri World File (.tfw): pixel_x, rot_y, rot_x, -pixel_y, center_x, center_y
        tfw_path = path.with_suffix(".tfw")
        half = pixel_size / 2.0
        tfw_path.write_text(
            f"{pixel_size:.10f}\n0.0000000000\n0.0000000000\n{-pixel_size:.10f}\n"
            f"{origin_x + half:.6f}\n{origin_y - half:.6f}\n",
            encoding="utf-8",
        )
        prj_path = path.with_suffix(".prj")
        prj_path.write_text(crs.to_wkt(), encoding="utf-8")

    return path

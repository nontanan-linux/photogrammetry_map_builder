"""Parser for DJI .MRK RTK event mark files."""

from __future__ import annotations

from pathlib import Path
from typing import List
import re

from ..models import MRKRecord


def _num(token: str) -> float:
    return float(token.split(",")[0].strip())


def parse_mrk_file(mrk_path: Path | str) -> List[MRKRecord]:
    """Parse a DJI .MRK file into a list of MRKRecord entries."""
    path = Path(mrk_path)
    records: List[MRKRecord] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = re.split(r"\t+", line)
            if len(parts) < 11:
                continue
            seq = int(parts[0].strip())
            gps_tow = float(parts[1].strip())
            gps_week = int(parts[2].strip("[] "))
            north_mm = _num(parts[3])
            east_mm = _num(parts[4])
            down_mm = _num(parts[5])
            lat = _num(parts[6])
            lon = _num(parts[7])
            ellh = _num(parts[8])
            stds = [float(s.strip()) for s in parts[9].split(",")]
            std_n, std_e, std_v = stds[0], stds[1], stds[2]
            quality = int(_num(parts[10]))
            records.append(
                MRKRecord(
                    seq=seq,
                    gps_tow=gps_tow,
                    gps_week=gps_week,
                    north_offset_mm=north_mm,
                    east_offset_mm=east_mm,
                    down_offset_mm=down_mm,
                    lat=lat,
                    lon=lon,
                    ellh=ellh,
                    std_n=std_n,
                    std_e=std_e,
                    std_v=std_v,
                    quality=quality,
                )
            )
    return records

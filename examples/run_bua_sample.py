"""Example script: run photogrammetry_map_builder on the Module-Test-Data sample."""

from pathlib import Path
from photogrammetry_map_builder import build_map

PKG_ROOT = Path(__file__).resolve().parents[1]
RESOURCES_DIR = PKG_ROOT / "resources" / "Module-Test-Data"
if not RESOURCES_DIR.exists():
    RESOURCES_DIR = PKG_ROOT.parent / "resource" / "Module-Test-Data"

RAW_DIR = RESOURCES_DIR / "Rawdata" / "DJI_202609300833_038_bua"
GCP_FILE = RESOURCES_DIR / "GCP" / "gcp_Bua_final.txt"
MRK_FILE = RAW_DIR / "DJI_20260930083707_0002_D.MRK"


def main() -> None:
    products = build_map(
        image_dir=RAW_DIR,
        output_dir=PKG_ROOT / "outputs" / "bua_sample",
        gcp_file=GCP_FILE,
        mrk_file=MRK_FILE,
        project_name="bua_sample",
        ortho_gsd_m=0.05,
        dsm_resolution_m=0.25,
        proc_scale=0.25,
    )
    print("Dashboard HTML:", products.dashboard_html)


if __name__ == "__main__":
    main()

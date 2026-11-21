"""Command-line interface for photogrammetry_map_builder."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from .io.exif_xmp import load_dataset_metadata
from .io.gcp import load_gcp_file
from .pipeline import MapBuilder, PipelineConfig


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pmb",
        description="Drone Photogrammetry & GIS Map Builder",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # build
    p_build = sub.add_parser(
        "build",
        help="Build orthomosaic, DSM, 3D point cloud, and GIS GeoJSON from drone imagery.",
    )
    p_build.add_argument("--input", "-i", default=None, help="Directory with drone images.")
    p_build.add_argument("--output", "-o", default=None, help="Output directory.")
    p_build.add_argument("--config", "-c", default=None, help="Optional YAML config file.")
    p_build.add_argument("--gcp", default=None, help="Optional GCP file path.")
    p_build.add_argument("--mrk", default=None, help="Optional DJI .MRK file path.")
    p_build.add_argument("--epsg", type=int, default=None, help="Target projected EPSG (auto UTM if omitted).")
    p_build.add_argument("--gsd", type=float, default=None, help="Orthomosaic GSD in meters/px (default: 0.05).")
    p_build.add_argument("--dsm-res", type=float, default=None, help="DSM resolution in meters/px (default: 0.25).")
    p_build.add_argument("--scale", type=float, default=None, help="Image processing scale (default: 0.25).")
    p_build.add_argument("--max-images", type=int, default=None, help="Optional limit on number of images.")
    p_build.add_argument("--name", default=None, help="Output filename prefix (default: drone_map).")
    p_build.add_argument("--quiet", action="store_true", help="Disable progress bars.")

    # inspect
    p_inspect = sub.add_parser(
        "inspect",
        help="Inspect drone dataset EXIF/XMP metadata and optional GCP file.",
    )
    p_inspect.add_argument("--input", "-i", required=True, help="Directory with drone images.")
    p_inspect.add_argument("--gcp", default=None, help="Optional GCP file path.")

    # view
    p_view = sub.add_parser(
        "view",
        help="Show output structure and launch local web viewer for index.html.",
    )
    p_view.add_argument("--output", "-o", required=True, help="Output directory containing index.html.")
    p_view.add_argument("--port", type=int, default=8765, help="Local HTTP server port (default: 8765).")
    p_view.add_argument("--no-serve", action="store_true", help="Print file paths without starting HTTP server.")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "inspect":
        metas = load_dataset_metadata(args.input)
        lats = [m.lat for m in metas]
        lons = [m.lon for m in metas]
        alts = [m.abs_alt for m in metas]
        rtk_fixed = sum(1 for m in metas if m.rtk_flag == 50)
        print(f"Images: {len(metas)} ({metas[0].drone_model})")
        print(f"Auto UTM EPSG: {metas[0].target_epsg}")
        print(f"Lat range: {min(lats):.7f} .. {max(lats):.7f}")
        print(f"Lon range: {min(lons):.7f} .. {max(lons):.7f}")
        print(f"Abs Alt range: {min(alts):.2f} .. {max(alts):.2f} m")
        print(f"RTK Fixed (flag=50): {rtk_fixed}/{len(metas)}")
        if args.gcp:
            gcps = load_gcp_file(args.gcp)
            obs_cnt = sum(len(g.observations) for g in gcps)
            print(f"GCPs: {len(gcps)} ({obs_cnt} image observations), CRS: {gcps[0].crs if gcps else 'N/A'}")
        return 0

    if args.command == "build":
        import yaml

        raw_cfg = {}
        if args.config:
            raw_cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}

        image_dir = args.input or raw_cfg.get("image_dir")
        output_dir = args.output or raw_cfg.get("output_dir")
        if not image_dir or not output_dir:
            parser.error("--input and --output are required (either via CLI or --config).")

        gcp_val = args.gcp or raw_cfg.get("gcp_file")
        mrk_val = args.mrk or raw_cfg.get("mrk_file")

        cfg = PipelineConfig(
            image_dir=Path(image_dir),
            output_dir=Path(output_dir),
            gcp_file=Path(gcp_val) if gcp_val else None,
            mrk_file=Path(mrk_val) if mrk_val else None,
            target_epsg=args.epsg if args.epsg is not None else raw_cfg.get("target_epsg"),
            proc_scale=args.scale if args.scale is not None else float(raw_cfg.get("proc_scale", 0.25)),
            ortho_gsd_m=args.gsd if args.gsd is not None else float(raw_cfg.get("ortho_gsd_m", 0.05)),
            dsm_resolution_m=args.dsm_res if args.dsm_res is not None else float(raw_cfg.get("dsm_resolution_m", 0.25)),
            max_images=args.max_images if args.max_images is not None else raw_cfg.get("max_images"),
            project_name=args.name or raw_cfg.get("project_name", "drone_map"),
            show_progress=not args.quiet,
        )
        products = MapBuilder(cfg).run()
        print(f"Map build complete -> {products.output_dir}")
        print(f"  Dashboard (Browser) : {products.dashboard_html}")
        print(f"  Orthophoto GeoTIFF  : {products.orthomosaic_tif}")
        print(f"  Plant Health (VARI) : {products.plant_health_tif}")
        print(f"  DSM (Surface Model) : {products.dsm_tif}")
        print(f"  DTM (Terrain Model) : {products.dtm_tif}")
        print(f"  3D Point Cloud PLY  : {products.point_cloud_ply}")
        print(f"  3D Model OBJ        : {products.model_3d_obj}")
        print(f"  Flight GeoJSON      : {products.flight_geojson}")
        print(f"  QA Report           : {products.report_md}")
        print(f"\nTip: Run `pmb view --output {products.output_dir}` to inspect results in your browser.")
        return 0

    if args.command == "view":
        import functools
        import http.server
        import socketserver

        out_dir = Path(args.output).resolve()
        index_html = out_dir / "index.html"
        if not index_html.exists():
            print(f"Error: {index_html} not found. Run `pmb build` first.")
            return 1

        print(f"Output directory: {out_dir}")
        for sub_dir in sorted(p for p in out_dir.iterdir() if p.is_dir()):
            files = ", ".join(f.name for f in sorted(sub_dir.iterdir()))
            print(f"  {sub_dir.name}/ -> {files}")
        print(f"  Dashboard: file://{index_html}")

        if args.no_serve:
            return 0

        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out_dir))
        print(f"\nServing dashboard at http://localhost:{args.port}/index.html (Ctrl+C to stop)")
        with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nStopped.")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

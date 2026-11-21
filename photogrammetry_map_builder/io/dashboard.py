"""Interactive HTML dashboard generator for inspecting photogrammetry & GIS outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from ..models import BundleResult, MapProducts


def export_dashboard_html(
    products: MapProducts,
    geojson_data: Optional[Dict[str, object]] = None,
    bundle: Optional[BundleResult] = None,
) -> Path:
    """Generate a self-contained `index.html` viewer in `products.output_dir`."""
    out_dir = products.output_dir
    html_path = out_dir / "index.html"

    def rel(p: Optional[Path]) -> str:
        if p is None:
            return ""
        try:
            return str(p.relative_to(out_dir))
        except ValueError:
            return str(p)

    stats = products.stats
    reproj_px = (
        f"{bundle.mean_reprojection_error_px:.3f} px" if bundle else "N/A"
    )
    gcp_rmse = (
        f"{bundle.gcp_rmse_3d_m:.4f} m"
        if bundle and bundle.gcp_rmse_3d_m is not None
        else "N/A"
    )
    tie_pts = f"{bundle.num_tie_points:,}" if bundle else "0"

    gcp_rows = ""
    if bundle and bundle.gcp_residuals:
        for r in bundle.gcp_residuals:
            gcp_rows += (
                f"<tr><td>{r['gcp_id']}</td><td>{r['image']}</td>"
                f"<td>{r['reproj_err_px']}</td><td>{r['err_3d_m']}</td></tr>"
            )
    else:
        gcp_rows = "<tr><td colspan='4'>ไม่มีข้อมูล GCP</td></tr>"

    geojson_json = json.dumps(geojson_data or {"type": "FeatureCollection", "features": []})

    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Photogrammetry Map Viewer — {stats.get('project_name', 'drone_map')}</title>
  <style>
    :root {{
      --bg: #0f172a; --card: #1e293b; --border: #334155;
      --text: #f8fafc; --muted: #94a3b8; --accent: #38bdf8; --green: #4ade80;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: system-ui, -apple-system, sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.5;
    }}
    header {{
      padding: 1.25rem 2rem; border-bottom: 1px solid var(--border);
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;
    }}
    header h1 {{ margin: 0; font-size: 1.25rem; }}
    .badge {{ background: #0284c7; color: #fff; padding: 0.25rem 0.65rem; border-radius: 999px; font-size: 0.8rem; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 1.5rem 2rem; }}
    .grid-cards {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
      gap: 1rem; margin-bottom: 1.5rem;
    }}
    .card {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: 10px; padding: 1rem;
    }}
    .card .label {{ color: var(--muted); font-size: 0.8rem; }}
    .card .value {{ font-size: 1.3rem; font-weight: 700; margin-top: 0.25rem; color: var(--accent); }}
    .tabs {{ display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; }}
    .tab-btn {{
      background: var(--card); color: var(--text); border: 1px solid var(--border);
      padding: 0.55rem 1rem; border-radius: 8px; cursor: pointer; font-weight: 600;
    }}
    .tab-btn.active {{ background: #0284c7; border-color: #38bdf8; }}
    .panel {{
      display: none; background: var(--card); border: 1px solid var(--border);
      border-radius: 12px; padding: 1.25rem; margin-bottom: 1.5rem;
    }}
    .panel.active {{ display: block; }}
    .preview-img {{
      max-width: 100%; max-height: 620px; display: block; margin: 0 auto;
      border-radius: 8px; background: #020617;
    }}
    canvas {{ width: 100%; height: 500px; background: #020617; border-radius: 8px; display: block; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 0.75rem; font-size: 0.9rem; }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 0.55rem 0.75rem; text-align: left; }}
    th {{ color: var(--muted); font-weight: 600; }}
    code {{ background: #020617; padding: 0.15rem 0.4rem; border-radius: 4px; color: var(--green); }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Photogrammetry &amp; GIS Map Viewer — {stats.get('project_name', 'drone_map')}</h1>
      <div style="color: var(--muted); font-size: 0.85rem;">อ้างอิงผลลัพธ์ตามมาตรฐาน Module 3 (Orthophoto, DSM, DTM, Plant Health, Point Cloud, 3D Model)</div>
    </div>
    <span class="badge">EPSG:{products.target_epsg}</span>
  </header>

  <main>
    <div class="grid-cards">
      <div class="card"><div class="label">จำนวนภาพถ่าย</div><div class="value">{stats.get('num_images', 0)}</div></div>
      <div class="card"><div class="label">Ortho GSD</div><div class="value">{stats.get('ortho_gsd_m', '-')} m/px</div></div>
      <div class="card"><div class="label">3D Tie Points</div><div class="value">{tie_pts}</div></div>
      <div class="card"><div class="label">Reprojection Error</div><div class="value">{reproj_px}</div></div>
      <div class="card"><div class="label">GCP 3D RMSE</div><div class="value">{gcp_rmse}</div></div>
    </div>

    <div class="tabs">
      <button class="tab-btn active" onclick="showTab('ortho', this)">1. Orthophoto</button>
      <button class="tab-btn" onclick="showTab('dsm', this)">2. DSM (Surface)</button>
      <button class="tab-btn" onclick="showTab('dtm', this)">3. DTM (Terrain)</button>
      <button class="tab-btn" onclick="showTab('health', this)">4. Plant Health (VARI)</button>
      <button class="tab-btn" onclick="showTab('gis', this)">5. Flight &amp; GCP Map</button>
      <button class="tab-btn" onclick="showTab('files', this)">6. วิธีเปิดไฟล์ผลลัพธ์</button>
    </div>

    <div id="tab-ortho" class="panel active">
      <p><strong>Orthophoto</strong> — ภาพแผนที่มุมมองด้านบนความละเอียดสูง (<code>{rel(products.orthomosaic_tif)}</code>)</p>
      <img class="preview-img" src="{rel(products.orthomosaic_preview_png)}" alt="Orthophoto Preview" />
    </div>

    <div id="tab-dsm" class="panel">
      <p><strong>DSM (Surface Model)</strong> — โมเดลความสูงรวมสิ่งปลูกสร้างและต้นไม้ (<code>{rel(products.dsm_tif)}</code>)</p>
      <img class="preview-img" src="02_elevation/{stats.get('project_name', 'drone_map')}_dsm_preview.png" alt="DSM Preview" />
    </div>

    <div id="tab-dtm" class="panel">
      <p><strong>DTM (Terrain Model)</strong> — โมเดลพื้นดินจริงที่กรองสิ่งปลูกสร้าง/ต้นไม้ออก (<code>{rel(products.dtm_tif)}</code>)</p>
      <img class="preview-img" src="02_elevation/{stats.get('project_name', 'drone_map')}_dtm_preview.png" alt="DTM Preview" />
    </div>

    <div id="tab-health" class="panel">
      <p><strong>Plant Health (VARI)</strong> — ดัชนีสุขภาพพืชจากภาพ RGB: แดง = พื้นดิน/สิ่งปลูกสร้าง, เขียว = พืชพรรณสมบูรณ์ (<code>{rel(products.plant_health_tif)}</code>)</p>
      <img class="preview-img" src="{rel(products.plant_health_preview_png)}" alt="Plant Health Preview" />
    </div>

    <div id="tab-gis" class="panel">
      <p><strong>แนวบิน (เส้นฟ้า), ตำแหน่งกล้อง (จุดขาว), ขอบเขตภาพ (กรอบเทา), และ GCP (สามเหลี่ยมเขียว)</strong></p>
      <canvas id="gisCanvas" width="1100" height="500"></canvas>
      <h3>GCP Residuals</h3>
      <table>
        <thead><tr><th>GCP ID</th><th>Image</th><th>Reproj Err (px)</th><th>3D Err (m)</th></tr></thead>
        <tbody>{gcp_rows}</tbody>
      </table>
    </div>

    <div id="tab-files" class="panel">
      <h3>โครงสร้างโฟลเดอร์ผลลัพธ์และโปรแกรมที่ใช้เปิดดู</h3>
      <table>
        <thead><tr><th>หมวดหมู่</th><th>ไฟล์ผลลัพธ์</th><th>โปรแกรมแนะนำสำหรับเปิดดู</th></tr></thead>
        <tbody>
          <tr><td>Orthophoto</td><td><code>{rel(products.orthomosaic_tif)}</code></td><td>QGIS / ArcGIS (มีไฟล์ <code>.tfw</code> + <code>.prj</code> พร้อมพิกัด EPSG:{products.target_epsg})</td></tr>
          <tr><td>DSM (Surface)</td><td><code>{rel(products.dsm_tif)}</code></td><td>QGIS (เปิดเป็น Singleband Pseudocolor / Hillshade)</td></tr>
          <tr><td>DTM (Terrain)</td><td><code>{rel(products.dtm_tif)}</code></td><td>QGIS (เปิดเปรียบเทียบความสูงพื้นดินจริง)</td></tr>
          <tr><td>Plant Health</td><td><code>{rel(products.plant_health_tif)}</code></td><td>QGIS / Preview PNG ในโฟลเดอร์ <code>03_plant_health/</code></td></tr>
          <tr><td>Point Cloud</td><td><code>{rel(products.point_cloud_ply)}</code></td><td>CloudCompare / MeshLab / Open3D</td></tr>
          <tr><td>3D Model</td><td><code>{rel(products.model_3d_obj)}</code></td><td>MeshLab / Blender / CloudCompare</td></tr>
          <tr><td>GIS Vectors</td><td><code>{rel(products.flight_geojson)}</code></td><td>QGIS / geojson.io</td></tr>
          <tr><td>QA Report</td><td><code>{rel(products.report_md)}</code></td><td>VS Code / Markdown Viewer / Text Editor</td></tr>
        </tbody>
      </table>
    </div>
  </main>

  <script>
    function showTab(name, btn) {{
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.getElementById('tab-' + name).classList.add('active');
      btn.classList.add('active');
      if (name === 'gis') drawGisMap();
    }}

    const geojson = {geojson_json};
    function drawGisMap() {{
      const canvas = document.getElementById('gisCanvas');
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      function scanCoord(c) {{
        if (c[0] < minX) minX = c[0];
        if (c[0] > maxX) maxX = c[0];
        if (c[1] < minY) minY = c[1];
        if (c[1] > maxY) maxY = c[1];
      }}
      for (const f of geojson.features) {{
        const g = f.geometry;
        if (g.type === 'Point') scanCoord(g.coordinates);
        else if (g.type === 'LineString') g.coordinates.forEach(scanCoord);
        else if (g.type === 'Polygon') g.coordinates[0].forEach(scanCoord);
      }}
      if (!isFinite(minX)) return;

      const pad = 40;
      const dx = Math.max(maxX - minX, 1e-6);
      const dy = Math.max(maxY - minY, 1e-6);
      const scale = Math.min((canvas.width - 2 * pad) / dx, (canvas.height - 2 * pad) / dy);
      const ox = (canvas.width - dx * scale) / 2;
      const oy = (canvas.height - dy * scale) / 2;
      const toPx = (c) => [ox + (c[0] - minX) * scale, canvas.height - (oy + (c[1] - minY) * scale)];

      // Footprints
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.25)';
      ctx.lineWidth = 1;
      for (const f of geojson.features) {{
        if (f.properties.layer === 'image_footprint') {{
          const pts = f.geometry.coordinates[0].map(toPx);
          ctx.beginPath();
          pts.forEach((p, idx) => idx === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1]));
          ctx.stroke();
        }}
      }}
      // Trajectory
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 2;
      for (const f of geojson.features) {{
        if (f.properties.layer === 'flight_trajectory') {{
          const pts = f.geometry.coordinates.map(toPx);
          ctx.beginPath();
          pts.forEach((p, idx) => idx === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1]));
          ctx.stroke();
        }}
      }}
      // Camera stations
      ctx.fillStyle = '#f8fafc';
      for (const f of geojson.features) {{
        if (f.properties.layer === 'camera_station') {{
          const [x, y] = toPx(f.geometry.coordinates);
          ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fill();
        }}
      }}
      // GCPs
      ctx.fillStyle = '#4ade80';
      ctx.font = '12px sans-serif';
      for (const f of geojson.features) {{
        if (f.properties.layer === 'gcp') {{
          const [x, y] = toPx(f.geometry.coordinates);
          ctx.beginPath();
          ctx.moveTo(x, y - 7); ctx.lineTo(x - 6, y + 5); ctx.lineTo(x + 6, y + 5);
          ctx.closePath(); ctx.fill();
          ctx.fillText(f.properties.gcp_id, x + 8, y + 4);
        }}
      }}
    }}
  </script>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    return html_path

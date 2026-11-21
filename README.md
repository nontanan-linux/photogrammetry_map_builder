# Photogrammetry Map Builder (`photogrammetry_map_builder`)

A modular Python package for constructing georeferenced **2D Orthomosaics**, **Digital Surface Models (DSM)**, **Digital Terrain Models (DTM)**, **Plant Health Indices (VARI)**, **3D Point Clouds**, **3D Triangle Meshes**, and **GIS Vector Layers (GeoJSON)** from UAV / drone imagery and RTK / GCP survey data.

Designed and implemented in alignment with **Module 3: Photogrammetry & 3D Model Generation** from the EEC Smart City GeoAI Training Curriculum (supported by the Thailand Board of Investment - BOI).

---

## 🌟 Key Features

- **Robust Metadata & RTK Ingestion**:
  - Parses DJI EXIF and XMP metadata, including RTK positioning status (`RtkFlag=50`), gimbal orientations (Yaw, Pitch, Roll), calibrated focal lengths, and `DewarpData` Brown-Conrady camera distortion parameters.
  - Supports DJI `.MRK` event marker logs with exposure timestamps and millimeter-level antenna offset corrections.
  - Automatically projects coordinates from WGS 84 (`EPSG:4326`) to the optimal local UTM zone (`EPSG:326xx` / `EPSG:327xx`) using `pyproj`.
- **Flexible Ground Control Point (GCP) Handling**:
  - Parses both plain coordinate lists (`EPSG:4326`) and WebODM / Pix4D multi-column format with 2D image pixel observations.
  - Computes 2D image reprojection errors and 3D ground position RMSE residuals.
- **Structure-from-Motion (SfM) & Georeferenced Bundle Adjustment**:
  - SIFT feature extraction with spatial nearest-neighbor image pair selection based on UTM proximity.
  - Robust Fundamental matrix estimation with RANSAC outlier filtering.
  - Multi-view track creation via Union-Find and linear Direct Linear Transform (DLT) triangulation.
  - Joint non-linear least-squares optimization (`scipy.optimize.least_squares`) incorporating RTK priors, gimbal IMU priors, and GCP ground constraints.
- **Elevation Models (DSM & DTM)**:
  - Generates Digital Surface Models (DSM) including all structures and vegetation.
  - Derives Digital Terrain Models (DTM) representing bare-earth elevation using morphological ground filtering.
  - Outputs standard 32-bit float GeoTIFFs with `GDAL_NODATA` tags and colormapped preview images.
- **Terrain-Aware Orthorectification**:
  - Back-projects pixels through the camera model onto the interpolated DSM.
  - Employs smooth nadir / center-weighted feather blending to eliminate seamlines across adjacent flight lines.
- **Plant Health Analysis**:
  - Computes the Visible Atmospherically Resistant Index (VARI) from RGB bands:
    $$\text{VARI} = \frac{G - R}{G + R - B}$$
  - Renders red-yellow-green vegetation previews highlighting healthy canopy vs. bare ground / built-up areas.
- **3D Export**:
  - Generates colored 3D Point Clouds (`.ply`) via `Open3D`.
  - Generates textured 3D triangle meshes (`.obj`) with normal vectors.
- **GIS Vectors & Interactive Dashboard**:
  - Exports flight trajectories, camera stations, image footprints, GCPs, and bounding boxes to standard WGS 84 GeoJSON.
  - Generates a standalone `index.html` interactive dashboard viewer for instant browser inspection.

---

## 📁 Package Structure

```text
photogrammetry_map_builder/
├── configs/                       # Ready-to-use pipeline configuration files
│   └── default_config.yaml        # Default YAML settings pointing to resources/
├── examples/                      # Example workflows and Python scripts
│   └── run_bua_sample.py          # Python API demo script
├── outputs/                       # Default output directory (subdirectories 01 to 06)
├── resources/                     # Package resource directory (datasets & GCPs)
│   └── Module-Test-Data/
│       ├── Rawdata/               # Aerial imagery (.JPG) and RTK logs (.MRK)
│       └── GCP/                   # Ground Control Point files (.txt)
├── photogrammetry_map_builder/    # Core Python library
│   ├── __init__.py                # Public API exports
│   ├── __main__.py                # Entrypoint for `python3 -m photogrammetry_map_builder`
│   ├── cli.py                     # Command-line interface (`inspect`, `build`, `view`)
│   ├── models.py                  # Dataclasses and internal schemas
│   ├── pipeline.py                # Pipeline orchestrator (`MapBuilder`, `PipelineConfig`)
│   ├── io/                        # File I/O: EXIF, XMP, MRK, GCP, GeoTIFF, GeoJSON, HTML Dashboard
│   ├── geometry/                  # Camera models, SfM, Point Cloud, DSM/DTM, 3D Mesh
│   └── mapping/                   # Orthorectification, Feather Blending, Plant Health (VARI)
├── pyproject.toml                 # Package definition & dependencies (PEP 517/621)
├── README.md                      # English documentation
└── tests/                         # Automated unit & integration tests (pytest)
```

---

## 💾 Dataset Download

To download the sample UAV flight dataset (DJI Matrice 4E imagery with RTK `.MRK` and GCP survey data):

- **Google Drive**: [Download Module-Test-Data Dataset](https://drive.google.com/drive/folders/1N7p9Vm6r3uBts-uarrThG0iciAd8AKI_?usp=sharing)
- Extract the downloaded files into `resources/Module-Test-Data/`:
  ```text
  resources/Module-Test-Data/
  ├── Rawdata/
  │   └── DJI_202609300833_038_bua/   # 99 aerial images (.JPG) + RTK log (.MRK)
  └── GCP/
      ├── EPSG4326_Bua.txt            # GCPs in WGS 84 geographic coordinates
      └── gcp_Bua_final.txt           # GCP coordinates & image pixel marks (WebODM format)
  ```

---

## 📦 Installation

Install the package in editable mode so that the `pmb` CLI command and Python modules are accessible globally:

```bash
cd /home/tacv/workspace/DDMdrone/photogrammetry_map_builder
pip install -e .
```

Verify the installation:

```bash
pmb --help
```

---

## 🛠️ Command-Line Interface (CLI)

The CLI provides three primary subcommands: **`inspect`**, **`build`**, and **`view`**.

### 1. `pmb inspect` — Inspect Dataset Metadata
Validates image files, coordinates, RTK fix ratio, and Ground Control Points before running processing.

```bash
# Automatically detects sample data in resources/Module-Test-Data/
pmb inspect

# Or specify custom paths:
pmb inspect \
  --input resources/Module-Test-Data/Rawdata/DJI_202609300833_038_bua \
  --gcp resources/Module-Test-Data/GCP/gcp_Bua_final.txt
```

**Example Output:**
```text
Images: 99 (DJI Matrice 4E)
Source: resources/Module-Test-Data/Rawdata/DJI_202609300833_038_bua
Auto UTM EPSG: 32647
Lat range: 13.2313755 .. 13.2332348
Lon range: 100.9543679 .. 100.9561978
Abs Alt range: 56.28 .. 56.54 m
RTK Fixed (flag=50): 99/99
GCPs: 5 (15 image observations), CRS: +proj=utm +zone=47 +ellps=WGS84 +datum=WGS84 +units=m +no_defs
```

---

### 2. `pmb build` — Run Mapping Pipeline
Executes the full photogrammetry pipeline: SfM bundle adjustment, DSM/DTM interpolation, orthomosaicking, vegetation index calculation, 3D model generation, and GIS vector export.

#### Option A: Using the default YAML configuration (Recommended)
```bash
pmb build --config configs/default_config.yaml
```

#### Option B: Direct CLI arguments (Fast 12-image test run)
```bash
pmb build \
  --input resources/Module-Test-Data/Rawdata/DJI_202609300833_038_bua \
  --gcp resources/Module-Test-Data/GCP/gcp_Bua_final.txt \
  --mrk resources/Module-Test-Data/Rawdata/DJI_202609300833_038_bua/DJI_20260930083707_0002_D.MRK \
  --output ./outputs/bua_quick \
  --name bua_quick \
  --max-images 12 \
  --gsd 0.05 \
  --dsm-res 0.25
```

#### CLI Build Arguments:
| Argument | Short | Default | Description |
|---|---|---|---|
| `--input` | `-i` | `None` | Path to directory containing drone images |
| `--output` | `-o` | `None` | Path to output directory |
| `--config` | `-c` | `None` | Path to YAML configuration file |
| `--gcp` | | `None` | Path to GCP coordinate file |
| `--mrk` | | `None` | Path to DJI `.MRK` exposure marker file |
| `--epsg` | | Auto UTM | Target projected EPSG code (e.g. `32647`) |
| `--gsd` | | `0.05` | Orthomosaic Ground Sample Distance (meters/pixel) |
| `--dsm-res` | | `0.25` | DSM / DTM grid resolution (meters/pixel) |
| `--scale` | | `0.25` | Downsampling factor for feature extraction (0.25 = fast & robust) |
| `--max-images` | | `None` | Limit number of processed images (useful for quick testing) |
| `--name` | | `drone_map` | File prefix for output products |
| `--quiet` | | `False` | Suppress interactive progress bars |

---

### 3. `pmb view` — Inspect Results in Web Browser
Launches a local HTTP server and presents all map layers, elevation models, plant health indices, flight trajectories, GCP residuals, and file paths in an interactive dashboard.

```bash
pmb view --output ./outputs/bua_quick
```

Open **`http://localhost:8765/index.html`** in any web browser.

- To change the server port: `pmb view --output ./outputs/bua_quick --port 8080`
- To inspect folder contents in the terminal without running a server: `pmb view --output ./outputs/bua_quick --no-serve`

---

## 🗂️ Output Directory Layout

Output products are organized into numbered subdirectories according to the Module 3 deliverables:

```text
outputs/<project_name>/
├── index.html                     # Standalone HTML dashboard viewer
│
├── 01_orthophoto/                 # High-resolution 2D Orthophoto
│   ├── <name>_ortho.tif           # Georeferenced Orthomosaic (RGBA GeoTIFF)
│   ├── <name>_ortho.tfw           # ESRI World File for GIS software
│   ├── <name>_ortho.prj           # WKT projection file
│   └── <name>_ortho_preview.png   # High-resolution PNG preview
│
├── 02_elevation/                  # Digital Elevation Models
│   ├── <name>_dsm.tif             # Digital Surface Model (DSM, includes structures/canopy)
│   ├── <name>_dsm_preview.png     # Colormapped DSM elevation preview
│   ├── <name>_dtm.tif             # Digital Terrain Model (DTM, bare-earth filtered)
│   └── <name>_dtm_preview.png     # Colormapped DTM elevation preview
│
├── 03_plant_health/               # Vegetation Analysis
│   ├── <name>_plant_health_vari.tif  # Visible Atmospherically Resistant Index (VARI GeoTIFF)
│   └── <name>_plant_health_preview.png# Green-Yellow-Red plant health preview
│
├── 04_3d_model/                   # 3D Point Clouds and Meshes
│   ├── <name>_pointcloud.ply      # Dense RGB Point Cloud (.ply, viewable in CloudCompare)
│   └── <name>_3d_model.obj        # 3D Triangle Mesh (.obj, viewable in MeshLab / Blender)
│
├── 05_gis_vectors/                # Spatial Vector Layers
│   └── <name>_flight.geojson      # Flight path, camera stations, footprints, GCPs (WGS 84)
│
└── 06_reports/                    # Quality Assurance & Calibration
    ├── <name>_report.json         # Processing statistics and bundle adjustment metrics
    └── <name>_report.md           # Human-readable Markdown report with GCP residual table
```

---

## 💻 Python API Usage

The pipeline can be directly integrated into other Python applications:

```python
from pathlib import Path
from photogrammetry_map_builder import PipelineConfig, MapBuilder, build_map

# Quick one-liner execution:
products = build_map(
    image_dir="resources/Module-Test-Data/Rawdata/DJI_202609300833_038_bua",
    output_dir="outputs/bua_survey",
    gcp_file="resources/Module-Test-Data/GCP/gcp_Bua_final.txt",
    mrk_file="resources/Module-Test-Data/Rawdata/DJI_202609300833_038_bua/DJI_20260930083707_0002_D.MRK",
    project_name="bua_survey",
    ortho_gsd_m=0.05,
    dsm_resolution_m=0.25,
    proc_scale=0.25,
)

print(f"Orthophoto GeoTIFF : {products.orthomosaic_tif}")
print(f"DSM GeoTIFF        : {products.dsm_tif}")
print(f"DTM GeoTIFF        : {products.dtm_tif}")
print(f"Plant Health VARI  : {products.plant_health_tif}")
print(f"Point Cloud PLY    : {products.point_cloud_ply}")
print(f"Dashboard Viewer   : {products.dashboard_html}")
```

---

## 🖥️ Recommended Software for Viewing Results

- **Web Browser** (Chrome / Firefox / Edge): Open `index.html` directly for an all-in-one interactive overview.
- **GIS Desktop** ([QGIS](https://qgis.org/) / ArcGIS Pro): Drag-and-drop `.tif` files from `01_orthophoto/`, `02_elevation/`, `03_plant_health/`, and `.geojson` from `05_gis_vectors/`.
- **3D Point Clouds & Meshes**:
  - [CloudCompare](https://www.cloudcompare.org/): For opening and measuring `04_3d_model/<name>_pointcloud.ply`.
  - [MeshLab](https://www.meshlab.net/) / [Blender](https://www.blender.org/): For inspecting and rendering `04_3d_model/<name>_3d_model.obj`.

---

## 🧪 Automated Testing

Execute the test suite to verify all I/O modules, camera geometry, and pipeline functions:

```bash
pytest -v
```

All 7 test suites validate:
1. Pinhole camera ray-ground projection and round-trip consistency.
2. End-to-end pipeline execution and output verification.
3. Automatic longitude/latitude to UTM zone EPSG calculation.
4. DJI Matrice 4E EXIF/XMP parsing and lens distortion parameter extraction.
5. DJI `.MRK` RTK log reading.
6. GCP coordinate parsing and CRS transformation.
7. Pure-Python GeoTIFF, World File (`.tfw`), and projection (`.prj`) generation.

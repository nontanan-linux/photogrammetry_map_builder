# photogrammetry_map_builder

Python package สำหรับสร้างแผนที่ **Orthophoto**, **Digital Surface Model (DSM)**, **Digital Terrain Model (DTM)**, **Plant Health (VARI)**, **3D Point Cloud**, **3D Mesh Model**, และ **GIS Vectors (GeoJSON)** จากภาพถ่ายโดรนและข้อมูล RTK/GCP ตามแนวทาง **Module 3: Photogrammetry & 3D Model Generation**

---

## 📦 การติดตั้ง (Installation)

แนะนำให้ติดตั้งในโหมด Editable เพื่อให้สามารถเรียกใช้คำสั่ง **`pmb`** ได้จากทุกที่ใน Terminal:

```bash
cd /home/tacv/workspace/DDMdrone/photogrammetry_map_builder
pip install -e .
```

*เมื่อติดตั้งแล้ว คำสั่ง `pmb` และ `python3 -m photogrammetry_map_builder` จะสามารถเรียกใช้งานได้ทันที*

---

## 📁 โครงสร้างแพ็กเกจ (Package Layout)

```text
photogrammetry_map_builder/
├── configs/
│   └── default_config.yaml        # ค่าคอนฟิกเริ่มต้นสำหรับการรันด้วย --config
├── examples/
│   └── run_bua_sample.py          # สคริปต์ตัวอย่างเรียกใช้ผ่าน Python API
├── outputs/                       # โฟลเดอร์เก็บผลลัพธ์ (แยกตาม project_name)
├── photogrammetry_map_builder/    # ซอร์สโค้ดหลักของแพ็กเกจ
│   ├── __init__.py                # Export คลาสและฟังก์ชันหลัก
│   ├── __main__.py                # Entrypoint สำหรับ python3 -m photogrammetry_map_builder
│   ├── cli.py                     # คำสั่ง CLI (inspect, build, view)
│   ├── models.py                  # Data models และโครงสร้างข้อมูล
│   ├── pipeline.py                # Pipeline orchestrator (MapBuilder)
│   ├── io/                        # จัดการไฟล์ EXIF/XMP, MRK, GCP, GeoTIFF, Dashboard
│   ├── geometry/                  # Camera Model, SfM, Point Cloud, DSM/DTM, 3D Mesh
│   └── mapping/                   # Orthorectification, Feather Blending, Plant Health (VARI)
├── pyproject.toml                 # กำหนดค่า Metadata และ Dependencies (PEP 517/621)
├── README.md                      # เอกสารคู่มือการใช้งาน
└── tests/                         # ชุดทดสอบอัตโนมัติ (pytest)
```

---

## 💾 ดาวน์โหลดชุดข้อมูลตัวอย่าง (Dataset Download)

ดาวน์โหลดชุดข้อมูลตัวอย่างสำหรับการทดสอบระบบ (ภาพถ่ายโดรน DJI Matrice 4E 99 ภาพ, ไฟล์ RTK `.MRK`, และพิกัด GCP) ได้ที่:
- **Google Drive**: [Download Module-Test-Data Dataset](https://drive.google.com/drive/folders/1N7p9Vm6r3uBts-uarrThG0iciAd8AKI_?usp=sharing)
- นำไฟล์ที่ดาวน์โหลดมาเก็บไว้ที่ `../resource/Module-Test-Data/`

---

## 🛠️ การใช้งานผ่าน Command Line (CLI Guide)

แพ็กเกจมี 3 คำสั่งหลัก: **`inspect`**, **`build`**, และ **`view`**

### 1. ตรวจสอบข้อมูลนำเข้า (`inspect`)
ตรวจสอบความถูกต้องของภาพถ่าย ตำแหน่งพิกัด สถานะ RTK และข้อมูล GCP ก่อนเริ่มประมวลผล:

```bash
pmb inspect \
  --input ../resource/Module-Test-Data/Rawdata/DJI_202609300833_038_bua \
  --gcp ../resource/Module-Test-Data/GCP/gcp_Bua_final.txt
```

**ตัวอย่างผลลัพธ์:**
```text
Images: 99 (DJI Matrice 4E)
Auto UTM EPSG: 32647
Lat range: 13.2313755 .. 13.2332348
Lon range: 100.9543679 .. 100.9561978
Abs Alt range: 56.28 .. 56.54 m
RTK Fixed (flag=50): 99/99
GCPs: 5 (15 image observations), CRS: +proj=utm +zone=47 +ellps=WGS84 +datum=WGS84 +units=m +no_defs
```

---

### 2. ประมวลผลสร้างแผนที่ (`build`)

#### แบบที่ 1: ใช้ไฟล์คอนฟิก YAML (แนะนำ)
```bash
pmb build --config configs/default_config.yaml
```

#### แบบที่ 2: ระบุพารามิเตอร์ผ่านคำสั่ง CLI โดยตรง
```bash
pmb build \
  --input ../resource/Module-Test-Data/Rawdata/DJI_202609300833_038_bua \
  --gcp ../resource/Module-Test-Data/GCP/gcp_Bua_final.txt \
  --mrk ../resource/Module-Test-Data/Rawdata/DJI_202609300833_038_bua/DJI_20260930083707_0002_D.MRK \
  --output ./outputs/bua_survey \
  --name bua_survey \
  --gsd 0.05 \
  --dsm-res 0.25
```

#### รายละเอียดพารามิเตอร์ของคำสั่ง `build`:
| ตัวเลือก | ตัวย่อ | ค่าเริ่มต้น | คำอธิบาย |
|---|---|---|---|
| `--input` | `-i` | (จำเป็น) | ไดเรกทอรีที่เก็บไฟล์ภาพถ่ายโดรน (.JPG, .TIF) |
| `--output` | `-o` | (จำเป็น) | ไดเรกทอรีสำหรับบันทึกผลลัพธ์ |
| `--config` | `-c` | `None` | ไฟล์ตั้งค่า YAML (แทนการใส่ flag ทั้งหมด) |
| `--gcp` | | `None` | ไฟล์พิกัด GCP (รองรับทั้ง EPSG:4326 และรูปแบบ WebODM) |
| `--mrk` | | `None` | ไฟล์บันทึกตำแหน่งเวลาเปิดชัตเตอร์ DJI `.MRK` |
| `--epsg` | | Auto UTM | ระบบพิกัดเป้าหมาย (หากไม่ระบุจะเลือก UTM Zone ให้อัตโนมัติ) |
| `--gsd` | | `0.05` | Ground Sample Distance ของ Orthophoto (เมตร/พิกเซล) |
| `--dsm-res` | | `0.25` | ความละเอียดของโมเดลความสูง DSM/DTM (เมตร/พิกเซล) |
| `--scale` | | `0.25` | สัดส่วนย่อภาพขณะประมวลผล SfM เพื่อความรวดเร็ว |
| `--max-images`| | `None` | จำกัดจำนวนภาพ (สำหรับทดสอบประมวลผลด่วน เช่น 10-15 ภาพ) |
| `--name` | | `drone_map` | ชื่อ Prefix ของไฟล์ผลลัพธ์ |
| `--quiet` | | `False` | ปิดแถบ Progress Bar |

---

### 3. ตรวจสอบและดูผลลัพธ์ (`view`)

เปิดดูผลลัพธ์ผ่านเว็บเบราว์เซอร์ด้วย Local Web Dashboard ทันที:

```bash
pmb view --output ./outputs/bua_survey
```

- ระบบจะเปิด Web Server ให้ที่ **`http://localhost:8765/index.html`**
- สามารถเปลี่ยนพอร์ตได้ด้วย `--port <เลขพอร์ต>` เช่น `--port 8080`
- หากต้องการแค่แสดงรายการไฟล์ในเทอร์มินัลโดยไม่เปิดเว็บเซิร์ฟเวอร์ ให้ใส่ `--no-serve`

---

## 🗂️ โครงสร้างการจัดเก็บผลลัพธ์ (Output Directory Structure)

ผลลัพธ์ทั้งหมดถูกจัดเก็บเป็นหมวดหมู่ตามมาตรฐาน [Module 3](file:///home/tacv/workspace/DDMdrone/docs/module_03/Module%203%20Photogrammetry%20_%203D%20Model%20Generation.pdf):

```text
outputs/<project_name>/
├── index.html                     # หน้า Interactive Dashboard รวมผลลัพธ์ทั้งหมด
│
├── 01_orthophoto/                 # แผนที่ภาพถ่ายมุมมองด้านบน (Orthophoto)
│   ├── <name>_ortho.tif           # ภาพ Orthomosaic GeoTIFF พร้อมพิกัด
│   ├── <name>_ortho.tfw           # World file สำหรับโปรแกรม GIS
│   ├── <name>_ortho.prj           # ข้อมูลระบบพิกัด WKT
│   └── <name>_ortho_preview.png   # ภาพตัวอย่างความละเอียดสูง
│
├── 02_elevation/                  # โมเดลความสูงพื้นผิว (DSM) และภูมิประเทศ (DTM)
│   ├── <name>_dsm.tif             # Digital Surface Model (รวมสิ่งปลูกสร้าง/ต้นไม้)
│   ├── <name>_dsm_preview.png     # ภาพแสดงระดับความสูง DSM แบบ Color Ramp
│   ├── <name>_dtm.tif             # Digital Terrain Model (กรองพื้นผิวดินจริง)
│   └── <name>_dtm_preview.png     # ภาพแสดงระดับความสูง DTM
│
├── 03_plant_health/               # วิเคราะห์ดัชนีสุขภาพพืช (Plant Health)
│   ├── <name>_plant_health_vari.tif  # Visible Atmospherically Resistant Index (VARI) GeoTIFF
│   └── <name>_plant_health_preview.png# ภาพจำแนกพื้นที่พืชพรรณ (เขียว=สมบูรณ์, แดง=สิ่งปลูกสร้าง/ดิน)
│
├── 04_3d_model/                   # โมเดลและกลุ่มจุด 3 มิติ
│   ├── <name>_pointcloud.ply      # 3D Point Cloud มีค่าสี RGB (เปิดด้วย CloudCompare)
│   └── <name>_3d_model.obj        # 3D Textured Triangle Mesh (เปิดด้วย MeshLab / Blender)
│
├── 05_gis_vectors/                # ชั้นข้อมูลเวกเตอร์ GIS
│   └── <name>_flight.geojson      # แนวบิน, ตำแหน่งกล้อง, Footprints, ขอบเขตแปลง และจุด GCP
│
└── 06_reports/                    # รายงานผลการประมวลผลและการประเมินความถูกต้อง (QA)
    ├── <name>_report.json         # สถิติและค่าความคลาดเคลื่อนรูปแบบ JSON
    └── <name>_report.md           # รายงานสรุปรูปแบบ Markdown พร้อมตาราง GCP Residuals
```

---

## 💻 การเรียกใช้งานผ่าน Python API

```python
from pathlib import Path
from photogrammetry_map_builder import PipelineConfig, MapBuilder, build_map

# วิธีที่ 1: เรียกใช้ผ่านฟังก์ชันลัด build_map
products = build_map(
    image_dir="../resource/Module-Test-Data/Rawdata/DJI_202609300833_038_bua",
    output_dir="./outputs/my_drone_survey",
    gcp_file="../resource/Module-Test-Data/GCP/gcp_Bua_final.txt",
    mrk_file="../resource/Module-Test-Data/Rawdata/DJI_202609300833_038_bua/DJI_20260930083707_0002_D.MRK",
    project_name="bua_pipeline",
    ortho_gsd_m=0.05,
    dsm_resolution_m=0.25,
    proc_scale=0.25,
)

print("Orthophoto Path :", products.orthomosaic_tif)
print("DSM Path        :", products.dsm_tif)
print("DTM Path        :", products.dtm_tif)
print("Dashboard HTML  :", products.dashboard_html)
```

---

## 🔧 การแก้ไขปัญหาที่พบบ่อย (Troubleshooting)

### ปัญหา: `ModuleNotFoundError: No module named 'photogrammetry_map_builder'`
- **สาเหตุ**: เรียกคำสั่งขณะที่อยู่ในไดเรกทอรีย่อยซ้ำกันสองชั้น เช่น `.../photogrammetry_map_builder/photogrammetry_map_builder` หรือยังไม่ได้ติดตั้ง package
- **วิธีแก้**:
  1. ถอยออกมาที่โฟลเดอร์หลักของแพ็กเกจ:
     ```bash
     cd /home/tacv/workspace/DDMdrone/photogrammetry_map_builder
     ```
  2. รันติดตั้งในโหมด editable:
     ```bash
     pip install -e .
     ```
  3. หลังจากนี้สามารถเรียกใช้งานผ่านคำสั่ง `pmb` ได้ทันทีจากทุกโฟลเดอร์

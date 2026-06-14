"""
Configuration for Lusail World Cup remote sensing analysis.
All paths, AOI, dates, and constants are centralized here.
"""
from pathlib import Path

# ----------------------------------------------------------------------------
# Project paths
# ----------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUT_DIR = ROOT_DIR / "outputs"
MAP_DIR = OUTPUT_DIR / "maps"
TABLE_DIR = OUTPUT_DIR / "tables"
GRAPH_DIR = OUTPUT_DIR / "graphs"
PPT_DIR = OUTPUT_DIR / "presentation"

for d in [DATA_DIR, RAW_DIR, PROCESSED_DIR, OUTPUT_DIR,
          MAP_DIR, TABLE_DIR, GRAPH_DIR, PPT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------------
# Study Area: Lusail City, Qatar
# Center: 25.4209 N, 51.4909 E
# AOI: ~12 km x 12 km bounding box (WGS84)
# Covers Lusail Stadium, Lusail Marina, residential & commercial zones,
# major roads, and surrounding desert.
# ----------------------------------------------------------------------------
CENTER_LAT = 25.4209
CENTER_LON = 51.4909
AOI_HALF_KM = 6.0  # half width/height in km -> 12 km box

# 1 degree latitude ~ 111 km
# 1 degree longitude at 25.42 N ~ 100.3 km
_DEG_LAT_PER_KM = 1.0 / 111.0
_DEG_LON_PER_KM = 1.0 / (111.320 * abs(__import__("math").cos(__import__("math").radians(CENTER_LAT))))

AOI_BBOX = (
    CENTER_LON - AOI_HALF_KM * _DEG_LON_PER_KM,  # min lon
    CENTER_LAT - AOI_HALF_KM * _DEG_LAT_PER_KM,  # min lat
    CENTER_LON + AOI_HALF_KM * _DEG_LON_PER_KM,  # max lon
    CENTER_LAT + AOI_HALF_KM * _DEG_LAT_PER_KM,  # max lat
)

# Working CRS — UTM Zone 39N (Qatar) gives accurate meters & area
WORK_CRS = "EPSG:32639"
LATLON_CRS = "EPSG:4326"

# Output spatial resolution (m) — Landsat native is 30 m
PIXEL_SIZE_M = 30.0

# ----------------------------------------------------------------------------
# Analysis time periods
# ----------------------------------------------------------------------------
# T1: 2000  — before WC bid
# T2: 2010  — WC hosting awarded
# T3: 2022  — WC opening year
# Same season (Jan–Apr) to control phenology.
TIME_PERIODS = {
    "2000": {"start": "2000-01-01", "end": "2000-04-30"},
    "2010": {"start": "2010-01-01", "end": "2010-04-30"},
    "2022": {"start": "2022-01-01", "end": "2022-04-30"},
}

# Max cloud cover (%) for scene selection
MAX_CLOUD_COVER = 10.0

# ----------------------------------------------------------------------------
# STAC API
# ----------------------------------------------------------------------------
# Microsoft Planetary Computer hosts a free, public copy of Landsat C2 L2
# (the AWS Earth Search copy lives in a Requester-Pays bucket and rejects
# anonymous reads). PC requires URL signing via planetary_computer.sign().
STAC_ENDPOINT = "https://planetarycomputer.microsoft.com/api/stac/v1"
STAC_COLLECTION = "landsat-c2-l2"  # Landsat Collection 2 Level-2 SR

# Earth Search v1 common asset names (consistent across Landsat 4/5/7/8/9)
# Some scenes may use slightly different aliases — both forms are tried.
BAND_ALIASES = {
    "blue":   ["blue"],
    "green":  ["green"],
    "red":    ["red"],
    "nir":    ["nir08", "nir"],
    "swir1":  ["swir16"],
    "swir2":  ["swir22"],
}

# Landsat C2 L2 surface-reflectance scale factor & offset
SR_SCALE = 0.0000275
SR_OFFSET = -0.2

# ----------------------------------------------------------------------------
# Land-cover classification (KMeans)
# ----------------------------------------------------------------------------
N_CLUSTERS = 5
CLASS_NAMES = ["Water", "Urban", "Vegetation", "Desert", "Mixed Surface"]
CLASS_COLORS = {
    "Water":         "#1f77b4",
    "Urban":         "#7f7f7f",
    "Vegetation":    "#2ca02c",
    "Desert":        "#e6c97a",
    "Mixed Surface": "#d62728",
}

# ----------------------------------------------------------------------------
# Map styling
# ----------------------------------------------------------------------------
MAP_DPI = 300
FIG_TITLE_PREFIX = "Lusail, Qatar"
DATA_SOURCE_TXT = "Data: USGS Landsat Collection 2 L2 (via AWS Earth Search STAC)"

RANDOM_SEED = 42

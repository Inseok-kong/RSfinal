"""
STAC-based Landsat C2 L2 acquisition for the Lusail AOI.

Strategy
--------
1. Query Earth Search v1 STAC API for the landsat-c2-l2 collection.
2. Pick the least-cloudy scene per time window that intersects the AOI.
3. Read only the AOI window from each band's COG asset (no full scene
   download). Reproject to WORK_CRS at a common grid so all years stack.
4. Apply Landsat C2 L2 surface-reflectance scale/offset.
5. Persist each year as a multi-band GeoTIFF in data/processed/.
"""
from __future__ import annotations

import math
import os
import warnings
from pathlib import Path
from typing import Dict, Tuple

# GDAL hints for reading remote Landsat COGs efficiently
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_USE_HEAD", "NO")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "60")
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("AWS_REQUEST_PAYER", "requester")
os.environ.setdefault("VSI_CACHE", "TRUE")

import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.windows import from_bounds
from pyproj import Transformer
from pystac_client import Client
import planetary_computer as pc

import config


# ----------------------------------------------------------------------------
# STAC client (lazy)
# ----------------------------------------------------------------------------
_client: Client | None = None


def _get_client() -> Client:
    """Open the PC STAC catalog with automatic SAS-token signing."""
    global _client
    if _client is None:
        _client = Client.open(config.STAC_ENDPOINT,
                              modifier=pc.sign_inplace)
    return _client


# ----------------------------------------------------------------------------
# Scene selection
# ----------------------------------------------------------------------------
# Platform penalty (added to cloud-cover score during ranking).
# Landsat-7 lost its Scan-Line Corrector on 2003-05-31, leaving permanent
# wedge-shaped gaps in every later scene — avoid it when alternatives exist.
PLATFORM_PENALTY = {
    "landsat-8": 0.0,
    "landsat-9": 0.0,
    "landsat-5": 1.0,   # mild preference for L8/L9 when both available
    "landsat-4": 5.0,
    "landsat-7": 1000.0,  # effectively last-resort
}


def _scene_score(item) -> float:
    cloud = float(item.properties.get("eo:cloud_cover", 100.0))
    plat = item.properties.get("platform", "").lower()
    return cloud + PLATFORM_PENALTY.get(plat, 50.0)


def _search_items(year_label: str, relax_cloud: bool = False) -> list:
    period = config.TIME_PERIODS[year_label]
    client = _get_client()
    kwargs = dict(
        collections=[config.STAC_COLLECTION],
        bbox=config.AOI_BBOX,
        datetime=f"{period['start']}/{period['end']}",
        max_items=200,
    )
    if not relax_cloud:
        kwargs["query"] = {"eo:cloud_cover": {"lt": config.MAX_CLOUD_COVER}}
    return list(client.search(**kwargs).items())


def find_best_scene(year_label: str) -> dict:
    """Return the STAC item with the lowest combined cloud+platform score."""
    items = _search_items(year_label)
    if not items:
        warnings.warn(f"[{year_label}] No scenes <{config.MAX_CLOUD_COVER}% cloud, relaxing.")
        items = _search_items(year_label, relax_cloud=True)
    if not items:
        raise RuntimeError(f"No Landsat scenes found for {year_label}")
    items.sort(key=_scene_score)
    chosen = items[0]
    print(f"[{year_label}] selected {chosen.id} | "
          f"cloud={chosen.properties.get('eo:cloud_cover'):.2f}% | "
          f"date={chosen.properties.get('datetime')[:10]} | "
          f"platform={chosen.properties.get('platform')}")
    return chosen


def find_composite_items(year_label: str, max_items: int = 6,
                         max_cloud: float = 30.0) -> list:
    """
    Return up to `max_items` lowest-cloud Landsat-7 scenes for the period,
    used to fill SLC-off stripes by per-pixel median compositing.
    """
    items = _search_items(year_label, relax_cloud=True)
    l7 = [it for it in items
          if it.properties.get("platform", "").lower() == "landsat-7"
          and float(it.properties.get("eo:cloud_cover", 100)) <= max_cloud]
    l7.sort(key=lambda it: float(it.properties.get("eo:cloud_cover", 100)))
    return l7[:max_items]


# ----------------------------------------------------------------------------
# Band-asset resolution (sensor-agnostic)
# ----------------------------------------------------------------------------
def _resolve_asset(item, logical_name: str):
    for alias in config.BAND_ALIASES[logical_name]:
        if alias in item.assets:
            return item.assets[alias]
    raise KeyError(f"Asset '{logical_name}' not found in {item.id}. "
                   f"Available: {list(item.assets.keys())}")


# ----------------------------------------------------------------------------
# Windowed read + reprojection
# ----------------------------------------------------------------------------
def _aoi_bounds_in_crs(dst_crs: str) -> Tuple[float, float, float, float]:
    """Project the WGS84 AOI bbox into the given CRS."""
    transformer = Transformer.from_crs(config.LATLON_CRS, dst_crs, always_xy=True)
    minx, miny = transformer.transform(config.AOI_BBOX[0], config.AOI_BBOX[1])
    maxx, maxy = transformer.transform(config.AOI_BBOX[2], config.AOI_BBOX[3])
    # transformer can swap order at edges — normalize
    return (min(minx, maxx), min(miny, maxy),
            max(minx, maxx), max(miny, maxy))


def _common_grid() -> dict:
    """Define the shared output grid in WORK_CRS for all years."""
    minx, miny, maxx, maxy = _aoi_bounds_in_crs(config.WORK_CRS)
    # Snap to pixel grid
    px = config.PIXEL_SIZE_M
    minx = math.floor(minx / px) * px
    miny = math.floor(miny / px) * px
    maxx = math.ceil(maxx / px) * px
    maxy = math.ceil(maxy / px) * px
    width = int((maxx - minx) / px)
    height = int((maxy - miny) / px)
    transform = rasterio.transform.from_origin(minx, maxy, px, px)
    return {
        "crs": config.WORK_CRS,
        "transform": transform,
        "width": width,
        "height": height,
        "bounds": (minx, miny, maxx, maxy),
    }


def _read_band_to_grid(href: str, grid: dict) -> np.ndarray:
    """Open COG, read AOI window, reproject onto the common grid."""
    dst = np.full((grid["height"], grid["width"]), np.nan, dtype="float32")
    with rasterio.open(href) as src:
        # AOI bounds expressed in the source CRS
        src_bounds = _aoi_bounds_in_crs(src.crs.to_string())
        window = from_bounds(*src_bounds, transform=src.transform).round_lengths().round_offsets()
        # Pad window slightly to avoid edge clipping during warp
        window = window.toranges()
        row_off = max(0, window[0][0] - 2)
        row_end = min(src.height, window[0][1] + 2)
        col_off = max(0, window[1][0] - 2)
        col_end = min(src.width, window[1][1] + 2)
        win = rasterio.windows.Window.from_slices(
            (row_off, row_end), (col_off, col_end)
        )
        src_data = src.read(1, window=win).astype("float32")
        src_transform = src.window_transform(win)

        # Mask Landsat C2 nodata (0 in scaled SR)
        src_data[src_data == 0] = np.nan

        reproject(
            source=src_data,
            destination=dst,
            src_transform=src_transform,
            src_crs=src.crs,
            dst_transform=grid["transform"],
            dst_crs=grid["crs"],
            resampling=Resampling.bilinear,
            src_nodata=np.nan,
            dst_nodata=np.nan,
        )
    # Apply SR scale & offset
    dst = dst * config.SR_SCALE + config.SR_OFFSET
    # Clip to physical range
    dst = np.clip(dst, 0.0, 1.0)
    return dst


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------
BAND_ORDER = ["blue", "green", "red", "nir", "swir1", "swir2"]


def _stack_bands_from_item(item, grid: dict) -> np.ndarray:
    bands = []
    for name in BAND_ORDER:
        asset = _resolve_asset(item, name)
        bands.append(_read_band_to_grid(asset.href, grid))
    return np.stack(bands, axis=0).astype("float32")  # (6, H, W)


def acquire_year(year_label: str, force: bool = False) -> Path:
    """Search, download (windowed), and stack 6 bands into one GeoTIFF.

    If the best scene is a Landsat-7 (SLC-off) image, build a per-pixel
    median composite from up to 6 of the lowest-cloud L7 scenes in the same
    period so that the wedge-shaped data gaps get filled.
    """
    out_path = config.PROCESSED_DIR / f"lusail_{year_label}.tif"
    if out_path.exists() and not force:
        print(f"[{year_label}] cached -> {out_path.name}")
        return out_path

    chosen = find_best_scene(year_label)
    grid = _common_grid()
    is_l7 = chosen.properties.get("platform", "").lower() == "landsat-7"

    if is_l7:
        # SLC-off compositing
        items = find_composite_items(year_label)
        if not items:
            items = [chosen]
        print(f"[{year_label}] L7 SLC-off -> median composite of {len(items)} scenes")
        cube = []
        for k, it in enumerate(items, 1):
            print(f"  [{k}/{len(items)}] {it.id} "
                  f"(cloud={it.properties.get('eo:cloud_cover'):.1f}%)")
            cube.append(_stack_bands_from_item(it, grid))
        cube_arr = np.stack(cube, axis=0)  # (N, 6, H, W)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            stack = np.nanmedian(cube_arr, axis=0).astype("float32")
        scene_ids = ";".join(it.id for it in items)
        platforms = ";".join(set(it.properties.get("platform", "") for it in items))
        datetime_tag = ";".join(it.properties.get("datetime", "")[:10] for it in items)
        cloud_tag = ";".join(f"{it.properties.get('eo:cloud_cover', 0):.1f}" for it in items)
    else:
        print(f"  reading bands for {chosen.id}")
        for name in BAND_ORDER:
            asset = _resolve_asset(chosen, name)
            print(f"    {name:>5s} <- {Path(asset.href).name.split('?')[0]}")
        stack = _stack_bands_from_item(chosen, grid)
        scene_ids = chosen.id
        platforms = chosen.properties.get("platform", "")
        datetime_tag = chosen.properties.get("datetime", "")
        cloud_tag = str(chosen.properties.get("eo:cloud_cover", ""))

    profile = {
        "driver": "GTiff",
        "height": grid["height"],
        "width":  grid["width"],
        "count":  len(BAND_ORDER),
        "dtype":  "float32",
        "crs":    grid["crs"],
        "transform": grid["transform"],
        "nodata": np.nan,
        "compress": "lzw",
        "tiled": True,
    }
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(stack)
        for i, n in enumerate(BAND_ORDER, start=1):
            dst.set_band_description(i, n)
        dst.update_tags(
            year=year_label,
            scene_id=scene_ids,
            platform=platforms,
            cloud_cover=cloud_tag,
            datetime=datetime_tag,
            composite=("median" if is_l7 else "single"),
        )
    print(f"[{year_label}] wrote -> {out_path}")
    return out_path


def acquire_all() -> Dict[str, Path]:
    return {yr: acquire_year(yr) for yr in config.TIME_PERIODS}


def read_stack(path: Path) -> Tuple[np.ndarray, dict]:
    """Return (bands_dict, profile). bands_dict keys are config band names."""
    with rasterio.open(path) as src:
        arr = src.read().astype("float32")
        profile = src.profile.copy()
        descriptions = src.descriptions
        tags = src.tags()
    bands = {descriptions[i]: arr[i] for i in range(arr.shape[0])}
    profile["tags"] = tags
    return bands, profile

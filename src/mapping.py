"""
Map production for Lusail study.

Every map produced here includes the four mandatory cartographic elements:
    * North arrow
    * Scale bar (in km, computed in working CRS metres)
    * Coordinate grid (lat / lon labels projected onto the working UTM CRS)
    * Legend (color bar or class legend)

The plot extent is the AOI in the working CRS (EPSG:32639, metres),
so the scale bar is computed directly from map units.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import matplotlib.pyplot as plt
from matplotlib import patches, colors as mcolors
from matplotlib.patches import Rectangle, FancyArrow
from matplotlib.lines import Line2D
import rasterio
from pyproj import Transformer

import config


# ----------------------------------------------------------------------------
# Cartographic decorations
# ----------------------------------------------------------------------------
def _add_north_arrow(ax, x=0.93, y=0.93, size=0.06):
    """Add a simple north arrow in axes-fraction coordinates."""
    arrow = FancyArrow(
        x, y - size, 0, size,
        width=0.012, head_width=0.03, head_length=0.025,
        length_includes_head=True,
        color="black", transform=ax.transAxes, clip_on=False,
    )
    ax.add_patch(arrow)
    ax.text(x, y + size * 0.25, "N",
            ha="center", va="bottom",
            fontsize=11, fontweight="bold",
            transform=ax.transAxes)


def _add_scale_bar(ax, length_m=2000, x=0.07, y=0.06,
                   height_axfrac=0.012):
    """
    Draw a 2-segment scale bar in the lower-left corner.
    The axis is in metres (working UTM CRS), so length_m is straightforward.
    """
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    width_m = xlim[1] - xlim[0]
    height_m = ylim[1] - ylim[0]

    x0 = xlim[0] + x * width_m
    y0 = ylim[0] + y * height_m
    bar_h = height_axfrac * height_m

    half = length_m / 2.0
    ax.add_patch(Rectangle((x0, y0), half, bar_h,
                           facecolor="black", edgecolor="black"))
    ax.add_patch(Rectangle((x0 + half, y0), half, bar_h,
                           facecolor="white", edgecolor="black"))
    ax.text(x0,            y0 + bar_h * 1.4, "0",
            ha="center", va="bottom", fontsize=8)
    ax.text(x0 + half,     y0 + bar_h * 1.4, f"{length_m/2000:.1f}",
            ha="center", va="bottom", fontsize=8)
    ax.text(x0 + length_m, y0 + bar_h * 1.4, f"{length_m/1000:.1f}",
            ha="center", va="bottom", fontsize=8)
    ax.text(x0 + length_m, y0 - bar_h * 0.8, "km",
            ha="left", va="top", fontsize=8)


def _add_latlon_grid(ax, bounds_utm, work_crs=config.WORK_CRS,
                     step_deg=0.02):
    """
    Place ticks/grid at round-number lat/lon, but on UTM-projected axes.
    """
    fwd = Transformer.from_crs(config.LATLON_CRS, work_crs, always_xy=True)
    inv = Transformer.from_crs(work_crs, config.LATLON_CRS, always_xy=True)

    # Lat/lon range of AOI corners
    minx, miny, maxx, maxy = bounds_utm
    lon_lo, lat_lo = inv.transform(minx, miny)
    lon_hi, lat_hi = inv.transform(maxx, maxy)
    lon_lo, lon_hi = sorted([lon_lo, lon_hi])
    lat_lo, lat_hi = sorted([lat_lo, lat_hi])

    def _round_range(lo, hi, step):
        start = np.floor(lo / step) * step
        stop  = np.ceil(hi  / step) * step
        return np.arange(start, stop + step / 2, step)

    lons = _round_range(lon_lo, lon_hi, step_deg)
    lats = _round_range(lat_lo, lat_hi, step_deg)

    # x-ticks: project each (lon, mean_lat) -> UTM x
    xticks, xlabels = [], []
    mean_lat = (lat_lo + lat_hi) / 2
    for lon in lons:
        xx, _ = fwd.transform(lon, mean_lat)
        if minx <= xx <= maxx:
            xticks.append(xx)
            xlabels.append(f"{lon:.2f}°E")

    yticks, ylabels = [], []
    mean_lon = (lon_lo + lon_hi) / 2
    for lat in lats:
        _, yy = fwd.transform(mean_lon, lat)
        if miny <= yy <= maxy:
            yticks.append(yy)
            ylabels.append(f"{lat:.2f}°N")

    ax.set_xticks(xticks)
    ax.set_xticklabels(xlabels, fontsize=8)
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=8)
    ax.grid(True, color="white", linewidth=0.6, alpha=0.7, linestyle=":")
    ax.set_xlabel("")
    ax.set_ylabel("")


def _add_footer(ax, year=None):
    txt = config.DATA_SOURCE_TXT + f"  |  CRS: {config.WORK_CRS}"
    if year:
        txt += f"  |  Year: {year}"
    ax.text(0.5, -0.07, txt,
            transform=ax.transAxes,
            ha="center", va="top", fontsize=7, color="dimgray")


def _decorate(ax, bounds, year=None,
              scale_bar_length_m=2000):
    _add_latlon_grid(ax, bounds)
    _add_scale_bar(ax, length_m=scale_bar_length_m)
    _add_north_arrow(ax)
    _add_footer(ax, year=year)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _bounds_and_extent(profile) -> tuple:
    transform = profile["transform"]
    height = profile["height"]
    width = profile["width"]
    minx = transform.c
    maxy = transform.f
    maxx = minx + transform.a * width
    miny = maxy + transform.e * height
    bounds = (minx, miny, maxx, maxy)
    extent = (minx, maxx, miny, maxy)
    return bounds, extent


def _save_geotiff(arr: np.ndarray, profile: dict, path: Path,
                  nodata=np.nan, count_override=None):
    prof = profile.copy()
    if arr.ndim == 2:
        prof.update(count=1, dtype="float32", nodata=nodata)
        arr_w = arr[np.newaxis, ...].astype("float32")
    else:
        prof.update(count=arr.shape[0], dtype=arr.dtype, nodata=nodata)
        arr_w = arr
    prof.pop("tags", None)
    prof.pop("descriptions", None)
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(arr_w)


# ----------------------------------------------------------------------------
# Map 1 — RGB true colour
# ----------------------------------------------------------------------------
def _rgb_stretch(rgb: np.ndarray, pct=(2, 98)) -> np.ndarray:
    out = np.empty_like(rgb)
    for k in range(rgb.shape[-1]):
        ch = rgb[..., k]
        lo, hi = np.nanpercentile(ch, pct)
        if hi <= lo:
            lo, hi = 0.0, 1.0
        out[..., k] = np.clip((ch - lo) / (hi - lo), 0, 1)
    out = np.nan_to_num(out, nan=0.0)
    return out


def plot_rgb(bands: dict, profile: dict, year: str) -> Path:
    rgb = np.stack([bands["red"], bands["green"], bands["blue"]], axis=-1)
    rgb = _rgb_stretch(rgb)

    bounds, extent = _bounds_and_extent(profile)
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(rgb, extent=extent, origin="upper")
    ax.set_title(f"{config.FIG_TITLE_PREFIX} — True Colour RGB ({year})",
                 fontsize=13, fontweight="bold")
    _decorate(ax, bounds, year=year)

    out = config.MAP_DIR / f"rgb_{year}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=config.MAP_DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_rgb_triptych(rgb_inputs: dict, profile: dict) -> Path:
    """rgb_inputs = {year: bands_dict}"""
    bounds, extent = _bounds_and_extent(profile)
    years = sorted(rgb_inputs.keys())
    fig, axes = plt.subplots(1, len(years), figsize=(6 * len(years), 7))
    if len(years) == 1:
        axes = [axes]
    for ax, year in zip(axes, years):
        b = rgb_inputs[year]
        rgb = _rgb_stretch(np.stack([b["red"], b["green"], b["blue"]], axis=-1))
        ax.imshow(rgb, extent=extent, origin="upper")
        ax.set_title(year, fontsize=14, fontweight="bold")
        _decorate(ax, bounds, year=year)
    fig.suptitle(f"{config.FIG_TITLE_PREFIX} — True Colour Comparison",
                 fontsize=15, fontweight="bold", y=1.02)
    out = config.MAP_DIR / "rgb_comparison.png"
    fig.tight_layout()
    fig.savefig(out, dpi=config.MAP_DPI, bbox_inches="tight")
    plt.close(fig)
    return out


# ----------------------------------------------------------------------------
# Map 2 — Single index maps
# ----------------------------------------------------------------------------
INDEX_CMAP = {
    "NDVI":  "RdYlGn",
    "NDBI":  "RdGy_r",
    "MNDWI": "RdYlBu",
    "BSI":   "YlOrBr",
}
INDEX_VMIN_VMAX = {
    "NDVI":  (-0.3, 0.6),
    "NDBI":  (-0.5, 0.5),
    "MNDWI": (-0.6, 0.6),
    "BSI":   (-0.2, 0.6),
}


def plot_index(arr: np.ndarray, profile: dict, name: str, year: str) -> Path:
    bounds, extent = _bounds_and_extent(profile)
    vmin, vmax = INDEX_VMIN_VMAX[name]

    fig, ax = plt.subplots(figsize=(9, 9))
    im = ax.imshow(arr, extent=extent, origin="upper",
                   cmap=INDEX_CMAP[name], vmin=vmin, vmax=vmax)
    ax.set_title(f"{config.FIG_TITLE_PREFIX} — {name} ({year})",
                 fontsize=13, fontweight="bold")
    cbar = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.04)
    cbar.set_label(name)

    _decorate(ax, bounds, year=year)

    out = config.MAP_DIR / f"{name.lower()}_{year}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=config.MAP_DPI, bbox_inches="tight")
    plt.close(fig)
    # Also store GeoTIFF
    _save_geotiff(arr, profile, config.MAP_DIR / f"{name.lower()}_{year}.tif")
    return out


# ----------------------------------------------------------------------------
# Map 3 — Difference maps
# ----------------------------------------------------------------------------
def plot_diff(arr: np.ndarray, profile: dict, name: str,
              y0: str, y1: str) -> Path:
    bounds, extent = _bounds_and_extent(profile)
    vmax = np.nanpercentile(np.abs(arr), 98)
    if not np.isfinite(vmax) or vmax == 0:
        vmax = 0.5
    fig, ax = plt.subplots(figsize=(9, 9))
    im = ax.imshow(arr, extent=extent, origin="upper",
                   cmap="RdBu_r", vmin=-vmax, vmax=vmax)
    ax.set_title(f"{config.FIG_TITLE_PREFIX} — Δ{name} ({y0} → {y1})",
                 fontsize=13, fontweight="bold")
    cbar = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.04)
    cbar.set_label(f"Δ{name}")
    _decorate(ax, bounds, year=f"{y0}→{y1}")

    out = config.MAP_DIR / f"d{name.lower()}_{y0}_{y1}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=config.MAP_DPI, bbox_inches="tight")
    plt.close(fig)
    _save_geotiff(arr, profile, config.MAP_DIR / f"d{name.lower()}_{y0}_{y1}.tif")
    return out


# ----------------------------------------------------------------------------
# Map 4 — Land-cover classification
# ----------------------------------------------------------------------------
def plot_landcover(semantic: np.ndarray, profile: dict, year: str) -> Path:
    bounds, extent = _bounds_and_extent(profile)

    cmap = mcolors.ListedColormap(
        [config.CLASS_COLORS[c] for c in config.CLASS_NAMES])
    norm = mcolors.BoundaryNorm(
        boundaries=np.arange(-0.5, len(config.CLASS_NAMES) + 0.5, 1),
        ncolors=len(config.CLASS_NAMES))

    show = np.where(semantic < 0, np.nan, semantic).astype("float32")

    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(show, extent=extent, origin="upper", cmap=cmap, norm=norm,
              interpolation="nearest")
    ax.set_title(f"{config.FIG_TITLE_PREFIX} — Land Cover ({year})",
                 fontsize=13, fontweight="bold")

    # Custom legend
    handles = [
        patches.Patch(facecolor=config.CLASS_COLORS[c],
                      edgecolor="black", label=c)
        for c in config.CLASS_NAMES
    ]
    ax.legend(handles=handles, loc="lower right",
              framealpha=0.9, fontsize=9, title="Class")

    _decorate(ax, bounds, year=year)

    out = config.MAP_DIR / f"landcover_{year}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=config.MAP_DPI, bbox_inches="tight")
    plt.close(fig)
    _save_geotiff(semantic.astype("float32"), profile,
                  config.MAP_DIR / f"landcover_{year}.tif", nodata=-1)
    return out


def plot_landcover_triptych(semantic_by_year: dict, profile: dict) -> Path:
    bounds, extent = _bounds_and_extent(profile)
    cmap = mcolors.ListedColormap(
        [config.CLASS_COLORS[c] for c in config.CLASS_NAMES])
    norm = mcolors.BoundaryNorm(
        boundaries=np.arange(-0.5, len(config.CLASS_NAMES) + 0.5, 1),
        ncolors=len(config.CLASS_NAMES))

    years = sorted(semantic_by_year.keys())
    fig, axes = plt.subplots(1, len(years), figsize=(6 * len(years), 7))
    if len(years) == 1:
        axes = [axes]
    for ax, year in zip(axes, years):
        sem = semantic_by_year[year]
        show = np.where(sem < 0, np.nan, sem).astype("float32")
        ax.imshow(show, extent=extent, origin="upper", cmap=cmap, norm=norm,
                  interpolation="nearest")
        ax.set_title(year, fontsize=14, fontweight="bold")
        _decorate(ax, bounds, year=year)

    handles = [patches.Patch(facecolor=config.CLASS_COLORS[c],
                             edgecolor="black", label=c)
               for c in config.CLASS_NAMES]
    fig.legend(handles=handles, loc="lower center", ncol=len(config.CLASS_NAMES),
               frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle(f"{config.FIG_TITLE_PREFIX} — Land-Cover Comparison",
                 fontsize=15, fontweight="bold", y=1.02)

    out = config.MAP_DIR / "landcover_comparison.png"
    fig.tight_layout()
    fig.savefig(out, dpi=config.MAP_DPI, bbox_inches="tight")
    plt.close(fig)
    return out

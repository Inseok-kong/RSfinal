"""
Quantitative analysis tables + summary CSVs + presentation graphs.

Outputs (under outputs/tables/ and outputs/graphs/):
  - mean_indices.csv       : Year, NDVI, NDBI, MNDWI, BSI
  - landcover_area.csv     : Year, <each class> km²
  - change_summary.csv     : Period, ΔUrban, ΔVeg, ΔWater, ΔDesert, ΔNDVI, ΔNDBI
  - transition_2000_2022.csv : From-To matrix in km²
  - bar_landcover.png      : Stacked land-cover area bar chart
  - line_indices.png       : Mean index trends 2000/2010/2022
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config


# ----------------------------------------------------------------------------
# Tables
# ----------------------------------------------------------------------------
def build_mean_indices_table(indices_by_year: dict) -> pd.DataFrame:
    """indices_by_year = {year: {NDVI: arr, NDBI: arr, ...}}"""
    rows = []
    for year, idx in indices_by_year.items():
        rows.append({
            "Year":  year,
            "NDVI":  float(np.nanmean(idx["NDVI"])),
            "NDBI":  float(np.nanmean(idx["NDBI"])),
            "MNDWI": float(np.nanmean(idx["MNDWI"])),
            "BSI":   float(np.nanmean(idx["BSI"])),
        })
    df = pd.DataFrame(rows).sort_values("Year").reset_index(drop=True)
    df.to_csv(config.TABLE_DIR / "mean_indices.csv", index=False)
    return df


def build_landcover_table(areas_by_year: dict) -> pd.DataFrame:
    """areas_by_year = {year: {class_name: area_km2}}"""
    rows = []
    for year, areas in areas_by_year.items():
        row = {"Year": year}
        row.update(areas)
        rows.append(row)
    df = pd.DataFrame(rows).sort_values("Year").reset_index(drop=True)
    df.to_csv(config.TABLE_DIR / "landcover_area.csv", index=False)
    return df


def build_change_summary(areas_by_year: dict,
                         indices_by_year: dict) -> pd.DataFrame:
    """Per-period deltas for the key variables."""
    years = sorted(areas_by_year.keys())
    periods = [(years[i], years[j])
               for i in range(len(years)) for j in range(i + 1, len(years))]
    rows = []
    for y0, y1 in periods:
        a0, a1 = areas_by_year[y0], areas_by_year[y1]
        i0, i1 = indices_by_year[y0], indices_by_year[y1]
        rows.append({
            "Period":      f"{y0} -> {y1}",
            "dUrban_km2":  a1.get("Urban", 0)      - a0.get("Urban", 0),
            "dVeg_km2":    a1.get("Vegetation", 0) - a0.get("Vegetation", 0),
            "dWater_km2":  a1.get("Water", 0)      - a0.get("Water", 0),
            "dDesert_km2": a1.get("Desert", 0)     - a0.get("Desert", 0),
            "dNDVI":       float(np.nanmean(i1["NDVI"])  - np.nanmean(i0["NDVI"])),
            "dNDBI":       float(np.nanmean(i1["NDBI"])  - np.nanmean(i0["NDBI"])),
            "dMNDWI":      float(np.nanmean(i1["MNDWI"]) - np.nanmean(i0["MNDWI"])),
            "dBSI":        float(np.nanmean(i1["BSI"])   - np.nanmean(i0["BSI"])),
        })
    df = pd.DataFrame(rows)
    df.to_csv(config.TABLE_DIR / "change_summary.csv", index=False)
    return df


def save_transition_matrix(matrix_df: pd.DataFrame,
                           filename: str = "transition_2000_2022.csv"):
    matrix_df.to_csv(config.TABLE_DIR / filename)


# ----------------------------------------------------------------------------
# Plots
# ----------------------------------------------------------------------------
def plot_landcover_bars(df: pd.DataFrame) -> Path:
    classes = config.CLASS_NAMES
    fig, ax = plt.subplots(figsize=(8, 5))
    bottom = np.zeros(len(df))
    for cls in classes:
        vals = df[cls].values if cls in df.columns else np.zeros(len(df))
        ax.bar(df["Year"].astype(str), vals, bottom=bottom,
               label=cls, color=config.CLASS_COLORS[cls],
               edgecolor="white")
        bottom += vals
    ax.set_ylabel("Area (km²)")
    ax.set_title("Lusail Land Cover Composition (Landsat C2 L2 / KMeans)")
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), frameon=False)
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    fig.tight_layout()
    out = config.GRAPH_DIR / "bar_landcover.png"
    fig.savefig(out, dpi=config.MAP_DPI)
    plt.close(fig)
    return out


def plot_index_trends(df: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = {"NDVI": "#2ca02c", "NDBI": "#7f7f7f",
              "MNDWI": "#1f77b4", "BSI": "#e6c97a"}
    for name, color in colors.items():
        ax.plot(df["Year"].astype(str), df[name],
                marker="o", linewidth=2, label=name, color=color)
    ax.axhline(0, color="black", linewidth=0.7, linestyle="--", alpha=0.5)
    ax.set_ylabel("Mean index value")
    ax.set_title("Lusail — Mean Spectral Indices over Time")
    ax.legend(frameon=False)
    ax.grid(linestyle=":", alpha=0.5)
    fig.tight_layout()
    out = config.GRAPH_DIR / "line_indices.png"
    fig.savefig(out, dpi=config.MAP_DPI)
    plt.close(fig)
    return out


def plot_urban_vs_desert(df: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5))
    years = df["Year"].astype(str)
    width = 0.35
    x = np.arange(len(years))
    ax.bar(x - width / 2, df["Urban"], width=width,
           color=config.CLASS_COLORS["Urban"], label="Urban")
    ax.bar(x + width / 2, df["Desert"], width=width,
           color=config.CLASS_COLORS["Desert"], label="Desert")
    ax.set_xticks(x)
    ax.set_xticklabels(years)
    ax.set_ylabel("Area (km²)")
    ax.set_title("Urban vs Desert Area — Lusail")
    ax.legend(frameon=False)
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    fig.tight_layout()
    out = config.GRAPH_DIR / "bar_urban_vs_desert.png"
    fig.savefig(out, dpi=config.MAP_DPI)
    plt.close(fig)
    return out

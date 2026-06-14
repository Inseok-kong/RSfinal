"""
Lusail World Cup remote-sensing analysis — end-to-end pipeline.

Usage
-----
    python main.py                # full pipeline
    python main.py --skip-download  # reuse cached GeoTIFFs in data/processed
    python main.py --force          # force re-download

Outputs
-------
    outputs/maps/        PNG (300dpi) + GeoTIFF for every map
    outputs/tables/      CSV summary tables (mean indices, areas, deltas, transitions)
    outputs/graphs/      Trend & bar charts for the slide deck
    outputs/presentation/ PPTX (13 slides) + expected_qa.md
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

import config

# Local modules
from src import data_acquisition as da
from src import indices as idx_mod
from src import classification as clf
from src import change_detection as cd
from src import analysis
from src import mapping
from src import presentation


def banner(msg: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n  {msg}\n{bar}")


def run(skip_download: bool = False, force: bool = False) -> int:
    t0 = time.time()

    # ------------------------------------------------------------------
    # 1) Data acquisition
    # ------------------------------------------------------------------
    banner("1. Data acquisition (STAC search + windowed read)")
    raster_paths: dict[str, Path] = {}
    for year in config.TIME_PERIODS:
        out_path = config.PROCESSED_DIR / f"lusail_{year}.tif"
        if skip_download and out_path.exists():
            raster_paths[year] = out_path
            print(f"[{year}] skip-download -> {out_path.name}")
            continue
        raster_paths[year] = da.acquire_year(year, force=force)

    # ------------------------------------------------------------------
    # 2) Load stacks + compute spectral indices
    # ------------------------------------------------------------------
    banner("2. Spectral indices (NDVI / NDBI / MNDWI / BSI)")
    bands_by_year, profile_by_year, idx_by_year = {}, {}, {}
    profile_common = None
    for year, p in raster_paths.items():
        bands, profile = da.read_stack(p)
        bands_by_year[year] = bands
        profile_by_year[year] = profile
        idx_by_year[year] = idx_mod.compute_all(bands)
        if profile_common is None:
            profile_common = profile
        print(f"[{year}] indices computed")

    # ------------------------------------------------------------------
    # 3) Land-cover classification (shared KMeans across all years)
    # ------------------------------------------------------------------
    banner("3. Land-cover classification (shared KMeans + Hungarian labelling)")
    raw_by_year, name_map = clf.classify_multi_year(bands_by_year, idx_by_year)
    print("  cluster -> class:", name_map)

    sem_by_year: dict[str, "any"] = {}
    areas_by_year: dict[str, dict] = {}
    for year in config.TIME_PERIODS:
        sem = clf.to_semantic(raw_by_year[year], name_map)
        sem_by_year[year] = sem
        areas_by_year[year] = clf.class_areas_km2(sem, config.PIXEL_SIZE_M)
        print(f"[{year}] " + " ".join(
            f"{c}={areas_by_year[year][c]:.2f}" for c in config.CLASS_NAMES))

    # ------------------------------------------------------------------
    # 4) Change detection (diff images + transition matrix)
    # ------------------------------------------------------------------
    banner("4. Change detection")
    years = sorted(idx_by_year.keys())
    diff_pairs = [(years[0], years[1]),
                  (years[1], years[2]),
                  (years[0], years[2])]
    diff_results = {}
    for y0, y1 in diff_pairs:
        for name in ["NDVI", "NDBI", "MNDWI", "BSI"]:
            arr = cd.diff(idx_by_year[y0][name], idx_by_year[y1][name])
            diff_results[(name, y0, y1)] = arr
        print(f"  Δ-stack {y0}→{y1} done")

    trans_2000_2022 = cd.transition_matrix(
        sem_by_year[years[0]], sem_by_year[years[-1]], config.PIXEL_SIZE_M
    )
    print("  Transition matrix 2000→2022 computed")

    # ------------------------------------------------------------------
    # 5) Quantitative tables + summary plots
    # ------------------------------------------------------------------
    banner("5. Quantitative analysis (CSV + graphs)")
    df_idx     = analysis.build_mean_indices_table(idx_by_year)
    df_lc      = analysis.build_landcover_table(areas_by_year)
    df_change  = analysis.build_change_summary(areas_by_year, idx_by_year)
    analysis.save_transition_matrix(trans_2000_2022)

    graph_lc       = analysis.plot_landcover_bars(df_lc)
    graph_indices  = analysis.plot_index_trends(df_idx)
    graph_urb_des  = analysis.plot_urban_vs_desert(df_lc)
    print(f"  saved: {df_idx.shape}, {df_lc.shape}, {df_change.shape} rows")

    # ------------------------------------------------------------------
    # 6) Maps
    # ------------------------------------------------------------------
    banner("6. Map production")
    map_paths = {}

    rgb_inputs = {}
    for year in years:
        map_paths[f"rgb_{year}"] = mapping.plot_rgb(
            bands_by_year[year], profile_by_year[year], year
        )
        rgb_inputs[year] = bands_by_year[year]
    map_paths["rgb_compare"] = mapping.plot_rgb_triptych(
        rgb_inputs, profile_by_year[years[-1]]
    )

    for year in years:
        for name in ["NDVI", "NDBI", "MNDWI", "BSI"]:
            map_paths[f"{name.lower()}_{year}"] = mapping.plot_index(
                idx_by_year[year][name], profile_by_year[year], name, year
            )

    for (name, y0, y1), arr in diff_results.items():
        # Only push full-period diffs into the deck, but write every diff map
        path = mapping.plot_diff(arr, profile_by_year[y1], name, y0, y1)
        if (y0, y1) == (years[0], years[-1]):
            map_paths[f"d{name.lower()}"] = path

    for year in years:
        map_paths[f"lc_{year}"] = mapping.plot_landcover(
            sem_by_year[year], profile_by_year[year], year
        )
    map_paths["lc_compare"] = mapping.plot_landcover_triptych(
        sem_by_year, profile_by_year[years[-1]]
    )
    map_paths["graph_lc"] = graph_lc
    map_paths["graph_indices"] = graph_indices
    map_paths["graph_urb_desert"] = graph_urb_des

    print(f"  produced {len(map_paths)} map artefacts")

    # ------------------------------------------------------------------
    # 7) Presentation deck + Q&A doc
    # ------------------------------------------------------------------
    banner("7. Presentation deck + expected Q&A")
    tables = {"mean_idx": df_idx, "lc_area": df_lc,
              "change":   df_change, "transition": trans_2000_2022}
    pptx = presentation.build_presentation(map_paths, tables)
    qa   = presentation.write_qa_document()
    print(f"  pptx -> {pptx}")
    print(f"  q&a  -> {qa}")

    banner(f"DONE in {time.time() - t0:.1f}s")
    print("Open outputs/ to inspect all artefacts.")
    return 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse cached GeoTIFFs in data/processed if present.")
    ap.add_argument("--force", action="store_true",
                    help="Force re-download even if cached files exist.")
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        sys.exit(run(skip_download=args.skip_download, force=args.force))
    except Exception:
        traceback.print_exc()
        sys.exit(1)

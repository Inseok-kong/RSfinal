"""
Spectral index computation: NDVI, NDBI, MNDWI, BSI.

All indices accept dictionaries of band arrays as produced by
data_acquisition.read_stack(...). Each function returns a float32
np.ndarray of identical shape with NaNs preserved.
"""
from __future__ import annotations

import numpy as np


def _safe_ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(np.abs(den) > 1e-9, num / den, np.nan)
    return out.astype("float32")


def ndvi(bands: dict) -> np.ndarray:
    """(NIR - RED) / (NIR + RED) — vegetation greenness."""
    nir, red = bands["nir"], bands["red"]
    return _safe_ratio(nir - red, nir + red)


def ndbi(bands: dict) -> np.ndarray:
    """(SWIR1 - NIR) / (SWIR1 + NIR) — built-up surfaces."""
    swir1, nir = bands["swir1"], bands["nir"]
    return _safe_ratio(swir1 - nir, swir1 + nir)


def mndwi(bands: dict) -> np.ndarray:
    """(GREEN - SWIR1) / (GREEN + SWIR1) — modified water index."""
    green, swir1 = bands["green"], bands["swir1"]
    return _safe_ratio(green - swir1, green + swir1)


def bsi(bands: dict) -> np.ndarray:
    """Bare Soil Index = ((SWIR1+RED) - (NIR+BLUE)) / ((SWIR1+RED) + (NIR+BLUE))."""
    swir1, red = bands["swir1"], bands["red"]
    nir, blue = bands["nir"], bands["blue"]
    return _safe_ratio((swir1 + red) - (nir + blue),
                       (swir1 + red) + (nir + blue))


INDEX_FUNCS = {
    "NDVI":  ndvi,
    "NDBI":  ndbi,
    "MNDWI": mndwi,
    "BSI":   bsi,
}


def compute_all(bands: dict) -> dict:
    """Return {index_name: ndarray} for every defined index."""
    return {name: fn(bands) for name, fn in INDEX_FUNCS.items()}


def nanmean(arr: np.ndarray) -> float:
    return float(np.nanmean(arr))

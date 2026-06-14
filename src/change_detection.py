"""
Change detection products:
  * Pixel-wise index differences (ΔNDVI, ΔNDBI, ΔMNDWI, ΔBSI)
  * Land-cover transition matrices between two semantic maps
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


def diff(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """b - a (later minus earlier)."""
    out = b.astype("float32") - a.astype("float32")
    return out


def transition_matrix(sem_a: np.ndarray, sem_b: np.ndarray,
                      pixel_size_m: float) -> pd.DataFrame:
    """
    From -> To (rows = from-class, cols = to-class), in km².
    Both inputs are semantic-class label arrays (0..N-1, -1 invalid).
    """
    pix_area = (pixel_size_m * pixel_size_m) / 1_000_000.0
    classes = config.CLASS_NAMES
    n = len(classes)
    mat = np.zeros((n, n), dtype="float64")

    valid = (sem_a >= 0) & (sem_b >= 0)
    a = sem_a[valid].astype("int32")
    b = sem_b[valid].astype("int32")
    # Bincount over flattened index for efficiency
    flat = a * n + b
    counts = np.bincount(flat, minlength=n * n).reshape(n, n)
    mat = counts.astype("float64") * pix_area

    df = pd.DataFrame(mat, index=classes, columns=classes)
    df.index.name = "From \\ To"
    return df

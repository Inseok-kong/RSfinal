"""
KMeans land-cover classification.

Inputs: per-year band stacks + spectral indices.
Output: integer label array with values 0..4 mapped to CLASS_NAMES
        Water / Urban / Vegetation / Desert / Mixed Surface.

To assign semantic labels to the KMeans clusters (which are arbitrary),
each cluster's centroid is scored on NDVI / NDBI / MNDWI / BSI signatures.
"""
from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from scipy.optimize import linear_sum_assignment

import config


FEATURE_NAMES = ["blue", "green", "red", "nir", "swir1", "swir2",
                 "NDVI", "NDBI", "MNDWI", "BSI"]


def _build_feature_matrix(bands: dict, idx: dict) -> tuple[np.ndarray, np.ndarray]:
    """Stack features into (N, F) matrix; return (X_valid, valid_mask)."""
    layers = [bands["blue"], bands["green"], bands["red"],
              bands["nir"], bands["swir1"], bands["swir2"],
              idx["NDVI"], idx["NDBI"], idx["MNDWI"], idx["BSI"]]
    cube = np.stack(layers, axis=-1)  # (H, W, F)
    H, W, F = cube.shape
    flat = cube.reshape(-1, F)
    valid = np.all(np.isfinite(flat), axis=1)
    return flat[valid], valid


def _semantic_label_map(centroids_unscaled: np.ndarray) -> dict:
    """
    Map KMeans cluster index -> semantic class name via Hungarian
    assignment on a score matrix derived from each centroid's
    NDVI / NDBI / MNDWI / BSI signature.
    """
    feat_idx = {n: i for i, n in enumerate(FEATURE_NAMES)}
    K = centroids_unscaled.shape[0]
    classes = config.CLASS_NAMES
    n_cls = len(classes)
    assert K == n_cls, f"Need K={n_cls} clusters for {n_cls} classes."

    score = np.zeros((K, n_cls), dtype="float64")
    for k in range(K):
        c = centroids_unscaled[k]
        ndvi = c[feat_idx["NDVI"]]
        ndbi = c[feat_idx["NDBI"]]
        mndwi = c[feat_idx["MNDWI"]]
        bsi = c[feat_idx["BSI"]]

        sigs = {
            # Water — strong positive MNDWI is decisive
            "Water":         3.0 * mndwi - ndbi - ndvi - bsi,
            # Vegetation — strong NDVI, low BSI
            "Vegetation":    3.0 * ndvi - bsi - ndbi,
            # Urban — high NDBI, low NDVI, low BSI
            "Urban":         2.0 * ndbi - ndvi - 0.5 * bsi,
            # Desert — high BSI, low NDVI/NDBI/MNDWI
            "Desert":        2.0 * bsi - ndvi - mndwi,
            # Mixed — flat signature, none of the others dominate
            "Mixed Surface": -abs(ndvi) - abs(ndbi) - abs(mndwi) - abs(bsi),
        }
        for j, cls in enumerate(classes):
            score[k, j] = sigs[cls]

    # Hungarian: maximize score = minimize -score
    row_ind, col_ind = linear_sum_assignment(-score)
    return {int(r): classes[int(c)] for r, c in zip(row_ind, col_ind)}


def classify(bands: dict, idx: dict,
             n_clusters: int = config.N_CLUSTERS) -> tuple[np.ndarray, dict]:
    """
    Single-year fit + predict. Kept for backward compatibility; for the
    main pipeline use `classify_multi_year` so cluster IDs are consistent
    across years.
    """
    H, W = bands["red"].shape
    X, valid = _build_feature_matrix(bands, idx)

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    km = KMeans(n_clusters=n_clusters,
                random_state=config.RANDOM_SEED,
                n_init=10)
    labels_valid = km.fit_predict(Xs)
    centroids_orig = scaler.inverse_transform(km.cluster_centers_)
    name_map = _semantic_label_map(centroids_orig)

    label_image = np.full(H * W, -1, dtype="int8")
    label_image[valid] = labels_valid.astype("int8")
    return label_image.reshape(H, W), name_map


def classify_multi_year(bands_by_year: dict, idx_by_year: dict,
                        n_clusters: int = config.N_CLUSTERS,
                        sample_size: int = 200_000
                        ) -> tuple[dict, dict]:
    """
    Fit ONE KMeans on the union of all years (with random sub-sampling),
    then predict each year. This makes cluster IDs — and therefore the
    semantic labels — directly comparable across time.

    Returns
    -------
    raw_label_by_year : {year: int8 H×W array, -1 nodata}
    name_map          : {cluster_idx: class_name}
    """
    rng = np.random.default_rng(config.RANDOM_SEED)
    years = sorted(bands_by_year.keys())

    # --- Build training pool --------------------------------------------
    pools = []
    per_year_matrices = {}
    per_year_valids = {}
    for y in years:
        X, valid = _build_feature_matrix(bands_by_year[y], idx_by_year[y])
        per_year_matrices[y] = X
        per_year_valids[y] = valid
        if X.shape[0] > sample_size // len(years):
            idx = rng.choice(X.shape[0], sample_size // len(years), replace=False)
            pools.append(X[idx])
        else:
            pools.append(X)
    pool = np.vstack(pools)

    # --- Fit shared scaler + KMeans -------------------------------------
    scaler = StandardScaler()
    pool_s = scaler.fit_transform(pool)

    km = KMeans(n_clusters=n_clusters,
                random_state=config.RANDOM_SEED,
                n_init=10)
    km.fit(pool_s)

    centroids_orig = scaler.inverse_transform(km.cluster_centers_)
    name_map = _semantic_label_map(centroids_orig)

    # --- Predict each year ----------------------------------------------
    raw_label_by_year = {}
    for y in years:
        X = per_year_matrices[y]
        valid = per_year_valids[y]
        Xs = scaler.transform(X)
        labels_valid = km.predict(Xs)

        H, W = bands_by_year[y]["red"].shape
        label_image = np.full(H * W, -1, dtype="int8")
        label_image[valid] = labels_valid.astype("int8")
        raw_label_by_year[y] = label_image.reshape(H, W)
    return raw_label_by_year, name_map


def to_semantic(label_image: np.ndarray, name_map: dict) -> np.ndarray:
    """
    Convert raw cluster ids to semantic class ids using CLASS_NAMES order.
    Returns int8 array; -1 stays as nodata.
    """
    out = np.full_like(label_image, -1, dtype="int8")
    class_id = {n: i for i, n in enumerate(config.CLASS_NAMES)}
    for cid, cname in name_map.items():
        out[label_image == cid] = class_id[cname]
    return out


def class_areas_km2(semantic: np.ndarray, pixel_size_m: float) -> dict:
    """Return {class_name: area_km2}."""
    pix_area_km2 = (pixel_size_m * pixel_size_m) / 1_000_000.0
    out = {}
    for i, name in enumerate(config.CLASS_NAMES):
        out[name] = float(np.sum(semantic == i)) * pix_area_km2
    return out

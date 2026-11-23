"""Unsupervised clustering experiments with a common interface.

Each algorithm sweeps its key hyperparameters; every candidate is scored with
internal metrics and bootstrap stability. Model selection uses ONLY internal
criteria — historical flood events are never consulted, so the later
validation remains independent.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.cluster.hierarchy import dendrogram, linkage
import hdbscan as hdbscan_lib
from sklearn.cluster import DBSCAN, AgglomerativeClustering, KMeans
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)
from sklearn.mixture import GaussianMixture
from sklearn.neighbors import NearestNeighbors

log = logging.getLogger("hillscope.ml")
SEED = 42
K_RANGE = range(2, 9)

ALGORITHMS = {
    "kmeans": {"id": "kmeans", "name": "K-Means", "family": "centroid",
               "purpose": "Partitions catchments into k groups of similar feature patterns."},
    "hierarchical": {"id": "hierarchical", "name": "Hierarchical (Ward)", "family": "hierarchical",
                     "purpose": "Builds a tree of catchment similarity; cut into k groups."},
    "dbscan": {"id": "dbscan", "name": "DBSCAN", "family": "density",
               "purpose": "Finds dense groups and flags unusual catchments as noise."},
    "hdbscan": {"id": "hdbscan", "name": "HDBSCAN", "family": "density",
                "purpose": "Density clustering across varying densities with membership strength."},
    "gmm": {"id": "gmm", "name": "Gaussian Mixture", "family": "probabilistic",
            "purpose": "Soft, overlapping behavioural groups with membership probabilities."},
}


@dataclass
class Candidate:
    algorithm: str
    params: dict
    labels: np.ndarray
    metrics: dict
    extra: dict = field(default_factory=dict)
    probabilities: np.ndarray | None = None
    model: object | None = None


def internal_metrics(X: np.ndarray, labels: np.ndarray) -> dict:
    """Silhouette / DB / CH on non-noise points; noise share reported separately."""
    mask = labels >= 0
    k = len(set(labels[mask]))
    sizes = np.bincount(labels[mask]) if mask.any() else np.array([])
    m = {
        "n_clusters": int(k),
        "noise_fraction": float(1 - mask.mean()),
        "n_noise": int((~mask).sum()),
        "cluster_sizes": sizes.tolist(),
        "min_cluster_fraction": float(sizes.min() / len(labels)) if k else 0.0,
    }
    if k >= 2 and mask.sum() > k:
        Xm, lm = X[mask], labels[mask]
        m["silhouette"] = float(silhouette_score(Xm, lm))
        m["davies_bouldin"] = float(davies_bouldin_score(Xm, lm))
        m["calinski_harabasz"] = float(calinski_harabasz_score(Xm, lm))
        # Cluster separation: min centroid distance / mean within-cluster distance.
        cents = np.array([Xm[lm == c].mean(axis=0) for c in range(k)])
        within = np.mean([np.linalg.norm(Xm[lm == c] - cents[c], axis=1).mean() for c in range(k)])
        d = np.linalg.norm(cents[:, None] - cents[None], axis=2)
        d[np.eye(k, dtype=bool)] = np.inf
        m["separation_ratio"] = float(d.min() / within) if within > 0 else None
    else:
        m.update(silhouette=None, davies_bouldin=None, calinski_harabasz=None, separation_ratio=None)
    return m


def _relabel_by_size(labels: np.ndarray) -> np.ndarray:
    """Deterministic labels: 0 = largest cluster; noise stays -1."""
    out = labels.copy()
    uniq = [c for c in np.unique(labels) if c >= 0]
    order = sorted(uniq, key=lambda c: (-(labels == c).sum(), c))
    for new, old in enumerate(order):
        out[labels == old] = new
    return out


def fit(algorithm: str, X: np.ndarray, params: dict) -> tuple[np.ndarray, np.ndarray | None, object]:
    if algorithm == "kmeans":
        m = KMeans(n_clusters=params["k"], n_init=20, random_state=SEED).fit(X)
        return m.labels_, None, m
    if algorithm == "hierarchical":
        m = AgglomerativeClustering(n_clusters=params["k"], linkage="ward").fit(X)
        return m.labels_, None, m
    if algorithm == "dbscan":
        m = DBSCAN(eps=params["eps"], min_samples=params["min_samples"]).fit(X)
        return m.labels_, None, m
    if algorithm == "hdbscan":
        m = hdbscan_lib.HDBSCAN(min_cluster_size=params["min_cluster_size"], min_samples=params.get("min_samples"),
                                cluster_selection_method="eom").fit(X)
        return m.labels_, m.probabilities_, m
    if algorithm == "gmm":
        m = GaussianMixture(n_components=params["k"], covariance_type=params.get("covariance", "full"),
                            n_init=5, random_state=SEED, reg_covar=1e-3).fit(X)
        return m.predict(X), m.predict_proba(X), m
    raise ValueError(f"unknown algorithm {algorithm}")


def param_grid(algorithm: str, X: np.ndarray) -> list[dict]:
    n = len(X)
    if algorithm in ("kmeans", "hierarchical"):
        return [{"k": k} for k in K_RANGE]
    if algorithm == "gmm":
        cov = "full" if n > 20 * X.shape[1] else "diag"
        return [{"k": k, "covariance": cov} for k in K_RANGE]
    if algorithm == "dbscan":
        grid = []
        for ms in (max(4, X.shape[1] // 2), X.shape[1] + 1, 2 * X.shape[1]):
            dist = NearestNeighbors(n_neighbors=ms).fit(X).kneighbors(X)[0][:, -1]
            for q in (0.5, 0.65, 0.8, 0.9):
                grid.append({"eps": round(float(np.quantile(dist, q)), 4), "min_samples": int(ms), "eps_quantile": q})
        return grid
    if algorithm == "hdbscan":
        return [{"min_cluster_size": int(s), "min_samples": int(m)}
                for s in (max(5, n // 40), max(8, n // 20), max(10, n // 12)) for m in (1, 3, 8)]
    raise ValueError(algorithm)


def stability(algorithm: str, X: np.ndarray, params: dict, labels: np.ndarray, n_boot: int = 15) -> float:
    """Mean ARI between full-data labels and labels re-fitted on 80% bootstrap subsamples."""
    rng = np.random.default_rng(SEED)
    scores = []
    for _ in range(n_boot):
        idx = rng.choice(len(X), size=int(0.8 * len(X)), replace=False)
        try:
            lb, _, _ = fit(algorithm, X[idx], params)
        except Exception:  # noqa: BLE001
            continue
        scores.append(adjusted_rand_score(labels[idx], lb))
    return float(np.mean(scores)) if scores else 0.0


def selection_score(m: dict) -> float:
    """Composite internal score used to choose a defensible configuration.

    Balances compactness/separation (silhouette, Davies–Bouldin), reproducibility
    (bootstrap ARI), and practicality (no tiny clusters, limited noise). It does
    NOT use historical events. Silhouette alone favours k=2 trivially, so
    stability and interpretability constraints are weighted in.
    """
    if m.get("silhouette") is None or m["n_clusters"] < 2:
        return -np.inf
    s = 0.40 * m["silhouette"] + 0.35 * m.get("stability", 0) - 0.10 * min(m["davies_bouldin"], 3) / 3
    s -= 0.6 * max(0.0, 0.05 - m["min_cluster_fraction"]) * 10  # penalise clusters < 5% of catchments
    s -= 0.5 * max(0.0, m["noise_fraction"] - 0.15)
    # interpretability: prefer 3–6 behavioural groups
    if m["n_clusters"] == 2:
        s -= 0.08
    if m["n_clusters"] > 6:
        s -= 0.03 * (m["n_clusters"] - 6)
    return float(s)


def density_space(X: np.ndarray, var: float = 0.85) -> tuple[np.ndarray, str]:
    """Density methods degrade in high dimensions (distance concentration), so DBSCAN/HDBSCAN
    are fitted on principal components retaining ``var`` of the variance. Metrics are still
    computed in the full scaled feature space for comparability with the other algorithms."""
    from sklearn.decomposition import PCA
    if X.shape[1] <= 6:
        return X, "scaled features"
    p = PCA(n_components=var, random_state=SEED).fit(X)
    return p.transform(X), f"PCA {p.n_components_} components ({var:.0%} variance)"


def run_algorithm(algorithm: str, X: np.ndarray, progress=None) -> tuple[Candidate, list[Candidate]]:
    """Sweep the parameter grid, score candidates, return (selected, all)."""
    cands: list[Candidate] = []
    Xfit, space = density_space(X) if algorithm in ("dbscan", "hdbscan") else (X, "scaled features")
    grid = param_grid(algorithm, Xfit)
    for i, p in enumerate(grid, 1):
        labels, proba, model = fit(algorithm, Xfit, p)
        labels = _relabel_by_size(labels)
        m = internal_metrics(X, labels)
        if m["n_clusters"] >= 2:
            m["stability"] = stability(algorithm, Xfit, p, labels)
        else:
            m["stability"] = None
        if algorithm == "gmm":
            m["bic"] = float(model.bic(X))
            m["aic"] = float(model.aic(X))
        if algorithm == "kmeans":
            m["inertia"] = float(model.inertia_)
        m["selection_score"] = selection_score(m)
        cands.append(Candidate(algorithm, p, labels, m, extra={"fit_space": space}, probabilities=proba, model=model))
        if progress:
            progress(f"{ALGORITHMS[algorithm]['name']}: evaluated {i}/{len(grid)} configurations")
    valid = [c for c in cands if np.isfinite(c.metrics["selection_score"])]
    if not valid:
        raise RuntimeError(f"{algorithm}: no configuration produced ≥2 clusters")
    best = max(valid, key=lambda c: c.metrics["selection_score"])
    if algorithm == "gmm":
        # Report BIC-optimal k alongside the composite choice for transparency.
        bic_best = min(cands, key=lambda c: c.metrics["bic"])
        best.extra["bic_optimal_k"] = bic_best.params["k"]
    if algorithm == "hdbscan":
        # Persistence is indexed by the library's original labels; map to our size-ordered labels.
        raw = best.model.labels_
        pers = best.model.cluster_persistence_
        mapping = {int(r): int(n) for r, n in zip(raw, best.labels) if r >= 0}
        best.extra["persistence"] = {str(mapping[r]): float(pers[r]) for r in sorted(mapping)}
        best.extra["mean_membership_probability"] = float(best.probabilities[best.labels >= 0].mean())
    return best, cands


def dendrogram_data(X: np.ndarray, labels: np.ndarray, truncate: int = 30) -> dict:
    """Ward linkage tree truncated to ``truncate`` leaves for display."""
    Z = linkage(X, method="ward")
    d = dendrogram(Z, truncate_mode="lastp", p=truncate, no_plot=True)
    return {"icoord": d["icoord"], "dcoord": d["dcoord"], "leaves": d["ivl"],
            "max_height": float(Z[:, 2].max())}

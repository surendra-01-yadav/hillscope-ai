import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import adjusted_rand_score

from app.features.preprocessing import preprocess
from app.ml import algorithms as algs
from app.ml.interpretation import elevation_bands, pca_projection, profile_clusters


def test_preprocess_scaling_log_and_redundancy():
    rng = np.random.default_rng(1)
    a = rng.lognormal(0, 1.2, 200)  # skewed, non-negative -> log1p
    df = pd.DataFrame({"a": a, "a_dup": a * 2 + 1e-9, "b": rng.normal(size=200), "c": np.r_[np.nan * np.ones(60), rng.normal(size=140)]})
    r = preprocess(df, ["a", "a_dup", "b", "c"])
    assert "c" in r.dropped_missing  # 30 % missing > 20 % threshold
    assert any(d["feature"] == "a_dup" and d["redundant_with"] == "a" for d in r.dropped_redundant)
    assert "a" in r.log_transformed
    assert r.features == ["a", "b"]
    assert np.allclose(np.median(r.X, axis=0), 0, atol=0.05)  # robust centring
    assert np.abs(r.X).max() <= 5.0  # winsorised


def test_preprocess_imputes_small_gaps():
    df = pd.DataFrame({"x": [1.0, 2.0, np.nan, 4.0, 5.0, 6.0], "y": [3.0, 1.0, 2.0, 5.0, 4.0, 0.0]})
    r = preprocess(df, ["x", "y"])
    assert r.imputed == {"x": 1}
    assert not np.isnan(r.X).any()


@pytest.mark.parametrize("alg", ["kmeans", "hierarchical", "gmm"])
def test_partitioning_recovers_blobs(blobs, alg):
    X, y = blobs
    labels, _, _ = algs.fit(alg, X[:180], {"k": 3})
    assert adjusted_rand_score(y[:180], labels) > 0.95


def test_dbscan_flags_outliers_as_noise(blobs):
    X, _ = blobs
    labels, _, _ = algs.fit("dbscan", X, {"eps": 1.5, "min_samples": 5})
    assert (labels[-2:] == -1).all()
    assert len(set(labels[labels >= 0])) == 3


def test_hdbscan_probabilities_and_noise(blobs):
    X, _ = blobs
    best, cands = algs.run_algorithm("hdbscan", X)
    assert best.metrics["n_clusters"] == 3
    assert best.probabilities is not None and best.probabilities.shape == (len(X),)
    assert (best.labels[-2:] == -1).all()
    assert set(best.extra["persistence"]) == {"0", "1", "2"}


def test_clustering_is_reproducible(blobs):
    X, _ = blobs
    a, _, _ = algs.fit("kmeans", X, {"k": 3})
    b, _, _ = algs.fit("kmeans", X, {"k": 3})
    assert (a == b).all()


def test_internal_metrics_and_noise_exclusion(blobs):
    X, y = blobs
    m = algs.internal_metrics(X, y)
    assert m["n_clusters"] == 3 and m["n_noise"] == 2
    assert m["silhouette"] > 0.7 and m["davies_bouldin"] < 0.5
    assert m["cluster_sizes"] == [60, 60, 60]
    single = algs.internal_metrics(X, np.zeros(len(X), dtype=int))
    assert single["silhouette"] is None


def test_selection_prefers_true_k(blobs):
    X, _ = blobs
    best, cands = algs.run_algorithm("kmeans", X[:180])
    assert best.params["k"] == 3
    assert all("stability" in c.metrics for c in cands)


def test_relabel_by_size_is_deterministic():
    lab = np.array([2, 2, 2, 0, 1, 1, -1])
    assert algs._relabel_by_size(lab).tolist() == [0, 0, 0, 2, 1, 1, -1]


def test_elevation_bands_tertiles():
    elev = np.arange(1, 91, dtype=float)
    labels, bands = elevation_bands(elev, 3)
    assert np.bincount(labels).tolist() == [30, 30, 30]
    assert bands[0]["name"] == "Lower elevation" and bands[2]["name"] == "Higher elevation"
    assert labels[0] == 0 and labels[-1] == 2


def test_profiles_label_from_measured_features():
    rng = np.random.default_rng(3)
    n = 120
    df = pd.DataFrame({
        "slope_mean": np.r_[rng.normal(35, 2, 60), rng.normal(12, 2, 60)],
        "melton": np.r_[rng.normal(1.2, 0.1, 60), rng.normal(0.3, 0.05, 60)],
        "flashiness_proxy": np.r_[rng.normal(60, 5, 60), rng.normal(10, 2, 60)],
        "rain_annual": rng.normal(1500, 50, n),
    })
    labels = np.r_[np.zeros(60, int), np.ones(60, int)]
    profs = profile_clusters(df, labels, list(df.columns))
    names = {p["cluster"]: p["name"] for p in profs}
    assert names[0].startswith("Rapid-response")
    assert names[1].startswith("Gentler")
    assert profs[0]["distinguishing"][0]["direction"] == "higher"


def test_pca_projection_shapes(blobs):
    X, _ = blobs
    p = pca_projection(X)
    assert len(p["coords"]) == len(X) and len(p["coords"][0]) == 2
    assert 0 < sum(p["explained_variance"]) <= 1.0


def test_model_persistence(tmp_path, blobs):
    import joblib
    X, _ = blobs
    labels, _, model = algs.fit("kmeans", X, {"k": 3})
    p = tmp_path / "m.joblib"
    joblib.dump(model, p)
    assert (joblib.load(p).predict(X) == labels).all()

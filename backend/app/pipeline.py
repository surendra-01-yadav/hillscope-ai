"""End-to-end discovery pipeline: real data -> features -> clustering -> evaluation -> profiles -> validation."""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

import joblib
import numpy as np
import pandas as pd

from .config import MODELS_DIR, PERIODS, PROCESSED_DIR, REGIONS
from .data import events as events_mod
from .data import raster, rainfall, vector
from .data.common import DataUnavailable
from .features.engineering import FEATURE_MAP, FEATURE_SETS, build_base, build_features, feature_keys
from .features.preprocessing import preprocess
from .ml import algorithms as algs
from .ml.interpretation import elevation_bands, pca_projection, profile_clusters
from .validation.historical import validate

log = logging.getLogger("hillscope.pipeline")

STAGES = [
    ("acquire", "Acquiring datasets"),
    ("prepare", "Preparing catchments"),
    ("features", "Extracting features"),
    ("cluster", "Running clustering"),
    ("evaluate", "Evaluating cluster quality"),
    ("profiles", "Generating behavioural profiles"),
]

Progress = Callable[[str, str], None]


def _noop(stage: str, msg: str) -> None:
    log.info("[%s] %s", stage, msg)


def acquire(region: dict, period: dict, progress: Progress = _noop) -> dict:
    """Ensure every real dataset is present locally (downloads only what is missing)."""
    p = lambda m: progress("acquire", m)  # noqa: E731
    status = {}
    g = vector.catchments(region, p)
    status["hydrobasins"] = "ok"
    raster.dem_mosaic(region, p)
    status["copernicus_dem"] = "ok"
    for name, fn in (("hydrorivers", lambda: vector.rivers(region, p)),
                     ("worldcover", lambda: None),  # read lazily in feature stage (COG overviews)
                     ("events", lambda: events_mod.all_events(region, p))):
        try:
            fn()
            status[name] = "ok"
        except DataUnavailable as e:
            status[name] = f"unavailable: {e.message}"
    rainfall.chirps_years(region, period["start"], period["end"], p)
    status["chirps"] = "ok"
    return status


def dataset_version(df: pd.DataFrame, keys: list[str]) -> str:
    h = hashlib.sha1()
    h.update(",".join(keys).encode())
    h.update(np.round(df[keys].astype(float).fillna(-9999).values, 4).tobytes())
    return "fv-" + h.hexdigest()[:12]


def _candidate_summary(c: algs.Candidate) -> dict:
    return {"algorithm": c.algorithm, "name": algs.ALGORITHMS[c.algorithm]["name"], "params": c.params,
            "metrics": c.metrics, "extra": c.extra}


def run_discovery(region_id: str, period_id: str, feature_set: str, algorithm: str,
                  progress: Progress = _noop) -> dict:
    t0 = time.time()
    region = REGIONS[region_id]
    period = PERIODS[period_id]
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"unknown feature set {feature_set}")
    if algorithm not in (*algs.ALGORITHMS, "auto"):
        raise ValueError(f"unknown algorithm {algorithm}")

    progress("acquire", "Checking local cache and real data providers")
    acq = acquire(region, period, progress)

    progress("prepare", "Loading HydroBASINS catchments and applying hill filter")
    base, base_report = build_base(region, lambda m: progress("prepare", m))
    progress("prepare", f"{len(base)} hill catchments retained of {base_report['filters']['initial_catchments']}")

    progress("features", "Computing rainfall regime, terrain and surface features")
    gdf, frep = build_features(region, period, lambda m: progress("features", m))
    keys = feature_keys(feature_set, [c for c in gdf.columns if c in FEATURE_MAP])
    pre = preprocess(gdf, keys)
    progress("features", f"{len(pre.features)} features after redundancy pruning ({len(keys)} candidates)")
    X = pre.X

    progress("cluster", "Sweeping hyperparameters for all five algorithms")
    best: dict[str, algs.Candidate] = {}
    sweeps: dict[str, list[dict]] = {}
    for a in algs.ALGORITHMS:
        try:
            b, cands = algs.run_algorithm(a, X, lambda m: progress("cluster", m))
            best[a] = b
            sweeps[a] = [{"params": c.params, "metrics": c.metrics} for c in cands]
        except RuntimeError as e:
            log.warning("%s produced no valid clustering: %s", a, e)
            sweeps[a] = []
    if not best:
        raise RuntimeError("no algorithm produced a valid clustering")
    recommended = max(best.values(), key=lambda c: c.metrics["selection_score"]).algorithm
    chosen_alg = recommended if algorithm == "auto" else algorithm
    if chosen_alg not in best:
        raise RuntimeError(f"{chosen_alg} produced no configuration with ≥2 clusters on this data")
    chosen = best[chosen_alg]
    labels = chosen.labels

    progress("evaluate", "Computing elevation-band baseline and PCA projection")
    band_labels, bands = elevation_bands(gdf["elev_mean"].values, 3)
    k = chosen.metrics["n_clusters"]
    band_k_labels, _ = elevation_bands(gdf["elev_mean"].values, max(k, 2))
    baseline_metrics = algs.internal_metrics(X, band_labels)
    baseline_k_metrics = algs.internal_metrics(X, band_k_labels)
    pca = pca_projection(X)
    dendro = algs.dendrogram_data(X, labels) if chosen_alg == "hierarchical" else None

    progress("profiles", "Interpreting clusters from measured feature distributions")
    profiles = profile_clusters(gdf, labels, pre.features)
    names = {p["cluster"]: p["name"] for p in profiles}
    progress("profiles", "Associating independent historical flood records (post-hoc)")
    import geopandas as gpd
    ev_path = PROCESSED_DIR / region_id / "events.parquet"
    ev = gpd.read_parquet(ev_path) if ev_path.exists() else events_mod.all_events(region)[0]
    dist = vector.districts(region)
    cpts = gpd.GeoDataFrame(geometry=gdf.representative_point().values, crs="EPSG:4326")
    dj = gpd.sjoin(cpts, dist, predicate="within", how="left")
    dj = dj[~dj.index.duplicated()]
    district_of = dj["district"].fillna("unassigned").values
    validation = validate(gdf, labels, band_labels, band_k_labels, ev, period, names=names,
                          baseline_names={b["band"]: b["name"] for b in bands}, districts=district_of)

    run_id = uuid.uuid4().hex[:12]
    dv = dataset_version(gdf, pre.features)
    model_path = MODELS_DIR / f"{run_id}.joblib"
    joblib.dump({"model": chosen.model, "features": pre.features, "scaler_center": pre.scaler_center,
                 "scaler_scale": pre.scaler_scale, "log_transformed": pre.log_transformed,
                 "params": chosen.params, "algorithm": chosen_alg}, model_path)

    probs = None
    if chosen.probabilities is not None:
        pr = chosen.probabilities
        probs = (pr.max(axis=1) if pr.ndim == 2 else pr).round(4).tolist()
    assignments = []
    for i, cid in enumerate(gdf["catchment_id"]):
        assignments.append({
            "catchment_id": cid, "cluster": int(labels[i]), "baseline_band": int(band_labels[i]),
            "probability": None if probs is None else probs[i], "pca": pca["coords"][i],
            "district": district_of[i],
        })

    result = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "region": region, "period": period,
        "feature_set": FEATURE_SETS[feature_set],
        "algorithm": chosen_alg, "algorithm_name": algs.ALGORITHMS[chosen_alg]["name"],
        "requested_algorithm": algorithm, "recommended_algorithm": recommended,
        "selected": _candidate_summary(chosen),
        "comparison": [_candidate_summary(c) for c in best.values()],
        "sweep": sweeps.get(chosen_alg, []),
        "selection_rule": algs.selection_score.__doc__.strip(),
        "preprocessing": pre.summary(),
        "correlation": pre.correlation,
        "features": [vars(FEATURE_MAP[k]) for k in pre.features],
        "assignments": assignments,
        "profiles": profiles,
        "baseline": {"bands": bands, "metrics": baseline_metrics, "same_k_metrics": baseline_k_metrics},
        "pca": {"explained_variance": pca["explained_variance"], "loadings": pca["loadings"],
                "note": "PCA is a dimensionality-reduction view of the scaled feature space; distances are not geographic."},
        "dendrogram": dendro,
        "validation": validation,
        "datasets": {**frep.get("datasets", {}), "acquisition": acq},
        "issues": frep.get("issues", []),
        "filters": frep.get("filters", {}),
        "dataset_version": dv,
        "model_path": str(model_path),
        "duration_s": round(time.time() - t0, 1),
    }
    out = PROCESSED_DIR / "runs" / f"{run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = sanitize(result)
    out.write_text(json.dumps(result, default=_json_default, allow_nan=False), encoding="utf-8")
    progress("profiles", f"Discovered {k} groups in {result['duration_s']} s")
    return result


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    return str(o)


def sanitize(o):
    """Recursively convert NaN/inf to None and NumPy scalars to Python types (strict JSON)."""
    if isinstance(o, dict):
        return {str(k): sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [sanitize(v) for v in o]
    if isinstance(o, np.ndarray):
        return sanitize(o.tolist())
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not np.isfinite(f) else f
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def persist_run(res: dict, feature_set: str, stage_log: dict | None = None) -> str:
    """Write the result JSON (with stage log) and register the run in the database."""
    from .db import Run, SessionLocal, init_db
    init_db()
    p = PROCESSED_DIR / "runs" / f"{res['run_id']}.json"
    if stage_log is not None:
        res["stage_log"] = stage_log
    p.write_text(json.dumps(res), encoding="utf-8")
    sel = res["selected"]
    with SessionLocal() as s:
        s.add(Run(id=res["run_id"], region=res["region"]["id"], period=res["period"]["id"], feature_set=feature_set,
                  algorithm=res["algorithm"], params=sel["params"], metrics=sel["metrics"],
                  features=[f["key"] for f in res["features"]], scaling="RobustScaler+log1p(skewed)",
                  dataset_version=res["dataset_version"], n_catchments=len(res["assignments"]),
                  n_clusters=sel["metrics"]["n_clusters"], silhouette=sel["metrics"].get("silhouette"),
                  result_path=str(p), model_path=res["model_path"], duration_s=res["duration_s"]))
        s.commit()
    return res["run_id"]

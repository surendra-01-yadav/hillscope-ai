"""HillScope AI — FastAPI application."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import geopandas as gpd
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from . import catalog, jobs
from .config import PERIODS, PROCESSED_DIR, REGIONS
from .db import Job, Report, Run, SessionLocal, init_db
from .features.engineering import FEATURE_MAP, FEATURE_SETS, FEATURES
from .ml.algorithms import ALGORITHMS
from .pipeline import STAGES, acquire, persist_run, run_discovery, sanitize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hillscope.api")

@asynccontextmanager
async def lifespan(_app):
    init_db()
    jobs.recover_interrupted()
    yield


app = FastAPI(title="HillScope AI", version="1.0.0", lifespan=lifespan,
              description="Unsupervised discovery of hill-catchment behaviour for flash-flood susceptibility analysis.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ schemas
class RegionPeriod(BaseModel):
    region: str
    period: str = "2001-2020"

    @field_validator("region")
    @classmethod
    def _region(cls, v):
        if v not in REGIONS:
            raise ValueError(f"unknown region '{v}'")
        return v

    @field_validator("period")
    @classmethod
    def _period(cls, v):
        if v not in PERIODS:
            raise ValueError(f"unknown period '{v}'")
        return v


class ClusterRequest(RegionPeriod):
    feature_set: str = "behavioural"
    algorithm: Literal["kmeans", "hierarchical", "dbscan", "hdbscan", "gmm", "auto"] = "kmeans"

    @field_validator("feature_set")
    @classmethod
    def _fs(cls, v):
        if v not in FEATURE_SETS:
            raise ValueError(f"unknown feature set '{v}'")
        return v


class ReportRequest(BaseModel):
    run_id: str = Field(min_length=6, max_length=32)


# ------------------------------------------------------------------ helpers
def _load_run(run_id: str) -> dict:
    with SessionLocal() as s:
        r = s.get(Run, run_id)
    if not r:
        raise HTTPException(404, f"run '{run_id}' not found")
    p = Path(r.result_path)
    if not p.exists():
        raise HTTPException(410, f"result file for run '{run_id}' is missing")
    return json.loads(p.read_text(encoding="utf-8"))


def _run_meta(r: Run) -> dict:
    return {"run_id": r.id, "region": r.region, "period": r.period, "feature_set": r.feature_set,
            "algorithm": r.algorithm, "algorithm_name": ALGORITHMS.get(r.algorithm, {}).get("name", r.algorithm),
            "params": r.params, "n_clusters": r.n_clusters, "n_catchments": r.n_catchments,
            "silhouette": r.silhouette, "dataset_version": r.dataset_version, "scaling": r.scaling,
            "features": r.features, "duration_s": r.duration_s,
            "created_at": r.created_at.isoformat() if r.created_at else None}


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/regions")
def regions():
    out = []
    for r in REGIONS.values():
        ready = (PROCESSED_DIR / r["id"] / "base_features.gpkg").exists()
        from .config import RAW_DIR
        cached = [pid for pid, p in PERIODS.items()
                  if all((RAW_DIR / "chirps" / r["id"] / f"chirps_v2_daily_p05_{y}.nc").exists() for y in range(p["start"], p["end"] + 1))]
        out.append({**r, "prepared": ready, "periods_cached": cached,
                    "periods_ready": [p for p in PERIODS if (PROCESSED_DIR / r["id"] / f"features_{p}.gpkg").exists()]})
    return {"regions": out, "periods": list(PERIODS.values()), "feature_sets": list(FEATURE_SETS.values())}


@app.get("/api/clustering/algorithms")
def algorithms():
    return {"algorithms": list(ALGORITHMS.values()) + [
        {"id": "auto", "name": "Auto-select", "family": "meta",
         "purpose": "Runs all five and picks the most defensible by internal criteria only."}]}


@app.get("/api/features")
def features():
    return {"features": [vars(f) for f in FEATURES], "feature_sets": list(FEATURE_SETS.values())}


@app.get("/api/datasets/status")
def datasets_status(region: str | None = None):
    if region and region not in REGIONS:
        raise HTTPException(404, "unknown region")
    return {"datasets": catalog.status(region)}


# ------------------------------------------------------------------ catchments
_geo_cache: dict[str, dict] = {}


@app.get("/api/catchments")
def catchments(region: str, simplify: float = Query(0.002, ge=0, le=0.05)):
    if region not in REGIONS:
        raise HTTPException(404, "unknown region")
    key = f"{region}:{simplify}"
    if key in _geo_cache:
        return _geo_cache[key]
    p = PROCESSED_DIR / region / "base_features.gpkg"
    if not p.exists():
        raise HTTPException(409, "Region not prepared yet — run data acquisition first (POST /api/data/acquire).")
    g = gpd.read_file(p)
    cols = ["catchment_id", "area_km2", "elev_mean", "elev_min", "elev_max", "slope_mean", "melton",
            "lc_tree", "lc_bare_snow", "drainage_density", "UP_AREA", "ORDER"]
    g = g[[c for c in cols if c in g.columns] + ["geometry"]].copy()
    g["geometry"] = g.geometry.simplify(simplify, preserve_topology=True)
    for c in g.columns:
        if c not in ("geometry", "catchment_id"):
            g[c] = g[c].astype(float).round(3)
    gj = sanitize(json.loads(g.to_json(drop_id=True)))
    gj["bbox"] = list(map(float, g.total_bounds))
    _geo_cache[key] = gj
    return gj


@app.get("/api/catchments/{catchment_id}")
def catchment_detail(catchment_id: str, region: str, period: str = "2001-2020", run_id: str | None = None):
    if region not in REGIONS or period not in PERIODS:
        raise HTTPException(404, "unknown region or period")
    p = PROCESSED_DIR / region / f"features_{period}.gpkg"
    if not p.exists():
        p = PROCESSED_DIR / region / "base_features.gpkg"
    if not p.exists():
        raise HTTPException(409, "Region not prepared")
    g = gpd.read_file(p)
    row = g[g["catchment_id"] == catchment_id]
    if row.empty:
        raise HTTPException(404, f"catchment {catchment_id} not found in {region}")
    rec = row.drop(columns="geometry").iloc[0].to_dict()
    feats = []
    for k, v in rec.items():
        if k in FEATURE_MAP and v is not None and not (isinstance(v, float) and np.isnan(v)):
            pct = float((g[k] <= v).mean())
            f = FEATURE_MAP[k]
            feats.append({**vars(f), "value": round(float(v), 4), "percentile": round(pct, 3)})
    out = {"catchment_id": catchment_id, "region": region, "period": period, "features": feats,
           "centroid": list(row.geometry.iloc[0].representative_point().coords[0])}
    if run_id:
        res = _load_run(run_id)
        a = next((x for x in res["assignments"] if x["catchment_id"] == catchment_id), None)
        if a:
            prof = next((p for p in res["profiles"] if p["cluster"] == a["cluster"]), None)
            out["assignment"] = {**a, "profile_name": prof["name"] if prof else None,
                                 "profile_summary": prof["summary"] if prof else None}
            counts = res["validation"]["windows"].get("concurrent", {}).get("all", {}).get("counts")
            idx = res["assignments"].index(a)
            out["recorded_events_concurrent"] = counts[idx] if counts else None
    return sanitize(out)


@app.get("/api/events")
def events(region: str, precision: str = "district,regional,state-wide"):
    if region not in REGIONS:
        raise HTTPException(404, "unknown region")
    p = PROCESSED_DIR / region / "events.parquet"
    if not p.exists():
        raise HTTPException(409, "Events not acquired yet")
    e = gpd.read_parquet(p)
    e = e[e["spatial_precision"].isin(precision.split(",")) & e.geometry.notna()].copy()
    e["geometry"] = e.geometry.simplify(0.01, preserve_topology=True)
    e["start_date"] = e["start_date"].astype(str)
    e["end_date"] = e["end_date"].astype(str)
    e["year"] = e["start_date"].str[:4]
    pts = e.copy()
    pts["geometry"] = e.geometry.representative_point()
    keep = ["event_id", "source", "start_date", "end_date", "year", "cause", "flash_type", "districts",
            "description", "spatial_precision", "source_confidence", "fatalities", "geometry"]
    return {"footprints": sanitize(json.loads(e[keep].to_json(drop_id=True))),
            "points": sanitize(json.loads(pts[keep].to_json(drop_id=True)))}


@app.get("/api/events/districts")
def events_by_district(region: str, start: int = 2001, end: int = 2023, flash_only: bool = False):
    """District-located IFI event counts as map points (district representative point)."""
    if region not in REGIONS:
        raise HTTPException(404, "unknown region")
    p = PROCESSED_DIR / region / "events.parquet"
    if not p.exists():
        raise HTTPException(409, "Events not acquired yet")
    from .data.vector import districts as get_districts
    from .validation.historical import filter_events
    e = filter_events(gpd.read_parquet(p), start, end, flash_only=flash_only, precisions=("district",))
    d = get_districts(REGIONS[region])
    feats = []
    for _, row in d.iterrows():
        mine = e[e["districts"].str.split(", ").map(lambda xs, n=row["district"]: n in xs)]
        if len(mine):
            pt = row.geometry.representative_point()
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [pt.x, pt.y]},
                          "properties": {"district": row["district"], "count": int(len(mine)),
                                         "flash": int(mine["flash_type"].astype(bool).sum())}})
    return {"type": "FeatureCollection", "features": feats}


# ------------------------------------------------------------------ jobs
@app.post("/api/data/acquire", status_code=202)
def data_acquire(req: RegionPeriod):
    region, period = REGIONS[req.region], PERIODS[req.period]

    def work(ctx):
        acquire(region, period, ctx.progress)
        from .features.engineering import build_base
        build_base(region, lambda m: ctx.progress("prepare", m))
        return None

    jid = jobs.submit("acquire", req.model_dump(), STAGES[:2], work)
    return {"job_id": jid}


@app.post("/api/features/extract", status_code=202)
def features_extract(req: RegionPeriod):
    region, period = REGIONS[req.region], PERIODS[req.period]

    def work(ctx):
        from .features.engineering import build_features
        acquire(region, period, ctx.progress)
        build_features(region, period, lambda m: ctx.progress("features", m))
        return None

    jid = jobs.submit("features", req.model_dump(), STAGES[:3], work)
    return {"job_id": jid}


@app.post("/api/clustering/run", status_code=202)
def clustering_run(req: ClusterRequest):
    def work(ctx):
        res = run_discovery(req.region, req.period, req.feature_set, req.algorithm, ctx.progress)
        return persist_run(res, req.feature_set, ctx.finish_all())

    jid = jobs.submit("clustering", req.model_dump(), STAGES, work)
    return {"job_id": jid}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with SessionLocal() as s:
        j = s.get(Job, job_id)
        if not j:
            raise HTTPException(404, "job not found")
        return jobs.job_dict(j)


# ------------------------------------------------------------------ results
@app.get("/api/clustering/results/{run_id}")
def clustering_result(run_id: str):
    return _load_run(run_id)


@app.get("/api/clusters/{cluster_id}")
def cluster_detail(cluster_id: int, run_id: str):
    res = _load_run(run_id)
    prof = next((p for p in res["profiles"] if p["cluster"] == cluster_id), None)
    if prof is None:
        raise HTTPException(404, f"cluster {cluster_id} not in run {run_id}")
    members = [a["catchment_id"] for a in res["assignments"] if a["cluster"] == cluster_id]
    val = {}
    for w, d in res["validation"]["windows"].items():
        val[w] = {t: next((g for g in d[t]["clusters"]["groups"] if g["group"] == cluster_id), None) for t in ("all", "flash")}
    return {"run_id": run_id, "profile": prof, "members": members, "validation": val}


@app.get("/api/validation/historical")
def validation_historical(run_id: str, window: Literal["concurrent", "out_of_period"] = "concurrent",
                          event_type: Literal["all", "flash"] = "all"):
    res = _load_run(run_id)
    w = res["validation"]["windows"].get(window)
    if not w:
        raise HTTPException(404, f"window {window} not available for this period")
    d = {k: v for k, v in w[event_type].items() if k != "counts"}
    return {"run_id": run_id, "window": window, "years": w["years"], "event_type": event_type, **d,
            "notes": res["validation"]["notes"]}


@app.get("/api/validation/baseline")
def validation_baseline(run_id: str):
    res = _load_run(run_id)
    w = res["validation"]["windows"]
    assoc = {win: {t: {"clusters": w[win][t]["clusters"]["epsilon_squared"],
                       "baseline": w[win][t]["baseline"]["epsilon_squared"],
                       "baseline_same_k": w[win][t]["baseline_same_k"]["epsilon_squared"]}
                   for t in ("all", "flash")} for win in w}
    return {"run_id": run_id, "bands": res["baseline"]["bands"],
            "internal": {"clusters": res["selected"]["metrics"], "baseline": res["baseline"]["metrics"],
                         "baseline_same_k": res["baseline"]["same_k_metrics"]},
            "event_association": assoc}


@app.get("/api/experiments")
def experiments(region: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    with SessionLocal() as s:
        q = s.query(Run)
        if region:
            q = q.filter(Run.region == region)
        total = q.count()
        rows = q.order_by(Run.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [_run_meta(r) for r in rows]}


# ------------------------------------------------------------------ reports
@app.post("/api/reports/generate", status_code=201)
def report_generate(req: ReportRequest):
    from .reports.pdf import build_report
    res = _load_run(req.run_id)
    rid, path, pages = build_report(res)
    with SessionLocal() as s:
        s.add(Report(id=rid, run_id=req.run_id, path=str(path), pages=pages))
        s.commit()
    return {"report_id": rid, "run_id": req.run_id, "pages": pages, "url": f"/api/reports/{rid}"}


@app.get("/api/reports")
def reports_list(run_id: str | None = None):
    with SessionLocal() as s:
        q = s.query(Report)
        if run_id:
            q = q.filter(Report.run_id == run_id)
        rows = q.order_by(Report.created_at.desc()).limit(50).all()
    return {"items": [{"report_id": r.id, "run_id": r.run_id, "pages": r.pages, "url": f"/api/reports/{r.id}",
                       "created_at": r.created_at.isoformat()} for r in rows]}


@app.get("/api/reports/{report_id}")
def report_get(report_id: str):
    with SessionLocal() as s:
        r = s.get(Report, report_id)
    if not r or not Path(r.path).exists():
        raise HTTPException(404, "report not found")
    return FileResponse(r.path, media_type="application/pdf", filename=f"hillscope_report_{r.run_id}.pdf")

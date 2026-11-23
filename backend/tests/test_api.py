"""API contract tests: validation errors, metadata endpoints, job lifecycle, and (with cached real data) results + reports."""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from conftest import has_real

client = TestClient(app)
client.__enter__()  # run startup (DB init)


def test_health_and_meta():
    assert client.get("/api/health").json() == {"status": "ok"}
    r = client.get("/api/regions").json()
    assert {x["id"] for x in r["regions"]} == {"uttarakhand", "himachal"}
    assert {p["id"] for p in r["periods"]} >= {"2001-2020"}
    algs = {a["id"] for a in client.get("/api/clustering/algorithms").json()["algorithms"]}
    assert algs == {"kmeans", "hierarchical", "dbscan", "hdbscan", "gmm", "auto"}
    feats = client.get("/api/features").json()["features"]
    assert all(f["nature"] in {"observed", "remotely sensed", "model-derived", "estimated"} for f in feats)


def test_dataset_status_reports_missing_discharge():
    ds = {d["id"]: d for d in client.get("/api/datasets/status").json()["datasets"]}
    assert ds["discharge"]["status"] == "unavailable"
    assert all("nature" in d and "license" in d for d in ds.values())


@pytest.mark.parametrize("payload", [
    {"region": "atlantis", "period": "2001-2020"},
    {"region": "uttarakhand", "period": "1900-1901"},
    {"region": "uttarakhand", "period": "2001-2020", "algorithm": "xgboost"},
    {"region": "uttarakhand", "period": "2001-2020", "feature_set": "nope"},
])
def test_invalid_clustering_input_rejected(payload):
    assert client.post("/api/clustering/run", json=payload).status_code == 422


def test_not_found_paths():
    assert client.get("/api/jobs/doesnotexist").status_code == 404
    assert client.get("/api/clustering/results/doesnotexist").status_code == 404
    assert client.get("/api/catchments?region=atlantis").status_code == 404
    assert client.post("/api/reports/generate", json={"run_id": "doesnotexist"}).status_code == 404
    assert client.get("/api/reports/doesnotexist").status_code == 404


def test_experiments_pagination_shape():
    r = client.get("/api/experiments?page=1&page_size=5").json()
    assert set(r) == {"total", "page", "page_size", "items"}
    assert client.get("/api/experiments?page=0").status_code == 422


def test_failed_job_is_reported(monkeypatch):
    """A processing failure must surface as a failed job with its error, not be hidden."""
    import app.main as m

    def boom(*a, **k):
        raise RuntimeError("provider exploded")
    monkeypatch.setattr(m, "run_discovery", boom)
    jid = client.post("/api/clustering/run", json={"region": "uttarakhand", "period": "2001-2020", "algorithm": "kmeans"}).json()["job_id"]
    for _ in range(50):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert j["status"] == "failed" and "provider exploded" in j["error"]


@pytest.mark.realdata
def test_catchments_geojson_real():
    if not has_real("uttarakhand"):
        pytest.skip("real data not cached")
    gj = client.get("/api/catchments?region=uttarakhand").json()
    assert gj["type"] == "FeatureCollection" and len(gj["features"]) > 100
    p = gj["features"][0]["properties"]
    assert {"catchment_id", "elev_mean", "area_km2"} <= set(p)
    cid = p["catchment_id"]
    d = client.get(f"/api/catchments/{cid}?region=uttarakhand").json()
    assert d["catchment_id"] == cid and d["features"]
    assert client.get("/api/catchments/000?region=uttarakhand").status_code == 404


@pytest.mark.realdata
def test_end_to_end_run_validation_and_report():
    """Full workflow on real cached data: clustering job -> results -> cluster -> validation -> baseline -> PDF."""
    period = "2001-2020"
    if not has_real("uttarakhand", period):
        pytest.skip("real CHIRPS 2001-2020 not cached")
    jid = client.post("/api/clustering/run", json={"region": "uttarakhand", "period": period,
                                                   "feature_set": "behavioural", "algorithm": "kmeans"}).json()["job_id"]
    t0 = time.time()
    while time.time() - t0 < 1500:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(1)
    assert j["status"] == "done", j.get("error")
    assert [s["status"] for s in j["stages"].values()] == ["done"] * 6
    run_id = j["result_id"]
    res = client.get(f"/api/clustering/results/{run_id}").json()
    k = res["selected"]["metrics"]["n_clusters"]
    assert k >= 2 and len(res["profiles"]) >= k
    assert res["selected"]["metrics"]["silhouette"] is not None
    assert {c["algorithm"] for c in res["comparison"]} >= {"kmeans", "hierarchical", "gmm"}
    assert res["datasets"]["discharge"]["status"] == "unavailable"
    c = client.get(f"/api/clusters/0?run_id={run_id}").json()
    assert c["members"] and c["profile"]["name"]
    v = client.get(f"/api/validation/historical?run_id={run_id}").json()
    assert v["n_events"] > 0 and v["clusters"]["groups"]
    b = client.get(f"/api/validation/baseline?run_id={run_id}").json()
    assert len(b["bands"]) == 3
    r = client.post("/api/reports/generate", json={"run_id": run_id})
    assert r.status_code == 201 and r.json()["pages"] >= 3
    pdf = client.get(r.json()["url"])
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"
    exps = client.get("/api/experiments?region=uttarakhand").json()
    assert any(e["run_id"] == run_id for e in exps["items"])

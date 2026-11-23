"""Data-pipeline unit tests (geometry, rainfall indices, zonal stats, validation logic) and real-data integrity checks."""
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from app.config import REGIONS
from app.data.raster import slope_degrees, zonal
from app.data.rainfall import weight_matrix
from app.data.vector import norm_name
from app.features.engineering import FEATURE_MAP, FEATURE_SETS, feature_keys, rainfall_features, shape_features
from app.validation.historical import catchment_event_counts, filter_events, group_association
from conftest import REAL_DATA, has_real


def test_norm_name_folds_diacritics():
    assert norm_name("Uttarākhand") == "uttarakhand"
    assert norm_name("Lahul & Spiti") == "lahulspiti"


def test_rainfall_indices_known_series():
    idx = pd.date_range("2001-01-01", "2002-12-31", freq="D")
    s = pd.Series(0.0, index=idx)
    s["2001-07-10"] = 100.0
    s["2001-07-11"] = 20.0
    s["2001-07-05"] = 10.0  # inside 7-day antecedent window of 2001 max
    s["2002-08-01"] = 60.0
    f = rainfall_features(pd.DataFrame({"c1": s})).loc["c1"]
    assert f["rx1day"] == pytest.approx(80.0)  # median of 100 and 60
    assert f["rx3day"] == pytest.approx((120 + 60) / 2)
    assert f["r50_days"] == pytest.approx(1.0)  # one >=50mm day per year
    assert f["monsoon_share"] == pytest.approx(1.0)
    assert f["api7_before_max"] == pytest.approx((10 + 0) / 2)  # 2001: 10 mm before; 2002: 0
    assert 0 < f["pci"] <= 100


def test_antecedent_rainfall_has_no_lookahead():
    idx = pd.date_range("2001-01-01", "2001-12-31", freq="D")
    s = pd.Series(0.0, index=idx)
    s["2001-06-01"] = 90.0
    s["2001-06-02"] = 50.0  # after the max: must not count as antecedent
    f = rainfall_features(pd.DataFrame({"c": s})).loc["c"]
    assert f["api7_before_max"] == 0.0


def test_shape_features_circle_vs_strip():
    g = gpd.GeoDataFrame(geometry=[Point(78, 30).buffer(0.1), box(78, 30, 78.6, 30.02)], crs="EPSG:4326")
    sf = shape_features(g)
    assert sf["compactness"].iloc[0] == pytest.approx(1.0, abs=0.05)
    assert sf["compactness"].iloc[1] > 2
    assert sf["elongation"].iloc[0] > sf["elongation"].iloc[1]


def test_zonal_statistics():
    vals = np.array([[1, 2], [3, np.nan]], dtype=float)
    zones = np.array([[1, 1], [2, 2]])
    z = zonal(vals, zones, 2)
    assert z["mean"].tolist() == [1.5, 3.0]
    assert z["count"].tolist() == [2, 1]


def test_slope_flat_and_ramp():
    from rasterio.transform import from_origin
    tr = from_origin(78, 31, 1 / 1200, 1 / 1200)
    flat = np.full((20, 20), 1000.0)
    assert np.nanmax(slope_degrees(flat, tr, -32767)) == pytest.approx(0)
    dx = 111_320 * np.cos(np.radians(31)) / 1200
    ramp = np.tile(np.arange(20) * dx, (20, 1))  # 1:1 rise over run -> 45°
    assert np.nanmedian(slope_degrees(ramp, tr, -32767)) == pytest.approx(45, abs=1.0)


def test_weight_matrix_rows_sum_to_one():
    xs = np.arange(78.025, 78.5, 0.05)
    ys = np.arange(30.475, 30.0, -0.05)
    g = gpd.GeoDataFrame(geometry=[box(78.0, 30.0, 78.2, 30.2), box(78.31, 30.31, 78.312, 30.312)], crs="EPSG:4326")
    W = weight_matrix(g, xs, ys)
    assert np.allclose(np.asarray(W.sum(axis=1)).ravel(), 1.0)


def test_feature_sets_are_consistent():
    for fs in FEATURE_SETS:
        keys = feature_keys(fs, list(FEATURE_MAP))
        assert keys and len(keys) == len(set(keys))
    assert all(f.nature == "estimated" for f in FEATURE_MAP.values() if f.group == "response_proxy")


def test_event_association_and_filters():
    cat = gpd.GeoDataFrame({"catchment_id": ["a", "b", "c"]},
                           geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(5, 5, 6, 6)], crs="EPSG:4326")
    ev = gpd.GeoDataFrame({
        "event_id": ["e1", "e2", "e3"], "start_date": pd.to_datetime(["2005-07-01", "2010-08-01", "1990-01-01"]),
        "spatial_precision": ["district", "district", "district"], "flash_type": [True, False, False],
    }, geometry=[box(-1, -1, 2.5, 2), box(0, 0, 1.2, 1.2), box(-10, -10, 10, 10)], crs="EPSG:4326")
    f = filter_events(ev, 2001, 2020)
    assert set(f["event_id"]) == {"e1", "e2"}  # e3 outside window
    assert set(filter_events(ev, 2001, 2020, flash_only=True)["event_id"]) == {"e1"}
    counts, pairs = catchment_event_counts(cat, f)
    assert counts.tolist() == [2, 1, 0]
    res = group_association(np.array([0, 0, 1]), counts, pairs, 20)
    g0 = res["groups"][0]
    assert g0["n_events"] == 2 and g0["catchments_with_events"] == 2 and g0["association_rate"] == 1.0
    assert res["groups"][1]["association_rate"] == 0.0


# ----------------------------------------------------------------- real data integrity
@pytest.mark.realdata
@pytest.mark.parametrize("region", list(REGIONS))
def test_real_catchments_schema_crs_and_bounds(region):
    if not has_real(region):
        pytest.skip("real data not cached")
    g = gpd.read_file(REAL_DATA / region / "base_features.gpkg")
    assert g.crs.to_epsg() == 4326
    assert g["catchment_id"].is_unique  # duplicate detection
    assert g.geometry.is_valid.all()
    x0, y0, x1, y1 = REGIONS[region]["bbox"]
    b = g.total_bounds
    assert b[0] >= x0 - 0.5 and b[2] <= x1 + 0.5 and b[1] >= y0 - 0.5 and b[3] <= y1 + 0.5  # spatial coverage
    assert (g["elev_mean"] >= REGIONS[region]["min_mean_elev_m"]).all()
    assert g["elev_max"].max() < 8900 and g["elev_min"].min() > -50  # unit sanity (metres)
    assert g["slope_mean"].between(0, 90).all()
    # SUB_AREA (km², HydroBASINS) agrees with equal-area geometry area
    assert np.median(np.abs(g["area_km2"] / g["geom_area_km2"] - 1)) < 0.05
    lc = g[["lc_tree", "lc_grass", "lc_crop", "lc_built", "lc_bare_snow", "lc_water"]].sum(axis=1)
    assert lc.between(0.9, 1.01).mean() > 0.95  # fractions sum to ~1


@pytest.mark.realdata
@pytest.mark.parametrize("region", list(REGIONS))
def test_real_events_have_dates_and_sources(region):
    p = REAL_DATA / region / "events.parquet"
    if not p.exists():
        pytest.skip("events not cached")
    e = gpd.read_parquet(p)
    assert e["event_id"].is_unique
    assert e["source"].notna().all()
    assert e["start_date"].notna().mean() > 0.95
    assert set(e["spatial_precision"]) <= {"district", "state", "state-wide", "regional"}


@pytest.mark.realdata
def test_real_chirps_temporal_coverage_and_units():
    p = REAL_DATA / "uttarakhand"
    files = sorted(p.glob("chirps_catchment_daily_*.parquet"))
    if not files:
        pytest.skip("CHIRPS catchment series not cached")
    d = pd.read_parquet(files[0])
    start, end = (int(x) for x in files[0].stem.split("_")[-2:])
    assert d.index.min() == pd.Timestamp(f"{start}-01-01") and d.index.max() == pd.Timestamp(f"{end}-12-31")
    assert d.index.is_unique and d.index.is_monotonic_increasing
    assert len(d) == len(pd.date_range(f"{start}-01-01", f"{end}-12-31"))
    assert np.nanmin(d.values) >= 0 and np.nanmax(d.values) < 1000  # mm/day plausibility
    assert np.isnan(d.values).mean() < 0.01

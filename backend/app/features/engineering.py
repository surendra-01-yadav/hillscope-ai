"""Catchment feature engineering from real datasets.

Every feature carries metadata: group, unit, data nature (observed /
remotely sensed / model-derived / estimated) and a plain-language definition.
Hydrological-response features from measured discharge are NOT produced
because no openly accessible gauged discharge exists for these catchments;
the "response proxy" group is explicitly marked *estimated*.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd

from ..config import PROCESSED_DIR
from ..data import raster, rainfall, vector
from ..data.common import DataUnavailable

log = logging.getLogger("hillscope.features")
EQUAL_AREA = "EPSG:6933"  # WGS84 / NSIDC EASE-Grid 2.0 Global (equal-area)


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    group: str  # terrain | rainfall | surface | response_proxy
    unit: str
    nature: str  # observed | remotely sensed | model-derived | estimated
    description: str


FEATURES: list[Feature] = [
    # terrain / geography
    Feature("area_km2", "Catchment area", "terrain", "km²", "remotely sensed", "HydroBASINS level-12 sub-basin area"),
    Feature("elev_mean", "Mean elevation", "terrain", "m", "remotely sensed", "Mean of Copernicus GLO-90 DEM"),
    Feature("elev_range", "Elevation range", "terrain", "m", "remotely sensed", "Max − min DEM elevation"),
    Feature("slope_mean", "Mean slope", "terrain", "°", "remotely sensed", "Mean terrain slope from DEM"),
    Feature("slope_std", "Slope variability", "terrain", "°", "remotely sensed", "Std. dev. of slope (terrain heterogeneity)"),
    Feature("steep_frac", "Steep terrain share", "terrain", "fraction", "remotely sensed", "Share of area with slope > 30°"),
    Feature("melton", "Melton ruggedness", "terrain", "–", "remotely sensed", "Relief (km) / √area (km²); high values typify flashy, debris-prone basins"),
    Feature("hypsometric", "Hypsometric integral", "terrain", "–", "remotely sensed", "(mean − min)/(max − min) elevation"),
    Feature("drainage_density", "Drainage density", "terrain", "km/km²", "remotely sensed", "HydroRIVERS length (≥10 km² upstream) per area — coarse network proxy"),
    Feature("compactness", "Gravelius compactness", "terrain", "–", "remotely sensed", "Perimeter / circumference of equal-area circle (1 = circular)"),
    Feature("elongation", "Elongation ratio", "terrain", "–", "remotely sensed", "Equal-area circle diameter / longest axis (1 = compact)"),
    # rainfall (CHIRPS)
    Feature("rain_annual", "Mean annual rainfall", "rainfall", "mm/yr", "observed", "CHIRPS v2.0 catchment-mean annual total"),
    Feature("rain_daily_mean", "Mean daily rainfall", "rainfall", "mm/day", "observed", "Mean of all days"),
    Feature("rx1day", "Max 1-day rainfall", "rainfall", "mm", "observed", "Median of annual maximum 1-day totals (ETCCDI Rx1day)"),
    Feature("rx3day", "Max 3-day rainfall", "rainfall", "mm", "observed", "Median of annual maximum 3-day totals"),
    Feature("rx7day", "Max 7-day rainfall", "rainfall", "mm", "observed", "Median of annual maximum 7-day totals"),
    Feature("sdii", "Rainfall intensity", "rainfall", "mm/wet day", "observed", "Simple daily intensity index: total on wet days (≥1 mm) / wet days"),
    Feature("r50_days", "Heavy-rain days", "rainfall", "days/yr", "observed", "Days per year with ≥ 50 mm"),
    Feature("wet_cv", "Daily rainfall variability", "rainfall", "–", "observed", "Coefficient of variation of wet-day rainfall"),
    Feature("annual_cv", "Inter-annual variability", "rainfall", "–", "observed", "CV of annual totals"),
    Feature("api7_before_max", "Antecedent rainfall", "rainfall", "mm", "observed", "Mean 7-day rainfall preceding each annual-maximum day"),
    Feature("pci", "Rainfall concentration", "rainfall", "%", "observed", "Precipitation Concentration Index of monthly totals (Oliver 1980)"),
    Feature("monsoon_share", "Monsoon share", "rainfall", "fraction", "observed", "Share of annual rainfall in June–September"),
    # ERA5-Land enrichment (optional)
    Feature("era5_p_hourly_p99", "Hourly intensity (P99)", "rainfall", "mm/h", "model-derived", "ERA5 hourly precipitation, 99th pct. of wet hours, JJAS (0.25° reanalysis)"),
    Feature("era5_hourly_concentration", "Sub-daily concentration", "rainfall", "fraction", "model-derived", "Mean share of a wet day's rain falling in its peak hour (ERA5 hourly)"),
    Feature("era5_soil_moisture_mean", "Soil moisture (monsoon)", "surface", "m³/m³", "model-derived", "ERA5-Land 0–7 cm soil moisture, JJAS mean"),
    # surface: land cover & soil
    Feature("lc_tree", "Tree cover", "surface", "fraction", "remotely sensed", "ESA WorldCover 2021 tree cover share"),
    Feature("lc_grass", "Grass/shrub/moss", "surface", "fraction", "remotely sensed", "WorldCover grassland + shrub + moss/lichen"),
    Feature("lc_crop", "Cropland", "surface", "fraction", "remotely sensed", "WorldCover cropland share"),
    Feature("lc_built", "Built-up", "surface", "fraction", "remotely sensed", "WorldCover built-up share"),
    Feature("lc_bare_snow", "Bare rock / snow / ice", "surface", "fraction", "remotely sensed", "WorldCover bare/sparse + snow & ice"),
    Feature("soil_clay", "Topsoil clay", "surface", "%", "model-derived", "SoilGrids 2.0 clay 0–5 cm (infiltration-related proxy, not measured infiltration)"),
    Feature("soil_sand", "Topsoil sand", "surface", "%", "model-derived", "SoilGrids 2.0 sand 0–5 cm (infiltration-related proxy)"),
    Feature("soil_soc", "Soil organic carbon", "surface", "g/kg", "model-derived", "SoilGrids 2.0 SOC 0–5 cm"),
    # estimated response proxies (NOT observed discharge)
    Feature("tc_kirpich_h", "Time of concentration (est.)", "response_proxy", "h", "estimated",
            "Kirpich formula with Hack's-law flow length — a terrain-based estimate, NOT measured lag"),
    Feature("flashiness_proxy", "Rapid-response proxy", "response_proxy", "mm/h", "estimated",
            "Rx1day / time of concentration — rainfall supply relative to estimated travel time; NOT discharge"),
]
FEATURE_MAP = {f.key: f for f in FEATURES}

FEATURE_SETS: dict[str, dict] = {
    "behavioural": {
        "id": "behavioural", "label": "Full behavioural",
        "description": "Terrain + rainfall regime + land surface + estimated response proxies",
        "groups": ["terrain", "rainfall", "surface", "response_proxy"],
    },
    "rain_terrain": {
        "id": "rain_terrain", "label": "Rainfall + terrain",
        "description": "Rainfall regime and terrain form only",
        "groups": ["terrain", "rainfall"],
    },
    "rain_response": {
        "id": "rain_response", "label": "Rainfall response",
        "description": "Rainfall extremes, concentration and estimated response proxies",
        "groups": ["rainfall", "response_proxy"],
        "extra": ["slope_mean", "melton"],
    },
}


def feature_keys(feature_set: str, available: list[str]) -> list[str]:
    fs = FEATURE_SETS[feature_set]
    keys = [f.key for f in FEATURES if f.group in fs["groups"]] + fs.get("extra", [])
    seen, out = set(), []
    for k in keys:
        if k in available and k not in seen:
            seen.add(k)
            out.append(k)
    return out


# ------------------------------------------------------------------ geometry
def shape_features(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    ea = gdf.to_crs(EQUAL_AREA)
    area = ea.area / 1e6
    perim = ea.length / 1e3
    mrr = ea.geometry.minimum_rotated_rectangle()
    def longest(geom):
        xs, ys = geom.exterior.coords.xy
        d = [np.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(len(xs) - 1)]
        return max(d) / 1e3 if d else np.nan
    L = mrr.map(longest)
    return pd.DataFrame({
        "geom_area_km2": area.values,
        "compactness": (perim / (2 * np.sqrt(np.pi * area))).values,
        "elongation": ((2 * np.sqrt(area / np.pi)) / L).values,
    }, index=gdf.index)


def drainage_density(gdf: gpd.GeoDataFrame, rivers: gpd.GeoDataFrame) -> np.ndarray:
    ea_c = gdf[["catchment_id", "geometry"]].to_crs(EQUAL_AREA)
    ea_r = rivers[["geometry"]].to_crs(EQUAL_AREA)
    inter = gpd.overlay(ea_r, ea_c, how="intersection", keep_geom_type=True)
    length = inter.assign(L=inter.length / 1e3).groupby("catchment_id")["L"].sum()
    area = ea_c.set_index("catchment_id").area / 1e6
    return (length.reindex(area.index).fillna(0.0) / area).values


# ------------------------------------------------------------------ rainfall
def rainfall_features(daily: pd.DataFrame) -> pd.DataFrame:
    """ETCCDI-style rainfall indices per catchment column; uses only the selected period."""
    d = daily
    years = d.index.year
    annual = d.groupby(years).sum(min_count=300)
    out = pd.DataFrame(index=d.columns)
    out["rain_annual"] = annual.mean()
    out["annual_cv"] = annual.std() / annual.mean()
    out["rain_daily_mean"] = d.mean()
    for w, key in ((1, "rx1day"), (3, "rx3day"), (7, "rx7day")):
        roll = d.rolling(w, min_periods=w).sum() if w > 1 else d
        out[key] = roll.groupby(years).max().median()
    wet = d.where(d >= 1.0)
    out["sdii"] = wet.mean()
    out["wet_cv"] = wet.std() / wet.mean()
    out["r50_days"] = (d >= 50).groupby(years).sum().mean()
    monthly = d.resample("MS").sum(min_count=25)
    mclim = monthly.groupby(monthly.index.month).mean()
    out["pci"] = 100 * (mclim**2).sum() / (mclim.sum() ** 2)
    out["monsoon_share"] = mclim.loc[[6, 7, 8, 9]].sum() / mclim.sum()
    # Antecedent 7-day rainfall before each year's maximum day (strictly prior days: no look-ahead).
    prior7 = d.shift(1).rolling(7, min_periods=7).sum()
    api = {}
    for c in d.columns:
        s = d[c]
        idx = s.groupby(years).idxmax().dropna()
        api[c] = prior7[c].reindex(idx.values).mean()
    out["api7_before_max"] = pd.Series(api)
    return out


# ------------------------------------------------------------------ assembly
def build_features(region: dict, period: dict, progress=None, include_era5: bool = True) -> tuple[gpd.GeoDataFrame, dict]:
    """Assemble the per-catchment feature table. Returns (GeoDataFrame, provenance report)."""
    cache = PROCESSED_DIR / region["id"] / f"features_{period['id']}.gpkg"
    report_path = cache.with_suffix(".json")
    if cache.exists() and report_path.exists():
        import json
        return gpd.read_file(cache), json.loads(report_path.read_text(encoding="utf-8"))

    g, report = build_base(region, progress)
    report = {**report, "period": period["id"]}
    return _add_period_features(g, report, region, period, cache, report_path, progress, include_era5)


def build_base(region: dict, progress=None) -> tuple[gpd.GeoDataFrame, dict]:
    """Period-independent features (terrain, network, land cover, soil), cached per region."""
    import json
    cache = PROCESSED_DIR / region["id"] / "base_features.gpkg"
    rp = cache.with_suffix(".json")
    if cache.exists() and rp.exists():
        return gpd.read_file(cache), json.loads(rp.read_text(encoding="utf-8"))
    report: dict = {"region": region["id"], "datasets": {}, "issues": [], "filters": {}}
    g = vector.catchments(region, progress)
    n0 = len(g)
    if progress:
        progress(f"Prepared {n0} HydroBASINS level-12 catchments")
    sh = shape_features(g)
    g = g.join(sh)
    g["area_km2"] = g["SUB_AREA"].astype(float)

    terr = pd.DataFrame(raster.terrain_stats(g, region, progress), index=g.index)
    g = g.join(terr)
    g["elev_range"] = g["elev_max"] - g["elev_min"]
    g["melton"] = (g["elev_range"] / 1000.0) / np.sqrt(g["area_km2"])
    g["hypsometric"] = (g["elev_mean"] - g["elev_min"]) / g["elev_range"].replace(0, np.nan)
    report["datasets"]["copernicus_dem"] = {"status": "ok", "nature": "remotely sensed"}

    try:
        rv = vector.rivers(region, progress)
        g["drainage_density"] = drainage_density(g, rv)
        report["datasets"]["hydrorivers"] = {"status": "ok", "nature": "remotely sensed"}
    except DataUnavailable as e:
        report["issues"].append({"dataset": "hydrorivers", "message": e.message})

    try:
        lc = pd.DataFrame(raster.worldcover_fractions(g, region, progress), index=g.index)
        g["lc_tree"] = lc["lc_tree"]
        g["lc_grass"] = lc["lc_grass"] + lc["lc_shrub"] + lc["lc_moss"]
        g["lc_crop"] = lc["lc_crop"]
        g["lc_built"] = lc["lc_built"]
        g["lc_bare_snow"] = lc["lc_bare"] + lc["lc_snow_ice"]
        g["lc_water"] = lc["lc_water"]
        report["datasets"]["worldcover"] = {"status": "ok", "nature": "remotely sensed"}
    except DataUnavailable as e:
        report["issues"].append({"dataset": "worldcover", "message": e.message})

    try:
        sg = pd.DataFrame(raster.soilgrids_stats(g, region, progress), index=g.index)
        g = g.join(sg)
        report["datasets"]["soilgrids"] = {"status": "ok", "nature": "model-derived"}
    except DataUnavailable as e:
        report["issues"].append({"dataset": "soilgrids", "message": e.message})

    # --- hill filter & sliver removal (documented in METHODOLOGY.md)
    keep = (g["elev_mean"] >= region["min_mean_elev_m"]) & (g["area_km2"] >= 10.0) & (g["dem_pixels"] > 50)
    report["filters"] = {
        "initial_catchments": int(n0),
        "below_hill_threshold": int((g["elev_mean"] < region["min_mean_elev_m"]).sum()),
        "slivers_lt_10km2": int((g["area_km2"] < 10.0).sum()),
        "retained": int(keep.sum()),
        "hill_threshold_m": region["min_mean_elev_m"],
    }
    g = g[keep].reset_index(drop=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    g.to_file(cache, driver="GPKG")
    rp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return g, report


def _add_period_features(g, report, region, period, cache, report_path, progress, include_era5):
    daily = rainfall.catchment_daily(g, region, period["start"], period["end"], progress)
    if progress:
        progress("Extracting rainfall regime indices")
    rf = rainfall_features(daily).reindex(g["catchment_id"])
    rf.index = g.index
    g = g.join(rf)
    report["datasets"]["chirps"] = {
        "status": "ok", "nature": "observed + remotely sensed",
        "days": int(len(daily)), "missing_fraction": float(np.isnan(daily.values).mean()),
        "start": str(daily.index.min().date()), "end": str(daily.index.max().date()),
    }
    if include_era5:
        try:
            e5 = rainfall.era5_features(g, region, progress)
            g = g.join(e5[["era5_p_hourly_p99", "era5_hourly_concentration", "era5_soil_moisture_mean"]])
            report["datasets"]["era5land"] = {"status": "ok", "nature": "model-derived"}
        except DataUnavailable as e:
            report["issues"].append({"dataset": "era5land", "message": e.message})
            report["datasets"]["era5land"] = {"status": "unavailable", "message": e.message}

    # --- estimated response proxies (Kirpich with Hack's-law flow length)
    L_km = 1.4 * g["area_km2"] ** 0.6  # Hack (1957), L in km for A in km²
    S = (g["elev_range"] / (L_km * 1000.0)).clip(lower=1e-3)
    g["tc_kirpich_h"] = 0.0195 * (L_km * 1000.0) ** 0.77 * S ** (-0.385) / 60.0
    g["flashiness_proxy"] = g["rx1day"] / g["tc_kirpich_h"]

    report["datasets"]["discharge"] = {
        "status": "unavailable",
        "message": "No openly accessible gauged discharge for these catchments (India-WRIS/CWC data are restricted; "
                   "GRDC requires a data request). Hydrological response is represented only by estimated proxies.",
    }
    report["n_catchments"] = int(len(g))
    cache.parent.mkdir(parents=True, exist_ok=True)
    g.to_file(cache, driver="GPKG")
    import json
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return g, report

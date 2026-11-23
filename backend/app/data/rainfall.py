"""Rainfall: CHIRPS v2.0 daily (0.05°) and ERA5-Land hourly enrichment.

CHIRPS is fetched as a bounding-box subset from the IRI/LDEO Data Library
mirror of the official UCSB-CHC product (one NetCDF per year), so only the
study region is downloaded. Catchment-mean daily series are obtained with an
area-weight matrix (fraction of each catchment falling in each 0.05° cell).

ERA5-Land hourly precipitation and soil moisture are fetched through the
Open-Meteo historical archive API (a redistribution of ECMWF ERA5-Land), on a
coarse 0.25° sampling grid and for monsoon months of a short window — a quota
constraint that is reported in the dataset status, never hidden.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from rasterio.features import rasterize
from rasterio.transform import from_origin
from scipy import sparse

from ..config import ERA5_GRID_DEG, ERA5_MONTHS, ERA5_YEARS, PROCESSED_DIR, RAW_DIR, URLS
from .common import DataUnavailable, download, record, session, now_iso

log = logging.getLogger("hillscope.data.rainfall")
CHIRPS_RES = 0.05


def _chirps_bounds(region: dict) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = region["bbox"]
    return x0, y0, x1, y1


def _validate_nc(p: Path) -> None:
    with open(p, "rb") as f:
        head = f.read(4)
    if not (head.startswith(b"CDF") or head.startswith(b"\x89HDF")):
        raise IOError("response is not NetCDF")


QUARTERS = [("1 Jan", "31 Mar"), ("1 Apr", "30 Jun"), ("1 Jul", "30 Sep"), ("1 Oct", "31 Dec")]


def _validate_part(p: Path) -> None:
    with open(p, "rb") as f:
        if not f.read(4).startswith((b"CDF", bytes([0x89]) + b"HDF")):
            raise IOError("response is not NetCDF")


def chirps_year(region: dict, year: int, progress=None) -> Path:
    """One year of CHIRPS for the region bbox. Fetched as four quarterly subsets (the IRI server
    drops long-running full-year requests), each cached, then merged and integrity-checked."""
    x0, y0, x1, y1 = _chirps_bounds(region)
    dest = RAW_DIR / "chirps" / region["id"] / f"chirps_v2_daily_p05_{year}.nc"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    parts = []
    for q, (a, b) in enumerate(QUARTERS, 1):
        url = URLS["chirps_iri"].format(x0=x0, x1=x1, y0=y0, y1=y1, year=year)
        url = url.replace(f"(1%20Jan%20{year})/(31%20Dec%20{year})", f"({a.replace(' ', '%20')}%20{year})/({b.replace(' ', '%20')}%20{year})")
        part = RAW_DIR / "chirps" / region["id"] / "parts" / f"chirps_{year}_q{q}.nc"
        parts.append(download(url, part, dataset="chirps", nature="observed + remotely sensed (satellite IR blended with station gauges)",
                              version="CHIRPS v2.0 daily-improved 0.05° (IRI mirror)", timeout=600, retries=6,
                              validate=_validate_part, progress=progress))
    dss = [xr.open_dataset(p, decode_times=False) for p in parts]
    merged = xr.concat(dss, dim="T").sortby("T")
    tmp = dest.with_suffix(".merge.nc")
    merged.to_netcdf(tmp)
    for d in dss:
        d.close()
    _validate_nc(tmp)
    tmp.replace(dest)
    from .common import record, sha256, now_iso
    record(dest.relative_to(RAW_DIR).as_posix(), dataset="chirps", url=URLS["chirps_iri"].split("X/")[0], retrieved_at=now_iso(),
           bytes=dest.stat().st_size, sha256=sha256(dest), version="CHIRPS v2.0 daily-improved 0.05° (IRI mirror)",
           nature="observed + remotely sensed (satellite IR blended with station gauges)", assembled_from="4 quarterly subsets")
    return dest


def chirps_years(region: dict, start: int, end: int, progress=None, workers: int = 4) -> list[Path]:
    years = list(range(start, end + 1))
    paths: dict[int, Path] = {}
    errors: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(chirps_year, region, y, None): y for y in years}
        for i, f in enumerate(as_completed(futs), 1):
            y = futs[f]
            try:
                paths[y] = f.result()
            except DataUnavailable as e:
                errors[y] = e.message
            if progress:
                progress(f"CHIRPS daily rainfall: {i}/{len(years)} years ready")
    if errors:
        raise DataUnavailable("chirps", f"years unavailable: {sorted(errors)} ({next(iter(errors.values()))})")
    return [paths[y] for y in years]


def _open_chirps(paths: list[Path]) -> xr.DataArray:
    arrs = []
    for p in paths:
        ds = xr.open_dataset(p, decode_times=False)
        t = pd.to_datetime(ds["T"].values.astype("float64") - 2440587.5, unit="D").normalize()
        da = ds["prcp"].assign_coords(T=t).load()
        ds.close()
        arrs.append(da)
    da = xr.concat(arrs, dim="T").sortby("Y", ascending=False)
    da = da.where(da >= 0)  # negative = missing
    return da


def weight_matrix(gdf: gpd.GeoDataFrame, xs: np.ndarray, ys: np.ndarray, sub: int = 10) -> sparse.csr_matrix:
    """Sparse (n_catchments x n_cells) area-fraction weights on a regular grid (ys descending)."""
    res = float(abs(xs[1] - xs[0]))
    west = float(xs[0] - res / 2)
    north = float(ys[0] + res / 2)
    H, W = len(ys), len(xs)
    tr = from_origin(west, north, res / sub, res / sub)
    zones = rasterize(((g, i + 1) for i, g in enumerate(gdf.geometry)), out_shape=(H * sub, W * sub),
                      transform=tr, fill=0, dtype="int32")
    rr, cc = np.nonzero(zones)
    cat = zones[rr, cc] - 1
    cell = (rr // sub) * W + (cc // sub)
    m = sparse.coo_matrix((np.ones_like(cat, dtype=float), (cat, cell)), shape=(len(gdf), H * W)).tocsr()
    rs = np.asarray(m.sum(axis=1)).ravel()
    # Catchments smaller than one sub-cell: fall back to the cell containing the centroid.
    missing = np.where(rs == 0)[0]
    if len(missing):
        m = m.tolil()
        for i in missing:
            c = gdf.geometry.iloc[i].representative_point()
            col = int(np.clip((c.x - west) // res, 0, W - 1))
            row = int(np.clip((north - c.y) // res, 0, H - 1))
            m[i, row * W + col] = 1.0
        m = m.tocsr()
        rs = np.asarray(m.sum(axis=1)).ravel()
    return sparse.diags(1.0 / rs) @ m


def catchment_daily(gdf: gpd.GeoDataFrame, region: dict, start: int, end: int, progress=None) -> pd.DataFrame:
    """Daily catchment-mean CHIRPS rainfall (mm/day), columns = catchment_id."""
    cache = PROCESSED_DIR / region["id"] / f"chirps_catchment_daily_{start}_{end}.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
        if list(df.columns) == list(gdf["catchment_id"]):
            return df
    paths = chirps_years(region, start, end, progress)
    if progress:
        progress("Aggregating CHIRPS grid to catchments (area-weighted)")
    da = _open_chirps(paths)
    xs, ys = da["X"].values, da["Y"].values
    Wm = weight_matrix(gdf, xs, ys)
    vals = da.values.reshape(da.shape[0], -1)  # T x cells
    nan = np.isnan(vals)
    filled = np.where(nan, 0.0, vals)
    s = (Wm @ filled.T).T
    cover = (Wm @ (~nan).astype(float).T).T
    with np.errstate(invalid="ignore", divide="ignore"):
        series = np.where(cover > 0.5, s / np.where(cover > 0, cover, 1), np.nan)
    df = pd.DataFrame(series, index=pd.DatetimeIndex(da["T"].values, name="date"), columns=gdf["catchment_id"].tolist())
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache)
    return df


# ------------------------------------------------------------------- ERA5-Land
def era5_points(gdf: gpd.GeoDataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """Snap catchment representative points to a coarse sampling grid; returns unique points and mapping."""
    rp = gdf.geometry.representative_point()
    lat = (np.round(rp.y / ERA5_GRID_DEG) * ERA5_GRID_DEG).round(3)
    lon = (np.round(rp.x / ERA5_GRID_DEG) * ERA5_GRID_DEG).round(3)
    keys = pd.Series(list(zip(lat, lon)))
    uniq = pd.DataFrame(sorted(set(keys)), columns=["lat", "lon"])
    idx = {k: i for i, k in enumerate(zip(uniq.lat, uniq.lon))}
    return uniq, np.array([idx[k] for k in keys])


def era5_features(gdf: gpd.GeoDataFrame, region: dict, progress=None) -> pd.DataFrame:
    """Per-catchment ERA5-Land monsoon statistics (model-derived reanalysis)."""
    pts, mapping = era5_points(gdf)
    import hashlib
    ph = hashlib.sha1(pts.to_csv(index=False).encode()).hexdigest()[:10]
    cache = PROCESSED_DIR / region["id"] / f"era5_features_v2_{ERA5_YEARS[0]}_{ERA5_YEARS[1]}_{ph}.parquet"
    if cache.exists():
        pf = pd.read_parquet(cache)
    else:
        rows = []
        s = session()
        batch = 10
        y0, y1 = ERA5_YEARS
        m0, m1 = ERA5_MONTHS
        for b in range(0, len(pts), batch):
            chunk = pts.iloc[b:b + batch]
            per_point: dict[int, list[pd.DataFrame]] = {i: [] for i in chunk.index}
            for year in range(y0, y1 + 1):
                base = {
                    "latitude": ",".join(f"{v:.3f}" for v in chunk.lat),
                    "longitude": ",".join(f"{v:.3f}" for v in chunk.lon),
                    "start_date": f"{year}-{m0:02d}-01",
                    "end_date": f"{year}-{m1:02d}-{30 if m1 in (4, 6, 9, 11) else 31}",
                    "timezone": "GMT",
                }
                # Open-Meteo serves ERA5-Land soil moisture but not ERA5-Land precipitation,
                # so hourly precipitation comes from ERA5 (0.25°), soil moisture from ERA5-Land.
                parts = {}
                for tag, extra in (("", {"hourly": "soil_moisture_0_to_7cm", "models": "era5_land"}),
                                   ("_era5p", {"hourly": "precipitation", "models": "era5"})):
                    dest = RAW_DIR / "era5land" / region["id"] / ph / f"pts{b:04d}_{year}{tag}.json"
                    if not dest.exists():
                        for attempt in range(6):
                            try:
                                r = s.get(URLS["era5land_openmeteo"], params={**base, **extra}, timeout=180)
                                if r.status_code == 429:
                                    raise IOError("rate limited")
                                r.raise_for_status()
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                dest.write_text(r.text, encoding="utf-8")
                                break
                            except Exception as e:  # noqa: BLE001
                                log.warning("ERA5 request failed (%s): %s", attempt, e)
                                time.sleep(15 * (attempt + 1))
                        else:
                            raise DataUnavailable("era5land", "Open-Meteo archive API unavailable or quota exhausted")
                    import json
                    js = json.loads(dest.read_text(encoding="utf-8"))
                    parts[tag] = js if isinstance(js, list) else [js]
                for n, i in enumerate(chunk.index):
                    hs, hp = parts[""][n]["hourly"], parts["_era5p"][n]["hourly"]
                    per_point[i].append(pd.DataFrame({"time": pd.to_datetime(hp["time"]), "p": hp["precipitation"],
                                                      "sm": hs["soil_moisture_0_to_7cm"]}))
            for i, frames in per_point.items():
                d = pd.concat(frames).set_index("time")
                d = d.astype(float)
                daily = d["p"].resample("D").sum(min_count=20)
                dmax = d["p"].resample("D").max()
                wet = daily > 1.0
                with np.errstate(invalid="ignore", divide="ignore"):
                    conc = (dmax[wet] / daily[wet]).mean()
                rows.append({
                    "pt": i,
                    "era5_p_hourly_p99": float(np.nanpercentile(d["p"][d["p"] > 0.1], 99)) if (d["p"] > 0.1).any() else np.nan,
                    "era5_p_hourly_max": float(d["p"].max()),
                    "era5_hourly_concentration": float(conc),
                    "era5_soil_moisture_mean": float(d["sm"].mean()),
                    "era5_soil_moisture_p90": float(d["sm"].quantile(0.9)),
                })
            if progress:
                progress(f"ERA5-Land reanalysis: {min(b + batch, len(pts))}/{len(pts)} sample points")
        pf = pd.DataFrame(rows).set_index("pt").sort_index()
        cache.parent.mkdir(parents=True, exist_ok=True)
        pf.to_parquet(cache)
        record(f"era5land/{region['id']}", dataset="era5land", url=URLS["era5land_openmeteo"], retrieved_at=now_iso(),
               version=f"ERA5 hourly precipitation + ERA5-Land soil moisture via Open-Meteo, JJAS {ERA5_YEARS[0]}-{ERA5_YEARS[1]}, {ERA5_GRID_DEG}° sampling",
               nature="model-derived (reanalysis)", n_points=len(pts))
    out = pf.reindex(mapping).reset_index(drop=True)
    out.index = gdf.index
    return out

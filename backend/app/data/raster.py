"""Raster datasets: Copernicus GLO-90 DEM, ESA WorldCover 2021, SoilGrids 2.0.

Zonal statistics are computed by rasterising catchment IDs onto each raster
grid (all-touched=False) and aggregating with NumPy bincount — fast enough for
a laptop and exact for the chosen grid.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.merge import merge
from rasterio.transform import from_bounds
from rasterio.windows import from_bounds as window_from_bounds

from ..config import PROCESSED_DIR, RAW_DIR, URLS
from .common import DataUnavailable, download, record, now_iso

log = logging.getLogger("hillscope.data.raster")


# ------------------------------------------------------------------- DEM
def _cop_tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"Copernicus_DSM_COG_30_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"


def dem_mosaic(region: dict, progress=None) -> Path:
    """Download Copernicus GLO-90 tiles covering the region and mosaic them."""
    out = PROCESSED_DIR / region["id"] / "dem_glo90.tif"
    if out.exists():
        return out
    x0, y0, x1, y1 = region["bbox"]
    paths = []
    for lat in range(math.floor(y0), math.ceil(y1)):
        for lon in range(math.floor(x0), math.ceil(x1)):
            name = _cop_tile_name(lat, lon)
            dest = RAW_DIR / "copernicus_dem" / f"{name}.tif"
            try:
                paths.append(download(
                    URLS["cop_dem"].format(name=name), dest, dataset="copernicus_dem",
                    nature="remotely sensed (TanDEM-X radar DSM)", version="GLO-90 DGED 2023_1",
                    progress=progress,
                ))
            except DataUnavailable as e:
                # Ocean/no-land tiles legitimately do not exist; any land tile failure is fatal.
                log.warning("DEM tile %s unavailable: %s", name, e.message)
    if not paths:
        raise DataUnavailable("copernicus_dem", "no DEM tiles could be retrieved")
    if progress:
        progress(f"Mosaicking {len(paths)} DEM tiles")
    srcs = [rasterio.open(p) for p in paths]
    arr, tr = merge(srcs, bounds=(x0, y0, x1, y1))
    prof = srcs[0].profile.copy()
    for s in srcs:
        s.close()
    prof.update(height=arr.shape[1], width=arr.shape[2], transform=tr, compress="deflate",
                driver="GTiff", tiled=True, count=1, dtype="float32", nodata=-32767.0)
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(arr[0].astype("float32"), 1)
    return out


def slope_degrees(dem: np.ndarray, transform, nodata) -> np.ndarray:
    """Slope (degrees) on a geographic grid using latitude-dependent pixel spacing (Horn-like central differences)."""
    z = dem.astype("float64")
    z[(z == nodata) | ~np.isfinite(z)] = np.nan
    rows = np.arange(z.shape[0])
    lat = transform.f + (rows + 0.5) * transform.e
    dy = abs(transform.e) * 111_320.0
    dx = transform.a * 111_320.0 * np.cos(np.radians(lat))[:, None]
    gy, gx = np.gradient(z)
    gy = gy / dy
    gx = gx / dx
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def zone_raster(gdf: gpd.GeoDataFrame, shape, transform) -> np.ndarray:
    """Rasterise catchments as 1..N integer zones (0 = outside)."""
    shapes = ((geom, i + 1) for i, geom in enumerate(gdf.geometry))
    return rasterize(shapes, out_shape=shape, transform=transform, fill=0, dtype="int32")


def zonal(values: np.ndarray, zones: np.ndarray, n: int) -> dict[str, np.ndarray]:
    """Count, mean, std, min, max, p10, p90 of ``values`` per zone (NaN ignored)."""
    v = values.ravel()
    z = zones.ravel()
    ok = (z > 0) & np.isfinite(v)
    v, z = v[ok], z[ok]
    cnt = np.bincount(z, minlength=n + 1)[1:].astype(float)
    s = np.bincount(z, weights=v, minlength=n + 1)[1:]
    s2 = np.bincount(z, weights=v * v, minlength=n + 1)[1:]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = s / cnt
        std = np.sqrt(np.maximum(s2 / cnt - mean**2, 0))
    mn = np.full(n, np.nan)
    mx = np.full(n, np.nan)
    p10 = np.full(n, np.nan)
    p90 = np.full(n, np.nan)
    order = np.argsort(z, kind="stable")
    zs, vs = z[order], v[order]
    bounds = np.searchsorted(zs, np.arange(1, n + 2))
    for i in range(n):
        seg = vs[bounds[i]:bounds[i + 1]]
        if seg.size:
            mn[i], mx[i] = seg.min(), seg.max()
            p10[i], p90[i] = np.percentile(seg, [10, 90])
    return {"count": cnt, "mean": mean, "std": std, "min": mn, "max": mx, "p10": p10, "p90": p90}


def terrain_stats(gdf: gpd.GeoDataFrame, region: dict, progress=None) -> dict[str, np.ndarray]:
    path = dem_mosaic(region, progress)
    if progress:
        progress("Computing slope and terrain statistics from DEM")
    with rasterio.open(path) as src:
        dem = src.read(1)
        tr = src.transform
        nod = src.nodata
    slope = slope_degrees(dem, tr, nod)
    z = dem.astype("float64")
    z[(z == nod) | ~np.isfinite(z)] = np.nan
    zones = zone_raster(gdf, z.shape, tr)
    n = len(gdf)
    e = zonal(z, zones, n)
    s = zonal(slope, zones, n)
    steep = zonal((slope > 30).astype(float) + np.where(np.isnan(slope), np.nan, 0), zones, n)
    return {
        "elev_mean": e["mean"], "elev_min": e["min"], "elev_max": e["max"], "elev_std": e["std"],
        "elev_p10": e["p10"], "elev_p90": e["p90"], "dem_pixels": e["count"],
        "slope_mean": s["mean"], "slope_std": s["std"], "slope_p90": s["p90"],
        "steep_frac": steep["mean"],
    }


# ------------------------------------------------------------------- WorldCover
WORLDCOVER_CLASSES = {
    10: "tree", 20: "shrub", 30: "grass", 40: "crop", 50: "built", 60: "bare",
    70: "snow_ice", 80: "water", 90: "wetland", 95: "mangrove", 100: "moss",
}


def _wc_tile(lat: int, lon: int) -> str:
    return f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"


def worldcover_fractions(gdf: gpd.GeoDataFrame, region: dict, progress=None, decimation: int = 8) -> dict[str, np.ndarray]:
    """Land-cover class fractions per catchment from ESA WorldCover 2021 (v200).

    Tiles are read remotely as Cloud-Optimised GeoTIFF overviews (decimation 8,
    ~80 m) and cached locally, avoiding ~100 MB downloads per 3°x3° tile.
    """
    cache = PROCESSED_DIR / region["id"] / f"worldcover_d{decimation}.tif"
    x0, y0, x1, y1 = region["bbox"]
    if not cache.exists():
        lats = range(3 * math.floor(y0 / 3), 3 * math.ceil(y1 / 3), 3)
        lons = range(3 * math.floor(x0 / 3), 3 * math.ceil(x1 / 3), 3)
        arrays, transforms = [], []
        env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                   GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="3")
        for lat in lats:
            for lon in lons:
                tile = _wc_tile(lat, lon)
                url = URLS["worldcover"].format(tile=tile)
                if progress:
                    progress(f"Reading ESA WorldCover tile {tile} (COG overview)")
                try:
                    with rasterio.Env(**env), rasterio.open(f"/vsicurl/{url}") as src:
                        win = window_from_bounds(max(x0, lon), max(y0, lat), min(x1, lon + 3), min(y1, lat + 3), src.transform)
                        win = win.round_offsets().round_lengths()
                        h, w = max(1, int(win.height // decimation)), max(1, int(win.width // decimation))
                        a = src.read(1, window=win, out_shape=(h, w))
                        b = src.window_bounds(win)
                        arrays.append(a)
                        transforms.append((b, a.shape))
                        record(f"worldcover/{tile}", dataset="worldcover", url=url, retrieved_at=now_iso(),
                               version="ESA WorldCover 10m 2021 v200", nature="remotely sensed (Sentinel-1/2 classification)",
                               access=f"COG overview read, decimation {decimation}")
                except Exception as e:  # noqa: BLE001
                    raise DataUnavailable("worldcover", f"tile {tile}: {e}") from e
        # Assemble onto a common grid at the decimated resolution.
        res = 3.0 / (36000 / decimation)
        W = int(round((x1 - x0) / res))
        H = int(round((y1 - y0) / res))
        tr = from_bounds(x0, y0, x1, y1, W, H)
        mosaic = np.zeros((H, W), dtype="uint8")
        for a, (b, _) in zip(arrays, transforms):
            c0 = int(round((b[0] - x0) / res))
            r0 = int(round((y1 - b[3]) / res))
            hh, ww = min(a.shape[0], H - r0), min(a.shape[1], W - c0)
            mosaic[r0:r0 + hh, c0:c0 + ww] = a[:hh, :ww]
        cache.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(cache, "w", driver="GTiff", height=H, width=W, count=1, dtype="uint8",
                           crs="EPSG:4326", transform=tr, compress="deflate", nodata=0) as dst:
            dst.write(mosaic, 1)
    with rasterio.open(cache) as src:
        lc = src.read(1)
        tr = src.transform
    zones = zone_raster(gdf, lc.shape, tr)
    n = len(gdf)
    valid = (zones > 0) & (lc > 0)
    tot = np.bincount(zones[valid], minlength=n + 1)[1:].astype(float)
    out = {}
    for code, name in WORLDCOVER_CLASSES.items():
        m = valid & (lc == code)
        c = np.bincount(zones[m], minlength=n + 1)[1:]
        with np.errstate(invalid="ignore", divide="ignore"):
            out[f"lc_{name}"] = c / tot
    out["lc_pixels"] = tot
    return out


# ------------------------------------------------------------------- SoilGrids
SOIL_PROPS = {"clay": "clay_0-5cm_mean", "sand": "sand_0-5cm_mean", "soc": "soc_0-5cm_mean"}


def soilgrids_stats(gdf: gpd.GeoDataFrame, region: dict, progress=None) -> dict[str, np.ndarray]:
    """Topsoil texture (g/kg -> %) and organic carbon from ISRIC SoilGrids 2.0 WCS (250 m)."""
    x0, y0, x1, y1 = region["bbox"]
    out = {}
    n = len(gdf)
    for prop, cov in SOIL_PROPS.items():
        dest = RAW_DIR / "soilgrids" / region["id"] / f"{cov}.tif"
        params = [
            ("SERVICE", "WCS"), ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"), ("COVERAGEID", cov),
            ("FORMAT", "image/tiff"), ("SUBSET", f"long({x0},{x1})"), ("SUBSET", f"lat({y0},{y1})"),
            ("SUBSETTINGCRS", "http://www.opengis.net/def/crs/EPSG/0/4326"),
            ("OUTPUTCRS", "http://www.opengis.net/def/crs/EPSG/0/4326"),
        ]

        def _check(p: Path):
            with open(p, "rb") as f:
                if f.read(2) not in (b"II", b"MM"):
                    raise IOError("WCS did not return a GeoTIFF")

        download(URLS["soilgrids_wcs"].format(prop=prop), dest, params=params, dataset="soilgrids",
                 nature="model-derived (digital soil mapping, ML on profiles + covariates)",
                 version="SoilGrids 2.0 (2020)", validate=_check, progress=progress)
        with rasterio.open(dest) as src:
            a = src.read(1).astype("float64")
            nod = src.nodata
            tr = src.transform
        if nod is not None:
            a[a == nod] = np.nan
        a[a <= 0] = np.nan  # 0 is used for no-data over glaciers/water in SoilGrids
        zones = zone_raster(gdf, a.shape, tr)
        st = zonal(a, zones, n)
        scale = 10.0 if prop in ("clay", "sand") else 10.0  # clay/sand g/kg -> %, soc dg/kg -> g/kg
        out[f"soil_{prop}"] = st["mean"] / scale
    return out

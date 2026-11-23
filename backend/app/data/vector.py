"""Vector datasets: administrative boundaries, HydroBASINS catchments, HydroRIVERS network."""
from __future__ import annotations

import logging
import re
import unicodedata
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from ..config import HYDROBASINS_LEVEL, PROCESSED_DIR, RAW_DIR, URLS
from .common import DataUnavailable, download, record, session, now_iso

log = logging.getLogger("hillscope.data.vector")
WGS84 = "EPSG:4326"


# ---------------------------------------------------------------- boundaries
def norm_name(s: str) -> str:
    """ASCII-fold and lowercase a place name ('Uttarākhand' -> 'uttarakhand')."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def admin_boundaries(level: str, progress=None) -> gpd.GeoDataFrame:
    """geoBoundaries (gbOpen) India ADM1 / ADM2, simplified geometry."""
    dest = RAW_DIR / "geoboundaries" / f"IND_{level}.geojson"
    if not dest.exists():
        try:
            meta = session().get(URLS["geoboundaries"].format(level=level), timeout=60).json()
        except Exception as e:  # noqa: BLE001
            raise DataUnavailable("geoboundaries", f"metadata request failed: {e}") from e
        url = meta.get("simplifiedGeometryGeoJSON") or meta["gjDownloadURL"]
        download(
            url, dest, dataset="geoboundaries", nature="administrative (official boundaries, compiled)",
            version=f"gbOpen {meta.get('boundaryYearRepresented', '?')} build {meta.get('buildDate', '?')}",
            progress=progress,
        )
        record(dest.relative_to(RAW_DIR).as_posix(), license=meta.get("boundaryLicense"),
               source=meta.get("boundarySource"))
    g = gpd.read_file(dest)
    if g.crs is None:
        g = g.set_crs(WGS84)
    return g.to_crs(WGS84)


def region_polygon(region: dict, progress=None) -> gpd.GeoDataFrame:
    adm1 = admin_boundaries("ADM1", progress)
    wanted = {norm_name(s) for s in region["states"]}
    sel = adm1[adm1["shapeName"].map(norm_name).isin(wanted)]
    if sel.empty:
        raise DataUnavailable("geoboundaries", f"state(s) {region['states']} not found in ADM1")
    return gpd.GeoDataFrame({"region": [region["id"]]}, geometry=[sel.union_all()], crs=WGS84)


def districts(region: dict, progress=None) -> gpd.GeoDataFrame:
    adm2 = admin_boundaries("ADM2", progress)
    poly = region_polygon(region, progress).geometry.iloc[0]
    rp = adm2.representative_point()
    d = adm2[rp.within(poly.buffer(0.01))].copy()
    d = d.rename(columns={"shapeName": "district"})[["district", "geometry"]].reset_index(drop=True)
    return d


# ---------------------------------------------------------------- hydrobasins
def _hydrobasins_zip(progress=None) -> Path:
    return download(
        URLS["hydrobasins"], RAW_DIR / "hydrosheds" / Path(URLS["hydrobasins"]).name,
        dataset="hydrobasins", nature="derived from SRTM-based HydroSHEDS (remote sensing)",
        version="HydroBASINS v1c", progress=progress,
    )


def catchments(region: dict, progress=None) -> gpd.GeoDataFrame:
    """HydroBASINS level-12 catchments whose representative point lies in the region."""
    cache = PROCESSED_DIR / region["id"] / "catchments_raw.gpkg"
    if cache.exists():
        return gpd.read_file(cache)
    z = _hydrobasins_zip(progress)
    with zipfile.ZipFile(z) as zf:
        shp = next(n for n in zf.namelist() if n.endswith(f"lev{HYDROBASINS_LEVEL:02d}_v1c.shp"))
    if progress:
        progress("Reading HydroBASINS catchment polygons")
    g = gpd.read_file(f"zip://{z.as_posix()}!{shp}", bbox=tuple(region["bbox"]), engine="pyogrio")
    g = g.set_crs(WGS84, allow_override=True)
    g["geometry"] = g.geometry.make_valid()  # a few HydroBASINS rings self-intersect
    poly = region_polygon(region, progress).geometry.iloc[0]
    g = g[g.representative_point().within(poly)].copy()
    if g.empty:
        raise DataUnavailable("hydrobasins", "no catchments intersect the study region")
    g["catchment_id"] = g["HYBAS_ID"].astype("int64").astype(str)
    keep = ["catchment_id", "HYBAS_ID", "NEXT_DOWN", "MAIN_BAS", "SUB_AREA", "UP_AREA", "ORDER", "DIST_MAIN", "geometry"]
    g = g[[c for c in keep if c in g.columns]].reset_index(drop=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    g.to_file(cache, driver="GPKG")
    return g


# ---------------------------------------------------------------- hydrorivers
def rivers(region: dict, progress=None) -> gpd.GeoDataFrame:
    cache = PROCESSED_DIR / region["id"] / "rivers.gpkg"
    if cache.exists():
        return gpd.read_file(cache)
    z = download(
        URLS["hydrorivers"], RAW_DIR / "hydrosheds" / Path(URLS["hydrorivers"]).name,
        dataset="hydrorivers", nature="derived from SRTM-based HydroSHEDS (remote sensing)",
        version="HydroRIVERS v1.0", progress=progress,
    )
    with zipfile.ZipFile(z) as zf:
        shp = next(n for n in zf.namelist() if n.endswith(".shp"))
    if progress:
        progress("Clipping HydroRIVERS network")
    r = gpd.read_file(f"zip://{z.as_posix()}!{shp}", bbox=tuple(region["bbox"]), engine="pyogrio")
    r = r.set_crs(WGS84, allow_override=True)
    r = r[["HYRIV_ID", "LENGTH_KM", "ORD_STRA", "UPLAND_SKM", "geometry"]]
    cache.parent.mkdir(parents=True, exist_ok=True)
    r.to_file(cache, driver="GPKG")
    return r


def bbox_geom(region: dict):
    return box(*region["bbox"])


def concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


__all__ = ["admin_boundaries", "region_polygon", "districts", "catchments", "rivers", "now_iso"]

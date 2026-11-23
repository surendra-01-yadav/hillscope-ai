"""Independent historical flood-event records.

Sources
-------
1. India Flood Inventory (IFI) v3 — Saharia et al. (2021), Nat. Hazards 108, built with
   the India Meteorological Department (IMD). District-level records; event
   geometry is the union of the affected districts (spatial precision: district).
2. Dartmouth Flood Observatory (DFO) Global Active Archive of Large Flood Events —
   ArcGIS FeatureServer mirror. Large-event extents (spatial precision: regional).

Records are read verbatim; nothing is invented. Events are NEVER used to fit
clusters, only for post-hoc association (see validation/historical.py).
"""
from __future__ import annotations

import io
import logging
import re
import zipfile

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

from ..config import PROCESSED_DIR, RAW_DIR, URLS
from .common import DataUnavailable, download, record, session, now_iso
from .vector import districts, norm_name

log = logging.getLogger("hillscope.data.events")

FLASH_PATTERN = re.compile(r"cloud\s*-?\s*burst|flash", re.I)
RAIN_PATTERN = re.compile(r"heavy\s*rain|rain|landslide|flood", re.I)

# Historic or alternate spellings in IMD records -> geoBoundaries district names.
DISTRICT_ALIASES = {
    "pauri": "garhwal", "pauri garhwal": "garhwal", "paurigarhwal": "garhwal", "garhwal": "garhwal",
    "haridwar": "hardwar", "tehri": "tehrigarhwal", "tehrigarhwal": "tehrigarhwal",
    "uttarkashi": "uttarkashi", "udhamsinghnagar": "udhamsinghnagar", "usnagar": "udhamsinghnagar",
    "lahaul": "lahulspiti", "lahaulspiti": "lahulspiti", "lahulspiti": "lahulspiti", "spiti": "lahulspiti",
    "lahaulandspiti": "lahulspiti", "lahulandspiti": "lahulspiti",
    "udamsinghnagar": "udhamsinghnagar", "uttarkashikashi": "uttarkashi", "rudraprayag": "rudraprayag",
    "chamoligarhwal": "chamoli", "dehradoon": "dehradun", "almorah": "almora", "kulu": "kullu",
    "sirmour": "sirmaur", "sirmaur": "sirmaur", "nainital": "nainital", "naintal": "nainital",
}


def _ifi_csv(progress=None) -> pd.DataFrame:
    z = download(URLS["ifi_repo"], RAW_DIR / "events" / "India-Flood-Inventory-main.zip", dataset="ifi",
                 nature="observed/reported (official IMD disaster records, compiled)",
                 version="IFI v3.0 (hydrosenselab GitHub)", progress=progress)
    with zipfile.ZipFile(z) as zf:
        name = next(n for n in zf.namelist() if n.endswith("India_Flood_Inventory_v3.csv"))
        raw = zf.read(name)
    df = pd.read_csv(io.BytesIO(raw), encoding="latin1")
    df.columns = [c.strip().lstrip("﻿").lstrip("ï»¿") for c in df.columns]
    return df


def ifi_events(region: dict, progress=None) -> gpd.GeoDataFrame:
    """IFI events for the region's state(s), geolocated to affected districts."""
    df = _ifi_csv(progress)
    wanted = {norm_name(s) for s in region["states"]}
    df = df[df["State"].map(norm_name).isin(wanted)].copy()
    dist = districts(region, progress)
    dist["key"] = dist["district"].map(norm_name)
    lookup = dict(zip(dist["key"], dist.index))
    rows = []
    for _, r in df.iterrows():
        txt = str(r.get("Districts") or "")
        parts = [p for p in re.split(r"[,;/&]| and ", txt) if p.strip()]
        idx = set()
        for p in parts:
            k = norm_name(p.replace("district", "").replace("District", ""))
            k = DISTRICT_ALIASES.get(k, k)
            if k in lookup:
                idx.add(lookup[k])
        start = pd.to_datetime(r.get("Start Date"), dayfirst=True, errors="coerce")
        end = pd.to_datetime(r.get("End Date"), dayfirst=True, errors="coerce")
        cause = str(r.get("Main Cause") or "")
        desc = " ".join(str(r.get(c) or "") for c in ("Main Cause", "Location", "Description of Casualties/injured", "Extent of damage")).strip()
        flash = bool(FLASH_PATTERN.search(cause) or FLASH_PATTERN.search(str(r.get("Location") or "")))
        if idx and len(idx) >= 0.75 * len(dist):
            geom = dist.loc[sorted(idx)].geometry.union_all()
            precision, conf = "state-wide", "low"
        elif idx:
            geom = dist.loc[sorted(idx)].geometry.union_all()
            precision, conf = "district", "medium"
        else:
            geom, precision, conf = None, "state", "low"
        rows.append({
            "event_id": r["UEI"], "source": "IFI v3 (IMD)", "start_date": start, "end_date": end,
            "cause": cause, "flash_type": flash, "districts": ", ".join(sorted(dist.loc[sorted(idx), "district"])) if idx else "",
            "description": desc[:400], "fatalities": pd.to_numeric(r.get("Human fatality"), errors="coerce"),
            "spatial_precision": precision, "source_confidence": conf, "geometry": geom,
        })
    g = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    return g


def dfo_events(region: dict, progress=None) -> gpd.GeoDataFrame:
    """DFO large flood events whose mapped extent intersects the region bbox."""
    cache = RAW_DIR / "events" / f"dfo_{region['id']}.geojson"
    if not cache.exists():
        x0, y0, x1, y1 = region["bbox"]
        params = {
            "where": "1=1", "geometry": f"{x0},{y0},{x1},{y1}", "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "outSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
            "returnGeometry": "true", "f": "geojson",
        }
        if progress:
            progress("Querying Dartmouth Flood Observatory archive")
        try:
            r = session().get(URLS["dfo_featureserver"], params=params, timeout=120)
            r.raise_for_status()
            gj = r.json()
        except Exception as e:  # noqa: BLE001
            raise DataUnavailable("dfo", f"FeatureServer query failed: {e}") from e
        if "features" not in gj:
            raise DataUnavailable("dfo", f"unexpected response: {str(gj)[:200]}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        import json
        cache.write_text(json.dumps(gj), encoding="utf-8")
        record(cache.relative_to(RAW_DIR).as_posix(), dataset="dfo", url=r.url.split("?")[0], retrieved_at=now_iso(),
               version="DFO Global Active Archive (ArcGIS mirror)", nature="observed/reported (media, government, satellite)",
               n_features=len(gj["features"]))
    g = gpd.read_file(cache)
    if g.empty:
        return gpd.GeoDataFrame(columns=["event_id", "geometry"], geometry="geometry", crs="EPSG:4326")
    g = g.set_crs("EPSG:4326", allow_override=True)
    out = gpd.GeoDataFrame({
        "event_id": "DFO-" + g["ID"].astype("Int64").astype(str),
        "source": "Dartmouth Flood Observatory",
        "start_date": pd.to_datetime(g["BEGAN"], unit="ms", errors="coerce"),
        "end_date": pd.to_datetime(g["ENDED"], unit="ms", errors="coerce"),
        "cause": g["MAINCAUSE"].fillna(""),
        "flash_type": g["MAINCAUSE"].fillna("").str.contains(FLASH_PATTERN),
        "districts": "",
        "description": ("Country: " + g["COUNTRY"].fillna("") + "; severity " + g["SEVERITY"].astype(str)),
        "fatalities": pd.to_numeric(g["DEAD"], errors="coerce"),
        "spatial_precision": "regional",
        "source_confidence": "medium",
    }, geometry=g.geometry, crs="EPSG:4326")
    return out


def all_events(region: dict, progress=None) -> tuple[gpd.GeoDataFrame, list[dict]]:
    """Combined events plus a list of provider issues (never silently dropped)."""
    frames, issues = [], []
    for name, fn in (("ifi", ifi_events), ("dfo", dfo_events)):
        try:
            frames.append(fn(region, progress))
        except DataUnavailable as e:
            issues.append({"dataset": name, "message": e.message})
            log.error("event source %s unavailable: %s", name, e.message)
    if not frames:
        raise DataUnavailable("events", "no historical event source available")
    g = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    g = g.drop_duplicates(subset=["event_id"]).reset_index(drop=True)
    cache = PROCESSED_DIR / region["id"] / "events.parquet"
    cache.parent.mkdir(parents=True, exist_ok=True)
    g.to_parquet(cache)
    return g, issues

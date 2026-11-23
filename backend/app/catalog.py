"""Dataset catalogue with attribution, licensing and data nature, plus local cache status."""
from __future__ import annotations

import json

from .config import PROCESSED_DIR, RAW_DIR
from .data.common import load_manifest

DATASETS = [
    {"id": "hydrobasins", "name": "HydroBASINS v1c (level 12)", "provider": "WWF / HydroSHEDS",
     "url": "https://www.hydrosheds.org/products/hydrobasins", "license": "HydroSHEDS licence (free, attribution)",
     "nature": "remotely sensed (derived)", "role": "Catchment boundaries, area, topology", "prefix": "hydrosheds/hybas"},
    {"id": "hydrorivers", "name": "HydroRIVERS v1.0", "provider": "WWF / HydroSHEDS",
     "url": "https://www.hydrosheds.org/products/hydrorivers", "license": "HydroSHEDS licence (free, attribution)",
     "nature": "remotely sensed (derived)", "role": "Drainage-density proxy", "prefix": "hydrosheds/HydroRIVERS"},
    {"id": "copernicus_dem", "name": "Copernicus DEM GLO-90", "provider": "ESA / Airbus (AWS Open Data)",
     "url": "https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM",
     "license": "Copernicus DEM licence (free)", "nature": "remotely sensed", "role": "Elevation, slope, relief",
     "prefix": "copernicus_dem/"},
    {"id": "chirps", "name": "CHIRPS v2.0 daily 0.05°", "provider": "UCSB Climate Hazards Center (via IRI Data Library)",
     "url": "https://www.chc.ucsb.edu/data/chirps", "license": "Public domain (CC0-like)",
     "nature": "observed + remotely sensed", "role": "Daily rainfall regime and extremes", "prefix": "chirps/"},
    {"id": "era5land", "name": "ERA5 hourly precip. + ERA5-Land soil moisture", "provider": "ECMWF Copernicus C3S (via Open-Meteo archive)",
     "url": "https://cds.climate.copernicus.eu/", "license": "Copernicus licence (free, attribution)",
     "nature": "model-derived (reanalysis)", "role": "Sub-daily intensity, soil moisture (enrichment)", "prefix": "era5land/"},
    {"id": "worldcover", "name": "ESA WorldCover 2021 v200", "provider": "ESA",
     "url": "https://esa-worldcover.org/", "license": "CC BY 4.0", "nature": "remotely sensed",
     "role": "Land-cover composition", "prefix": "worldcover/"},
    {"id": "soilgrids", "name": "SoilGrids 2.0", "provider": "ISRIC",
     "url": "https://soilgrids.org/", "license": "CC BY 4.0", "nature": "model-derived",
     "role": "Topsoil texture & carbon (infiltration-related proxies)", "prefix": "soilgrids/"},
    {"id": "geoboundaries", "name": "geoBoundaries gbOpen IND ADM1/ADM2", "provider": "William & Mary geoLab",
     "url": "https://www.geoboundaries.org/", "license": "ODbL 1.0", "nature": "administrative",
     "role": "Study-region and district boundaries", "prefix": "geoboundaries/"},
    {"id": "ifi", "name": "India Flood Inventory v3", "provider": "HydroSense Lab IIT Delhi with IMD",
     "url": "https://github.com/hydrosenselab/India-Flood-Inventory", "license": "Open (cite Saharia et al. 2021)",
     "nature": "observed / reported", "role": "Independent historical validation (district-level)", "prefix": "events/India"},
    {"id": "dfo", "name": "DFO Global Active Archive of Large Flood Events", "provider": "Dartmouth Flood Observatory",
     "url": "https://floodobservatory.colorado.edu/Archives/index.html", "license": "Free for research & education",
     "nature": "observed / reported", "role": "Independent historical validation (regional extents)", "prefix": "events/dfo"},
    {"id": "discharge", "name": "Gauged river discharge", "provider": "CWC / India-WRIS, GRDC",
     "url": "https://indiawris.gov.in/", "license": "Restricted", "nature": "observed",
     "role": "Measured hydrological response — NOT AVAILABLE", "prefix": None},
]


def status(region_id: str | None = None) -> list[dict]:
    man = load_manifest()
    rep = {}
    if region_id:
        p = PROCESSED_DIR / region_id / "base_features.json"
        if p.exists():
            rep = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for d in DATASETS:
        entries = {k: v for k, v in man.items() if d["prefix"] and k.startswith(d["prefix"])}
        if region_id and d["id"] in ("chirps", "soilgrids", "era5land"):
            entries = {k: v for k, v in entries.items() if f"/{region_id}" in k or k.endswith(region_id)} or entries
        if region_id and d["id"] == "dfo":
            entries = {k: v for k, v in entries.items() if region_id in k}
        st = "cached" if entries else "not downloaded"
        if d["id"] == "discharge":
            st = "unavailable"
        issue = next((i["message"] for i in rep.get("issues", []) if i["dataset"] == d["id"]), None)
        if issue:
            st = "unavailable"
        out.append({
            **{k: v for k, v in d.items() if k != "prefix"},
            "status": st, "issue": issue,
            "files": len(entries),
            "bytes": int(sum(v.get("bytes", 0) or 0 for v in entries.values())),
            "versions": sorted({v.get("version") for v in entries.values() if v.get("version")}),
            "last_retrieved": max((v.get("retrieved_at") for v in entries.values() if v.get("retrieved_at")), default=None),
        })
    return out

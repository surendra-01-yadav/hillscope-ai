"""Central configuration: paths, study regions and dataset endpoints."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("HILLSCOPE_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = DATA_DIR / "reports"
MODELS_DIR = DATA_DIR / "models"
DB_URL = os.environ.get("HILLSCOPE_DB_URL", f"sqlite:///{(DATA_DIR / 'hillscope.db').as_posix()}")

for _d in (RAW_DIR, PROCESSED_DIR, REPORTS_DIR, MODELS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

USER_AGENT = "HillScopeAI/1.0 (research prototype; unsupervised catchment analysis)"

# ---------------------------------------------------------------------------
# Study regions. `states` are matched against geoBoundaries ADM1 names.
# `min_mean_elev_m` restricts the analysis to hill catchments (documented in
# docs/METHODOLOGY.md); plains catchments are excluded rather than clustered.
# ---------------------------------------------------------------------------
REGIONS: dict[str, dict] = {
    "uttarakhand": {
        "id": "uttarakhand",
        "name": "Uttarakhand Himalaya",
        "country": "India",
        "states": ["Uttarakhand"],
        "bbox": [77.5, 28.6, 81.1, 31.5],  # lon_min, lat_min, lon_max, lat_max
        "center": [79.2, 30.15],
        "min_mean_elev_m": 500.0,
    },
    "himachal": {
        "id": "himachal",
        "name": "Himachal Pradesh",
        "country": "India",
        "states": ["Himachal Pradesh"],
        "bbox": [75.5, 30.3, 79.1, 33.3],
        "center": [77.3, 31.9],
        "min_mean_elev_m": 500.0,
    },
}

# Selectable rainfall analysis periods (inclusive years).
PERIODS: dict[str, dict] = {
    "2001-2020": {"id": "2001-2020", "label": "2001 – 2020 (20 yr)", "start": 2001, "end": 2020},
    "2001-2010": {"id": "2001-2010", "label": "2001 – 2010 (10 yr)", "start": 2001, "end": 2010},
    "2011-2020": {"id": "2011-2020", "label": "2011 – 2020 (10 yr)", "start": 2011, "end": 2020},
}

HYDROBASINS_LEVEL = 12

URLS = {
    "hydrobasins": f"https://data.hydrosheds.org/file/hydrobasins/standard/hybas_as_lev{HYDROBASINS_LEVEL:02d}_v1c.zip",
    "hydrorivers": "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_as_shp.zip",
    "cop_dem": "https://copernicus-dem-90m.s3.amazonaws.com/{name}/{name}.tif",
    "worldcover": "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif",
    "soilgrids_wcs": "https://maps.isric.org/mapserv?map=/map/{prop}.map",
    "chirps_iri": (
        "https://iridl.ldeo.columbia.edu/SOURCES/.UCSB/.CHIRPS/.v2p0/.daily-improved/.global/.0p05/.prcp/"
        "X/{x0}/{x1}/RANGEEDGES/Y/{y0}/{y1}/RANGEEDGES/T/(1%20Jan%20{year})/(31%20Dec%20{year})/RANGEEDGES/data.nc"
    ),
    "era5land_openmeteo": "https://archive-api.open-meteo.com/v1/archive",
    "geoboundaries": "https://www.geoboundaries.org/api/current/gbOpen/IND/{level}/",
    "ifi_repo": "https://github.com/hydrosenselab/India-Flood-Inventory/archive/refs/heads/main.zip",
    "dfo_featureserver": (
        "https://services1.arcgis.com/AXaYBvnJsB5Q7sDF/ArcGIS/rest/services/"
        "Global_Archive_of_large_flood_events/FeatureServer/0/query"
    ),
}

# ERA5-Land enrichment window (hourly, monsoon months). Kept short to respect
# the free Open-Meteo API quota; documented as a limitation.
ERA5_YEARS = (2018, 2020)
ERA5_MONTHS = (6, 9)
ERA5_GRID_DEG = 0.25

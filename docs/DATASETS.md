# Datasets

Every dataset is fetched from its real provider, cached under `data/raw/`, and recorded in
`data/raw/manifest.json` with source URL, retrieval timestamp, byte size, SHA-256, provider
version and **data nature**. Provider failures raise `DataUnavailable`; they are reported in
the API (`GET /api/datasets/status`), the UI and the PDF report — never silently replaced.

| Dataset | Provider / access | Nature | Used for | Licence |
|---|---|---|---|---|
| HydroBASINS v1c, level 12 (Asia) | HydroSHEDS — `data.hydrosheds.org` (zip, ~80 MB) | remotely sensed (SRTM-derived) | Catchment polygons, area, topology | HydroSHEDS licence (free, attribution) |
| HydroRIVERS v1.0 (Asia) | HydroSHEDS (zip, ~90 MB) | remotely sensed (derived) | Drainage-density proxy (rivers ≥10 km² upstream) | HydroSHEDS licence |
| Copernicus DEM GLO-90 | ESA/Airbus via AWS Open Data (`copernicus-dem-90m` COGs, 1°×1° tiles) | remotely sensed (TanDEM-X) | Elevation, slope, relief, ruggedness | Copernicus DEM licence |
| CHIRPS v2.0 daily, 0.05° | UCSB Climate Hazards Center, bbox subset via IRI/LDEO Data Library | observed + remotely sensed | Daily rainfall regime, extremes, antecedent rain, concentration | Public domain |
| ERA5 hourly precipitation & ERA5-Land soil moisture | ECMWF/C3S via Open-Meteo archive API | model-derived (reanalysis) | Sub-daily intensity, monsoon soil moisture | Copernicus licence |
| ESA WorldCover 2021 v200 | ESA, COG on AWS (read at ~80 m via overviews) | remotely sensed | Land-cover fractions | CC BY 4.0 |
| SoilGrids 2.0 | ISRIC WCS (250 m) | model-derived | Topsoil clay/sand/SOC (infiltration-related proxies) | CC BY 4.0 |
| geoBoundaries gbOpen IND ADM1/ADM2 | William & Mary geoLab API | administrative | Study region and district polygons | ODbL 1.0 |
| India Flood Inventory v3 | HydroSense Lab, IIT Delhi + IMD (GitHub) | observed / reported | Independent validation (district-level) | Open, cite Saharia et al. 2021 |
| DFO Global Active Archive | Dartmouth Flood Observatory (ArcGIS FeatureServer mirror) | observed / reported | Independent validation (regional extents; displayed, not used in default metrics) | Research/education |
| Gauged discharge | CWC / India-WRIS, GRDC | observed | **Not available** — restricted access | — |

## Acquisition procedure

```bash
cd backend
python -m app.cli acquire --region uttarakhand --period 2001-2020
python -m app.cli acquire --region himachal --period 2001-2020
```

or from the UI (Explore → *Acquire & prepare data*), or `POST /api/data/acquire`.
Approximate cache size: ~0.5 GB per region. CHIRPS via the IRI Data Library is the slow step
— each year is requested as four quarterly bbox subsets (the server drops long full-year requests),
cached under `data/raw/chirps/<region>/parts/`, merged and integrity-checked. It runs once. If the
connection is flaky, `python -m app.fetch_chirps` keeps retrying missing years.

No API keys are required. Optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `HILLSCOPE_DATA_DIR` | `./data` | Cache / database location |
| `HILLSCOPE_DB_URL` | `sqlite:///data/hillscope.db` | SQLAlchemy URL (e.g. `postgresql+psycopg://…`) |

## Integrity checks

* CRS: all vectors are EPSG:4326; area/length computed in EPSG:6933 (equal-area).
* CHIRPS NetCDF files are opened and checked for a complete year (≥365 daily grids) before caching.
* Duplicate detection: catchment IDs (HYBAS_ID) and event IDs are unique (tested).
* Spatial coverage: catchments must lie within the region bbox; `SUB_AREA` vs geometry area agree (tested).
* Temporal coverage: the daily series must cover every day of the selected period (tested).
* Units: elevations in metres (plausibility bounds), rainfall mm/day ≥0 and <1000, land-cover fractions sum to ~1.
* Missing values: CHIRPS cells with negative fill are NaN; catchment means require ≥50 % valid area weight.
* Invalid source geometries (2 HydroBASINS polygons in Himachal) are repaired with `make_valid`.

## Known provider caveats

* **CARTO basemaps** now require an API key; the UI uses Esri Dark Gray / World Imagery tiles instead.
* **Open-Meteo** does not serve ERA5-Land precipitation, so hourly precipitation comes from ERA5 (0.25°); soil moisture is ERA5-Land.
* **India Flood Inventory** has no coordinates for Himachal/Uttarakhand records; events are geolocated by matching district names
  (alias table in `app/data/events.py`) to geoBoundaries ADM2 polygons. Unmatched records are kept with `spatial_precision = state`
  and excluded from catchment-level metrics.
* **Dartmouth Flood Observatory** extents are large (often whole states); they are stored with `spatial_precision = regional`.

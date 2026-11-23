# Architecture

```
frontend/  React 19 + TypeScript + Vite + Tailwind 4 + MapLibre GL + Recharts
backend/   FastAPI + SQLAlchemy (SQLite → PostgreSQL-ready) + scikit-learn/hdbscan + GeoPandas/Rasterio/Xarray
data/      raw/ (provider caches + manifest.json) · processed/ (per-region features, runs/) · models/ · reports/
docs/      DATASETS · METHODOLOGY · ARCHITECTURE
```

## Backend modules

| Module | Responsibility |
|---|---|
| `app/config.py` | Paths, study regions, periods, provider URLs |
| `app/data/common.py` | Cached downloads, retries, provenance manifest, `DataUnavailable` |
| `app/data/vector.py` | geoBoundaries, HydroBASINS (bbox read from zip), HydroRIVERS |
| `app/data/raster.py` | Copernicus DEM mosaic + slope, WorldCover COG overviews, SoilGrids WCS, zonal stats (rasterise + bincount) |
| `app/data/rainfall.py` | CHIRPS IRI subsets, sparse area-weight matrix → catchment daily series; ERA5/ERA5-Land via Open-Meteo |
| `app/data/events.py` | IFI v3 district geolocation, DFO FeatureServer |
| `app/features/engineering.py` | Feature catalogue (metadata + nature), base (period-independent) and period features, proxies |
| `app/features/preprocessing.py` | Missingness, log transform, redundancy pruning, robust scaling |
| `app/ml/algorithms.py` | Five algorithms, sweeps, metrics, bootstrap stability, selection score, dendrogram |
| `app/ml/interpretation.py` | Profiles and labels from measured distributions, elevation baseline, PCA |
| `app/validation/historical.py` | Event filtering, spatial association, Kruskal–Wallis ε², windows |
| `app/pipeline.py` | Orchestration with real stage callbacks, model persistence (joblib), result JSON |
| `app/jobs.py` | Single-worker background executor; job stages persisted in DB for polling |
| `app/reports/pdf.py` | ReportLab + Matplotlib scientific report |
| `app/main.py` | REST API |
| `app/cli.py` | `acquire`, `run`, `status` commands |

### Caching layers

1. `data/raw/**` — provider files (never re-downloaded; SHA-256 in manifest).
2. `processed/<region>/base_features.gpkg` — terrain, land cover, soil per catchment.
3. `processed/<region>/chirps_catchment_daily_<start>_<end>.parquet` and `features_<period>.gpkg`.
4. `processed/runs/<run_id>.json` + `models/<run_id>.joblib` + `runs` table — replayable experiments.

A cold discovery (data cached) takes ≈ 25–40 s on a laptop, dominated by bootstrap stability.

### Job model

`POST /api/clustering/run` returns `202 {job_id}`; the work runs on a background thread so normal
requests stay responsive. Pipeline code calls `progress(stage, message)` as it actually works;
these messages are stored on the job and rendered verbatim by the UI. Jobs interrupted by a
restart are marked failed on startup.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness |
| GET | `/api/regions` | regions, periods, feature sets, preparation state |
| GET | `/api/features` | feature catalogue with nature labels |
| GET | `/api/datasets/status?region=` | provenance, cache status, provider issues |
| GET | `/api/catchments?region=` | simplified GeoJSON with base attributes |
| GET | `/api/catchments/{id}?region=&period=&run_id=` | feature values, percentiles, assignment |
| GET | `/api/events?region=` | event footprints + points |
| GET | `/api/events/districts?region=&start=&end=&flash_only=` | district event counts for the map |
| POST | `/api/data/acquire` | job: download + prepare region |
| POST | `/api/features/extract` | job: build period features |
| POST | `/api/clustering/run` | job: full discovery pipeline |
| GET | `/api/jobs/{id}` | job status and real stage log |
| GET | `/api/clustering/algorithms` | algorithm descriptions |
| GET | `/api/clustering/results/{run_id}` | full result |
| GET | `/api/clusters/{cluster_id}?run_id=` | profile, members, validation |
| GET | `/api/validation/historical?run_id=&window=&event_type=` | association statistics |
| GET | `/api/validation/baseline?run_id=` | clusters vs elevation baseline |
| GET | `/api/experiments?region=&page=&page_size=` | paginated run history |
| POST | `/api/reports/generate` | build PDF |
| GET | `/api/reports` · `/api/reports/{id}` | list / download PDF |

Interactive docs: `http://127.0.0.1:8000/docs`.

## Frontend

One persistent MapLibre map (`components/MapView.tsx`) is shared by all pages; pages render
compact floating panels over it. Four sections only: **Explore**, **Discover**, **Validate**,
**Reports**. A guided demo (`components/DemoGuide.tsx`) drives the real UI and triggers the real
pipeline. Basemaps: Esri Dark Gray / World Imagery; terrain hillshade from AWS Terrain Tiles.

## PostgreSQL / PostGIS

All persistence goes through SQLAlchemy with portable column types (JSON, DateTime). Set
`HILLSCOPE_DB_URL` to a PostgreSQL URL. Geometry currently lives in GeoPackage/Parquet caches;
moving catchments to PostGIS is a matter of `GeoDataFrame.to_postgis` in `build_base`.

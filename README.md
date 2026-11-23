# HillScope AI

**Intelligent catchment behaviour discovery for flash-flood susceptibility in hilly regions.**

Hill catchments that receive similar rainfall can respond very differently. HillScope AI uses
**unsupervised machine learning** on real terrain, rainfall and land-surface data to discover
groups of Himalayan catchments with similar behaviour, explains what makes each group different,
and checks — independently — whether those groups relate to recorded floods better than a simple
elevation-band grouping.

> HillScope discovers behavioural similarity and *potential* susceptibility patterns. It does not
> predict flash floods, and clustering does not establish causation. No observed discharge is
> available for these catchments; hydrological response is represented by clearly labelled
> **estimated** proxies.

## What's inside

* **Real data only** — HydroBASINS L12 catchments, Copernicus GLO-90 DEM, CHIRPS v2.0 daily rainfall
  (2001–2020), ERA5/ERA5-Land, ESA WorldCover, SoilGrids, HydroRIVERS, India Flood Inventory (IMD),
  Dartmouth Flood Observatory. See [docs/DATASETS.md](docs/DATASETS.md).
* **~36 documented features** in terrain, rainfall, surface and response-proxy groups, each tagged
  observed / remotely sensed / model-derived / estimated.
* **Five unsupervised algorithms** — K-Means, Ward hierarchical, DBSCAN, HDBSCAN, Gaussian Mixture —
  with hyperparameter sweeps, silhouette / Davies–Bouldin / Calinski–Harabasz, bootstrap stability,
  and defensible model selection that never uses flood records.
* **Mandatory elevation-band baseline**, compared on internal metrics and event association.
* **Independent historical validation** (concurrent and out-of-period windows, all floods vs
  flash-flood/cloudburst records).
* **Interactive map app** with four sections — Explore, Discover, Validate, Reports — a guided demo,
  and PDF scientific reports.
* Methodology and limitations: [docs/METHODOLOGY.md](docs/METHODOLOGY.md) · Architecture & API:
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requirements

* Python 3.11+ (tested on 3.13) with GDAL-backed wheels for rasterio/pyogrio (standard pip wheels work on Windows, macOS, Linux)
* Node.js 20+ (tested on 26)
* Internet access for the first data acquisition (~0.5 GB per region, no API keys needed)

## Run locally

### 1. Backend

```bash
cd backend
python -m pip install -r requirements.txt
```

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API docs: http://127.0.0.1:8000/docs

### 2. Acquire real data (one time, cached)

From the UI (Explore → *Acquire & prepare data*) or the CLI:

```bash
cd backend
python -m app.cli acquire --region uttarakhand --period 2001-2020
```

```bash
python -m app.cli acquire --region himachal --period 2001-2020
```

CHIRPS rainfall (via the IRI Data Library) is the slow step — roughly 2–3 minutes per region-year,
four years in parallel. Everything is cached under `data/raw` with a provenance manifest; later runs
reuse it. `python -m app.cli status --region uttarakhand` shows what is cached.

### 3. Frontend

```bash
cd frontend
npm install
```

```bash
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api` to `127.0.0.1:8000`.

### 4. Demo walkthrough

Click **Demo** (bottom of the left rail). It walks through: real region map → configuration →
**Discover Groups** (runs the real pipeline, ~30 s) → inspect and compare groups → historical
validation vs elevation baseline → PDF report. Previously computed experiments can be replayed
instantly ("Replay cached experiment" in Discover, or Reports → Experiment history); cached results
are labelled with their computation time and dataset version.

## Tests

```bash
cd backend
python -m pytest -q
```

Unit tests cover preprocessing, all algorithms, metrics, noise handling, reproducibility, baseline,
model persistence, rainfall indices (incl. no look-ahead), geometry, zonal statistics, event
association and API validation/failure handling. Tests marked `realdata` check schemas, CRS,
duplicates, spatial/temporal coverage and units on the cached real datasets, and run the full
end-to-end workflow (clustering job → results → validation → baseline → PDF). They skip
automatically if the data has not been acquired.

```bash
cd frontend
npm test
```

Frontend tests cover navigation, map rendering mode, catchment selection, the discovery workflow,
cluster highlighting/comparison, validation view and report download.

## Project layout

```
backend/app     data ingestion · features · ml · validation · reports · API · jobs · CLI
backend/tests   pytest suites
frontend/src    React app (pages/, components/, api.ts, store.tsx)
data/           caches, SQLite DB, models, reports (git-ignored)
docs/           DATASETS.md · METHODOLOGY.md · ARCHITECTURE.md
```

## Citation of data

Lehner & Grill 2013 (HydroSHEDS); Funk et al. 2015 (CHIRPS); Muñoz-Sabater et al. 2021 (ERA5-Land);
Hersbach et al. 2020 (ERA5); Zanaga et al. 2022 (WorldCover); Poggio et al. 2021 (SoilGrids 2.0);
Saharia et al. 2021 (India Flood Inventory); Brakenridge, Dartmouth Flood Observatory;
Runfola et al. 2020 (geoBoundaries); Copernicus DEM © DLR/Airbus, provided under COPERNICUS by the
European Union and ESA.

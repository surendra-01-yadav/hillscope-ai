# Scientific methodology and limitations

## 1. Question

Do hill catchments that receive comparable rainfall fall into distinct *behavioural* groups —
combinations of terrain form, rainfall regime and land surface that plausibly govern how
quickly and strongly they respond — and do those groups relate to independently recorded floods
better than a naive elevation grouping?

The system discovers **similarity and potential susceptibility patterns**. It does not forecast
flash floods, and clustering does not establish causation.

## 2. Units of analysis

HydroBASINS level-12 sub-basins (median ≈ 135 km²) whose representative point lies inside the
state (geoBoundaries ADM1). Exclusions, applied before any modelling:

* mean elevation < 500 m (plains — outside the "hill" question),
* slivers < 10 km² (clipped at the region edge; zonal statistics unreliable).

Uttarakhand: 386 → 322 catchments. Himachal Pradesh: 427 → 386.

## 3. Features

All features carry a nature label: *observed*, *remotely sensed*, *model-derived*, or *estimated*.

| Group | Features |
|---|---|
| Terrain (DEM, HydroBASINS, HydroRIVERS) | area, mean elevation, elevation range, mean slope, slope variability, steep share (>30°), Melton ruggedness (relief/√area), hypsometric integral, drainage density, Gravelius compactness, elongation |
| Rainfall (CHIRPS, period-specific) | mean annual & daily rainfall, Rx1day/Rx3day/Rx7day (median of annual maxima), SDII intensity, days ≥50 mm, wet-day CV, inter-annual CV, 7-day antecedent rainfall before annual maxima, Precipitation Concentration Index, monsoon share |
| Rainfall (ERA5, model) | P99 hourly precipitation, peak-hour share of wet-day rainfall |
| Surface | WorldCover fractions (tree, grass/shrub/moss, crop, built, bare+snow/ice), SoilGrids clay/sand/SOC 0–5 cm, ERA5-Land monsoon soil moisture |
| Response proxies (**estimated**) | Kirpich time of concentration using Hack's-law flow length; Rx1day / Tc ("rapid-response proxy") |

**No observed discharge** is available (CWC/India-WRIS data are restricted; GRDC requires a
request). Peak discharge, lag, recession and runoff ratios are therefore *not* computed. The two
response proxies are formula-based estimates from terrain and rainfall and are labelled as such
everywhere; they must not be read as measured hydrological response.

**Leakage control.** Rainfall indices use only days inside the selected period; antecedent
rainfall uses strictly preceding days. Historical events are never used in features, fitting or
model selection.

## 4. Preprocessing (`app/features/preprocessing.py`)

1. Drop features with >20 % missing or constant values; median-impute remaining gaps.
2. `log1p` for non-negative features with skewness > 1.
3. Redundancy pruning: if |Spearman ρ| > 0.9, keep the earlier feature in the documented priority order
   (e.g. `steep_frac` is dropped in favour of `slope_mean`, ρ≈0.99).
4. Robust scaling (median / IQR), winsorised at ±5; outliers (|z|>3.5) are counted and reported.

## 5. Unsupervised models (`app/ml/algorithms.py`)

| Model | Sweep | Notes |
|---|---|---|
| K-Means | k = 2…8, n_init = 20 | inertia, silhouette, DB, CH |
| Agglomerative (Ward) | k = 2…8 | dendrogram (truncated) |
| DBSCAN | min_samples ∈ {d/2, d+1, 2d}, ε from k-distance quantiles {0.5…0.9} | fitted in PCA space (85 % variance) |
| HDBSCAN (`hdbscan` library) | min_cluster_size ∈ {n/40, n/20, n/12}, min_samples ∈ {1,3,8} | persistence & membership probabilities; PCA space |
| Gaussian Mixture | k = 2…8, full/diag covariance | BIC, AIC, membership probabilities |

Density methods are fitted on principal components because distance concentration in ~30
dimensions makes density estimates meaningless; their *metrics* are still computed in the full
scaled space for comparability.

**Evaluation**: silhouette, Davies–Bouldin, Calinski–Harabasz, separation ratio, cluster-size
distribution, noise share, and **bootstrap stability** (mean ARI between full-data labels and
labels refitted on 15 × 80 % subsamples).

**Selection** (per algorithm and overall) uses a composite internal score:
`0.40·silhouette + 0.35·stability − 0.10·DB/3`, penalising clusters < 5 % of catchments,
noise > 15 %, k = 2 (uninformative) and k > 6 (uninterpretable). Silhouette alone is not used,
and historical events are never consulted.

**Baseline (mandatory)**: elevation tertiles of catchment mean elevation (Lower/Middle/Higher),
plus elevation bands with the same k as the clustering, evaluated with the same internal metrics
and the same event-association statistics.

## 6. Interpretation (`app/ml/interpretation.py`)

For each cluster, the median of every feature is compared with the regional median in IQR units
(robust z). The five largest |z| are the *distinguishing characteristics*. Plain-language
traits (e.g. "steep", "extreme-rainfall", "glaciated/bare") are derived from those, and a
profile name is chosen by rule from the traits **after** clustering. If no feature deviates by
≥0.35 IQR, the group is labelled "Mixed / transitional". Response wording ("rapid-response",
"slower-response") is used only when the estimated response proxies themselves differ by ≥0.5 IQR;
otherwise terrain-only names are used (e.g. "Steep, rugged terrain", "Gentler, cultivated lower hills").
Names describe behaviour, not risk.

PCA (2 components) is shown only as a dimensionality-reduction view; distances in that plot are
feature-space distances, not geography.

## 7. Historical validation (`app/validation/historical.py`)

* Events: IFI v3 records geolocated to districts (`spatial_precision = district`). Statewide
  records (≥75 % of districts) and unmatched records are excluded from metrics.
* Association: a catchment is associated with an event if its representative point lies in the
  event footprint (union of affected districts).
* Per group: catchments, distinct events, catchments with events, association rate,
  events per catchment-year, lift vs regional mean, districts spanned.
* Strength: Kruskal–Wallis H on per-catchment event counts across groups and the rank effect size
  ε² = (H − k + 1)/(n − k). Computed identically for clusters, elevation tertiles and same-k bands.
* Windows: **concurrent** (same years as the rainfall features) and **out-of-period**
  (years after the feature window up to 2023) to separate temporal overlap from association.
* Event types: all floods, and flash-flood/cloudburst records (keyword match on cause/location).

## 8. Limitations

1. No measured discharge; response features are estimates.
2. CHIRPS (~5 km) under-resolves convective cloudbursts; ERA5 hourly precipitation is 0.25° reanalysis over JJAS 2018–2020 only (API quota).
3. Validation resolution is district-scale; all catchments in an affected district share an event.
   This favours groupings that align with district geography (elevation often does).
4. Event reporting is incomplete and uneven over time (more records after 2019); absence of a
   record is not evidence of safety.
5. Spatial autocorrelation: neighbouring catchments are not independent; p-values are indicative.
6. SoilGrids and WorldCover are infiltration-related proxies, not measured infiltration.
7. Geophysical feature spaces are often continua; DBSCAN/HDBSCAN find weak density structure
   here, which is itself a finding: groups are a useful partition, not discrete natural types.
8. HydroRIVERS only contains rivers with ≥10 km² upstream area, so drainage density is a coarse proxy.

## 9. Distinguishing the three kinds of evidence

| | What it is | Where |
|---|---|---|
| Unsupervised discovery | Clusters fitted only on features | Discover page, `selected`, `comparison` |
| External historical validation | Post-hoc association with independent event records | Validate page, `validation` |
| Predictive performance | **None claimed** — no predictive model has been built or validated | — |

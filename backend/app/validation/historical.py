"""Post-clustering historical validation against independent flood records.

Historical events are used ONLY here, after clustering. The output measures
*association* between discovered groups and recorded events; it is not
predictive skill, and absence of a recorded event is not evidence of safety.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.stats import kruskal

PRECISION_ORDER = ["district", "regional", "state-wide", "state"]


def filter_events(events: gpd.GeoDataFrame, start: int, end: int, *, flash_only: bool = False,
                  precisions: tuple[str, ...] = ("district",)) -> gpd.GeoDataFrame:
    e = events[events.geometry.notna() & ~events.geometry.is_empty].copy()
    yr = pd.to_datetime(e["start_date"]).dt.year
    e = e[(yr >= start) & (yr <= end)]
    e = e[e["spatial_precision"].isin(precisions)]
    if flash_only:
        e = e[e["flash_type"].astype(bool)]
    return e


def catchment_event_counts(catchments: gpd.GeoDataFrame, events: gpd.GeoDataFrame) -> tuple[np.ndarray, pd.DataFrame]:
    """Events associated with each catchment (representative point within event footprint)."""
    pts = gpd.GeoDataFrame({"cidx": np.arange(len(catchments))}, geometry=catchments.representative_point().values,
                           crs=catchments.crs)
    if events.empty:
        return np.zeros(len(catchments), dtype=int), pd.DataFrame(columns=["cidx", "event_id"])
    j = gpd.sjoin(pts, events[["event_id", "geometry"]], predicate="within", how="inner")
    pairs = j[["cidx", "event_id"]].drop_duplicates()
    counts = np.bincount(pairs["cidx"].values, minlength=len(catchments))
    return counts, pairs


def group_association(labels: np.ndarray, counts: np.ndarray, pairs: pd.DataFrame, n_years: int,
                      districts: np.ndarray | None = None, names: dict | None = None) -> dict:
    groups = []
    overall_rate = counts.mean() / max(n_years, 1)
    for g in sorted(set(labels)):
        m = labels == g
        idx = np.where(m)[0]
        ev = pairs[pairs["cidx"].isin(idx)]["event_id"].nunique() if len(pairs) else 0
        rate = counts[m].mean() / max(n_years, 1)
        groups.append({
            "group": int(g), "name": (names or {}).get(int(g), f"Group {g}"),
            "n_catchments": int(m.sum()),
            "n_events": int(ev),
            "catchments_with_events": int((counts[m] > 0).sum()),
            "association_rate": round(float((counts[m] > 0).mean()), 3),
            "events_per_catchment": round(float(counts[m].mean()), 3),
            "events_per_catchment_year": round(float(rate), 4),
            "lift": round(float(rate / overall_rate), 3) if overall_rate > 0 else None,
            "districts_spanned": int(len(set(districts[m]))) if districts is not None else None,
        })
    valid = [g for g in sorted(set(labels)) if g >= 0]
    samples = [counts[labels == g] for g in valid if (labels == g).sum() > 0]
    H = p = eps2 = None
    n = int(sum(len(s) for s in samples))
    k = len(samples)
    if k >= 2 and len(np.unique(counts)) > 1:
        H, p = kruskal(*samples)
        eps2 = (H - k + 1) / (n - k) if n > k else None
    rates = [g["events_per_catchment_year"] for g in groups if g["group"] >= 0]
    return {
        "groups": groups,
        "kruskal_H": None if H is None else round(float(H), 3),
        "kruskal_p": None if p is None else float(p),
        "epsilon_squared": None if eps2 is None else round(float(max(eps2, 0.0)), 4),
        "rate_ratio_max_min": round(max(rates) / min(rates), 3) if rates and min(rates) > 0 else None,
        "overall_events_per_catchment_year": round(float(overall_rate), 4),
    }


def validate(catchments: gpd.GeoDataFrame, labels: np.ndarray, baseline_labels: np.ndarray,
             baseline_k_labels: np.ndarray, events: gpd.GeoDataFrame, period: dict, *,
             names: dict, baseline_names: dict, districts: np.ndarray | None = None,
             event_end_year: int = 2023) -> dict:
    """Run concurrent- and out-of-period validation for clusters and both baselines."""
    windows = {
        "concurrent": (period["start"], period["end"]),
        "out_of_period": (period["end"] + 1, event_end_year),
    }
    out = {"windows": {}, "notes": NOTES}
    for wname, (a, b) in windows.items():
        if a > b:
            continue
        res = {"years": [a, b]}
        for flash in (False, True):
            ev = filter_events(events, a, b, flash_only=flash)
            counts, pairs = catchment_event_counts(catchments, ev)
            n_years = b - a + 1
            key = "flash" if flash else "all"
            res[key] = {
                "n_events": int(len(ev)),
                "n_events_matched": int(pairs["event_id"].nunique()) if len(pairs) else 0,
                "catchments_with_events": int((counts > 0).sum()),
                "spatial_coverage": round(float((counts > 0).mean()), 3),
                "clusters": group_association(labels, counts, pairs, n_years, districts, names),
                "baseline": group_association(baseline_labels, counts, pairs, n_years, districts, baseline_names),
                "baseline_same_k": group_association(baseline_k_labels, counts, pairs, n_years, districts),
                "counts": counts.tolist(),
            }
        out["windows"][wname] = res
    return out


NOTES = [
    "Historical events were not used for feature selection, clustering, or model selection.",
    "Association measures co-occurrence of recorded events with discovered groups; it is not predictive accuracy.",
    "IFI events are geolocated to districts, so all catchments in an affected district share an event; "
    "validation resolution is therefore district-scale.",
    "Absence of a recorded event does not imply a catchment is safe — reporting coverage is uneven.",
    "Spatial autocorrelation means neighbouring catchments are not independent; p-values are indicative only.",
    "Out-of-period validation uses events after the rainfall feature window to avoid temporal overlap.",
]

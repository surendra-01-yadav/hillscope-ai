"""Cluster interpretation, elevation-band baseline and PCA projection.

Profile labels are assigned AFTER clustering from the measured feature
distributions (cluster median vs regional median, in robust-z units). They
describe behaviour (e.g. "steep, rapid-response terrain"), and are not risk
categories.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from ..features.engineering import FEATURE_MAP

# Interpretable labels triggered by the strongest distinguishing features.
# (feature, direction) -> (label, plain-language trait)
TRAITS = {
    ("flashiness_proxy", 1): "rapid-response", ("tc_kirpich_h", -1): "rapid-response",
    ("melton", 1): "rugged", ("slope_mean", 1): "steep", ("steep_frac", 1): "steep",
    ("elev_mean", 1): "high-altitude", ("lc_bare_snow", 1): "glaciated/bare",
    ("rx1day", 1): "extreme-rainfall", ("rx3day", 1): "extreme-rainfall", ("r50_days", 1): "extreme-rainfall",
    ("sdii", 1): "intense-rainfall", ("rain_annual", 1): "wet", ("rain_annual", -1): "dry",
    ("wet_cv", 1): "high-variability", ("annual_cv", 1): "high-variability", ("pci", 1): "seasonally-concentrated",
    ("slope_mean", -1): "gentle", ("melton", -1): "subdued", ("tc_kirpich_h", 1): "slower-response",
    ("flashiness_proxy", -1): "slower-response", ("lc_tree", 1): "forested", ("lc_crop", 1): "cultivated",
    ("lc_built", 1): "urbanising", ("area_km2", 1): "large", ("elev_mean", -1): "lower-hill",
    ("era5_p_hourly_p99", 1): "intense-hourly-rainfall", ("api7_before_max", 1): "wet-antecedent",
    ("rx1day", -1): "low-extreme-rainfall", ("rx3day", -1): "low-extreme-rainfall", ("rx7day", -1): "low-extreme-rainfall",
    ("r50_days", -1): "low-extreme-rainfall", ("sdii", -1): "low-extreme-rainfall",
}

PROFILE_RULES = [
    ({"rapid-response", "steep", "rugged"}, "Rapid-response steep terrain"),
    ({"extreme-rainfall", "intense-rainfall", "wet", "intense-hourly-rainfall"}, "High rainfall-extreme exposure"),
    ({"high-altitude", "glaciated/bare"}, "High-altitude glaciated terrain"),
    ({"high-variability", "seasonally-concentrated"}, "High rainfall-variability"),
    ({"gentle", "subdued", "slower-response", "lower-hill", "cultivated", "urbanising"}, "Gentler, slower-response hills"),
    ({"forested"}, "Forested mid-hills"),
    ({"dry", "low-extreme-rainfall"}, "Lower rainfall-exposure catchments"),
]


def profile_clusters(df: pd.DataFrame, labels: np.ndarray, features: list[str]) -> list[dict]:
    """Per-cluster statistics and a data-derived profile label."""
    data = df[features].astype(float)
    med = data.median()
    iqr = (data.quantile(0.75) - data.quantile(0.25)).replace(0, np.nan)
    iqr = iqr.fillna(data.std()).replace(0, 1.0)
    profiles = []
    used_names: dict[str, int] = {}
    for c in sorted(set(labels)):
        m = labels == c
        sub = df.loc[m]
        cm = data.loc[m].median()
        z = ((cm - med) / iqr).replace([np.inf, -np.inf], 0).fillna(0)
        order = z.abs().sort_values(ascending=False)
        top = []
        for k in order.index[:5]:
            f = FEATURE_MAP.get(k)
            top.append({"feature": k, "label": f.label if f else k, "z": round(float(z[k]), 2),
                        "direction": "higher" if z[k] > 0 else "lower",
                        "cluster_median": round(float(cm[k]), 3), "region_median": round(float(med[k]), 3),
                        "unit": f.unit if f else "", "nature": f.nature if f else ""})
        if c < 0:
            name, traits = "Unusual catchments (noise)", ["atypical feature combination"]
        else:
            traits = []
            for k in order.index[:6]:
                if abs(z[k]) < 0.35:
                    continue
                t = TRAITS.get((k, 1 if z[k] > 0 else -1))
                if t and t not in traits:
                    traits.append(t)
            name = "Mixed / transitional"
            best = 0
            for keys, label in PROFILE_RULES:
                # Score rules by summed |z| of supporting traits among the top features.
                score = sum(1.0 / (i + 1) for i, t in enumerate(traits) if t in keys)
                if score > best:
                    best, name = score, label
            # Response wording only when the (estimated) response proxies themselves support it.
            resp = float(z.get("flashiness_proxy", 0)) - float(z.get("tc_kirpich_h", 0))
            if name == "Rapid-response steep terrain" and resp < 0.5:
                name = "Steep, rugged terrain"
            if name == "Gentler, slower-response hills" and resp > -0.5:
                name = "Gentler, cultivated lower hills" if ({"cultivated", "urbanising"} & set(traits)) else "Gentler lower hills"
            if order.iloc[0] < 0.35:
                name = "Mixed / transitional"
            used_names[name] = used_names.get(name, 0) + 1
        summary = _sentence(top[:3])
        stats = {}
        for k in ["elev_mean", "slope_mean", "area_km2", "rain_annual", "rx1day", "rx3day", "sdii",
                  "melton", "tc_kirpich_h", "flashiness_proxy", "lc_tree", "lc_bare_snow"]:
            if k in df.columns:
                v = sub[k].astype(float)
                stats[k] = {"median": _r(v.median()), "p25": _r(v.quantile(0.25)), "p75": _r(v.quantile(0.75)),
                            "mean": _r(v.mean())}
        profiles.append({  # names made unique after the loop
            "cluster": int(c), "name": name, "traits": traits, "n_catchments": int(m.sum()),
            "share": round(float(m.mean()), 3), "summary": summary, "distinguishing": top, "stats": stats,
            "z_profile": {k: round(float(z[k]), 3) for k in features},
        })
    _disambiguate(profiles)
    return profiles


def _disambiguate(profiles: list[dict]) -> None:
    """When two groups receive the same rule name, qualify each by its strongest own distinguishing feature."""
    from collections import Counter
    counts = Counter(p["name"] for p in profiles if p["cluster"] >= 0)
    base = {id(p): p["name"] for p in profiles}
    new_names = {}
    for p in profiles:
        if p["cluster"] < 0 or counts[base[id(p)]] < 2:
            continue
        others = [q for q in profiles if base[id(q)] == base[id(p)] and q is not p]
        # pick the feature on which this group differs most from its namesakes
        # Ignore the features that define the shared name; qualify by what else separates them.
        rule_traits = next((keys for keys, label in PROFILE_RULES if base[id(p)].startswith(label.split(",")[0])), set())
        shared = {k for (k, _d), t in TRAITS.items() if t in rule_traits} | {"tc_kirpich_h", "flashiness_proxy"}
        cands = [k for k in p["z_profile"] if k not in shared] or list(p["z_profile"])
        best = max(cands, key=lambda k: min(abs(p["z_profile"][k] - q["z_profile"].get(k, 0)) for q in others))
        f = FEATURE_MAP.get(best)
        direction = "higher" if all(p["z_profile"][best] > q["z_profile"].get(best, 0) for q in others) else "lower"
        new_names[id(p)] = f"{base[id(p)]} · {direction} {(f.label if f else best).lower()}"
    for p in profiles:
        p["name"] = new_names.get(id(p), p["name"])


def _r(v):
    return None if pd.isna(v) else round(float(v), 3)


def _sentence(top: list[dict]) -> str:
    bits = []
    for t in top:
        mag = "much " if abs(t["z"]) >= 1.5 else ""
        bits.append(f"{mag}{t['direction']} {t['label'].lower()}")
    return ("Compared with the region: " + ", ".join(bits) + ".") if bits else "Close to regional medians."


def elevation_bands(elev: np.ndarray, n_bands: int = 3) -> tuple[np.ndarray, list[dict]]:
    """Mandatory baseline: equal-count elevation tertiles of catchment mean elevation."""
    qs = np.quantile(elev, np.linspace(0, 1, n_bands + 1))
    labels = np.clip(np.searchsorted(qs[1:-1], elev, side="right"), 0, n_bands - 1)
    names = ["Lower elevation", "Middle elevation", "Higher elevation"] if n_bands == 3 else [f"Band {i+1}" for i in range(n_bands)]
    bands = [{"band": i, "name": names[i], "min_m": round(float(qs[i]), 1), "max_m": round(float(qs[i + 1]), 1),
              "n_catchments": int((labels == i).sum())} for i in range(n_bands)]
    return labels.astype(int), bands


def pca_projection(X: np.ndarray) -> dict:
    p = PCA(n_components=min(2, X.shape[1]), random_state=0)
    Y = p.fit_transform(X)
    return {"coords": np.round(Y, 4).tolist(), "explained_variance": [round(float(v), 4) for v in p.explained_variance_ratio_],
            "loadings": np.round(p.components_, 4).tolist()}

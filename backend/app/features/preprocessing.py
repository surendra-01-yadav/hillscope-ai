"""Reproducible preprocessing: missing data, skew transforms, redundancy pruning, robust scaling."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import skew
from sklearn.preprocessing import RobustScaler

MAX_MISSING = 0.2
SKEW_THRESHOLD = 1.0
REDUNDANCY_RHO = 0.90
CLIP = 5.0


@dataclass
class PreprocessResult:
    X: np.ndarray
    features: list[str]
    dropped_missing: list[str] = field(default_factory=list)
    dropped_redundant: list[dict] = field(default_factory=list)
    log_transformed: list[str] = field(default_factory=list)
    imputed: dict = field(default_factory=dict)
    outliers: dict = field(default_factory=dict)
    correlation: dict = field(default_factory=dict)
    scaler_center: list[float] = field(default_factory=list)
    scaler_scale: list[float] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "features_used": self.features,
            "dropped_missing": self.dropped_missing,
            "dropped_redundant": self.dropped_redundant,
            "log_transformed": self.log_transformed,
            "imputed_counts": self.imputed,
            "outliers": self.outliers,
            "scaling": "RobustScaler (median / IQR), winsorised at ±5",
            "redundancy_rule": f"|Spearman ρ| > {REDUNDANCY_RHO}: later feature in priority order dropped",
            "skew_rule": f"log1p applied when skewness > {SKEW_THRESHOLD} and values ≥ 0",
        }


def preprocess(df: pd.DataFrame, keys: list[str]) -> PreprocessResult:
    """Transform feature table ``df[keys]`` into a scaled matrix. Feature order = priority."""
    data = df[keys].astype(float).replace([np.inf, -np.inf], np.nan)
    miss = data.isna().mean()
    dropped_missing = [k for k in keys if miss[k] > MAX_MISSING]
    keep = [k for k in keys if k not in dropped_missing]
    data = data[keep]
    # Constant columns carry no information.
    const = [k for k in keep if data[k].nunique(dropna=True) <= 1]
    keep = [k for k in keep if k not in const]
    dropped_missing += const
    data = data[keep]
    imputed = {k: int(v) for k, v in data.isna().sum().items() if v > 0}
    data = data.fillna(data.median())

    logged = []
    for k in keep:
        v = data[k].values
        if v.min() >= 0 and skew(v) > SKEW_THRESHOLD:
            data[k] = np.log1p(v)
            logged.append(k)

    rho = data.corr(method="spearman").fillna(0).values
    dropped_red: list[dict] = []
    selected: list[int] = []
    for i, k in enumerate(keep):
        clash = next((j for j in selected if abs(rho[i, j]) > REDUNDANCY_RHO), None)
        if clash is None:
            selected.append(i)
        else:
            dropped_red.append({"feature": k, "redundant_with": keep[clash], "rho": round(float(rho[i, clash]), 3)})
    feats = [keep[i] for i in selected]
    data = data[feats]

    scaler = RobustScaler(quantile_range=(25, 75))
    X = scaler.fit_transform(data.values)
    scale = scaler.scale_.copy()
    # Guard against zero IQR (e.g., mostly-zero fractions): fall back to std.
    zero = scaler.scale_ == 0
    if zero.any():
        sd = data.values[:, zero].std(axis=0)
        sd[sd == 0] = 1.0
        X[:, zero] = (data.values[:, zero] - scaler.center_[zero]) / sd
        scale[zero] = sd
    n_out = (np.abs(X) > 3.5).sum(axis=0)
    X = np.clip(X, -CLIP, CLIP)
    sub = rho[np.ix_(selected, selected)]
    return PreprocessResult(
        X=X, features=feats, dropped_missing=dropped_missing, dropped_redundant=dropped_red,
        log_transformed=[k for k in logged if k in feats], imputed=imputed,
        outliers={"rule": "|robust z| > 3.5", "per_feature": {f: int(c) for f, c in zip(feats, n_out)},
                  "catchments_with_any": int((np.abs(X) >= 3.5).any(axis=1).sum())},
        correlation={"features": feats, "matrix": np.round(sub, 3).tolist()},
        scaler_center=scaler.center_.tolist(), scaler_scale=scale.tolist(),
    )

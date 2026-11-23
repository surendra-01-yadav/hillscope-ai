"""Test configuration.

Unit tests use small, explicitly constructed fixtures to check algorithm
behaviour (these are test inputs, never displayed as results). Integration
tests marked ``realdata`` run against the cached real datasets and are skipped
when those caches are absent.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Isolate the test database from the application database.
_tmp = tempfile.mkdtemp(prefix="hillscope-test-")
os.environ.setdefault("HILLSCOPE_DB_URL", f"sqlite:///{Path(_tmp, 'test.db').as_posix()}")

REAL_DATA = ROOT.parent / "data" / "processed"


def has_real(region: str, period: str | None = None) -> bool:
    base = REAL_DATA / region / "base_features.gpkg"
    if period is None:
        return base.exists()
    return base.exists() and all((ROOT.parent / "data" / "raw" / "chirps" / region / f"chirps_v2_daily_p05_{y}.nc").exists()
                                 for y in range(int(period[:4]), int(period[-4:]) + 1))


def pytest_configure(config):
    config.addinivalue_line("markers", "realdata: requires cached real datasets")


@pytest.fixture(scope="session")
def blobs():
    """Three well-separated Gaussian blobs plus two far outliers (deterministic)."""
    import numpy as np
    rng = np.random.default_rng(0)
    centers = np.array([[0, 0, 0], [8, 8, 0], [0, 8, 8]], dtype=float)
    X = np.vstack([c + rng.normal(scale=0.6, size=(60, 3)) for c in centers] + [np.array([[30, -30, 30], [-30, 30, -30]])])
    y = np.array([0] * 60 + [1] * 60 + [2] * 60 + [-1, -1])
    return X, y

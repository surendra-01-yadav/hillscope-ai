"""Command-line entry points.

    python -m app.cli acquire --region uttarakhand --period 2001-2020
    python -m app.cli run --region uttarakhand --period 2001-2020 --algorithm kmeans
    python -m app.cli status --region uttarakhand
"""
from __future__ import annotations

import argparse
import json
import logging

from .config import PERIODS, REGIONS


def main() -> None:
    ap = argparse.ArgumentParser(prog="hillscope")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("acquire", "run", "status"):
        p = sub.add_parser(name)
        p.add_argument("--region", choices=list(REGIONS), default="uttarakhand")
        p.add_argument("--period", choices=list(PERIODS), default="2001-2020")
        if name == "run":
            p.add_argument("--algorithm", default="kmeans", choices=["kmeans", "hierarchical", "dbscan", "hdbscan", "gmm", "auto"])
            p.add_argument("--feature-set", default="behavioural")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = lambda s, m: print(f"[{s}] {m}", flush=True)  # noqa: E731
    region, period = REGIONS[a.region], PERIODS[a.period]
    if a.cmd == "acquire":
        from .features.engineering import build_base, build_features
        from .pipeline import acquire
        print(json.dumps(acquire(region, period, log), indent=2))
        build_base(region, lambda m: log("prepare", m))
        build_features(region, period, lambda m: log("features", m))
    elif a.cmd == "run":
        from .pipeline import persist_run, run_discovery
        r = run_discovery(a.region, a.period, a.feature_set, a.algorithm, log)
        persist_run(r, a.feature_set)
        m = r["selected"]["metrics"]
        print(f"run {r['run_id']}: {r['algorithm_name']} k={m['n_clusters']} silhouette={m['silhouette']:.3f}")
    elif a.cmd == "status":
        from .catalog import status
        for d in status(a.region):
            print(f"{d['id']:15s} {d['status']:15s} {d['files']:4d} files  {d['nature']}")


if __name__ == "__main__":
    main()

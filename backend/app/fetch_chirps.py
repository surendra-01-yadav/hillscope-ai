"""Patient CHIRPS fetcher for flaky connections: keeps retrying missing years with low concurrency.

    python -m app.fetch_chirps --regions uttarakhand himachal --start 2001 --end 2020
"""
from __future__ import annotations

import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from .config import RAW_DIR, REGIONS
from .data.common import DataUnavailable
from .data.rainfall import chirps_year


def missing(region: str, start: int, end: int) -> list[int]:
    d = RAW_DIR / "chirps" / region
    return [y for y in range(start, end + 1) if not (d / f"chirps_v2_daily_p05_{y}.nc").exists()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regions", nargs="+", default=list(REGIONS))
    ap.add_argument("--start", type=int, default=2001)
    ap.add_argument("--end", type=int, default=2020)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--passes", type=int, default=30)
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    for p in range(a.passes):
        todo = [(r, y) for r in a.regions for y in missing(r, a.start, a.end)]
        print(f"pass {p + 1}: {len(todo)} region-years missing", flush=True)
        if not todo:
            break

        def one(ry):
            r, y = ry
            try:
                chirps_year(REGIONS[r], y)
                print(f"  ok {r} {y}", flush=True)
            except DataUnavailable as e:
                print(f"  retry later {r} {y}: {e.message[:80]}", flush=True)

        with ThreadPoolExecutor(a.workers) as ex:
            list(ex.map(one, todo))
        time.sleep(30)
    left = {r: missing(r, a.start, a.end) for r in a.regions}
    print("remaining:", left, flush=True)


if __name__ == "__main__":
    main()

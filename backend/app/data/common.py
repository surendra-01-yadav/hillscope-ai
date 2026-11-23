"""Shared helpers for real-data acquisition: cached downloads and a provenance manifest.

Every file fetched from an external provider is recorded in
``data/raw/manifest.json`` with its source URL, retrieval timestamp, size,
SHA-256 hash, provider version and data nature (observed / remotely sensed /
model-derived / estimated). Nothing is ever substituted silently: a failed
provider raises ``DataUnavailable`` which is surfaced to the API and the UI.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from ..config import RAW_DIR, USER_AGENT

log = logging.getLogger("hillscope.data")
_MANIFEST = RAW_DIR / "manifest.json"
_lock = threading.Lock()


class DataUnavailable(RuntimeError):
    """A real data provider could not deliver the requested data."""

    def __init__(self, dataset: str, message: str):
        super().__init__(f"{dataset}: {message}")
        self.dataset = dataset
        self.message = message


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def load_manifest() -> dict:
    if _MANIFEST.exists():
        try:
            return json.loads(_MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("manifest corrupt; starting fresh")
    return {}


def record(key: str, **entry) -> None:
    with _lock:
        m = load_manifest()
        m[key] = {**m.get(key, {}), **entry}
        _MANIFEST.write_text(json.dumps(m, indent=2), encoding="utf-8")


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def download(
    url: str,
    dest: Path,
    *,
    dataset: str,
    nature: str,
    version: str,
    params: dict | None = None,
    retries: int = 4,
    timeout: int = 300,
    validate: Callable[[Path], None] | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Download ``url`` to ``dest`` once; reuse the cached file afterwards."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    key = dest.relative_to(RAW_DIR).as_posix()
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    # Unique temp name per process/thread so concurrent fetches never interleave writes.
    tmp = dest.with_suffix(dest.suffix + f".{os.getpid()}-{threading.get_ident()}.part")
    last_err: Exception | None = None
    s = session()
    for attempt in range(1, retries + 1):
        try:
            if progress:
                progress(f"Downloading {dest.name}")
            with s.get(url, params=params, stream=True, timeout=timeout) as r:
                if r.status_code == 429:
                    raise requests.HTTPError("429 rate limited", response=r)
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for b in r.iter_content(1 << 20):
                        f.write(b)
            if tmp.stat().st_size == 0:
                raise IOError("empty response")
            if validate:
                validate(tmp)
            tmp.replace(dest)
            record(
                key,
                dataset=dataset,
                url=r.url,
                retrieved_at=now_iso(),
                bytes=dest.stat().st_size,
                sha256=sha256(dest),
                version=version,
                nature=nature,
            )
            return dest
        except Exception as e:  # noqa: BLE001 - provider errors are reported, not hidden
            last_err = e
            log.warning("download failed (%s/%s) %s: %s", attempt, retries, url, e)
            if tmp.exists():
                tmp.unlink()
            time.sleep(min(60, 4 * attempt**2))
    raise DataUnavailable(dataset, f"download failed after {retries} attempts: {last_err}")

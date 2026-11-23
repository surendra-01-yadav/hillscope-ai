"""Background job runner so long geospatial/ML work never blocks API requests.

Progress messages are emitted by the real pipeline code as it executes; the
UI displays exactly these messages (no simulated progress).
"""
from __future__ import annotations

import logging
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from .db import Job, SessionLocal

log = logging.getLogger("hillscope.jobs")
# Two workers: a slow data download should not block an analysis on already-cached data.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hillscope-job")
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def recover_interrupted() -> None:
    with SessionLocal() as s:
        for j in s.query(Job).filter(Job.status.in_(["queued", "running"])).all():
            j.status = "failed"
            j.error = "Interrupted: the server restarted before this job finished."
        s.commit()


class JobContext:
    def __init__(self, job_id: str, stage_names: list[tuple[str, str]]):
        self.job_id = job_id
        self.order = [k for k, _ in stage_names]
        self.stages = {k: {"label": lbl, "status": "pending", "messages": [], "started": None, "finished": None}
                       for k, lbl in stage_names}

    def progress(self, stage: str, message: str) -> None:
        with _lock:
            if stage not in self.stages:
                self.stages[stage] = {"label": stage, "status": "pending", "messages": [], "started": None, "finished": None}
                self.order.append(stage)
            idx = self.order.index(stage)
            for k in self.order[:idx]:
                if self.stages[k]["status"] in ("pending", "running"):
                    self.stages[k]["status"] = "done"
                    self.stages[k]["finished"] = self.stages[k]["finished"] or _now()
            st = self.stages[stage]
            if st["status"] == "pending":
                st["status"] = "running"
                st["started"] = _now()
            st["messages"] = (st["messages"] + [{"t": _now(), "m": message}])[-25:]
            snapshot = {k: dict(v) for k, v in self.stages.items()}
        with SessionLocal() as s:
            j = s.get(Job, self.job_id)
            if j:
                j.stage = stage
                j.message = message
                j.stages = snapshot
                s.commit()

    def finish_all(self) -> dict:
        for k in self.order:
            if self.stages[k]["status"] in ("pending", "running"):
                self.stages[k]["status"] = "done" if self.stages[k]["started"] else "skipped"
                self.stages[k]["finished"] = self.stages[k]["finished"] or _now()
        return self.stages


def submit(kind: str, request: dict, stage_names: list[tuple[str, str]],
           fn: Callable[[JobContext], str | None]) -> str:
    job_id = uuid.uuid4().hex[:12]
    ctx = JobContext(job_id, stage_names)
    with SessionLocal() as s:
        s.add(Job(id=job_id, kind=kind, status="queued", request=request, stages=ctx.stages))
        s.commit()

    def runner():
        with SessionLocal() as s:
            j = s.get(Job, job_id)
            j.status = "running"
            s.commit()
        try:
            result_id = fn(ctx)
            stages = ctx.finish_all()
            with SessionLocal() as s:
                j = s.get(Job, job_id)
                j.status, j.result_id, j.stages = "done", result_id, stages
                s.commit()
        except Exception as e:  # noqa: BLE001 - surfaced to the client verbatim
            log.error("job %s failed: %s\n%s", job_id, e, traceback.format_exc())
            with SessionLocal() as s:
                j = s.get(Job, job_id)
                j.status, j.error = "failed", f"{type(e).__name__}: {e}"
                cur = j.stage
                st = dict(ctx.stages)
                if cur in st:
                    st[cur] = {**st[cur], "status": "failed"}
                j.stages = st
                s.commit()

    _executor.submit(runner)
    return job_id


def job_dict(j: Job) -> dict:
    return {"id": j.id, "kind": j.kind, "status": j.status, "stage": j.stage, "message": j.message,
            "stages": j.stages, "request": j.request, "result_id": j.result_id, "error": j.error,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "updated_at": j.updated_at.isoformat() if j.updated_at else None}

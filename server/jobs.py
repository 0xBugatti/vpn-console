"""In-memory background jobs, shared by service actions and tunnel actions.

Long host operations (a tunnel can take ~100 s to connect) run on a worker thread and are
polled at GET /api/jobs/{id}. Jobs live only in memory: a console restart forgets them,
which is fine because the outcome is also written to the audit log.
"""
from __future__ import annotations

import threading
from typing import Any

_jobs: dict[str, dict[str, Any]] = {}
_seq = 0
_lock = threading.Lock()


def create(detail: str) -> str:
    global _seq
    with _lock:
        _seq += 1
        job_id = f"job-{_seq}"
        _jobs[job_id] = {"done": False, "ok": False, "detail": detail}
    return job_id


def update(job_id: str, **fields: Any) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def get(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None

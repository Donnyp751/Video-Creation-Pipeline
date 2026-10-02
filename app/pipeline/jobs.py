"""In-process job queue backed by SQLite.

Long provider calls must not block HTTP requests: the API submits a job and returns its id;
the dashboard polls job status. Phases reported from inside providers (GENERATING,
DOWNLOADING, REVIEWING) are written to the job row. Redis/Celery can replace this later
without changing the services.
"""

from __future__ import annotations

import asyncio
import traceback
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from app.core.db import Database, Job
from app.core.progress import reset_reporter, set_reporter


class JobRunner:
    def __init__(self, db: Database, max_concurrent: int = 4):
        self.db = db
        self._sem = asyncio.Semaphore(max_concurrent)
        self._tasks: set[asyncio.Task] = set()

    def _update(self, job_id: int, **fields) -> None:
        with self.db.Session() as s:
            job = s.get(Job, job_id)
            if job is None:
                return
            for k, v in fields.items():
                setattr(job, k, v)
            s.commit()

    def submit(self, project_id: str, kind: str, fn: Callable[[], Awaitable[object]],
               scene_id: int | None = None) -> int:
        with self.db.Session() as s:
            job = Job(project_id=project_id, kind=kind, scene_id=scene_id, status="QUEUED")
            s.add(job)
            s.commit()
            job_id = job.id

        async def run() -> None:
            async with self._sem:
                token = set_reporter(lambda st, msg: self._update(job_id, status=st, message=msg))
                self._update(job_id, status="GENERATING")
                try:
                    result = await fn()
                    self._update(job_id, status="COMPLETE",
                                 message=str(result)[:2000] if result is not None else None)
                except Exception as e:
                    self._update(job_id, status="FAILED", error=f"{e}\n\n"
                                 f"{traceback.format_exc()[-3000:]}")
                finally:
                    reset_reporter(token)

        task = asyncio.get_running_loop().create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job_id

    def list(self, project_id: str | None = None, limit: int = 50) -> list[Job]:
        with self.db.Session() as s:
            stmt = select(Job).order_by(Job.id.desc()).limit(limit)
            if project_id:
                stmt = stmt.where(Job.project_id == project_id)
            return list(s.scalars(stmt))

    def mark_interrupted(self) -> None:
        """Jobs left running by a previous process can never finish."""
        with self.db.Session() as s:
            for job in s.scalars(select(Job).where(Job.status.not_in(["COMPLETE", "FAILED"]))):
                job.status = "FAILED"
                job.error = "interrupted (server restarted)"
            s.commit()

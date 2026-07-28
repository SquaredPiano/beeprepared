"""The contract every job handler implements."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from typing import Callable, Optional

from backend.models.graph import JobBundle
from backend.models.jobs import JobModel

ProgressReporter = Callable[[str, int], None]


def _ignore(_stage: str, _percent: int) -> None:
    """Default reporter, used when nobody is listening."""


class JobHandler(ABC):
    """
    Does the work for one kind of job and describes what it produced.

    Handlers never write to the database. They return a `JobBundle` and the
    runner commits it in a single transaction, so a handler that fails partway
    through cannot leave a half-written graph behind.

    Progress is reported through a callback carried by the handler rather than
    published directly, which keeps the event transport out of the handler and
    lets a test assert on the sequence of stages. The callback is per job and
    the instance is not: a handler is built once and shared by every worker, so
    it is attached by `with_progress` on a copy and never written to the shared
    instance.
    """

    progress: ProgressReporter = staticmethod(_ignore)

    def with_progress(self, reporter: Optional[ProgressReporter]) -> "JobHandler":
        """
        Return a copy of this handler that reports to `reporter`.

        Assigning the reporter here would write to an instance several jobs are
        running on at once: the job that attached last would own the callback,
        and every job still in flight would report into that job's project under
        that job's id.

        The copy is shallow on purpose: the collaborators opened in `__init__`
        are what make construction expensive and they stay shared. Only the
        reporter differs per job, and no handler keeps any other per-job state.
        """
        attached = copy.copy(self)
        attached.progress = reporter or _ignore
        return attached

    def report(self, stage: str, percent: int) -> None:
        """
        Announce the stage now running and how far through the job it is.

        A reporter that fails is swallowed: progress is decoration, and losing a
        WebSocket mid-run must not fail work that is otherwise succeeding.
        """
        try:
            self.progress(stage, max(0, min(100, percent)))
        except Exception:
            pass

    @abstractmethod
    async def run(self, job: JobModel) -> JobBundle:
        """Do the work and return everything that should be committed."""

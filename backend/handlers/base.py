"""The contract every job handler implements."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from typing import Callable, Optional

from backend.models.graph import JobBundle
from backend.models.jobs import JobModel

ProgressReporter = Callable[[str, int], None]


def _ignore(_stage: str, _percent: int) -> None:
    """The reporter we fall back to when nobody's listening."""


class JobHandler(ABC):
    """
    Does the work for one kind of job, and reports back what it made.

    A handler never writes to the database itself. It hands back a `JobBundle`
    and the runner commits the whole thing in one transaction. That matters
    because model calls fail often, so a handler dying halfway through is
    normal, and we do not want half a graph left behind when it does.

    Progress goes out through a callback the handler carries, not by publishing
    straight from here. That keeps the event transport out of the handler, and it
    lets a test collect the stages and check the order they came in. The callback
    belongs to one job, but the handler doesn't: it's built once and every worker
    shares it. So `with_progress` attaches the callback to a copy, and the shared
    instance is never written to.
    """

    progress: ProgressReporter = staticmethod(_ignore)

    def with_progress(self, reporter: Optional[ProgressReporter]) -> "JobHandler":
        """
        Hand back a copy of this handler that reports to `reporter`.

        We can't just assign the reporter, because several jobs are running on
        this one instance at the same time. Whichever job attached last would own
        the callback, and every job still in flight would publish its progress
        into that job's project, under that job's id.

        The copy is shallow on purpose. What makes a handler expensive to build
        is the collaborators it opens in `__init__`, and those stay shared. The
        reporter is the only thing that differs per job, and a handler keeps no
        other per-job state.
        """
        attached = copy.copy(self)
        attached.progress = reporter or _ignore
        return attached

    def report(self, stage: str, percent: int) -> None:
        """
        Say which stage is running now, and how far through the job we are.

        If the reporter throws, we swallow it. Progress is decoration, and a
        WebSocket dropping mid-run mustn't fail work that's otherwise going fine.
        """
        try:
            self.progress(stage, max(0, min(100, percent)))
        except Exception:
            pass

    @abstractmethod
    async def run(self, job: JobModel) -> JobBundle:
        """Do the work, and hand back everything the runner should commit."""

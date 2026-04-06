"""
Job handler contract.

A handler is effectively a pure function from a job to a ``JobBundle``: it does
the work and describes the result, but never writes to the database. The runner
owns persistence, so a handler that throws halfway through cannot leave the
knowledge graph half-written.

Handler responsibilities:

1. Fetch the *content* of the input artifact ids (from the DB or object storage).
2. Pass that content to the pure services in ``services/``.
3. Mint new UUIDs for the output artifacts.
4. Build the ``EdgePayload`` list linking every input to the output.

Handlers report progress through an injected callback rather than publishing
events themselves. That keeps them testable - a unit test passes a list's
``append`` and asserts on the sequence - and keeps knowledge of the event
transport in the runner where it belongs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

from backend.models.jobs import JobModel
from backend.models.protocol import JobBundle

# (stage label, percent complete 0-100)
ProgressCallback = Callable[[str, int], None]


def _noop(_stage: str, _percent: int) -> None:
    """Default reporter, used when nobody is listening."""


class JobHandler(ABC):
    """Base class for all job handlers."""

    #: Replaced by the runner before ``run`` is awaited.
    progress: ProgressCallback = staticmethod(_noop)

    def with_progress(self, callback: Optional[ProgressCallback]) -> "JobHandler":
        """Attach a progress reporter. Returns self so it can be chained."""
        self.progress = callback or _noop
        return self

    def report(self, stage: str, percent: int) -> None:
        """Report a named stage and how far through the job it is."""
        try:
            self.progress(stage, max(0, min(100, percent)))
        except Exception:  # pragma: no cover - reporting must never fail a job
            pass

    @abstractmethod
    async def run(self, job: JobModel) -> JobBundle:
        """Do the work and return everything that should be committed."""

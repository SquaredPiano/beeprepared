"""
Base Handler: Abstract base class for all job handlers.

Extracted to avoid circular imports between job_runner and handlers.
"""

from backend.models.jobs import JobModel
from backend.models.protocol import JobBundle


class JobHandler:
    """
    Abstract Base Class for Job Handlers.
    
    ARCHITECTURAL HARD CONSTRAINT:
    Handlers are responsible for:
    1. Fetching the *content* of input artifact IDs (from DB or R2).
    2. Passing content to the pure services (generators.py).
    3. Generating **new UUIDs** for output artifacts.
    4. Creating the **EdgePayload** linking Input ID -> Output ID.
    
    Handlers MUST return a JobBundle. They MUST NOT commit to DB.
    """
    async def run(self, job: JobModel) -> JobBundle:
        raise NotImplementedError("Handlers must implement run()")

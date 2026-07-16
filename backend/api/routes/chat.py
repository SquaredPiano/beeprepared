"""The assistant: answers questions, or rebuilds the artifact in view."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.api.deps import get_current_user, get_db, require_artifact, require_project
from backend.api.schemas import ChatRequest, ChatResponse
from backend.handlers.sources import ArtifactFlattener
from backend.llm.base import LLMProvider
from backend.llm.factory import get_provider
from backend.models.artifacts import GENERATED_TYPES
from backend.services.database import Database
from backend.services.dispatcher import enqueue
from backend.services.events import CHAT_MESSAGE, JOB_CREATED, publish

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["assistant"])

ARTIFACT_CONTEXT_LIMIT = 6_000
SUMMARY_CONTEXT_LIMIT = 2_000
HISTORY_LIMIT = 50

CLASSIFIER_PROMPT = """
You are the assistant inside a study-material generator. The user is looking at
an artifact and has sent you a message.

Choose one action:

- "refine" when they want the artifact changed, regenerated or made different:
  "make it harder", "add more examples", "focus on chapter 3", "too easy",
  "shorter please". Restate their request as a clear directive in instructions,
  and set target_type to the artifact type to produce.
- "answer" when they are asking a question and the artifact should not change:
  "what does this mean?", "why is B correct?", "explain X".

When it is genuinely ambiguous, choose "answer" and ask what they want changed.
Regenerating something the user did not ask you to regenerate is worse than one
extra question.

Always fill reply. For a refine, confirm briefly what you are about to change.
For an answer, give the answer, grounded in the material below, and say so when
the material does not cover it.
"""


class Intent(BaseModel):
    """How the assistant read the user's message."""

    action: str = Field(description="'refine' to change the artifact, 'answer' to reply")
    target_type: Optional[str] = Field(None, description="Artifact type to produce when refining")
    instructions: Optional[str] = Field(None, description="The change, restated as a directive")
    reply: str = Field(description="What to say back to the user")


class AssistantContext:
    """Assembles what the model needs to see to answer or revise."""

    def __init__(self, database: Database, flattener: Optional[ArtifactFlattener] = None) -> None:
        self._database = database
        self._flattener = flattener or ArtifactFlattener()

    def build(self, project_id: str, artifact: Optional[Dict[str, Any]], message: str) -> str:
        return (
            f"{self._project(project_id)}\n\n"
            f"--- ARTIFACT IN VIEW ---\n{self._artifact(artifact)}\n\n"
            f"--- USER MESSAGE ---\n{message}"
        )

    def _project(self, project_id: str) -> str:
        cores = self._database.select(
            "artifacts",
            [("project_id", f"eq.{project_id}"), ("type", "eq.knowledge_core")],
            order="created_at.desc",
            limit=1,
        )
        if not cores:
            return "This project has no source material yet."

        core = (cores[0].get("content") or {}).get("core") or {}
        concepts = ", ".join(concept.get("name", "") for concept in (core.get("concepts") or [])[:12])
        return (
            f"Project material: {core.get('title', 'Untitled')}\n"
            f"Summary: {(core.get('summary') or '')[:SUMMARY_CONTEXT_LIMIT]}\n"
            f"Key concepts: {concepts}"
        )

    def _artifact(self, artifact: Optional[Dict[str, Any]]) -> str:
        if not artifact:
            return "No artifact is open."

        body = self._flattener.flatten(artifact) or ""
        return f"Type: {artifact.get('type')}\nContent:\n{body[:ARTIFACT_CONTEXT_LIMIT]}"


@router.post("", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
    provider: LLMProvider = Depends(get_provider),
) -> ChatResponse:
    """Answer a message, or queue a refinement of the artifact in view."""
    require_project(request.project_id, user_id, database)
    artifact = require_artifact(request.artifact_id, user_id, database) if request.artifact_id else None

    _record(database, request, "user", request.message, {})

    context = AssistantContext(database).build(request.project_id, artifact, request.message)
    intent = await _classify(provider, context)

    if intent.action != "refine" or artifact is None:
        reply = intent.reply if artifact or intent.action != "refine" else (
            "Open an artifact and I can revise it for you."
        )
        return _reply(database, request, ChatResponse(reply=reply, action="answer"))

    target_type = intent.target_type if intent.target_type in GENERATED_TYPES else artifact.get("type")
    if target_type not in GENERATED_TYPES:
        return _reply(database, request, ChatResponse(
            reply=f"I cannot regenerate a '{artifact.get('type')}' artifact.", action="answer",
        ))

    job_id = database.insert("jobs", {
        "project_id": request.project_id,
        "type": "refine",
        "status": "pending",
        "payload": {
            "source_artifact_id": request.artifact_id,
            "instructions": intent.instructions or request.message,
            "target_type": target_type,
        },
    })[0]["id"]

    publish(request.project_id, JOB_CREATED, {"job_id": job_id, "type": "refine"})
    enqueue(job_id)
    logger.info("Assistant queued refine job %s", job_id)

    return _reply(database, request, ChatResponse(
        reply=intent.reply, action="refine", job_id=job_id, target_type=target_type,
    ))


@router.get("/{project_id}/history")
def get_history(
    project_id: str,
    limit: int = Query(HISTORY_LIMIT, ge=1, le=200),
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> List[Dict[str, Any]]:
    """The recent conversation for a project, oldest first."""
    require_project(project_id, user_id, database)
    messages = database.select(
        "chat_messages", [("project_id", f"eq.{project_id}")], order="created_at.desc", limit=limit
    )
    return list(reversed(messages))


async def _classify(provider: LLMProvider, context: str) -> Intent:
    try:
        return await provider.complete_as(CLASSIFIER_PROMPT, Intent, context=context)
    except Exception as error:
        logger.warning("Assistant classification failed: %s", error)
        return Intent(
            action="answer",
            reply=(
                "I could not reach the model just now. Try again shortly, or tell me "
                "exactly what to change and I will regenerate the artifact."
            ),
        )


def _reply(database: Database, request: ChatRequest, response: ChatResponse) -> ChatResponse:
    _record(database, request, "assistant", response.reply,
            {"action": response.action, "job_id": response.job_id})
    publish(request.project_id, CHAT_MESSAGE, response.model_dump())
    return response


def _record(
    database: Database,
    request: ChatRequest,
    role: str,
    content: str,
    metadata: Dict[str, Any],
) -> None:
    database.insert("chat_messages", {
        "project_id": request.project_id,
        "artifact_id": request.artifact_id,
        "role": role,
        "content": content,
        "metadata": metadata,
    })

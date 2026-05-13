"""
Assistant routes: the chat panel that steers generation.

The problem this solves: generation used to be a slot machine. You clicked
"generate quiz", and if the result was too easy, or covered the wrong chapter,
your only recourse was to click it again and hope. There was no way to *say*
what you wanted.

Now there is. A message is classified into one of two intents:

- **refine** - "make the questions harder", "focus on chapter 3", "shorter
  answers". A ``refine`` job is queued against the artifact currently in view
  and the user watches it rebuild.
- **answer** - "what's the difference between these two concepts?". Answered
  directly from the project's material.

Classification is done by the model rather than by keyword matching, because
"can you make this harder?" and "is this hard?" differ by one word and mean
completely different things. A conservative fallback keeps a classification
failure from queueing a job the user did not ask for.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.deps import get_current_user, get_db, require_artifact, require_project
from backend.api.schemas import ChatRequest, ChatResponse
from backend.core.services.llm_factory import LLMFactory
from backend.models.artifacts import GENERATED_ARTIFACT_TYPES
from backend.services.db_interface import DBInterface
from backend.services.dispatcher import enqueue
from backend.services.events import EVENT_CHAT_MESSAGE, EVENT_JOB_CREATED, publish

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["assistant"])

MAX_CONTEXT_CHARS = 6000


class Intent(BaseModel):
    """How the assistant read the user's message."""

    action: str = Field(description="'refine' to change the artifact, 'answer' to reply in chat")
    target_type: Optional[str] = Field(None, description="Artifact type to produce, if regenerating")
    instructions: Optional[str] = Field(None, description="The change, restated as a directive")
    reply: str = Field(description="What to say back to the user")


def _artifact_context(artifact: Optional[Dict[str, Any]]) -> str:
    """A compact text view of the artifact under discussion."""
    if not artifact:
        return "No artifact is currently open."

    from backend.handlers.generate_handler import GenerateHandler

    flattened = GenerateHandler._flatten(artifact) or ""
    return (
        f"Artifact type: {artifact.get('type')}\n"
        f"Content:\n{flattened[:MAX_CONTEXT_CHARS]}"
    )


def _project_context(db: DBInterface, project_id: str) -> str:
    """The project's Knowledge Core summary, so questions can be answered from source."""
    cores = db.select(
        "artifacts",
        [("project_id", f"eq.{project_id}"), ("type", "eq.knowledge_core")],
        order="created_at.desc",
        limit=1,
    )
    if not cores:
        return "This project has no source material ingested yet."

    core = (cores[0].get("content") or {}).get("core") or {}
    concepts = ", ".join(c.get("name", "") for c in (core.get("concepts") or [])[:12])
    return (
        f"Project material: {core.get('title', 'Untitled')}\n"
        f"Summary: {(core.get('summary') or '')[:2000]}\n"
        f"Key concepts: {concepts}"
    )


CLASSIFIER_PROMPT = """
You are the assistant inside a study-material generator. The user is looking at
an artifact and has sent you a message.

Decide what they want:

- **"refine"** - they want the artifact changed, regenerated, or made different
  in some way ("make it harder", "add more examples", "focus on chapter 3",
  "these questions are too easy", "shorter please"). Restate their request as a
  clear directive in `instructions`, and set `target_type` to the artifact type
  to produce - the same type unless they asked for a different one.
- **"answer"** - they are asking a question, or want an explanation, and the
  artifact should not change ("what does this mean?", "why is B correct?",
  "explain concept X").

When it is genuinely ambiguous, choose "answer" and ask what they would like
changed. Regenerating something the user did not ask you to regenerate is worse
than one extra question.

Always fill `reply` with what to say back. For a refine, that is a short
confirmation of what you are about to change. For an answer, it is the answer
itself - grounded in the material below, and honest when the material does not
cover it.
"""


@router.post("", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> ChatResponse:
    """Handle one assistant message: answer it, or queue a refinement."""
    require_project(request.project_id, user_id, db)

    artifact = None
    if request.artifact_id:
        artifact = require_artifact(request.artifact_id, user_id, db)

    db.insert("chat_messages", {
        "project_id": request.project_id,
        "artifact_id": request.artifact_id,
        "role": "user",
        "content": request.message,
        "metadata": {},
    })

    context = (
        f"{_project_context(db, request.project_id)}\n\n"
        f"--- ARTIFACT IN VIEW ---\n{_artifact_context(artifact)}\n\n"
        f"--- USER MESSAGE ---\n{request.message}"
    )

    try:
        llm = LLMFactory.get_provider()
        result = await llm.generate_content_async(
            prompt=CLASSIFIER_PROMPT, context=context, schema=Intent
        )
        intent = result if isinstance(result, Intent) else Intent(**result)
    except Exception as exc:
        logger.warning("Assistant classification failed: %s", exc)
        intent = Intent(
            action="answer",
            reply=(
                "I could not reach the model just now. Try again in a moment - or "
                "if you want this artifact changed, tell me exactly what to change "
                "and I will regenerate it."
            ),
        )

    response = ChatResponse(reply=intent.reply, action="answer")

    if intent.action == "refine":
        if not artifact:
            response.reply = "Open an artifact first and I can revise it for you."
            return _record(db, request, response)

        target_type = intent.target_type or artifact.get("type")
        if target_type not in GENERATED_ARTIFACT_TYPES:
            target_type = artifact.get("type")
        if target_type not in GENERATED_ARTIFACT_TYPES:
            response.reply = f"I cannot regenerate a '{artifact.get('type')}' artifact."
            return _record(db, request, response)

        rows = db.insert("jobs", {
            "project_id": request.project_id,
            "type": "refine",
            "status": "pending",
            "payload": {
                "source_artifact_id": request.artifact_id,
                "instructions": intent.instructions or request.message,
                "target_type": target_type,
            },
        })
        job_id = rows[0]["id"]

        publish(request.project_id, EVENT_JOB_CREATED, {"job_id": job_id, "type": "refine"})
        enqueue(job_id)

        response.action = "refine"
        response.job_id = job_id
        response.target_type = target_type
        logger.info("Assistant queued refine job %s for artifact %s", job_id, request.artifact_id)

    return _record(db, request, response)


def _record(db: DBInterface, request: ChatRequest, response: ChatResponse) -> ChatResponse:
    """Persist the assistant's turn and broadcast it to any open sockets."""
    db.insert("chat_messages", {
        "project_id": request.project_id,
        "artifact_id": request.artifact_id,
        "role": "assistant",
        "content": response.reply,
        "metadata": {"action": response.action, "job_id": response.job_id},
    })
    publish(request.project_id, EVENT_CHAT_MESSAGE, response.model_dump())
    return response


@router.get("/{project_id}/history")
def history(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Recent conversation for a project, oldest first."""
    require_project(project_id, user_id, db)
    messages = db.select(
        "chat_messages",
        [("project_id", f"eq.{project_id}")],
        order="created_at.desc",
        limit=limit,
    )
    return list(reversed(messages))

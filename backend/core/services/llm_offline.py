"""
Offline LLM provider.

A deterministic, dependency-free stand-in that derives its output from the
source material with regex and heuristics instead of a model. It exists so that
three things stay true when no API key is configured:

1. ``docker compose up`` produces a working demo, not a wall of 401s.
2. The integration tests exercise the real pipeline (handlers, DB writes,
   validation, DAG traversal) without spending tokens or needing a network.
3. A revoked key degrades the *quality* of generated artifacts rather than
   taking the whole product down.

The output is honest about what it is - artifacts are tagged so the UI can show
that they came from the offline engine.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Type, Union

from pydantic import BaseModel

from backend.core.llm_interface import LLMProvider

logger = logging.getLogger(__name__)

STOPWORDS = {
    "about", "after", "again", "also", "because", "been", "before", "being",
    "between", "both", "could", "does", "during", "each", "every", "from",
    "have", "having", "here", "into", "material", "more", "most", "must",
    "other", "over", "should", "since", "some", "source", "such", "than",
    "that", "their", "them", "then", "there", "these", "they", "this",
    "those", "through", "under", "until", "using", "very", "were", "what",
    "when", "where", "which", "while", "will", "with", "would", "your",
}


class OfflineLLM(LLMProvider):
    """Heuristic provider used when no upstream model is configured."""

    is_offline = True

    def __init__(self) -> None:
        logger.warning(
            "No LLM credentials configured - using the offline heuristic provider. "
            "Set OPENROUTER_API_KEY for real generations."
        )

    # -- text mining --------------------------------------------------------

    @staticmethod
    def _terms(text: str, limit: int = 10) -> List[str]:
        """Most frequent non-trivial words, used as stand-in key concepts."""
        counts: dict[str, int] = {}
        display: dict[str, str] = {}
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text):
            key = word.lower()
            if key in STOPWORDS:
                continue
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, word.strip("_-").title())

        ranked = sorted(counts, key=lambda k: (-counts[k], k))
        terms = [display[key] for key in ranked[:limit]]
        return terms or ["Core Concept", "Key Idea", "Study Focus"]

    @staticmethod
    def _sentences(text: str, limit: int = 12) -> List[str]:
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", text)
            if len(sentence.strip()) > 25
        ]
        if not sentences:
            fallback = text.strip()[:220] or "This material introduces the main ideas for the project."
            sentences = [fallback]
        return sentences[:limit]

    @staticmethod
    def _source_text(prompt: str, context: Optional[str]) -> str:
        import json

        if not context:
            return prompt
        try:
            parsed = json.loads(context)
        except (json.JSONDecodeError, TypeError):
            return context

        if not isinstance(parsed, dict):
            return context

        parts = [str(parsed.get("title") or ""), str(parsed.get("summary") or "")]
        for concept in (parsed.get("concepts") or [])[:12]:
            if isinstance(concept, dict):
                parts.append(str(concept.get("name") or ""))
                parts.append(str(concept.get("description") or ""))
        for fact in (parsed.get("key_facts") or [])[:12]:
            if isinstance(fact, dict):
                parts.append(str(fact.get("fact") or ""))
        return " ".join(part for part in parts if part) or context

    # -- schema fixtures ----------------------------------------------------

    def _build(self, prompt: str, context: Optional[str], schema: Type[BaseModel]):
        text = self._source_text(prompt, context)
        terms = self._terms(text)
        sentences = self._sentences(text)
        title = terms[0] if terms else "Study Material"
        name = schema.__name__

        def sentence(index: int) -> str:
            return sentences[index % len(sentences)]

        if name == "KnowledgeCore":
            return schema.model_validate({
                "title": title,
                "summary": " ".join(sentences[:3]),
                "concepts": [
                    {
                        "name": term,
                        "description": f"{term} is a recurring idea in the source material.",
                        "importance_score": max(5, 10 - index),
                    }
                    for index, term in enumerate(terms[:6])
                ],
                "section_hierarchy": [{
                    "title": "Overview",
                    "summary": sentences[0],
                    "subsections": [
                        {"title": term, "summary": sentence(index)}
                        for index, term in enumerate(terms[:3])
                    ],
                }],
                "notes": [{"heading": "Key Notes", "bullets": sentences[:5]}],
                "definitions": [
                    {
                        "term": term,
                        "definition": f"A recurring concept in this material: {term}.",
                        "context": sentence(index),
                    }
                    for index, term in enumerate(terms[:4])
                ],
                "examples": [
                    {"description": sentence(index), "relevance": f"Illustrates {term}."}
                    for index, term in enumerate(terms[:2])
                ],
                "key_facts": [
                    {"fact": item, "category": "Offline Extraction"} for item in sentences[:5]
                ],
            })

        if name == "ExamSpec":
            return schema.model_validate({
                "discipline": "General",
                "exam_style": "Conceptual short-answer assessment",
                "cognitive_targets": ["Recall", "Understanding", "Application"],
                "grading_philosophy": "Award credit for clear, accurate use of the source material.",
                "instructions_tone": "Formal",
            })

        if name == "QuestionBatch":
            q_type = next((c for c in ("MCQ", "Short Answer", "Problem Set") if c in prompt), "Short Answer")
            match = re.search(r"EXACTLY\s+(\d+)", prompt)
            count = int(match.group(1)) if match else 5
            return schema.model_validate({"questions": [
                {
                    "id": str(index + 1),
                    "text": f"Explain the role of {terms[index % len(terms)]} in the source material.",
                    "type": q_type,
                    "options": (
                        [terms[index % len(terms)], f"Not {terms[index % len(terms)]}",
                         "Unrelated detail", "Insufficient information"]
                        if q_type == "MCQ" else None
                    ),
                    "points": 3 if q_type == "MCQ" else 5,
                    "model_answer": sentence(index),
                    "grading_notes": "Full credit requires an accurate explanation grounded in the material.",
                }
                for index in range(count)
            ]})

        if name == "QuizModel":
            return schema.model_validate({
                "title": f"Quiz: {title}",
                "questions": [
                    {
                        "id": f"Q{index + 1}",
                        "text": f"Which statement best matches {terms[index % len(terms)]}?",
                        "type": "MCQ",
                        "options": [
                            sentence(index)[:120],
                            f"{terms[index % len(terms)]} is unrelated to the material.",
                            "The source does not mention this topic.",
                            "All listed statements are equally unsupported.",
                        ],
                        "correct_answer_index": 0,
                        "explanation": sentence(index),
                        "topic_focus": terms[index % len(terms)],
                    }
                    for index in range(12)
                ],
            })

        if name == "FlashcardModel":
            return schema.model_validate({"cards": [
                {
                    "front": f"What should you remember about {term}?",
                    "back": sentence(index),
                    "hint": "Look at how this idea connects to the summary.",
                    "source_reference": "Offline engine",
                }
                for index, term in enumerate((terms * 3)[:15])
            ]})

        if name == "SlidesModel":
            return schema.model_validate({
                "title": f"Slides: {title}",
                "audience_level": "General",
                "slides": [
                    {
                        "heading": term,
                        "main_idea": sentence(index)[:160],
                        "bullet_points": sentences[:3],
                        "visual_cue": f"Simple diagram for {term}",
                        "speaker_notes": sentence(index),
                    }
                    for index, term in enumerate((terms * 2)[:8])
                ],
            })

        if name == "MindMapModel":
            return schema.model_validate({
                "title": f"Mind Map: {title}",
                "root": {
                    "label": title,
                    "detail": sentences[0],
                    "children": [
                        {
                            "label": term,
                            "detail": sentence(index)[:140],
                            "children": [
                                {"label": inner, "detail": sentence(index + offset + 1)[:140]}
                                for offset, inner in enumerate(terms[index + 1: index + 3])
                            ],
                        }
                        for index, term in enumerate(terms[:5])
                    ],
                },
            })

        if name == "CheatSheetModel":
            return schema.model_validate({
                "title": f"Cheat Sheet: {title}",
                "sections": [
                    {
                        "heading": term,
                        "entries": [sentence(index), sentence(index + 1)],
                    }
                    for index, term in enumerate(terms[:6])
                ],
            })

        if name == "StudyGuideModel":
            return schema.model_validate({
                "title": f"Study Guide: {title}",
                "estimated_minutes": 45,
                "objectives": [f"Understand {term}" for term in terms[:5]],
                "body": self._markdown(title, sentences, terms),
                "checklist": [f"Can you explain {term} without notes?" for term in terms[:6]],
            })

        raise NotImplementedError(f"Offline provider has no fixture for schema {name}")

    @staticmethod
    def _markdown(title: str, sentences: List[str], terms: List[str]) -> str:
        bullets = "\n".join(f"- {item}" for item in sentences[:8])
        concepts = "\n".join(f"### {term}\n\n{sentences[index % len(sentences)]}\n"
                             for index, term in enumerate(terms[:5]))
        return (
            f"# {title}\n\n"
            "> Generated by the BeePrepared offline engine. Configure `OPENROUTER_API_KEY` "
            "for model-authored notes.\n\n"
            f"## Summary\n\n{' '.join(sentences[:3])}\n\n"
            f"## Key Points\n\n{bullets}\n\n"
            f"## Concepts\n\n{concepts}\n"
            f"## Review Questions\n\n"
            + "\n".join(f"{index + 1}. What is the significance of {term}?"
                        for index, term in enumerate(terms[:5]))
            + "\n"
        )

    # -- LLMProvider --------------------------------------------------------

    def generate_content(
        self,
        prompt: str,
        context: Optional[str] = None,
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None,
    ) -> Union[str, BaseModel]:
        if schema is not None:
            return self._build(prompt, context, schema)

        text = self._source_text(prompt, context)
        if "Return exactly OK" in prompt:
            return "OK"
        sentences = self._sentences(text)
        terms = self._terms(text)
        # A cleaning pass should return the text it was given, not notes about it.
        if "Fix grammar" in prompt or "Do NOT summarize" in prompt:
            return text
        return self._markdown(terms[0] if terms else "Study Notes", sentences, terms)

    async def generate_content_async(
        self,
        prompt: str,
        context: Optional[str] = None,
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None,
    ) -> Union[str, BaseModel]:
        return self.generate_content(prompt, context, schema, model_name)

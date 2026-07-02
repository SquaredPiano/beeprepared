"""Deterministic provider used when no API key is configured."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Type

from backend.llm.base import LLMError, LLMProvider, Schema

logger = logging.getLogger(__name__)

STOPWORDS = frozenset("""
about after again also because been before being between both could does during
each every from have having here into material more most must other over should
since some source such than that their them then there these they those through
under until using very were what when where which while will with would your
""".split())

WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{3,}")
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


class OfflineProvider(LLMProvider):
    """
    Derives artifacts from the source material with frequency analysis.

    Output quality is far below a real model, but every pipeline stage runs, so
    a missing key degrades results instead of breaking the product.
    """

    name = "offline"
    supports_audio = False

    def __init__(self) -> None:
        logger.warning("No OPENROUTER_API_KEY set. Using the offline provider.")

    async def complete(self, prompt: str, context: Optional[str] = None) -> str:
        source = self._source_text(prompt, context)
        if "verbatim" in prompt or "Do NOT summarize" in prompt:
            return source
        return self._markdown(source)

    async def complete_as(
        self,
        prompt: str,
        schema: Type[Schema],
        context: Optional[str] = None,
    ) -> Schema:
        builder = self._builders().get(schema.__name__)
        if builder is None:
            raise LLMError(f"The offline provider has no fixture for {schema.__name__}")
        return schema.model_validate(builder(prompt, self._source_text(prompt, context)))

    def _builders(self) -> Dict[str, Callable[[str, str], Dict[str, Any]]]:
        return {
            "KnowledgeCore": self._knowledge_core,
            "ExamSpec": self._exam_spec,
            "QuestionBatch": self._question_batch,
            "QuizModel": self._quiz,
            "FlashcardModel": self._flashcards,
            "SlidesModel": self._slides,
            "StudyGuideModel": self._study_guide,
            "CheatSheetModel": self._cheat_sheet,
            "MindMapModel": self._mind_map,
            "CoreSummary": self._core_summary,
            "CombinedContext": self._combined_context,
            "Intent": self._intent,
        }

    @staticmethod
    def _source_text(prompt: str, context: Optional[str]) -> str:
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
                parts += [str(concept.get("name") or ""), str(concept.get("description") or "")]
        for fact in (parsed.get("key_facts") or [])[:12]:
            if isinstance(fact, dict):
                parts.append(str(fact.get("fact") or ""))
        return " ".join(part for part in parts if part) or context

    @staticmethod
    def _terms(text: str, limit: int = 10) -> List[str]:
        counts: Dict[str, int] = {}
        display: Dict[str, str] = {}
        for word in WORD.findall(text):
            key = word.lower()
            if key in STOPWORDS:
                continue
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, word.strip("_-").title())

        ranked = sorted(counts, key=lambda key: (-counts[key], key))
        return [display[key] for key in ranked[:limit]] or ["Core Concept", "Key Idea", "Study Focus"]

    @staticmethod
    def _sentences(text: str, limit: int = 12) -> List[str]:
        found = [s.strip() for s in SENTENCE_BREAK.split(text) if len(s.strip()) > 25]
        return found[:limit] or [text.strip()[:220] or "This material introduces the main ideas."]

    def _parts(self, text: str) -> tuple[List[str], List[str], Callable[[int], str]]:
        terms, sentences = self._terms(text), self._sentences(text)
        return terms, sentences, lambda index: sentences[index % len(sentences)]

    def _knowledge_core(self, _prompt: str, text: str) -> Dict[str, Any]:
        terms, sentences, sentence = self._parts(text)
        return {
            "title": terms[0],
            "summary": " ".join(sentences[:3]),
            "concepts": [
                {"name": term, "description": f"{term} recurs throughout the material.",
                 "importance_score": max(5, 10 - index)}
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
            "notes": [{"heading": "Key notes", "bullets": sentences[:5]}],
            "definitions": [
                {"term": term, "definition": f"A recurring concept: {term}.", "context": sentence(index)}
                for index, term in enumerate(terms[:4])
            ],
            "examples": [
                {"description": sentence(index), "relevance": f"Illustrates {term}."}
                for index, term in enumerate(terms[:2])
            ],
            "key_facts": [
                {"fact": item, "category": "Offline extraction"} for item in sentences[:5]
            ],
        }

    def _exam_spec(self, _prompt: str, _text: str) -> Dict[str, Any]:
        return {
            "discipline": "General",
            "exam_style": "Conceptual short-answer assessment",
            "cognitive_targets": ["Recall", "Understanding", "Application"],
            "grading_philosophy": "Award credit for accurate use of the source material.",
            "instructions_tone": "Formal",
        }

    def _question_batch(self, prompt: str, text: str) -> Dict[str, Any]:
        terms, _, sentence = self._parts(text)
        kind = next((c for c in ("MCQ", "Short Answer", "Problem Set") if c in prompt), "Short Answer")
        match = re.search(r"EXACTLY\s+(\d+)", prompt)
        count = int(match.group(1)) if match else 5

        return {"questions": [{
            "id": str(index + 1),
            "text": f"Explain the role of {terms[index % len(terms)]} in the source material.",
            "type": kind,
            "options": (
                [terms[index % len(terms)], f"Not {terms[index % len(terms)]}",
                 "Unrelated detail", "Insufficient information"] if kind == "MCQ" else None
            ),
            "points": 3 if kind == "MCQ" else 5,
            "model_answer": sentence(index),
            "grading_notes": "Full credit requires an explanation grounded in the material.",
        } for index in range(count)]}

    def _quiz(self, _prompt: str, text: str) -> Dict[str, Any]:
        terms, _, sentence = self._parts(text)
        return {"title": f"Quiz: {terms[0]}", "questions": [{
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
        } for index in range(12)]}

    def _flashcards(self, _prompt: str, text: str) -> Dict[str, Any]:
        terms, _, sentence = self._parts(text)
        return {"cards": [{
            "front": f"What should you remember about {term}?",
            "back": sentence(index),
            "hint": "Connect this idea back to the summary.",
            "source_reference": "Offline provider",
        } for index, term in enumerate((terms * 3)[:15])]}

    def _slides(self, _prompt: str, text: str) -> Dict[str, Any]:
        terms, sentences, sentence = self._parts(text)
        return {
            "title": f"Slides: {terms[0]}",
            "audience_level": "General",
            "slides": [{
                "heading": term,
                "main_idea": sentence(index)[:160],
                "bullet_points": sentences[:3],
                "visual_cue": f"Simple diagram for {term}",
                "speaker_notes": sentence(index),
            } for index, term in enumerate((terms * 2)[:8])],
        }

    def _study_guide(self, _prompt: str, text: str) -> Dict[str, Any]:
        terms, _, _ = self._parts(text)
        return {
            "title": f"Study guide: {terms[0]}",
            "estimated_minutes": 45,
            "objectives": [f"Understand {term}" for term in terms[:5]],
            "body": self._markdown(text),
            "checklist": [f"Can you explain {term} without notes?" for term in terms[:6]],
        }

    def _cheat_sheet(self, _prompt: str, text: str) -> Dict[str, Any]:
        terms, _, sentence = self._parts(text)
        return {
            "title": f"Cheat sheet: {terms[0]}",
            "sections": [
                {"heading": term, "entries": [sentence(index), sentence(index + 1)]}
                for index, term in enumerate(terms[:6])
            ],
        }

    def _mind_map(self, _prompt: str, text: str) -> Dict[str, Any]:
        terms, sentences, sentence = self._parts(text)
        return {
            "title": f"Mind map: {terms[0]}",
            "root": {
                "label": terms[0],
                "detail": sentences[0][:140],
                "children": [{
                    "label": term,
                    "detail": sentence(index)[:140],
                    "children": [
                        {"label": leaf, "detail": sentence(index + offset + 1)[:140]}
                        for offset, leaf in enumerate(terms[index + 1 : index + 3])
                    ],
                } for index, term in enumerate(terms[:5])],
            },
        }

    def _core_summary(self, _prompt: str, text: str) -> Dict[str, Any]:
        terms, sentences, _ = self._parts(text)
        return {
            "source_title": terms[0],
            "key_concepts": terms[:7],
            "key_facts": sentences[:7],
            "summary": " ".join(sentences[:3]),
        }

    def _combined_context(self, _prompt: str, text: str) -> Dict[str, Any]:
        terms, sentences, _ = self._parts(text)
        return {
            "source_count": 1,
            "source_titles": [terms[0]],
            "unified_summary": " ".join(sentences[:3]),
            "all_concepts": terms[:10],
            "all_facts": sentences[:10],
            "conflict_notes": None,
        }

    def _intent(self, _prompt: str, _text: str) -> Dict[str, Any]:
        return {
            "action": "answer",
            "target_type": None,
            "instructions": None,
            "reply": (
                "No language model is configured, so I cannot answer questions or "
                "revise artifacts. Set OPENROUTER_API_KEY to enable the assistant."
            ),
        }

    def _markdown(self, text: str) -> str:
        terms, sentences, sentence = self._parts(text)
        bullets = "\n".join(f"- {item}" for item in sentences[:8])
        concepts = "\n".join(
            f"### {term}\n\n{sentence(index)}\n" for index, term in enumerate(terms[:5])
        )
        questions = "\n".join(
            f"{index + 1}. What is the significance of {term}?"
            for index, term in enumerate(terms[:5])
        )
        return (
            f"# {terms[0]}\n\n"
            "> Generated by the BeePrepared offline provider. "
            "Set `OPENROUTER_API_KEY` for model-authored notes.\n\n"
            f"## Summary\n\n{' '.join(sentences[:3])}\n\n"
            f"## Key points\n\n{bullets}\n\n"
            f"## Concepts\n\n{concepts}\n"
            f"## Review questions\n\n{questions}\n"
        )

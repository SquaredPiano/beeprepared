"""Typesets an exam as a LaTeX document, then compiles that to a PDF."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from shutil import which
from typing import Optional

from pylatex import Document, Enumerate, Itemize, Package, Section
from pylatex.utils import NoEscape

from backend.models.artifacts import ExamQuestion, FinalExamModel

logger = logging.getLogger(__name__)

ANSWER_SPACE = {"Short Answer": "4cm", "Problem Set": "8cm"}
COMPILE_TIMEOUT_SECONDS = 120


class ExamPdfRenderer:
    """
    Produces an exam booklet: cover page, then the questions, then a solution key.

    Question text goes through to LaTeX untouched. We ask the model to write its
    mathematics as LaTeX, so if we escaped the text every formula would come out
    on the page as literal backslashes.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def pdflatex_available() -> bool:
        return which("pdflatex") is not None

    def render(self, exam: FinalExamModel, filename: str) -> Optional[Path]:
        """
        Write the exam out and return the path to what we produced.

        Normally that's the PDF. If pdflatex isn't installed, or the compile
        doesn't produce anything, you get the .tex source back, which the user can
        still download and build somewhere else.
        """
        document = self._build(exam)
        stem = self.output_dir / filename

        document.generate_tex(str(stem))
        tex_path = stem.with_suffix(".tex")

        if not self.pdflatex_available():
            logger.info("pdflatex is not installed; keeping the LaTeX source only")
            return tex_path

        pdf_path = self._compile(tex_path)
        return pdf_path or tex_path

    def _compile(self, tex_path: Path) -> Optional[Path]:
        command = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-output-directory", str(self.output_dir),
            str(tex_path),
        ]

        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=COMPILE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            logger.error("pdflatex timed out compiling %s", tex_path.name)
            return None

        pdf_path = tex_path.with_suffix(".pdf")
        if pdf_path.exists():
            return pdf_path

        logger.error(
            "pdflatex produced no PDF (exit %d): %s",
            result.returncode,
            result.stdout.decode("utf-8", errors="replace")[-400:],
        )
        return None

    def _build(self, exam: FinalExamModel) -> Document:
        document = Document(documentclass="article", document_options=["11pt"])
        for package in ("geometry", "amsmath", "amssymb", "titlesec"):
            options = ["margin=1in"] if package == "geometry" else None
            document.packages.append(Package(package, options=options))

        self._cover(document, exam)
        self._questions(document, exam)
        self._solution_key(document, exam)
        return document

    @staticmethod
    def _cover(document: Document, exam: FinalExamModel) -> None:
        total_points = sum(question.points for question in exam.questions)
        instructions = exam.instructions or "Answer all questions."

        for line in (
            r"\begin{titlepage}",
            r"\centering",
            r"\vspace*{1cm}",
            r"{\Huge \textbf{FINAL EXAM} \par}",
            r"\vspace{1.5cm}",
            r"{\Large \textbf{" + exam.title + r"} \par}",
            r"\vspace{0.5cm}",
            r"{\large \today \par}",
            r"\vspace{2cm}",
            r"\textbf{INSTRUCTIONS TO CANDIDATES} \par",
            r"\vspace{0.5cm}",
            r"\textit{" + instructions + r"}",
            r"\vfill",
            r"{\large Total points: " + str(total_points) + r" \par}",
            r"\end{titlepage}",
        ):
            document.append(NoEscape(line))

    @classmethod
    def _questions(cls, document: Document, exam: FinalExamModel) -> None:
        document.append(NoEscape(r"\newpage"))

        with document.create(Section(NoEscape("Questions"), numbering=False)):
            with document.create(Enumerate()) as questions:
                for question in exam.questions:
                    questions.add_item(NoEscape(f"{question.text} ({question.points} points)"))
                    cls._answer_area(document, question)
                    document.append(NoEscape(r"\vspace{0.5cm}"))

    @staticmethod
    def _answer_area(document: Document, question: ExamQuestion) -> None:
        if question.type == "MCQ" and question.options:
            with document.create(Itemize()) as options:
                for option in question.options:
                    options.add_item(NoEscape(option))
            return

        space = ANSWER_SPACE.get(question.type)
        if space:
            document.append(NoEscape(rf"\vspace{{{space}}}"))

    @staticmethod
    def _solution_key(document: Document, exam: FinalExamModel) -> None:
        document.append(NoEscape(r"\newpage"))

        with document.create(Section(NoEscape(r"Solution key \& grading rubric"), numbering=False)):
            document.append(NoEscape(r"\textbf{Confidential: instructor use only}"))
            document.append(NoEscape(r"\vspace{0.5cm}"))

            with document.create(Enumerate()) as answers:
                for question in exam.questions:
                    answers.add_item(NoEscape(r"\textbf{" + question.id + r"}"))
                    document.append(NoEscape(r" \ \ \textbf{Model answer:} " + question.model_answer))
                    document.append(NoEscape(r" \\ \textit{Grading notes:} " + question.grading_notes))
                    document.append(NoEscape(r"\vspace{0.3cm}"))

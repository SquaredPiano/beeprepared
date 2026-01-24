import os
import logging
import subprocess
from pylatex import Document, Section, Subsection, Command, Itemize, Enumerate, Package, NoEscape
from pylatex.utils import bold, italic

from backend.models.artifacts import FinalExamModel

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PDFRenderer:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    def _check_pdflatex(self) -> bool:
        """Check if pdflatex is installed."""
        from shutil import which
        return which('pdflatex') is not None

    def render_exam(self, exam: FinalExamModel, filename: str = "final_exam"):
        """
        Renders a FinalExamModel to a PDF (and .tex) file with Ontario Tech University Style.
        """
        # Document Setup without lastpage dependency
        doc = Document(documentclass='article', document_options=['11pt'])
        doc.packages.append(Package('geometry', options=['margin=1in']))
        doc.packages.append(Package('amsmath'))
        doc.packages.append(Package('amssymb'))
        doc.packages.append(Package('titlesec'))
        # fancyhdr removed as it often pulls in lastpage or other deps, we keep it simple for now
        # or we keep fancyhdr but strictly avoid referencing LastPage
        doc.packages.append(Package('fancyhdr')) 
        
        # --- Front Cover ---
        doc.append(NoEscape(r'\begin{titlepage}'))
        doc.append(NoEscape(r'\centering'))
        doc.append(NoEscape(r'\vspace*{1cm}'))
        
        # Branding Update
        doc.append(NoEscape(r'{\Huge \textbf{ONTARIO TECH UNIVERSITY} \par}'))
        doc.append(NoEscape(r'\vspace{1.5cm}'))
        
        # Use NoEscape for all content to prevent math breaking
        doc.append(NoEscape(r'{\Large \textbf{' + exam.title + r'} \par}'))
        doc.append(NoEscape(r'\vspace{0.5cm}'))
        doc.append(NoEscape(r'{\large \today \par}'))
        
        doc.append(NoEscape(r'\vspace{2cm}'))
        doc.append(NoEscape(r'\textbf{INSTRUCTIONS TO CANDIDATES} \par'))
        doc.append(NoEscape(r'\vspace{0.5cm}'))
        doc.append(NoEscape(r'\textit{' + (exam.instructions or "Please answer all questions.") + r'}'))
        
        doc.append(NoEscape(r'\vspace{3cm}'))
        doc.append(NoEscape(r'\textbf{DO NOT OPEN THIS BOOKLET UNTIL TOLD TO DO SO} \par'))
        doc.append(NoEscape(r'\vfill'))
        doc.append(NoEscape(r'{\large Total Points: 100 \par}'))
        doc.append(NoEscape(r'\end{titlepage}'))
        
        # --- Questions ---
        doc.append(NoEscape(r'\newpage'))
        # Using NoEscape for section titles too
        with doc.create(Section(NoEscape('Questions'), numbering=False)):
            with doc.create(Enumerate()) as enum:
                if exam.questions:
                    for q in exam.questions:
                        # Question Text wrapped in NoEscape
                        enum.add_item(NoEscape(q.text + f" ({q.points} points)"))
                        
                        # Options or Workspace
                        if q.type == 'MCQ' and q.options:
                            with doc.create(Itemize()) as opts:
                                for opt in q.options:
                                    opts.add_item(NoEscape(opt))
                        elif q.type == 'Short Answer':
                            doc.append(NoEscape(r'\vspace{4cm}')) # Blank gap
                        elif q.type == 'Problem Set':
                            doc.append(NoEscape(r'\vspace{8cm}')) # Larger blank gap
                        
                        doc.append(NoEscape(r'\vspace{0.5cm}'))

        # --- Answer Key & Rubric (New Page) ---
        doc.append(NoEscape(r'\newpage'))
        with doc.create(Section(NoEscape('Solution Key & Grading Rubric'), numbering=False)):
            doc.append(NoEscape(r'\textbf{Confidential - Instructor Use Only}'))
            doc.append(NoEscape(r'\vspace{0.5cm}'))
            
            if exam.questions:
                with doc.create(Enumerate()) as enum:
                    for q in exam.questions:
                        # Answer key data usually contains LaTeX too
                        enum.add_item(NoEscape(r'\textbf{' + q.id + r'}'))
                        doc.append(NoEscape(r' \ \ \textbf{Model Answer:} ' + q.model_answer))
                        doc.append(NoEscape(r' \\ \textit{Grading Notes:} ' + q.grading_notes))
                        doc.append(NoEscape(r'\vspace{0.3cm}'))

        # Output path
        filepath = os.path.join(self.output_dir, filename)
        
        logger.info(f"Generating LaTeX for {filename}...")
        
        try:
            doc.generate_tex(filepath)
            logger.info(f"Generated {filepath}.tex")

            if self._check_pdflatex():
                logger.info("Compiling PDF...")
                # Use clean_tex=False to debug .tex if needed.
                doc.generate_pdf(filepath, clean_tex=False)
                logger.info(f"Successfully generated {filepath}.pdf")
            else:
                logger.warning("pdflatex not found. Skipping PDF compilation. Only .tex file generated.")
                
        except Exception as e:
            logger.error(f"Failed to render exam PDF: {e}")

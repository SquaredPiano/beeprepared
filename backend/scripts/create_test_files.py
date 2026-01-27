from pptx import Presentation
from docx import Document
import fitz # PyMuPDF
import os

def create_samples():
    # 3. Create PDF
    pdf_doc = fitz.open()
    page = pdf_doc.new_page()
    page.insert_text((50, 50), "This is a test PDF document.")
    pdf_doc.save("sample.pdf")
    pdf_doc.close()

if __name__ == "__main__":
    create_samples()

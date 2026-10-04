"""Utilities for extracting text from resume PDFs."""

from pathlib import Path

import pymupdf as fitz


def extract_text_from_pdf(file_path: Path) -> str:
    """Extract meaningful text from every page of a PDF file."""

    try:
        with file_path.open("rb") as pdf_file:
            pdf_bytes = pdf_file.read()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            page_text = [page.get_text() for page in document]
    except (OSError, RuntimeError, ValueError, fitz.FileDataError) as error:
        raise ValueError("Unable to read the PDF file") from error

    return "\n".join(page_text).strip()

"""Signature spot detection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber

from .errors import EXIT_INVALID_INPUT, EXIT_USAGE, PdfSignError


@dataclass
class Candidate:
    page: int  # 1-based
    bbox: list[float]  # [x0, y0, x1, y1], PDF points, bottom-left origin
    source: str  # acroform | anchor | line
    label: str
    score: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bbox"] = [round(v, 2) for v in self.bbox]
        d["score"] = round(self.score, 3)
        return d


def check_pdf_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_file():
        raise PdfSignError("file_not_found", f"File not found: {p}", EXIT_USAGE)
    return p


def detect_candidates(path: str | Path) -> tuple[int, list[Candidate]]:
    """Return (page_count, candidates sorted by score desc)."""
    p = check_pdf_path(path)
    try:
        with pdfplumber.open(p) as pdf:
            pages = len(pdf.pages)
    except Exception as exc:  # pdfminer/pypdfium raise many types
        raise PdfSignError("invalid_pdf", f"Cannot read PDF: {exc}", EXIT_INVALID_INPUT) from exc
    return pages, []

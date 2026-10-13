"""Stamp a PNG signature onto a PDF (visual signature only, not a cryptographic one)."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .detect import MIN_SCORE, Candidate, check_pdf_path, detect_candidates, filter_candidates
from .errors import EXIT_INVALID_INPUT, EXIT_NO_CANDIDATE, EXIT_USAGE, PdfSignError
from .placement import fit_stamp, text_boxes
from .geometry import user_to_visual_point, user_to_visual_rect, visual_to_user_point, visual_to_user_rect

DEFAULT_WIDTH = 150.0
DEFAULT_MIN_WIDTH = 100.0


@dataclass
class Placement:
    page: int
    stamp: list[float]  # [x0, y0, x1, y1] user space (axis-aligned) actually covered by the image
    source: str
    label: str
    score: float | None
    _visual: list[float]  # stamp rect in the displayed frame
    clamped: bool = False  # --width exceeded the line length and was capped
    min_width_applied: bool = False  # stamp enlarged to the minimum legible width
    overlaps_text: bool = False  # the stamp still covers some text

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "stamp": [round(v, 2) for v in self.stamp],
            "source": self.source,
            "label": self.label,
            "score": None if self.score is None else round(self.score, 3),
            "clamped": self.clamped,
            "min_width_applied": self.min_width_applied,
            "overlaps_text": self.overlaps_text,
        }


def load_signature(path: str | Path) -> tuple[Image.Image, Path]:
    p = Path(path)
    if not p.is_file():
        raise PdfSignError("file_not_found", f"Signature image not found: {p}", EXIT_USAGE)
    try:
        with Image.open(p) as im:
            im.load()
            img = im.convert("RGBA")
    except Exception as exc:
        raise PdfSignError("invalid_image", f"Cannot read image: {exc}", EXIT_INVALID_INPUT) from exc
    if img.width < 1 or img.height < 1:
        raise PdfSignError("invalid_image", "Image has no pixels", EXIT_INVALID_INPUT)
    return img, p


def default_output(pdf: Path) -> Path:
    return pdf.with_name(f"{pdf.stem}.signed.pdf")


def _fit(box_w: float, box_h: float, aspect: float, width: float | None) -> tuple[float, float]:
    """Image size (w, h) keeping aspect (w/h). Explicit width wins; otherwise fit inside the box."""
    if width is not None:
        return width, width / aspect
    w = min(box_w, box_h * aspect)
    return w, w / aspect


def plan_from_candidate(c: Candidate, geo: tuple[int, list[float]], aspect: float,
                        width: float | None, boxes: list[list[float]] | None = None,
                        min_width: float = 0.0) -> Placement:
    rot, crop = geo
    if c.line is not None and boxes is not None:
        lx0, ly, lx1, _ = user_to_visual_rect(rot, crop, c.line)
        label = user_to_visual_rect(rot, crop, c.anchor) if c.anchor else None
        vis, fl = fit_stamp(boxes, lx0, lx1, ly, aspect, width, min_width, label)
        return Placement(c.page, _to_user(rot, crop, vis), c.source, c.label, c.score, vis,
                         fl["clamped"], fl["min_width_applied"], fl["overlaps_text"])
    vx0, vy0, vx1, vy1 = user_to_visual_rect(rot, crop, c.bbox)
    w, h = _fit(vx1 - vx0, vy1 - vy0, aspect, width)
    vis = [vx0, vy0, vx0 + w, vy0 + h]
    return Placement(c.page, _to_user(rot, crop, vis), c.source, c.label, c.score, vis)


def plan_manual(page: int, x: float, y: float, geo: tuple[int, list[float]], aspect: float,
                width: float | None) -> Placement:
    rot, crop = geo
    w, h = _fit(0, 0, aspect, width if width is not None else DEFAULT_WIDTH)
    vx, vy = user_to_visual_point(rot, crop, x, y)
    vis = [vx, vy, vx + w, vy + h]
    return Placement(page, _to_user(rot, crop, vis), "manual", "", None, vis)


def _to_user(rot: int, crop: list[float], vis: list[float]) -> list[float]:
    return visual_to_user_rect(rot, crop, vis)


def _overlay(png: Image.Image, pl: Placement, rot: int, crop: list[float]):
    """One-page PDF whose content, in user space, shows the image upright in the displayed page."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(max(crop[2], 1), max(crop[3], 1)))
    ox, oy = visual_to_user_point(rot, crop, pl._visual[0], pl._visual[1])
    c.translate(ox, oy)
    c.rotate(rot)  # undo /Rotate so the image reads upright
    c.drawImage(ImageReader(png), 0, 0, pl._visual[2] - pl._visual[0],
                pl._visual[3] - pl._visual[1], mask="auto")
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def page_geometry(reader: PdfReader, index: int) -> tuple[int, list[float]]:
    page = reader.pages[index]
    return int(page.rotation) % 360, [float(v) for v in page.cropbox]


def choose_candidates(cands: list[Candidate], all_pages: bool, index: int | None) -> list[Candidate]:
    if all_pages:
        best: dict[int, Candidate] = {}
        for c in cands:  # already sorted by score desc
            best.setdefault(c.page, c)
        return [best[p] for p in sorted(best)]
    i = (index or 1) - 1
    if i < 0 or i >= len(cands):
        return []
    return [cands[i]]


def sign_pdf(
    pdf: str | Path,
    signature: str | Path,
    output: str | Path | None = None,
    *,
    candidate: int | None = None,
    page: int | None = None,
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    all_pages: bool = False,
    match: str | None = None,
    exclude: str | None = None,
    force: bool = False,
    min_width: float = DEFAULT_MIN_WIDTH,
) -> dict:
    src = check_pdf_path(pdf)
    manual = [v is not None for v in (page, x, y)]
    if any(manual) and not all(manual):
        raise PdfSignError("usage", "--page, --x and --y must be given together", EXIT_USAGE)
    if all(manual) and (all_pages or candidate is not None):
        raise PdfSignError("usage", "Manual coordinates cannot be combined with --all/--candidate",
                           EXIT_USAGE)
    if width is not None and width <= 0:
        raise PdfSignError("usage", "--width must be positive", EXIT_USAGE)
    png, sig_path = load_signature(signature)
    dest = Path(output) if output else default_output(src)
    if dest.resolve() == src.resolve():
        raise PdfSignError("output_is_input", "Refusing to overwrite the input PDF", EXIT_USAGE)
    if dest.exists() and not force:
        raise PdfSignError("output_exists", f"Output exists (use --force): {dest}", EXIT_USAGE)

    try:
        reader = PdfReader(str(src))
        n = len(reader.pages)
    except Exception as exc:
        raise PdfSignError("invalid_pdf", f"Cannot read PDF: {exc}", EXIT_INVALID_INPUT) from exc
    aspect = png.width / png.height

    plans: list[Placement] = []
    if all(manual):
        if not 1 <= page <= n:  # type: ignore[operator]
            raise PdfSignError("usage", f"--page must be within 1..{n}", EXIT_USAGE)
        plans.append(plan_manual(page, x, y, page_geometry(reader, page - 1), aspect, width))  # type: ignore[arg-type]
    else:
        _, cands = detect_candidates(src)
        cands = filter_candidates([c for c in cands if c.score >= MIN_SCORE], match, exclude)
        chosen = choose_candidates(cands, all_pages, candidate)
        if not chosen:
            raise PdfSignError("no_candidate", "No signature spot found; use --page/--x/--y "
                               "or relax --match/--exclude", EXIT_NO_CANDIDATE)
        with pdfplumber.open(src) as plumb:
            for c in chosen:
                boxes = text_boxes(plumb.pages[c.page - 1])
                plans.append(
                    plan_from_candidate(c, page_geometry(reader, c.page - 1), aspect, width, boxes, min_width)
                )

    writer = PdfWriter(clone_from=reader)
    for pl in plans:
        rot, crop = page_geometry(reader, pl.page - 1)
        writer.pages[pl.page - 1].merge_page(_overlay(png, pl, rot, crop))
    with open(dest, "wb") as f:
        writer.write(f)
    return {
        "input": str(src),
        "output": str(dest),
        "signature": str(sig_path),
        "placements": [p.to_dict() for p in plans],
    }

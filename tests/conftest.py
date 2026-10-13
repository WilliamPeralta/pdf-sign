"""Programmatic fixtures: PDFs generated with reportlab, one AcroForm /Sig via pypdf."""

from __future__ import annotations

import io

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# A4 is 595.27 x 841.89 pt.
ANCHOR_LINE_Y = 500  # baseline (bottom-left origin) of the "Firma" text in fixtures


@pytest.fixture
def signature_png(tmp_path):
    """Small RGBA PNG (200x80) with a transparent background."""
    path = tmp_path / "sig.png"
    img = Image.new("RGBA", (200, 80), (0, 0, 0, 0))
    for x in range(10, 190):
        for y in range(30, 50):
            img.putpixel((x, y), (10, 20, 120, 255))
    img.save(path)
    return path


@pytest.fixture
def anchor_underscore_pdf(tmp_path):
    """Page with 'Firma:' followed by an underscore run on the same line."""
    path = tmp_path / "anchor_underscore.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, "Contratto di prova")
    c.drawString(72, ANCHOR_LINE_Y, "Firma: ____________________")
    c.save()
    return path


@pytest.fixture
def anchor_drawn_line_pdf(tmp_path):
    """Page with 'Signature' and a drawn horizontal line just to its right."""
    path = tmp_path / "anchor_line.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, ANCHOR_LINE_Y, "Signature")
    c.line(160, ANCHOR_LINE_Y - 2, 360, ANCHOR_LINE_Y - 2)
    c.save()
    return path


@pytest.fixture
def anchor_only_pdf(tmp_path):
    """Anchor text with no line nearby."""
    path = tmp_path / "anchor_only.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, ANCHOR_LINE_Y, "Il dichiarante")
    c.save()
    return path


@pytest.fixture
def conferma_pdf(tmp_path):
    """'conferma' contains 'firma' as a substring: must never match."""
    path = tmp_path / "conferma.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, "Si conferma la ricezione. Confermato e firmatario non rilevanti.")
    c.drawString(72, 650, "Infirmare la tesi, designed and assigned to the team.")
    c.save()
    return path


@pytest.fixture
def underscore_only_pdf(tmp_path):
    """Underscore line with no anchor."""
    path = tmp_path / "underscore_only.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 600, "Nome: ____________________")
    c.save()
    return path


@pytest.fixture
def blank_pdf(tmp_path):
    path = tmp_path / "blank.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, "Just some ordinary text without anything to sign.")
    c.save()
    return path


@pytest.fixture
def two_page_pdf(tmp_path):
    """Anchor + underscore on both pages."""
    path = tmp_path / "two_pages.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    for _ in range(2):
        c.drawString(72, 400, "Firma: ____________________")
        c.showPage()
    c.save()
    return path


@pytest.fixture
def acroform_sig_pdf(tmp_path):
    """Blank page with a real /FT /Sig AcroForm field at [100, 200, 300, 260]."""
    base = io.BytesIO()
    c = canvas.Canvas(base, pagesize=A4)
    c.drawString(72, 700, "Form with a signature field")
    c.save()
    base.seek(0)

    writer = PdfWriter(clone_from=PdfReader(base))
    page = writer.pages[0]
    field = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Sig"),
            NameObject("/T"): TextStringObject("ClientSignature"),
            NameObject("/Rect"): ArrayObject(
                [FloatObject(100), FloatObject(200), FloatObject(300), FloatObject(260)]
            ),
            NameObject("/F"): NumberObject(4),
            NameObject("/P"): page.indirect_reference,
        }
    )
    ref = writer._add_object(field)
    page[NameObject("/Annots")] = ArrayObject([ref])
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject(
        {NameObject("/Fields"): ArrayObject([ref]), NameObject("/SigFlags"): NumberObject(1)}
    )
    path = tmp_path / "acroform_sig.pdf"
    with open(path, "wb") as f:
        writer.write(f)
    return path


@pytest.fixture
def rotated_pdf(tmp_path):
    """/Rotate 90 page whose content is drawn rotated so it reads upright when displayed.

    Rotated-frame point (a, b) is user-space (-b, a); text at (100, -300) starts at user (300, 100).
    """
    base = io.BytesIO()
    c = canvas.Canvas(base, pagesize=A4)
    c.setFont("Helvetica", 12)
    c.rotate(90)
    c.drawString(100, -300, "Firma: ____________________")
    c.save()
    base.seek(0)
    writer = PdfWriter(clone_from=PdfReader(base))
    writer.pages[0].rotate(90)
    path = tmp_path / "rotated.pdf"
    with open(path, "wb") as f:
        writer.write(f)
    return path


@pytest.fixture
def offset_mediabox_pdf(tmp_path):
    """Page whose MediaBox origin is (50, 50) rather than (0, 0)."""
    base = io.BytesIO()
    c = canvas.Canvas(base, pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, ANCHOR_LINE_Y, "Firma: ____________________")
    c.save()
    base.seek(0)
    writer = PdfWriter(clone_from=PdfReader(base))
    page = writer.pages[0]
    from pypdf.generic import RectangleObject

    box = RectangleObject([50, 50, 50 + 595.27, 50 + 841.89])
    page.mediabox = box
    page.cropbox = box
    path = tmp_path / "offset.pdf"
    with open(path, "wb") as f:
        writer.write(f)
    return path


@pytest.fixture
def real_layout_pdf(tmp_path):
    """Modeled on real HR forms: anchors with the underscore run on the NEXT line,
    two signers side by side, prose blanks, and a second page."""
    path = tmp_path / "real_layout.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 11)
    c.drawString(72, 780, "Targa: ________")
    c.drawString(72, 750, "Il dipendente ______________ dichiara di aver preso visione.")
    c.drawString(72, 300, "Firma del datore di lavoro")
    c.drawString(72, 285, "____________________")
    c.drawString(330, 300, "Firma per accettazione")
    c.drawString(330, 285, "____________________")
    c.showPage()
    c.setFont("Helvetica", 11)
    c.drawString(72, 200, "Timbro e firma del legale rappresentante")
    c.drawString(72, 185, "______________________")
    c.drawString(330, 200, "Firma del dipendente")
    c.drawString(330, 185, "______________________")
    c.save()
    return path


@pytest.fixture
def scanned_like_pdf(tmp_path):
    """Image-only page: no text layer."""
    from reportlab.lib.utils import ImageReader

    img = Image.new("RGB", (100, 100), "white")
    path = tmp_path / "scanned.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawImage(ImageReader(img), 50, 50, 400, 400)
    c.save()
    return path

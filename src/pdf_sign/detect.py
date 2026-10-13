"""Signature spot detection: AcroForm /Sig fields, text anchors, underscore / drawn lines.

All page analysis happens in the displayed (visual) frame and results are converted back to
PDF user space, so bboxes can be used directly by `sign`.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from .errors import EXIT_INVALID_INPUT, EXIT_USAGE, PdfSignError
from .geometry import visual_to_user_rect

MIN_SCORE = 0.5
BOX_HEIGHT = 40.0  # default stamp box height on a line
MIN_BOX_HEIGHT = 24.0
DEFAULT_WIDTH = 150.0  # default stamp box width when only an anchor is known

_ANCHOR_PATTERNS = [
    r"letto,?\s+confermato\s+e\s+sottoscritto",
    r"timbro\s+e\s+firma",
    r"firma\s+leggibile",
    r"firma\s+del\s+cliente",
    r"il\s+dichiarante",
    r"sign\s+here",
    r"in\s+fede",
    r"firmato",
    r"signature",
    r"signed",
    r"firma",
]
# (?<!\w)/(?!\w) = whole word only: "firmatario", "infirmare", "designed" never match.
ANCHOR_RE = re.compile(r"(?<!\w)(?:" + "|".join(_ANCHOR_PATTERNS) + r")(?!\w)", re.IGNORECASE)
UNDERSCORE_RE = re.compile(r"_{3,}")
EMPLOYER_RE = re.compile(r"datore|legale\s+rappresentante|timbro|employer", re.IGNORECASE)
SIGNER_RE = re.compile(r"dipendente|accettazione|dichiarante|lavoratore|employee", re.IGNORECASE)


@dataclass
class Candidate:
    page: int  # 1-based
    bbox: list[float]  # [x0, y0, x1, y1], PDF user space, bottom-left origin
    source: str  # acroform | anchor | line
    label: str
    score: float
    role: str = "unknown"  # employer | signer | unknown (hint derived from label)

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


def role_of(label: str) -> str:
    if EMPLOYER_RE.search(label):
        return "employer"
    if SIGNER_RE.search(label):
        return "signer"
    return "unknown"


def filter_candidates(
    cands: list[Candidate], match: str | None = None, exclude: str | None = None
) -> list[Candidate]:
    """Keep candidates whose label matches `match` and does not match `exclude` (regex, case-insens.)."""
    try:
        m = re.compile(match, re.IGNORECASE) if match else None
        x = re.compile(exclude, re.IGNORECASE) if exclude else None
    except re.error as exc:
        raise PdfSignError("usage", f"Invalid regex: {exc}", EXIT_USAGE) from exc
    return [
        c for c in cands if (m is None or m.search(c.label)) and (x is None or not x.search(c.label))
    ]


# --------------------------------------------------------------------------- page analysis


@dataclass
class _Seg:
    """A run of text on one visual line without large gaps (one column of a form row)."""

    text: str
    chars: list  # parallel to text; None for synthetic spaces
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def height(self) -> float:
        return max(self.bottom - self.top, 1.0)


@dataclass
class _Run:
    """A horizontal line a signature can sit on (underscore run or drawn line)."""

    x0: float
    x1: float
    y: float  # top-based visual coordinate of the line
    owner: _Seg | None = None  # segment containing the run (underscores only)
    pure: bool = False  # underscores form the whole segment (not a prose blank)
    claimed: bool = False


def _segments(chars: list[dict]) -> list[_Seg]:
    chars = [c for c in chars if c.get("text") is not None]
    chars.sort(key=lambda c: (c["top"], c["x0"]))
    rows: list[list[dict]] = []
    for c in chars:
        size = max(c["bottom"] - c["top"], 1.0)
        if rows and abs(c["top"] - rows[-1][0]["top"]) <= 0.4 * size:
            rows[-1].append(c)
        else:
            rows.append([c])
    segs: list[_Seg] = []
    for row in rows:
        row.sort(key=lambda c: c["x0"])
        cur: list[dict] = []
        for c in row:
            size = max(c["bottom"] - c["top"], 1.0)
            if cur and c["x0"] - cur[-1]["x1"] > 2.5 * size:
                segs.append(_build_seg(cur))
                cur = []
            cur.append(c)
        if cur:
            segs.append(_build_seg(cur))
    return [s for s in segs if s.text.strip()]


def _build_seg(row: list[dict]) -> _Seg:
    text: list[str] = []
    mapping: list = []
    prev = None
    for c in row:
        size = max(c["bottom"] - c["top"], 1.0)
        if prev is not None and c["x0"] - prev["x1"] > 0.15 * size and c["text"] != " " and prev["text"] != " ":
            text.append(" ")
            mapping.append(None)
        text.append(c["text"])
        mapping.append(c)
        prev = c
    real = [c for c in row if c["text"].strip()] or row
    return _Seg(
        "".join(text),
        mapping,
        min(c["x0"] for c in real),
        max(c["x1"] for c in real),
        min(c["top"] for c in real),
        max(c["bottom"] for c in real),
    )


def _clean_label(text: str) -> str:
    return re.sub(r"\s+", " ", UNDERSCORE_RE.sub(" ", text)).strip()[:200]


def _collect_runs(segs: list[_Seg], page) -> list[_Run]:
    runs: list[_Run] = []
    for s in segs:
        pure = not _clean_label(s.text)
        for m in UNDERSCORE_RE.finditer(s.text):
            first, last = s.chars[m.start()], s.chars[m.end() - 1]
            runs.append(_Run(first["x0"], last["x1"], last["bottom"], owner=s, pure=pure))
    for ln in page.lines:
        if abs(ln["bottom"] - ln["top"]) < 1.5 and ln["x1"] - ln["x0"] >= 30:
            runs.append(_Run(ln["x0"], ln["x1"], (ln["top"] + ln["bottom"]) / 2))
    for r in page.rects:
        if r["bottom"] - r["top"] < 2 and r["x1"] - r["x0"] >= 30:
            runs.append(_Run(r["x0"], r["x1"], (r["top"] + r["bottom"]) / 2))
    return runs


def _options(a: _Seg, runs: list[_Run]) -> list[tuple[float, str, _Run]]:
    """Possible lines for anchor segment `a`: (cost, relation, run), cheaper is better."""
    h = a.height
    opts: list[tuple[float, str, _Run]] = []
    for r in runs:
        if r.owner is a:  # "Firma: ____" in the same segment
            opts.append((0.0, "right", r))
            continue
        if r.owner is not None and not r.pure:
            continue  # blank inside prose: never a signature line
        overlaps = r.x1 > a.x0 and r.x0 < a.x1 + 10
        if a.top + 0.4 * h <= r.y <= a.bottom + 0.6 * h and 0 <= r.x0 - a.x1 + 2 <= 150:
            opts.append((r.x0 - a.x1 + 2 + 0.0, "right", r))
        elif 0.6 * h < r.y - a.bottom <= 45 and overlaps:
            opts.append(((r.y - a.bottom) + 0.3 * abs(r.x0 - a.x0), "below", r))
        elif 0 <= a.top - r.y <= 30 and overlaps:
            opts.append((20 + (a.top - r.y) + 0.3 * abs(r.x0 - a.x0), "above", r))
    return sorted(opts, key=lambda o: o[0])


def _line_box(line_y: float, anchor: _Seg, rel: str) -> tuple[float, float]:
    """Vertical extent (top-based frame) of a stamp straddling the line like a handwritten signature.

    The ink crosses the line (25% of the height below it) and never covers the anchor label:
    the box is clamped to the label edge, and kept at MIN_BOX_HEIGHT by growing away from the label.
    """
    top = line_y - 0.75 * BOX_HEIGHT
    bottom = line_y + 0.25 * BOX_HEIGHT
    if rel == "below":  # label above the line
        top = max(top, anchor.bottom + 2)
        if bottom - top < MIN_BOX_HEIGHT:
            bottom = top + MIN_BOX_HEIGHT
    elif rel == "above":  # label under the line
        bottom = min(bottom, anchor.top - 2)
        if bottom - top < MIN_BOX_HEIGHT:
            top = bottom - MIN_BOX_HEIGHT
    return top, bottom


def _detect_page(page, pageno: int, rot: int, crop: list[float]) -> list[Candidate]:
    hd = float(page.height)
    bb = page.bbox

    def to_user(x0: float, top0: float, x1: float, top1: float) -> list[float]:
        # pdfplumber frame -> visual bottom-left frame -> user space
        vx0, vx1 = x0 - bb[0], x1 - bb[0]
        vy0, vy1 = hd - (top1 - bb[1]), hd - (top0 - bb[1])
        return visual_to_user_rect(rot, crop, [vx0, vy0, vx1, vy1])

    segs = _segments(page.chars)
    if not segs:
        return []
    runs = _collect_runs(segs, page)
    anchors = [s for s in segs if ANCHOR_RE.search(s.text)]

    # Greedy, cheapest-first assignment so adjacent columns do not steal each other's line.
    pool = sorted(
        ((cost, id(a), a, rel, r) for a in anchors for cost, rel, r in _options(a, runs)),
        key=lambda t: (t[0], t[1]),
    )
    assigned: dict[int, tuple[str, _Run]] = {}
    for _, aid, a, rel, r in pool:
        if aid in assigned or r.claimed:
            continue
        assigned[aid] = (rel, r)
        r.claimed = True

    out: list[Candidate] = []
    for a in anchors:
        label = _clean_label(a.text)
        short = len(label.split()) <= 6
        hit = assigned.get(id(a))
        if hit:
            rel, r = hit
            score = (0.9 if short else 0.6) - (0.1 if rel == "above" else 0.0)
            top_t, bot_t = _line_box(r.y, a, rel)
            box = to_user(r.x0, top_t, r.x1, bot_t)
            out.append(Candidate(pageno, box, "line", label, score, role_of(label)))
        else:
            score = 0.6 if short else 0.4
            baseline = a.bottom
            if a.x1 + 8 + DEFAULT_WIDTH <= page.width - 20:
                box = to_user(a.x1 + 8, baseline - BOX_HEIGHT, a.x1 + 8 + DEFAULT_WIDTH, baseline)
            else:
                box = to_user(a.x0, baseline + 6, a.x0 + DEFAULT_WIDTH, baseline + 6 + BOX_HEIGHT)
            out.append(Candidate(pageno, box, "anchor", label, score, role_of(label)))

    for r in runs:
        if not r.claimed and (r.owner is None or r.pure):
            box = to_user(r.x0, r.y - 0.75 * BOX_HEIGHT, r.x1, r.y + 0.25 * BOX_HEIGHT)
            out.append(Candidate(pageno, box, "line", "", 0.2))
    return out


def _acroform_candidates(reader: PdfReader) -> list[Candidate]:
    out: list[Candidate] = []
    for i, page in enumerate(reader.pages, start=1):
        for ref in page.get("/Annots") or []:
            try:
                annot = ref.get_object()
                if annot.get("/Subtype") != "/Widget":
                    continue
                ftype, node = None, annot
                while node is not None and ftype is None:
                    ftype = node.get("/FT")
                    node = node.get("/Parent")
                    node = node.get_object() if node is not None else None
                if ftype != "/Sig" or annot.get("/V") is not None:
                    continue  # not a signature field, or already signed
                x0, y0, x1, y1 = (float(v) for v in annot["/Rect"])
                label = str(annot.get("/T") or "signature field")
                out.append(
                    Candidate(
                        i,
                        [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
                        "acroform",
                        label,
                        1.0,
                        role_of(label),
                    )
                )
            except Exception:
                continue  # malformed annotation: skip it, keep the rest
    return out


def _intersects(a: list[float], b: list[float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def detect_candidates(
    path: str | Path, include_low: bool = False
) -> tuple[int, list[Candidate]]:
    """Return (page_count, candidates sorted by score desc). Low scores need include_low."""
    p = check_pdf_path(path)
    try:
        reader = PdfReader(str(p))
        n = len(reader.pages)
        cands = _acroform_candidates(reader)
        fields = list(cands)
        with pdfplumber.open(p) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                rpage = reader.pages[i - 1]
                crop = [float(v) for v in rpage.cropbox]
                rot = int(rpage.rotation)
                for c in _detect_page(page, i, rot, crop):
                    if any(f.page == i and _intersects(c.bbox, f.bbox) for f in fields):
                        continue  # the real form field already covers this spot
                    cands.append(c)
    except PdfSignError:
        raise
    except Exception as exc:  # pypdf/pdfminer raise many types for broken files
        raise PdfSignError("invalid_pdf", f"Cannot read PDF: {exc}", EXIT_INVALID_INPUT) from exc
    if not include_low:
        cands = [c for c in cands if c.score >= MIN_SCORE]
    cands.sort(key=lambda c: (-c.score, c.page, -c.bbox[3], c.bbox[0]))
    return n, cands

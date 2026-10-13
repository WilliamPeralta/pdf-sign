"""Free-space placement of a stamp around a signature line.

Everything here works in the displayed frame with a bottom-left origin ("visual" frame).
Text boxes come from pdfplumber chars; underscores are the line itself, not obstacles.
"""

from __future__ import annotations

MAX_BAND = 60.0  # tallest stamp band around a line
DEFAULT_BELOW = 40.0  # room assumed below the line when no text is close
LOOKUP_BELOW = 80.0  # text further below than this is ignored
MAX_BELOW = 45.0  # never let the stamp reach further below the line than this
MARGIN = 2.0
MIN_BAND = 6.0

Rect = list[float]


def text_boxes(page) -> list[Rect]:
    """Char boxes (visual bottom-left frame) of every non-space, non-underscore char."""
    hd = float(page.height)
    bb = page.bbox
    out: list[Rect] = []
    for c in page.chars:
        t = c.get("text") or ""
        if not t.strip() or set(t) <= {"_"}:
            continue
        out.append([c["x0"] - bb[0], hd - (c["bottom"] - bb[1]), c["x1"] - bb[0], hd - (c["top"] - bb[1])])
    return out


def band(boxes: list[Rect], x0: float, x1: float, line_y: float) -> tuple[float, float]:
    """Free vertical band (bottom, top) around the line within [x0, x1]; always contains line_y."""
    near = [b for b in boxes if b[0] < x1 and b[2] > x0]
    above = [b[1] for b in near if (b[1] + b[3]) / 2 > line_y]
    below = [b[3] for b in near if (b[1] + b[3]) / 2 <= line_y and b[3] >= line_y - LOOKUP_BELOW]
    top = (min(above) - MARGIN) if above else line_y + MAX_BAND
    bottom = (max(below) + MARGIN) if below else line_y - DEFAULT_BELOW
    bottom = max(bottom, line_y - MAX_BELOW, 0.0)
    top = max(top, line_y + 1)
    bottom = min(bottom, line_y - 1)
    top = min(top, bottom + MAX_BAND)
    return bottom, max(top, bottom + MIN_BAND)


def _fits(boxes: list[Rect], x0: float, w: float, line_y: float, aspect: float) -> bool:
    lo, hi = band(boxes, x0, x0 + w, line_y)
    return w / aspect <= (hi - lo) + 1e-6


def fit_stamp(
    boxes: list[Rect], x0: float, x1: float, line_y: float, aspect: float, width: float | None = None
) -> tuple[Rect, bool]:
    """Largest stamp (aspect w/h kept) left-aligned at x0, crossing line_y, clear of all text.

    Without `width` it is bounded by the line length; with `width` that is the wish and the result
    shrinks if text is in the way (second value True when it did).
    """
    wish = width if width is not None else (x1 - x0)
    valid: list[float] = []
    w = wish
    for _ in range(8):  # fixed point: width implied by the band over the current x-range
        lo, hi = band(boxes, x0, x0 + w, line_y)
        nw = min(wish, (hi - lo) * aspect)
        if _fits(boxes, x0, nw, line_y, aspect):
            valid.append(nw)
        if abs(nw - w) < 0.01:
            break
        w = nw
    w = min(w, wish)
    while not _fits(boxes, x0, w, line_y, aspect) and w > 1:  # conservative shrink fallback
        w *= 0.95
    valid.append(w)
    w = max(valid)
    h = w / aspect
    lo, hi = band(boxes, x0, x0 + w, line_y)
    b = min(max(line_y - 0.25 * h, lo), hi - h)  # straddle the line: ~25% below it
    return [x0, b, x0 + w, b + h], (width is not None and w < width - 0.01)

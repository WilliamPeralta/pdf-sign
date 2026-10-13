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


def _free_width(boxes: list[Rect], x0: float, x1: float, line_y: float, aspect: float) -> float:
    """Widest stamp (aspect kept) that fits the free band around the line without touching text."""
    wish = x1 - x0
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
    return max(valid)


def _overlap(r: Rect, b: Rect) -> float:
    dx = min(r[2], b[2]) - max(r[0], b[0])
    dy = min(r[3], b[3]) - max(r[1], b[1])
    return dx * dy if dx > 0 and dy > 0 else 0.0


def _in(b: Rect, label: Rect) -> bool:
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return label[0] <= cx <= label[2] and label[1] <= cy <= label[3]


def fit_stamp(
    boxes: list[Rect],
    x0: float,
    x1: float,
    line_y: float,
    aspect: float,
    width: float | None = None,
    min_width: float = 0.0,
    label: Rect | None = None,
    floor: float = 0.0,
) -> tuple[Rect, dict]:
    """Stamp (aspect w/h kept) left-aligned near x0 that crosses line_y with the least text overlap.

    Size: explicit `width` wins (capped at the line length -> `clamped`); otherwise the largest size
    fitting the free band, enlarged to `min_width` (capped at the line length) when smaller.
    Position: searched so 15-60% of the height is below the line; the score is the intersection
    area with text, 3x for the anchor label; ties prefer leftmost, then ~25% below the line.
    """
    line_len = x1 - x0
    clamped = applied = False
    if width is not None:
        w = min(width, line_len)
        clamped = width > line_len + 0.01
    else:
        w0 = _free_width(boxes, x0, x1, line_y, aspect)
        w = w0
        if w0 < min_width:
            w = min(min_width, line_len)
            applied = w > w0 + 0.01
    h = w / aspect
    near = [b for b in boxes if b[2] > x0 and b[0] < x1 and b[3] > line_y - 2 * h and b[1] < line_y + 2 * h]

    def score(r: Rect) -> float:
        return sum(_overlap(r, b) * (3.0 if label and _in(b, label) else 1.0) for b in near)

    bottoms = []
    k = 0.0
    while line_y - 0.6 * h + k <= line_y - 0.15 * h + 1e-9:
        bottoms.append(line_y - 0.6 * h + k)
        k += 2.0
    lo, hi = band(boxes, x0, x0 + w, line_y)
    b0 = min(max(line_y - 0.25 * h, lo), hi - h)  # free-band position, when it exists
    if b0 < line_y < b0 + h:
        bottoms.append(b0)
    xs = []
    k = 0.0
    while x0 + k < x1 - w:
        xs.append(x0 + k)
        k += 4.0
    xs.append(max(x0, x1 - w))
    best = None
    for bottom in bottoms:
        if bottom < floor:
            continue
        frac = (line_y - bottom) / h
        for x in xs:
            r = [x, bottom, x + w, bottom + h]
            key = (round(score(r), 2), round(x, 2), abs(frac - 0.25))
            if best is None or key < best[0]:
                best = (key, r)
    if best is None:  # page floor excludes every position: fall back to the free-band one
        best = ((0, 0, 0), [x0, b0, x0 + w, b0 + h])
    rect = best[1]
    flags = {"clamped": clamped, "min_width_applied": applied, "overlaps_text": score(rect) > 0.01}
    return rect, flags

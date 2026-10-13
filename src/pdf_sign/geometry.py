"""Conversions between the displayed ("visual") page frame and PDF user space.

Visual frame: origin at the bottom-left of the *displayed* page (after /Rotate), x right, y up.
User space: raw PDF coordinates, bottom-left origin, may have a non-zero crop/media box origin.
Rects are [x0, y0, x1, y1].
"""

from __future__ import annotations

Rect = list[float]


def _normalize(r: Rect) -> Rect:
    return [min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])]


def visual_to_user_point(rot: int, crop: Rect, vx: float, vy: float) -> tuple[float, float]:
    cx0, cy0, cx1, cy1 = crop
    w, h = cx1 - cx0, cy1 - cy0
    rot %= 360
    if rot == 0:
        ux, uy = vx, vy
    elif rot == 90:
        ux, uy = w - vy, vx
    elif rot == 180:
        ux, uy = w - vx, h - vy
    elif rot == 270:
        ux, uy = vy, h - vx
    else:
        raise ValueError(f"unsupported rotation {rot}")
    return cx0 + ux, cy0 + uy


def user_to_visual_point(rot: int, crop: Rect, x: float, y: float) -> tuple[float, float]:
    cx0, cy0, cx1, cy1 = crop
    w, h = cx1 - cx0, cy1 - cy0
    ux, uy = x - cx0, y - cy0
    rot %= 360
    if rot == 0:
        return ux, uy
    if rot == 90:
        return uy, w - ux
    if rot == 180:
        return w - ux, h - uy
    if rot == 270:
        return h - uy, ux
    raise ValueError(f"unsupported rotation {rot}")


def visual_to_user_rect(rot: int, crop: Rect, r: Rect) -> Rect:
    a = visual_to_user_point(rot, crop, r[0], r[1])
    b = visual_to_user_point(rot, crop, r[2], r[3])
    return _normalize([a[0], a[1], b[0], b[1]])


def user_to_visual_rect(rot: int, crop: Rect, r: Rect) -> Rect:
    a = user_to_visual_point(rot, crop, r[0], r[1])
    b = user_to_visual_point(rot, crop, r[2], r[3])
    return _normalize([a[0], a[1], b[0], b[1]])

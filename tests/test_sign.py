import json
import subprocess
import sys

import pdfplumber
import pytest
from pypdf import PdfReader

from pdf_sign.geometry import user_to_visual_point, visual_to_user_point


def run_cli(*args):
    return subprocess.run([sys.executable, "-m", "pdf_sign", *args], capture_output=True, text=True)


def sign(pdf, png, *extra):
    r = run_cli("sign", str(pdf), "--signature", str(png), *extra)
    return r, (json.loads(r.stdout) if r.stdout else None)


def image_count(path, page=0):
    xo = PdfReader(str(path)).pages[page]["/Resources"].get("/XObject") or {}
    return sum(1 for v in xo.values() if v.get_object().get("/Subtype") == "/Image")


def ink_bbox(path, page=0, scale=2):
    """Bounding box of the signature ink (dark blue) in PDF points, top-left origin (pdfplumber frame)."""
    with pdfplumber.open(path) as pdf:
        pg = pdf.pages[page]
        img = pg.to_image(resolution=72 * scale).original.convert("RGB")
    xs, ys = [], []
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = img.getpixel((x, y))
            if b > 90 and r < 60 and g < 80:
                xs.append(x)
                ys.append(y)
    assert xs, "no signature ink found in render"
    return min(xs) / scale, min(ys) / scale, max(xs) / scale, max(ys) / scale


def test_auto_sign_default_output(anchor_underscore_pdf, signature_png):
    r, out = sign(anchor_underscore_pdf, signature_png)
    assert r.returncode == 0, r.stderr
    dest = anchor_underscore_pdf.with_name("anchor_underscore.signed.pdf")
    assert dest.exists() and out["output"] == str(dest)
    assert image_count(dest) == 1
    assert image_count(anchor_underscore_pdf) == 0  # input untouched
    p = out["placements"][0]
    assert p["page"] == 1 and p["source"] == "line"
    # ink sits on the underscore line (baseline y=500 -> top-based ~342), right of "Firma:"
    x0, top, x1, bottom = ink_bbox(dest)
    assert x0 > 100
    # ink lies inside the stamp box, which straddles the line (baseline y=500)
    _, sy0, _, sy1 = p["stamp"]
    assert sy0 < 500 < sy1  # crosses the baseline line
    assert 841.89 - sy1 - 1 <= top and bottom <= 841.89 - sy0 + 1


def test_keeps_aspect_ratio_and_fits_box(anchor_underscore_pdf, signature_png):
    _, out = sign(anchor_underscore_pdf, signature_png)
    x0, y0, x1, y1 = out["placements"][0]["stamp"]
    assert (x1 - x0) / (y1 - y0) == pytest.approx(200 / 80, rel=0.01)
    assert y1 - y0 <= 60.01


def test_never_overwrites_without_force(anchor_underscore_pdf, signature_png, tmp_path):
    out_pdf = tmp_path / "o.pdf"
    out_pdf.write_bytes(b"existing")
    r, _ = sign(anchor_underscore_pdf, signature_png, "-o", str(out_pdf))
    assert r.returncode == 1 and json.loads(r.stderr)["error"]["code"] == "output_exists"
    assert out_pdf.read_bytes() == b"existing"
    r, _ = sign(anchor_underscore_pdf, signature_png, "-o", str(out_pdf), "--force")
    assert r.returncode == 0 and image_count(out_pdf) == 1


def test_refuses_output_equal_to_input(anchor_underscore_pdf, signature_png):
    r, _ = sign(anchor_underscore_pdf, signature_png, "-o", str(anchor_underscore_pdf), "--force")
    assert r.returncode == 1


def test_no_candidate_exit_2(blank_pdf, signature_png):
    r, _ = sign(blank_pdf, signature_png)
    assert r.returncode == 2
    assert json.loads(r.stderr)["error"]["code"] == "no_candidate"
    assert not blank_pdf.with_name("blank.signed.pdf").exists()


def test_invalid_image_exit_3(anchor_underscore_pdf, tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_text("nope")
    r, _ = sign(anchor_underscore_pdf, bad)
    assert r.returncode == 3 and json.loads(r.stderr)["error"]["code"] == "invalid_image"


def test_missing_signature_file(anchor_underscore_pdf, tmp_path):
    r, _ = sign(anchor_underscore_pdf, tmp_path / "missing.png")
    assert r.returncode == 1


def test_manual_coordinates(blank_pdf, signature_png, tmp_path):
    out = tmp_path / "m.pdf"
    r, data = sign(blank_pdf, signature_png, "--page", "1", "--x", "100", "--y", "300",
                   "--width", "100", "-o", str(out))
    assert r.returncode == 0, r.stderr
    assert data["placements"][0]["source"] == "manual"
    assert data["placements"][0]["stamp"] == [100, 300, 200, 340]
    x0, top, x1, bottom = ink_bbox(out)
    assert x0 == pytest.approx(100 + 100 * 10 / 200, abs=3)  # ink starts 10px into the PNG
    assert bottom == pytest.approx(841.89 - 300 - 100 * 30 / 200, abs=3)


def test_manual_requires_all_coordinates(blank_pdf, signature_png):
    r, _ = sign(blank_pdf, signature_png, "--page", "1", "--x", "100")
    assert r.returncode == 1 and json.loads(r.stderr)["error"]["code"] == "usage"


def test_manual_page_out_of_range(blank_pdf, signature_png):
    r, _ = sign(blank_pdf, signature_png, "--page", "5", "--x", "1", "--y", "1")
    assert r.returncode == 1


def test_width_override_on_candidate(anchor_drawn_line_pdf, signature_png):
    _, out = sign(anchor_drawn_line_pdf, signature_png, "--width", "80")
    x0, y0, x1, y1 = out["placements"][0]["stamp"]
    assert x1 - x0 == pytest.approx(80, abs=0.1)


def test_acroform_field_is_filled_exactly(acroform_sig_pdf, signature_png):
    _, out = sign(acroform_sig_pdf, signature_png)
    p = out["placements"][0]
    assert p["source"] == "acroform"
    x0, y0, x1, y1 = p["stamp"]
    assert 100 <= x0 and x1 <= 300 and 200 <= y0 and y1 <= 260


def test_match_selects_signer_only(real_layout_pdf, signature_png):
    r, out = sign(real_layout_pdf, signature_png, "--match", "accettazione|dipendente")
    assert r.returncode == 0
    assert out["placements"][0]["label"] == "Firma per accettazione"
    assert len(out["placements"]) == 1


def test_all_signs_best_spot_per_page(real_layout_pdf, signature_png):
    dest = real_layout_pdf.with_name("all.pdf")
    r, out = sign(real_layout_pdf, signature_png, "--all", "--match", "accettazione|dipendente",
                  "-o", str(dest))
    assert r.returncode == 0, r.stderr
    assert [p["page"] for p in out["placements"]] == [1, 2]
    assert image_count(dest, 0) == 1 and image_count(dest, 1) == 1


def test_candidate_index_and_exclude(real_layout_pdf, signature_png):
    _, out = sign(real_layout_pdf, signature_png, "--exclude", "datore|legale", "--candidate", "2")
    assert out["placements"][0]["label"] == "Firma del dipendente"
    r, _ = sign(real_layout_pdf, signature_png, "--candidate", "9", "--force")
    assert r.returncode == 2


def test_rotated_page_signature_is_upright(rotated_pdf, signature_png, tmp_path):
    out = tmp_path / "rot.pdf"
    r, data = sign(rotated_pdf, signature_png, "-o", str(out))
    assert r.returncode == 0, r.stderr
    # Rendered (displayed) frame: ink must be wider than tall (upright 2.5:1 image), left of x=300
    x0, top, x1, bottom = ink_bbox(out)
    assert (x1 - x0) > (bottom - top)
    # displayed position matches the anchor: user (300,100) -> visual (100, 295 from bottom)
    vx, vy = user_to_visual_point(90, [0, 0, 595.27, 841.89], 300, 100)
    assert x0 > vx
    assert bottom == pytest.approx(595.27 - vy, abs=20)  # ink near the line (PNG ink is mid-image), displayed top-based frame


def test_offset_mediabox_signature_inside_page(offset_mediabox_pdf, signature_png, tmp_path):
    out = tmp_path / "off.pdf"
    r, data = sign(offset_mediabox_pdf, signature_png, "-o", str(out))
    assert r.returncode == 0, r.stderr
    x0, y0, x1, y1 = data["placements"][0]["stamp"]
    assert 50 <= x0 and x1 <= 50 + 595.3 and 50 <= y0 and y1 <= 50 + 841.9
    ink_bbox(out)  # visible in render


def test_geometry_roundtrip():
    crop = [10, 20, 610, 820]
    for rot in (0, 90, 180, 270):
        v = user_to_visual_point(rot, crop, 123, 456)
        assert visual_to_user_point(rot, crop, *v) == pytest.approx((123, 456))


def _word_box(path, word, page=0):
    with pdfplumber.open(path) as pdf:
        for w in pdf.pages[page].extract_words():
            if w["text"] == word:
                return w
    raise AssertionError(word)


def _underscore_y(path, page=0, below=None):
    with pdfplumber.open(path) as pdf:
        ys = sorted(c["bottom"] for c in pdf.pages[page].chars if c["text"] == "_" and (below is None or c["bottom"] > below))
    return ys[0]


def test_stamp_straddles_line_without_covering_label(real_layout_pdf, signature_png):
    _, out = sign(real_layout_pdf, signature_png, "--match", "accettazione")
    sx0, sy0, sx1, sy1 = out["placements"][0]["stamp"]
    s_top, s_bottom = 841.89 - sy1, 841.89 - sy0  # top-based frame
    label = _word_box(real_layout_pdf, "accettazione")
    line_y = _underscore_y(real_layout_pdf, below=label["bottom"])
    assert s_top >= label["bottom"]  # never covers the label
    assert s_top < line_y < s_bottom  # ink crosses the line
    assert sy1 - sy0 >= 24 - 0.01
    assert sx0 == pytest.approx(330, abs=2)  # left-aligned to the line start


def test_stamp_above_label_layout_does_not_cover_label(tmp_path, signature_png):
    from reportlab.pdfgen import canvas

    p = tmp_path / "label_below.pdf"
    c = canvas.Canvas(str(p))
    c.setFont("Helvetica", 11)
    c.drawString(72, 400, "____________________")
    c.drawString(72, 388, "Il dichiarante")
    c.save()
    _, out = sign(p, signature_png)
    pl = out["placements"][0]
    _, sy0, _, sy1 = pl["stamp"]
    label = _word_box(p, "dichiarante")
    assert 841.89 - sy0 <= label["top"] + 0.01  # stamp bottom stays above the label top
    assert sy1 - sy0 >= 24 - 0.01


# ---- free-space placement: grow into free space, never touch text, --width is clamped ----


def _text_boxes(path, page=0):
    with pdfplumber.open(path) as pdf:
        pg = pdf.pages[page]
        return [(c["x0"], c["top"], c["x1"], c["bottom"]) for c in pg.chars
                if c["text"].strip() and c["text"] != "_"], pg.height


def assert_no_text_overlap(path, stamp, page=0):
    boxes, height = _text_boxes(path, page)
    sx0, sy0, sx1, sy1 = stamp
    s = (sx0, height - sy1, sx1, height - sy0)  # top-based
    for b in boxes:
        hit = s[0] < b[2] and b[0] < s[2] and s[1] < b[3] and b[1] < s[3]
        assert not hit, f"stamp {s} intersects text {b}"


@pytest.fixture
def text_below_pdf(tmp_path):
    """Underscore line with a name 20pt below it and prose above."""
    from reportlab.pdfgen import canvas

    p = tmp_path / "text_below.pdf"
    c = canvas.Canvas(str(p))
    c.setFont("Helvetica", 11)
    c.drawString(72, 430, "Per accettazione, il dipendente")
    c.drawString(72, 400, "Firma")
    c.drawString(72, 385, "____________________")
    c.drawString(72, 365, "Mario Rossi, matricola 123")
    c.save()
    return p


def test_stamp_grows_into_free_space_below_line(real_layout_pdf, signature_png):
    _, out = sign(real_layout_pdf, signature_png, "--match", "accettazione")
    _, sy0, _, sy1 = out["placements"][0]["stamp"]
    assert sy1 - sy0 > 40  # old rule capped at 24pt here
    assert sy1 - sy0 <= 60.01
    assert sy0 < 282.6 < sy1
    assert out["placements"][0]["clamped"] is False


def test_stamp_stops_before_text_below(text_below_pdf, signature_png):
    _, out = sign(text_below_pdf, signature_png, "--match", "^Firma$", "--min-width", "0")
    st = out["placements"][0]["stamp"]
    boxes, height = _text_boxes(text_below_pdf)
    name_top = min(b[1] for b in boxes if b[1] > height - 385)  # text under the line
    assert height - st[1] <= name_top + 0.01
    assert st[1] < 385 - 2.4 < st[3]  # crosses the line
    assert_no_text_overlap(text_below_pdf, st)


@pytest.mark.parametrize("fixture,match", [
    ("real_layout_pdf", "accettazione"),
    ("real_layout_pdf", "datore"),
    ("anchor_underscore_pdf", None),
    ("text_below_pdf", "^Firma$"),
])
def test_stamp_never_intersects_text(request, signature_png, fixture, match):
    pdf = request.getfixturevalue(fixture)
    extra = (["--match", match] if match else []) + ["--min-width", "0"]
    _, out = sign(pdf, signature_png, *extra)
    assert_no_text_overlap(pdf, out["placements"][0]["stamp"])


def test_width_is_clamped_to_line_length(text_below_pdf, signature_png):
    _, out = sign(text_below_pdf, signature_png, "--match", "^Firma$", "--width", "400")
    pl = out["placements"][0]
    x0, y0, x1, y1 = pl["stamp"]
    assert pl["clamped"] is True  # wider than the line
    assert x1 - x0 < 400
    assert (x1 - x0) / (y1 - y0) == pytest.approx(2.5, rel=0.01)


def test_width_not_clamped_when_it_fits(text_below_pdf, signature_png):
    _, out = sign(text_below_pdf, signature_png, "--match", "^Firma$", "--width", "40")
    pl = out["placements"][0]
    assert pl["clamped"] is False and pl["min_width_applied"] is False
    assert pl["stamp"][2] - pl["stamp"][0] == pytest.approx(40, abs=0.1)


# ---- minimum legible size + overlap-minimizing search ----


@pytest.fixture
def crowded_left_pdf(tmp_path):
    """Long line; text hugging it on the left (above and below), free space to the right."""
    from reportlab.pdfgen import canvas

    p = tmp_path / "crowded_left.pdf"
    c = canvas.Canvas(str(p))
    c.setFont("Helvetica", 11)
    c.drawString(72, 400, "Firma")
    c.drawString(72, 385, "________________________________________")
    c.drawString(72, 375, "Mario Rossi")
    c.save()
    return p


def test_min_width_enforced_and_flagged(text_below_pdf, signature_png):
    _, out = sign(text_below_pdf, signature_png, "--match", "^Firma$")
    pl = out["placements"][0]
    x0, y0, x1, y1 = pl["stamp"]
    assert x1 - x0 >= 100 - 0.01
    assert pl["min_width_applied"] is True
    assert pl["overlaps_text"] is True  # a 40pt stamp cannot fit the 19pt band
    assert y0 < 385 - 2.4 < y1  # still crosses the line
    assert 0.15 * (y1 - y0) - 0.5 <= (385 - 2.4) - y0 <= 0.6 * (y1 - y0) + 0.5


def test_min_width_zero_disables(text_below_pdf, signature_png):
    _, out = sign(text_below_pdf, signature_png, "--match", "^Firma$", "--min-width", "0")
    pl = out["placements"][0]
    assert pl["min_width_applied"] is False and pl["overlaps_text"] is False
    assert pl["stamp"][2] - pl["stamp"][0] < 100


def test_min_width_capped_by_line_length(real_layout_pdf, signature_png):
    _, out = sign(real_layout_pdf, signature_png, "--match", "accettazione", "--min-width", "300")
    x0, _, x1, _ = out["placements"][0]["stamp"]
    assert x1 - x0 <= 125  # the underscore run is ~110pt long


def test_search_moves_stamp_away_from_text(crowded_left_pdf, signature_png):
    _, out = sign(crowded_left_pdf, signature_png, "--match", "^Firma$")
    pl = out["placements"][0]
    x0, _, x1, _ = pl["stamp"]
    assert x1 - x0 >= 100 - 0.01
    assert pl["overlaps_text"] is False
    assert x0 > 72 + 55  # slid right of "Mario Rossi" / "Firma"
    assert_no_text_overlap(crowded_left_pdf, pl["stamp"])


def test_explicit_width_wins_over_min_width(crowded_left_pdf, signature_png):
    _, out = sign(crowded_left_pdf, signature_png, "--match", "^Firma$", "--width", "60")
    pl = out["placements"][0]
    assert pl["stamp"][2] - pl["stamp"][0] == pytest.approx(60, abs=0.1)
    assert pl["min_width_applied"] is False and pl["clamped"] is False


def test_label_overlap_is_penalized_3x():
    from pdf_sign.placement import fit_stamp

    label = [0.0, 120.0, 100.0, 130.0]
    below = [0.0, 70.0, 100.0, 85.0]
    rect, flags = fit_stamp([label, below], 0.0, 100.0, 100.0, 2.5, min_width=100.0, label=label)
    assert rect[3] <= 120.01  # keeps clear of the label even though the other text is hit
    assert flags["overlaps_text"] is True
    # without the label weighting the tie-break (~25% below) would have covered the label
    rect2, _ = fit_stamp([label, below], 0.0, 100.0, 100.0, 2.5, min_width=100.0, label=None)
    assert rect2[3] > 120.01

import json
import subprocess
import sys

import pytest

from pdf_sign.detect import detect_candidates, filter_candidates


def cands(path, **kw):
    return detect_candidates(path, **kw)[1]


def test_acroform_signature_field(acroform_sig_pdf):
    pages, found = detect_candidates(acroform_sig_pdf)
    assert pages == 1
    top = found[0]
    assert top.source == "acroform"
    assert top.page == 1
    assert top.bbox == [100, 200, 300, 260]
    assert top.label == "ClientSignature"
    assert top.score == 1.0


def test_anchor_with_underscore_same_line(anchor_underscore_pdf):
    top = cands(anchor_underscore_pdf)[0]
    assert top.source == "line"
    assert top.label == "Firma:"
    x0, y0, x1, y1 = top.bbox
    # underscores start right of "Firma:" (x > 72+30) and the box sits on the baseline (500)
    assert 100 < x0 < 140 and 485 <= y0 <= 492  # straddles: ~10pt below the line
    assert y1 - y0 == pytest.approx(40, abs=1)
    assert top.score >= 0.8


def test_anchor_with_drawn_line(anchor_drawn_line_pdf):
    top = cands(anchor_drawn_line_pdf)[0]
    assert top.source == "line"
    assert top.bbox[0] == pytest.approx(160, abs=1)
    assert top.bbox[2] == pytest.approx(360, abs=1)
    assert top.bbox[1] == pytest.approx(488, abs=3)


def test_anchor_without_line_places_right(anchor_only_pdf):
    top = cands(anchor_only_pdf)[0]
    assert top.source == "anchor"
    assert top.label == "Il dichiarante"
    assert top.bbox[0] > 72 + 60  # right of the anchor text
    assert 0.5 <= top.score < 0.8


def test_lookalike_words_do_not_match(conferma_pdf):
    assert cands(conferma_pdf, include_low=True) == []


def test_underscore_only_is_low_score(underscore_only_pdf):
    assert cands(underscore_only_pdf) == []
    low = cands(underscore_only_pdf, include_low=True)
    # "Nome: ____" is a prose blank, never a candidate
    assert low == []


def test_bare_underscore_line_low_score_with_all(tmp_path):
    from reportlab.pdfgen import canvas

    p = tmp_path / "bare.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(100, 300, "______________________")
    c.save()
    assert cands(p) == []
    low = cands(p, include_low=True)
    assert len(low) == 1 and low[0].source == "line" and low[0].score < 0.5


def test_no_candidate(blank_pdf):
    assert cands(blank_pdf, include_low=True) == []


def test_scanned_pdf_has_no_candidates(scanned_like_pdf):
    pages, found = detect_candidates(scanned_like_pdf)
    assert pages == 1 and found == []


def test_real_layout_underscore_on_next_line(real_layout_pdf):
    found = cands(real_layout_pdf)
    labels = {c.label: c for c in found}
    assert set(labels) == {
        "Firma del datore di lavoro",
        "Firma per accettazione",
        "Timbro e firma del legale rappresentante",
        "Firma del dipendente",
    }
    # prose blanks ("Targa: ____", "Il dipendente ____ dichiara") are not candidates
    emp = labels["Firma per accettazione"]
    assert emp.page == 1 and emp.source == "line" and emp.score >= 0.8
    # image sits just above the underscore line (baseline 285), starts at the run's x0
    assert emp.bbox[0] == pytest.approx(330, abs=2)
    # label sits 15pt above the line: box is clamped under the label, min height 24, crosses the line
    assert emp.bbox[1] < 282.6 < emp.bbox[3]
    assert emp.bbox[3] - emp.bbox[1] == pytest.approx(24, abs=1)
    assert labels["Firma del dipendente"].page == 2
    # the two columns resolve to distinct underscore runs
    assert labels["Firma del datore di lavoro"].bbox[0] == pytest.approx(72, abs=2)


def test_role_hints(real_layout_pdf):
    roles = {c.label: c.role for c in cands(real_layout_pdf)}
    assert roles["Firma del datore di lavoro"] == "employer"
    assert roles["Timbro e firma del legale rappresentante"] == "employer"
    assert roles["Firma per accettazione"] == "signer"
    assert roles["Firma del dipendente"] == "signer"


def test_filter_match_and_exclude(real_layout_pdf):
    found = cands(real_layout_pdf)
    mine = filter_candidates(found, match="accettazione|dipendente")
    assert {c.label for c in mine} == {"Firma per accettazione", "Firma del dipendente"}
    rest = filter_candidates(found, exclude="DATORE|legale")
    assert len(rest) == 2


def test_sorted_by_score_desc(real_layout_pdf, anchor_only_pdf):
    s = [c.score for c in cands(real_layout_pdf)]
    assert s == sorted(s, reverse=True)


def test_rotated_page_uses_user_space(rotated_pdf):
    top = cands(rotated_pdf)[0]
    x0, y0, x1, y1 = top.bbox
    assert top.label == "Firma:"
    # visual horizontal runs along user-space Y on a /Rotate 90 page
    assert (y1 - y0) > (x1 - x0)
    # line at user x~300; box extends 10pt below it (user +x) and 30pt above (user -x)
    assert x1 == pytest.approx(310, abs=8)
    assert x1 - x0 == pytest.approx(40, abs=1)
    assert y0 > 100


def test_offset_mediabox(offset_mediabox_pdf):
    top = cands(offset_mediabox_pdf)[0]
    # content origin offset by (0,0) in user space; box lives inside the shifted mediabox
    assert top.bbox[1] == pytest.approx(488, abs=5)
    assert top.bbox[0] > 100


def run_cli(*args):
    return subprocess.run([sys.executable, "-m", "pdf_sign", *args], capture_output=True, text=True)


def test_cli_detect_json_and_exit_codes(anchor_underscore_pdf, blank_pdf):
    r = run_cli("detect", str(anchor_underscore_pdf))
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["pages"] == 1
    c = data["candidates"][0]
    assert set(c) == {"page", "bbox", "source", "label", "score", "role"}
    r = run_cli("detect", str(blank_pdf))
    assert r.returncode == 2
    assert json.loads(r.stdout)["candidates"] == []
    assert r.stderr == ""


def test_cli_detect_match_exclude(real_layout_pdf):
    r = run_cli("detect", str(real_layout_pdf), "--match", "accettazione|dipendente")
    data = json.loads(r.stdout)
    assert {c["label"] for c in data["candidates"]} == {"Firma per accettazione", "Firma del dipendente"}
    assert {c["role"] for c in data["candidates"]} == {"signer"}
    r = run_cli("detect", str(real_layout_pdf), "--match", "nonexistent")
    assert r.returncode == 2

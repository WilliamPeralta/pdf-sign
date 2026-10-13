# Feature: pdf-sign CLI

## Objective
A small, agent-friendly CLI that detects where a PDF should be signed and stamps a PNG signature image there.

## Problem / Why
PDFs arrive frequently with a request to sign them. Signing manually is slow. An AI agent should be able to call a deterministic CLI with JSON output to detect the spot and apply the signature.

## Scope
- `detect`: find signature placement candidates, ranked, JSON output.
- `sign`: stamp a PNG (with alpha) on the best candidate or explicit coordinates; write a new PDF, never overwrite the input.
- Visual signature only. NOT a cryptographic/qualified digital signature (PAdES/CAdES).

## Constraints
- Permissively licensed dependencies only (no AGPL): pdfplumber (MIT), pypdf (BSD-3), reportlab (BSD), Pillow (MIT-CMU).
- Python >= 3.11, managed with `uv`. Entry point `pdf-sign`.
- Agent-friendly: no prompts, stable JSON on stdout, errors as JSON on stderr, non-zero exit codes.

## Detection strategy (ordered by confidence)
1. AcroForm signature fields (`/FT /Sig`) -> exact rect.
2. Text anchors (IT/EN): "Firma", "Signature", "Signed", "Il dichiarante", "Letto, confermato e sottoscritto", "In fede", etc.
3. Underscore lines / drawn horizontal lines near anchors -> placement on the line.
4. Fallback: none found -> empty candidates, exit code 2.

## Delivery strategy
ask-on-risk. Forecast ~600 authored lines (incl. tests) -> slicing question deferred: local-only project, no remote yet.

## TDD
Mode: enabled (source: user global config "Strict TDD Mode: enabled"). Runner: `uv run pytest`.

## Tasks
- [x] T1 Scaffold: pyproject (uv), package `pdf_sign`, CLI skeleton (`detect`, `sign`), pytest + test PDF fixtures generated with reportlab. Route: delegated (writer trigger: 2+ non-trivial files).
- [x] T2 Detection: AcroForm sig fields + text anchors + underscore/line heuristics, scoring, JSON output. Route: delegated.
- [x] T3 Signing: PNG overlay via reportlab + pypdf merge, auto (best candidate) and manual coordinates, size/aspect handling. Route: delegated.
- [x] T4 Agent docs: README with JSON contract, exit codes, examples for agents. Route: delegated.

## Acceptance criteria
- `pdf-sign detect in.pdf` prints JSON candidates with page, bbox, source, score.
- `pdf-sign sign in.pdf --signature sig.png [-o out.pdf]` produces a signed PDF; image visible at detected spot.
- `--page/--x/--y/--width` override detection.
- Tests cover form field, text anchor, underscore line, no-candidate cases.

## Progress / Evidence
- T1 done. RED: 4/4 cli tests failed (no module), then 2 more RED for sign subcommand; GREEN: 5 passed (`uv run pytest -q`). Commit: see git log (chore: scaffold pdf-sign cli).
- T2 done. RED: test_detect.py ImportError (detect_candidates/filter_candidates missing); GREEN: 22 passed. Real-doc smoke (read-only corpus, not committed): 20 files, signer/employer spots found on all text PDFs, 0 candidates (exit 2) on the 2 scanned Gennaio files. Added `role` hint and `--match/--exclude`. Commit: feat(detect).
- T3 done. RED: 13 failed/5 passed in tests/test_sign.py (sign not implemented); GREEN: 40 passed. Render-based pixel checks (pdfplumber/pypdfium2) cover default, manual, rotated (/Rotate 90) and offset-mediabox pages. Commit: feat(sign).
- T4 done. README with JSON contract, exit codes, licenses (verified from package metadata), limitations. Commit: docs.
- Placement fix (coordinator decision): stamp straddles the line, clamped below the label (min 24pt). RED: test_stamp_straddles_line_without_covering_label failed; GREEN: 42 passed after updating placement-dependent expectations. Commit: fix(sign) place stamp across the line.
- Free-space placement (replaces 25%/24pt rule): band around line bounded by nearest text above/below, cap 60pt, `--width` clamped (`clamped` flag). RED: 5 new tests failed (growth, stops before text below, clamped keys); GREEN: 50 passed. Commit: fix(sign) grow stamp into free space around the line.

## Next step
Done locally; awaiting user decisions (see report).

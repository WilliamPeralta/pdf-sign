# pdf-sign

Small, agent-friendly CLI that finds where a PDF should be signed and stamps a PNG signature image there.

> Visual signature only. This is an image on the page, **not** a cryptographic or qualified digital signature (PAdES/CAdES).

## Install

```sh
uv sync
uv run pdf-sign --help
```

Python >= 3.11. Dependencies (all permissive; AGPL libraries such as PyMuPDF are deliberately avoided; licenses checked from installed package metadata):

| Package | License | Use |
|---|---|---|
| pdfplumber 0.11 | MIT | text, lines, coordinates |
| pdfminer.six, charset-normalizer | MIT | pdfplumber deps |
| pypdfium2 | BSD-3 / Apache-2.0 | pdfplumber dep, page rendering in tests |
| pypdf 6 | BSD-3 | AcroForm fields, page merging |
| reportlab 5 | BSD | image overlay, test fixtures |
| Pillow 12 | MIT-CMU | PNG handling |

## Contract (for agents)

- No prompts, ever. **stdout is JSON only**; library warnings are silenced.
- Errors: JSON on stderr, `{"error": {"code": "...", "message": "..."}}`.
- Exit codes: `0` ok, `1` usage / IO error, `2` no candidate found, `3` invalid PDF or image.
- Coordinates are PDF points in **user space** (bottom-left origin, same frame as AcroForm `/Rect`), including pages with `/Rotate` and non-zero MediaBox origin. On rotated pages the box is the axis-aligned user-space rectangle; the signature is stamped upright as displayed.

### `pdf-sign detect <pdf> [--all] [--match RE] [--exclude RE]`

```json
{"file": "in.pdf", "pages": 2, "candidates": [
  {"page": 2, "bbox": [59.7, 693.06, 480.1, 733.06], "source": "line",
   "label": "Firma del dipendente", "score": 0.9, "role": "signer"}
]}
```

- Sorted by `score` desc. Without `--all`, candidates below 0.5 are hidden; with no candidates the JSON has `"candidates": []` and the exit code is `2`.
- `source`: `acroform` (empty `/FT /Sig` field, score 1.0), `line` (anchor + underscore run or drawn line, 0.9; 0.8 when the line is above the label; 0.6 when the anchor sits in long prose), `anchor` (anchor text only, box placed right of it or below, 0.6 / 0.4), `line` with empty label (bare underscore line, 0.2, only with `--all`).
- `label`: the full anchor text line (underscores removed). `role`: hint from the label, `employer` (datore, legale rappresentante, timbro), `signer` (dipendente, accettazione, dichiarante, lavoratore) or `unknown`. It is only a hint: pass `--match`/`--exclude` to pick the right signer.
- Anchors (IT/EN, case-insensitive, whole words only, so `firmatario`, `infirmare`, `designed` do not match): firma, firmato, signature, sign here, signed, il dichiarante, letto, confermato e sottoscritto, in fede, timbro e firma, firma del cliente, firma leggibile.
- Line placement: underscore run (3+) or drawn horizontal line on the same line to the right of the anchor, just below it, or just above it. Underscore blanks inside prose (`Targa: ____`, `il dipendente ____ dichiara`) are never candidates.
- `bbox` is the free vertical band around the line within the line's x-range: its top is 2 pt under the nearest text above the line, its bottom is 2 pt over the nearest text below (within 80 pt; otherwise 40 pt below the line), never lower than 45 pt below the line or the page edge, and at most 60 pt tall. `sign` fits the PNG (aspect kept) as large as possible in that band and the line length, left-aligned to the line start, crossing the line, and never intersecting text.

### `pdf-sign sign <pdf> --signature <png> [options]`

| Option | Meaning |
|---|---|
| `-o, --output` | output path; default `<name>.signed.pdf` next to the input |
| `--force` | allow overwriting an existing output (the input is never overwritten) |
| `--candidate N` | 1-based index into the filtered `detect` list (default 1) |
| `--match RE` / `--exclude RE` | filter candidates by label (case-insensitive regex) |
| `--all` | stamp the best spot on every page that has one |
| `--page P --x X --y Y` | manual placement (bottom-left of the image, user space); all three required; no detection |
| `--width W` | image width in points, aspect ratio kept (manual default 150). For detected line spots it is shrunk when text is in the way and the placement reports `"clamped": true`; manual coordinates are taken literally |

Without `--width` the image is fitted inside the candidate box keeping the PNG aspect ratio. Output:

```json
{"input": "in.pdf", "output": "in.signed.pdf", "signature": "sig.png",
 "placements": [{"page": 2, "stamp": [59.7, 693.06, 159.7, 733.06],
                 "source": "line", "label": "Firma del dipendente", "score": 0.9, "clamped": false}]}
```

### Agent recipe

```sh
pdf-sign detect doc.pdf                                  # inspect labels / roles
pdf-sign sign doc.pdf --signature sig.png --all --match 'accettazione|dipendente'
# fallback when detect exits 2:
pdf-sign sign doc.pdf --signature sig.png --page 1 --x 100 --y 120 --width 140
```

## Limitations

- Scanned / image-only PDFs have no text layer: no anchors, `detect` exits 2. OCR is future work (use manual coordinates meanwhile).
- Sideways text on a rotated page whose content is not upright when displayed is not analysed.
- Obstacles are text chars only; table borders or images near the line are not avoided.
- `--all` signs one spot per page, even when a page has several signers; narrow with `--match`.

## Development

```sh
uv run pytest -q
```

Tests generate all PDFs with reportlab (and a `/Sig` field with pypdf) in `tmp_path`; signature placement is verified by rendering pages and locating the ink.

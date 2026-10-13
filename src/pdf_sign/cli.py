"""Command line interface. stdout is JSON only; errors are JSON on stderr."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings

from . import __version__
from .detect import detect_candidates, filter_candidates
from .sign import sign_pdf
from .errors import EXIT_NO_CANDIDATE, EXIT_OK, EXIT_USAGE, PdfSignError


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # type: ignore[override]
        raise PdfSignError("usage", message, EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="pdf-sign",
        description="Detect signature spots in a PDF and stamp a PNG signature there. "
        "Output is JSON on stdout; errors are JSON on stderr. "
        "Exit codes: 0 ok, 1 usage/IO, 2 no candidate, 3 invalid PDF/image.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    d = sub.add_parser("detect", help="List ranked signature candidates as JSON.")
    d.add_argument("pdf")
    d.add_argument("--all", action="store_true", help="Include low-score candidates.")
    d.add_argument("--match", help="Keep candidates whose label matches this regex (case-insens.).")
    d.add_argument("--exclude", help="Drop candidates whose label matches this regex.")

    s = sub.add_parser("sign", help="Stamp a PNG signature onto a PDF.")
    s.add_argument("pdf")
    s.add_argument("--signature", required=True, help="PNG image (alpha supported).")
    s.add_argument("-o", "--output", help="Output PDF (default: <name>.signed.pdf).")
    s.add_argument("--force", action="store_true", help="Overwrite an existing output file.")
    s.add_argument("--candidate", type=int, help="1-based index in the detect list (default 1).")
    s.add_argument("--all", action="store_true", help="Sign the best spot on every page.")
    s.add_argument("--match", help="Only consider candidates whose label matches this regex.")
    s.add_argument("--exclude", help="Ignore candidates whose label matches this regex.")
    s.add_argument("--page", type=int, help="Manual placement: 1-based page.")
    s.add_argument("--x", type=float, help="Manual placement: left edge, PDF points (user space).")
    s.add_argument("--y", type=float, help="Manual placement: bottom edge, PDF points (user space).")
    s.add_argument("--width", type=float, help="Signature width in points (aspect ratio kept).")
    return parser


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _run(args: argparse.Namespace) -> int:
    if args.command == "detect":
        pages, cands = detect_candidates(args.pdf, include_low=args.all)
        cands = filter_candidates(cands, args.match, args.exclude)
        _emit({"file": args.pdf, "pages": pages, "candidates": [c.to_dict() for c in cands]})
        return EXIT_OK if cands else EXIT_NO_CANDIDATE
    if args.command == "sign":
        _emit(
            sign_pdf(
                args.pdf, args.signature, args.output, candidate=args.candidate, page=args.page,
                x=args.x, y=args.y, width=args.width, all_pages=args.all, match=args.match,
                exclude=args.exclude, force=args.force,
            )
        )
        return EXIT_OK
    raise PdfSignError("usage", f"Unknown command {args.command}", EXIT_USAGE)


def _quiet_libraries() -> None:
    # Library chatter (e.g. pypdf "Ignoring wrong pointing object") must never reach stdout.
    for name in ("pypdf", "pdfminer", "pdfplumber"):
        logging.getLogger(name).setLevel(logging.ERROR)
    warnings.simplefilter("ignore")


def main(argv: list[str] | None = None) -> int:
    _quiet_libraries()
    try:
        return _run(build_parser().parse_args(argv))
    except PdfSignError as exc:
        sys.stderr.write(
            json.dumps({"error": {"code": exc.code, "message": exc.message}}) + "\n"
        )
        return exc.exit_code

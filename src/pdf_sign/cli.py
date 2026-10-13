"""Command line interface. stdout is JSON only; errors are JSON on stderr."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .detect import detect_candidates
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

    s = sub.add_parser("sign", help="Stamp a PNG signature onto a PDF.")
    s.add_argument("pdf")
    s.add_argument("--signature", required=True, help="PNG image (alpha supported).")
    s.add_argument("-o", "--output", help="Output PDF (default: <name>.signed.pdf).")
    return parser


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _run(args: argparse.Namespace) -> int:
    if args.command == "detect":
        pages, cands = detect_candidates(args.pdf)
        _emit({"file": args.pdf, "pages": pages, "candidates": [c.to_dict() for c in cands]})
        return EXIT_OK if cands else EXIT_NO_CANDIDATE
    if args.command == "sign":
        raise PdfSignError("not_implemented", "sign is not implemented yet", EXIT_USAGE)
    raise PdfSignError("usage", f"Unknown command {args.command}", EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(build_parser().parse_args(argv))
    except PdfSignError as exc:
        sys.stderr.write(
            json.dumps({"error": {"code": exc.code, "message": exc.message}}) + "\n"
        )
        return exc.exit_code

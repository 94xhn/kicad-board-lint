"""Command-line interface for kicad-board-lint."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from . import __version__
from .checks import (
    build_expectations,
    check_duplicate_pad_nets,
    check_ghost_pads,
    check_power_width,
)
from .core import load_board

EXIT_CLEAN = 0
EXIT_VIOLATIONS = 1
EXIT_USAGE = 2

ALL_CHECKS = ("ghost-pads", "power-width")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kicad-board-lint",
        description=(
            "Find board problems KiCad's DRC silently accepts: copper pads "
            "with no net, duplicate pads that disagree about their net, and "
            "power tracks too thin for their current."
        ),
    )
    parser.add_argument(
        "boards", nargs="+", metavar="BOARD.kicad_pcb", help="board file(s) to check"
    )
    parser.add_argument(
        "--check",
        default=",".join(ALL_CHECKS),
        metavar="LIST",
        help=f"comma-separated checks to run (default: {','.join(ALL_CHECKS)})",
    )
    parser.add_argument(
        "--pro",
        metavar="PROJECT.kicad_pro",
        help=(
            "project file for net-class track widths "
            "(default: <board>.kicad_pro when present; single board only)"
        ),
    )
    parser.add_argument(
        "--rule",
        action="append",
        default=[],
        metavar="PATTERN=MM",
        help="expected min width for matching nets (fnmatch), e.g. --rule 'VBAT=0.8'",
    )
    parser.add_argument(
        "--current",
        action="append",
        default=[],
        metavar="PATTERN=AMPS",
        help="expected current for matching nets; min width via IPC-2221",
    )
    parser.add_argument(
        "--delta-t", type=float, default=10.0, metavar="C",
        help="allowed temperature rise for IPC-2221 (default: 10)",
    )
    parser.add_argument(
        "--copper-oz", type=float, default=1.0, metavar="OZ",
        help="outer copper weight for IPC-2221 (default: 1.0)",
    )
    parser.add_argument(
        "--min-segment", type=float, default=0.0, metavar="MM",
        help=(
            "exempt segments shorter than this from the width check "
            "(pad-escape stubs; try 2.0). Default: 0 = check everything"
        ),
    )
    parser.add_argument(
        "--ignore-ref",
        action="append",
        default=[],
        metavar="PATTERN",
        help="reference pattern to skip (fnmatch, repeatable), e.g. --ignore-ref 'LOGO*'",
    )
    parser.add_argument(
        "--ignore-pad",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "pad number pattern to skip in pad checks (fnmatch, repeatable), "
            "e.g. --ignore-pad MP for connector mounting pins"
        ),
    )
    parser.add_argument("--format", choices=("text", "json"), default="text", dest="fmt")
    parser.add_argument(
        "--strict", action="store_true", help="treat warnings as errors"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def _load_pro(board_path: Path, args: argparse.Namespace) -> dict | None:
    pro_path = Path(args.pro) if args.pro else board_path.with_suffix(".kicad_pro")
    if not pro_path.is_file():
        if args.pro:
            raise OSError(f"project file not found: {pro_path}")
        return None
    return json.loads(pro_path.read_text(encoding="utf-8"))


def _check_file(path: Path, checks: tuple[str, ...], args: argparse.Namespace) -> dict:
    board = load_board(path.read_text(encoding="utf-8"))
    ignore = tuple(args.ignore_ref)
    findings = []

    if "ghost-pads" in checks:
        ignore_pads = tuple(args.ignore_pad)
        findings += check_ghost_pads(
            board, ignore_refs=ignore, ignore_pads=ignore_pads
        )
        findings += check_duplicate_pad_nets(
            board, ignore_refs=ignore, ignore_pads=ignore_pads
        )

    if "power-width" in checks:
        pro_data = _load_pro(path, args)
        expectations, source_findings = build_expectations(
            board.net_set(),
            pro_data=pro_data,
            rules=args.rule,
            currents=args.current,
            delta_t_c=args.delta_t,
            copper_oz=args.copper_oz,
        )
        findings += source_findings
        findings += check_power_width(
            board, expectations, min_segment_mm=args.min_segment
        )

    if args.strict:
        findings = [
            dataclasses.replace(f, severity="error")
            if f.severity == "warning"
            else f
            for f in findings
        ]
    findings.sort(key=lambda f: (f.severity != "error", f.rule, f.message))
    return {
        "path": str(path),
        "footprints": len(board.footprints),
        "segments": len(board.segments),
        "errors": sum(1 for f in findings if f.severity == "error"),
        "warnings": sum(1 for f in findings if f.severity == "warning"),
        "findings": findings,
    }


def _render_text(result: dict) -> str:
    lines = [
        f"{result['path']}: {result['footprints']} footprints, "
        f"{result['segments']} segments - {result['errors']} error(s), "
        f"{result['warnings']} warning(s)"
    ]
    for f in result["findings"]:
        location = (
            f"  at ({f.x_mm:.3f}, {f.y_mm:.3f}) mm"
            if f.x_mm is not None
            else ""
        )
        lines.append(f"  {f.severity.upper():7s} {f.rule:15s} {f.message}{location}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    checks = tuple(c.strip() for c in args.check.split(",") if c.strip())
    unknown = [c for c in checks if c not in ALL_CHECKS]
    if unknown:
        print(
            f"error: unknown check(s): {', '.join(unknown)} "
            f"(available: {', '.join(ALL_CHECKS)})",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if args.pro and len(args.boards) > 1:
        print("error: --pro is only valid with a single board", file=sys.stderr)
        return EXIT_USAGE

    results = []
    file_errors = 0
    for raw in args.boards:
        path = Path(raw)
        try:
            results.append(_check_file(path, checks, args))
        except OSError as exc:
            print(f"error: cannot read {path}: {exc}", file=sys.stderr)
            file_errors += 1
        except ValueError as exc:
            print(f"error: {path}: {exc}", file=sys.stderr)
            file_errors += 1

    total_errors = sum(r["errors"] for r in results)
    total_warnings = sum(r["warnings"] for r in results)

    if args.fmt == "json":
        payload = {
            "version": __version__,
            "files": [
                {**r, "findings": [f.to_dict() for f in r["findings"]]}
                for r in results
            ],
            "total_errors": total_errors,
            "total_warnings": total_warnings,
        }
        print(json.dumps(payload, indent=2))
    else:
        for result in results:
            print(_render_text(result))
        verdict = "FAIL" if total_errors else "PASS"
        print(
            f"{verdict}: {total_errors} error(s), {total_warnings} warning(s) "
            f"across {len(results)} file(s)"
        )
    if file_errors:
        return EXIT_USAGE  # an unreadable/unparseable file outranks lint results
    return EXIT_VIOLATIONS if total_errors else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())

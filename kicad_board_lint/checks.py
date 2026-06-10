"""Lint rules: ghost pads, duplicate-pad net mismatches, power track width.

These target the class of problems KiCad's own ERC/DRC silently accepts:

* a copper pad with **no net** passes DRC — KiCad treats it as standalone
  copper that neither needs a connection nor counts as a short. Stale
  netlists, wrong-symbol/footprint pairings and script bugs all end here.
* a **too-thin power track** passes DRC — clearance is checked, current
  capacity is not.
"""

from __future__ import annotations

import difflib
import fnmatch
from dataclasses import dataclass

from .core import Board

IPC_K_OUTER = 0.048
IPC_K_INNER = 0.024
MIL_PER_OZ = 1.378  # copper thickness in mil per oz/ft^2
MM_PER_MIL = 0.0254


@dataclass(frozen=True)
class Finding:
    rule: str  # "ghost-pad" | "dup-pad-net" | "power-width" | "netclass-orphan"
    severity: str  # "error" | "warning"
    message: str
    ref: str | None = None
    net: str | None = None
    x_mm: float | None = None
    y_mm: float | None = None

    def to_dict(self) -> dict:
        out = {"rule": self.rule, "severity": self.severity, "message": self.message}
        for key in ("ref", "net", "x_mm", "y_mm"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


def _ignored(ref: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(ref, pat) for pat in patterns)


# --------------------------------------------------------------- ghost pads


def check_ghost_pads(
    board: Board, *, ignore_refs: tuple[str, ...] = ()
) -> list[Finding]:
    """Copper pads with no net assigned.

    DRC never flags these. Causes seen in the wild: a stale netlist (pads
    silently skipped during sync), a symbol with fewer pins than the footprint
    has pads (the extra pads float), or scripts losing nets on save.

    Skipped: NPTH pads, unnumbered mechanical pads, and footprints marked
    ``board_only`` (mounting holes, logos — they legitimately carry no net).
    """
    findings: list[Finding] = []
    for fp in board.footprints:
        if "board_only" in fp.attrs or _ignored(fp.ref, ignore_refs):
            continue
        for pad in fp.pads:
            if pad.pad_type == "np_thru_hole" or not pad.number:
                continue
            if not pad.net:  # None (no net entry) or "" (explicit net 0)
                findings.append(
                    Finding(
                        rule="ghost-pad",
                        severity="error",
                        message=(
                            f"{fp.ref or fp.lib_id} pad {pad.number} has no net "
                            "(DRC will not flag this)"
                        ),
                        ref=fp.ref,
                        x_mm=pad.x_mm,
                        y_mm=pad.y_mm,
                    )
                )
    return findings


def check_duplicate_pad_nets(
    board: Board, *, ignore_refs: tuple[str, ...] = ()
) -> list[Finding]:
    """Same-numbered pads within one footprint that disagree about their net.

    Tactile switches, SOT-223 tabs, thermal pads and multi-pad terminals all
    repeat pad numbers. Some toolpaths assign the net to only one of them —
    the rest export as <no net> and autorouters treat contact as a short.
    """
    findings: list[Finding] = []
    for fp in board.footprints:
        if _ignored(fp.ref, ignore_refs):
            continue
        groups: dict[str, set[str | None]] = {}
        for pad in fp.pads:
            if pad.pad_type == "np_thru_hole" or not pad.number:
                continue
            groups.setdefault(pad.number, set()).add(pad.net or None)
        for number, nets in groups.items():
            if len(nets) > 1:
                shown = " vs ".join(
                    f'"{n}"' if n else "<none>" for n in sorted(nets, key=str)
                )
                findings.append(
                    Finding(
                        rule="dup-pad-net",
                        severity="error",
                        message=(
                            f"{fp.ref or fp.lib_id}: duplicate pads \"{number}\" "
                            f"disagree about their net: {shown}"
                        ),
                        ref=fp.ref,
                    )
                )
    return findings


# -------------------------------------------------------------- power width


def ipc2221_min_width_mm(
    amps: float,
    *,
    delta_t_c: float = 10.0,
    copper_oz: float = 1.0,
    internal: bool = False,
) -> float:
    """Minimum track width per IPC-2221 (I = k * dT^0.44 * A^0.725)."""
    k = IPC_K_INNER if internal else IPC_K_OUTER
    area_mil2 = (amps / (k * delta_t_c**0.44)) ** (1 / 0.725)
    width_mil = area_mil2 / (MIL_PER_OZ * copper_oz)
    return width_mil * MM_PER_MIL


def _suggest(name: str, board_nets: set[str]) -> str | None:
    if name.startswith("/") and name[1:] in board_nets:
        return name[1:]
    if "/" + name in board_nets:
        return "/" + name
    close = difflib.get_close_matches(name, sorted(board_nets), n=1, cutoff=0.6)
    return close[0] if close else None


def _parse_assignments(args: list[str], what: str) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []
    for raw in args:
        pattern, sep, value = raw.partition("=")
        if not sep or not pattern:
            raise ValueError(f"invalid {what} '{raw}', expected PATTERN=VALUE")
        pairs.append((pattern, float(value)))
    return pairs


def build_expectations(
    board_nets: set[str],
    *,
    pro_data: dict | None = None,
    rules: list[str] | None = None,
    currents: list[str] | None = None,
    delta_t_c: float = 10.0,
    copper_oz: float = 1.0,
) -> tuple[dict[str, tuple[float, str]], list[Finding]]:
    """Resolve each net's expected minimum track width.

    Sources in increasing precedence: ``.kicad_pro`` net classes, ``--rule``
    patterns, ``--current`` patterns (converted via IPC-2221).
    Also reports net-class entries that match nothing on the board — a net
    class silently falls back to Default when the name is wrong (the classic
    ``+5V`` vs ``/+5V`` prefix trap), and nothing in KiCad tells you.
    """
    expectations: dict[str, tuple[float, str]] = {}
    findings: list[Finding] = []

    net_settings = (pro_data or {}).get("net_settings", {})
    for cls in net_settings.get("classes", []):
        name = cls.get("name", "")
        width = cls.get("track_width")
        if name == "Default" or width is None:
            continue
        for net in cls.get("nets") or []:
            if net in board_nets:
                expectations[net] = (float(width), f"netclass {name}")
            else:
                hint = _suggest(net, board_nets)
                suffix = f' — did you mean "{hint}"?' if hint else ""
                findings.append(
                    Finding(
                        rule="netclass-orphan",
                        severity="warning",
                        message=(
                            f'netclass "{name}" assigns net "{net}" but the '
                            f"board has no such net (it silently falls back "
                            f"to Default){suffix}"
                        ),
                        net=net,
                    )
                )
    for entry in net_settings.get("netclass_patterns") or []:
        pattern = entry.get("pattern", "")
        cls_name = entry.get("netclass", "")
        width = next(
            (
                c.get("track_width")
                for c in net_settings.get("classes", [])
                if c.get("name") == cls_name
            ),
            None,
        )
        if not pattern or cls_name == "Default" or width is None:
            continue
        for net in board_nets:
            if fnmatch.fnmatchcase(net, pattern):
                expectations[net] = (float(width), f"netclass {cls_name}")

    for pattern, width in _parse_assignments(list(rules or []), "--rule"):
        for net in board_nets:
            if fnmatch.fnmatchcase(net, pattern):
                expectations[net] = (width, f"rule {pattern}")

    for pattern, amps in _parse_assignments(list(currents or []), "--current"):
        width = round(
            ipc2221_min_width_mm(amps, delta_t_c=delta_t_c, copper_oz=copper_oz), 3
        )
        for net in board_nets:
            if fnmatch.fnmatchcase(net, pattern):
                expectations[net] = (width, f"IPC-2221 {amps}A @ {delta_t_c}degC")

    return expectations, findings


def check_power_width(
    board: Board,
    expectations: dict[str, tuple[float, str]],
    *,
    tolerance_mm: float = 0.001,
    min_segment_mm: float = 0.0,
) -> list[Finding]:
    """Tracks narrower than their net's expected width. One finding per net.

    ``min_segment_mm`` exempts segments shorter than the given length —
    pad-escape stubs out of fine-pitch ICs are necessarily narrower than the
    net's bulk width and a short neck is acceptable practice; 2.0 is a
    reasonable value when escapes dominate the report.
    """
    by_net: dict[str, list] = {}
    for seg in board.segments:
        if seg.net in expectations:
            by_net.setdefault(seg.net, []).append(seg)

    findings: list[Finding] = []
    for net in sorted(by_net):
        expected, source = expectations[net]
        segments = by_net[net]
        thin = [
            s
            for s in segments
            if s.width_mm < expected - tolerance_mm
            and s.length_mm >= min_segment_mm
        ]
        if not thin:
            continue
        worst = min(thin, key=lambda s: s.width_mm)
        findings.append(
            Finding(
                rule="power-width",
                severity="error",
                message=(
                    f'net "{net}": {len(thin)} of {len(segments)} segment(s) '
                    f"narrower than {expected}mm (worst {worst.width_mm}mm at "
                    f"({worst.x_mm}, {worst.y_mm}) mm; {source}; "
                    "DRC does not check current capacity)"
                ),
                net=net,
                x_mm=worst.x_mm,
                y_mm=worst.y_mm,
            )
        )
    return findings

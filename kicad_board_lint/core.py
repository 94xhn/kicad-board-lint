"""Board model for kicad-board-lint.

Zero-dependency: parses ``.kicad_pcb`` s-expression text directly, no pcbnew
bindings or KiCad installation required. Supports KiCad 5 through 10,
including the KiCad 10 format change where pads and segments store the net
*name* directly instead of a numeric id resolved through the board net table.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .sexp import QuotedStr, parse


@dataclass(frozen=True)
class Pad:
    number: str
    pad_type: str  # "smd" | "thru_hole" | "np_thru_hole" | "connect"
    net: str | None  # net name; None = no net entry; "" = explicit net 0
    x_mm: float  # absolute board coordinates
    y_mm: float


@dataclass(frozen=True)
class Footprint:
    ref: str
    lib_id: str
    layer: str
    x_mm: float
    y_mm: float
    rot_deg: float
    attrs: tuple[str, ...]  # e.g. ("board_only", "exclude_from_bom")
    pads: tuple[Pad, ...]


@dataclass(frozen=True)
class Segment:
    net: str
    layer: str
    width_mm: float
    length_mm: float
    x_mm: float  # segment start, for locating reports
    y_mm: float


@dataclass
class Board:
    footprints: list[Footprint] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    net_names: dict[int, str] = field(default_factory=dict)

    def net_set(self) -> set[str]:
        nets: set[str] = set(self.net_names.values())
        nets.update(s.net for s in self.segments)
        nets.update(p.net for f in self.footprints for p in f.pads if p.net)
        nets.discard("")
        return nets


def _net_name(tokens: list, net_names: dict[int, str]) -> str:
    """Normalize a ``(net ...)`` payload to a net name across formats.

    KiCad <= 9: ``(net 42 "GND")`` or ``(net 42)``; KiCad 10: ``(net "GND")``.
    """
    if len(tokens) >= 2:
        return str(tokens[1])
    token = tokens[0]
    if isinstance(token, QuotedStr):
        return str(token)
    try:
        net_id = int(token)
    except ValueError:
        return str(token)
    return net_names.get(net_id, f"#{net_id}")


def _rotated(lx: float, ly: float, rot_deg: float) -> tuple[float, float]:
    """Footprint-local pad offset -> board delta (screen Y-down convention)."""
    rad = math.radians(rot_deg)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    return (lx * cos_r + ly * sin_r, -lx * sin_r + ly * cos_r)


def _parse_pad(node: list, fp_x: float, fp_y: float, fp_rot: float,
               net_names: dict[int, str]) -> Pad | None:
    if len(node) < 3:
        return None
    number = str(node[1])
    pad_type = str(node[2])
    lx = ly = 0.0
    net: str | None = None
    for item in node[3:]:
        if not isinstance(item, list) or not item:
            continue
        if item[0] == "at" and len(item) >= 3:
            lx, ly = float(item[1]), float(item[2])
        elif item[0] == "net" and len(item) >= 2:
            net = _net_name(item[1:], net_names)
    dx, dy = _rotated(lx, ly, fp_rot)
    return Pad(
        number=number,
        pad_type=pad_type,
        net=net,
        x_mm=round(fp_x + dx, 4),
        y_mm=round(fp_y + dy, 4),
    )


def _parse_footprint(node: list, net_names: dict[int, str]) -> Footprint:
    lib_id = str(node[1]) if len(node) >= 2 and isinstance(node[1], str) else ""
    ref = ""
    layer = ""
    x = y = rot = 0.0
    attrs: tuple[str, ...] = ()
    pad_nodes: list[list] = []
    for item in node[2:]:
        if not isinstance(item, list) or not item:
            continue
        head = item[0]
        if head == "at" and len(item) >= 3:
            x, y = float(item[1]), float(item[2])
            rot = float(item[3]) if len(item) >= 4 else 0.0
        elif head == "layer" and len(item) >= 2:
            layer = str(item[1])
        elif head == "attr":
            attrs = tuple(str(t) for t in item[1:] if isinstance(t, str))
        elif head == "property" and len(item) >= 3 and item[1] == "Reference":
            ref = str(item[2])
        elif head == "fp_text" and len(item) >= 3 and item[1] == "reference":
            ref = ref or str(item[2])  # KiCad 5/6 reference text
        elif head == "pad":
            pad_nodes.append(item)
    pads = tuple(
        p for p in (_parse_pad(n, x, y, rot, net_names) for n in pad_nodes)
        if p is not None
    )
    return Footprint(
        ref=ref, lib_id=lib_id, layer=layer,
        x_mm=x, y_mm=y, rot_deg=rot, attrs=attrs, pads=pads,
    )


def _parse_segment(node: list, net_names: dict[int, str]) -> Segment | None:
    start = end = width = layer = net_tokens = None
    for item in node[1:]:
        if not isinstance(item, list) or not item:
            continue
        head = item[0]
        if head == "start" and len(item) >= 3:
            start = (float(item[1]), float(item[2]))
        elif head == "end" and len(item) >= 3:
            end = (float(item[1]), float(item[2]))
        elif head == "width" and len(item) >= 2:
            width = float(item[1])
        elif head == "layer" and len(item) >= 2:
            layer = str(item[1])
        elif head == "net" and len(item) >= 2:
            net_tokens = item[1:]
    if start is None or width is None or layer is None or net_tokens is None:
        return None
    length = math.hypot(end[0] - start[0], end[1] - start[1]) if end else 0.0
    return Segment(
        net=_net_name(net_tokens, net_names),
        layer=layer,
        width_mm=width,
        length_mm=round(length, 4),
        x_mm=start[0],
        y_mm=start[1],
    )


def load_board(text: str) -> Board:
    """Extract footprints, pads and track segments from ``.kicad_pcb`` text."""
    forms = parse(text)
    root = next(
        (f for f in forms if isinstance(f, list) and f and f[0] == "kicad_pcb"),
        None,
    )
    if root is None:
        raise ValueError("not a KiCad board file: no (kicad_pcb ...) form found")

    board = Board()
    children = [n for n in root if isinstance(n, list) and n]

    # Net table first — present in KiCad <= 9, absent in KiCad 10.
    for node in children:
        if node[0] == "net" and len(node) >= 2:
            try:
                net_id = int(node[1])
            except (TypeError, ValueError):
                continue
            name = node[2] if len(node) >= 3 and isinstance(node[2], str) else ""
            board.net_names[net_id] = name

    for node in children:
        head = node[0]
        if head in ("footprint", "module"):  # "module" is the KiCad 5 spelling
            board.footprints.append(_parse_footprint(node, board.net_names))
        elif head == "segment":
            seg = _parse_segment(node, board.net_names)
            if seg is not None:
                board.segments.append(seg)
    return board

"""kicad-board-lint: find board problems KiCad's DRC silently accepts."""

from .checks import (
    Finding,
    build_expectations,
    check_duplicate_pad_nets,
    check_ghost_pads,
    check_power_width,
    ipc2221_min_width_mm,
)
from .core import Board, Footprint, Pad, Segment, load_board

__version__ = "0.1.0"

__all__ = [
    "Board",
    "Finding",
    "Footprint",
    "Pad",
    "Segment",
    "build_expectations",
    "check_duplicate_pad_nets",
    "check_ghost_pads",
    "check_power_width",
    "ipc2221_min_width_mm",
    "load_board",
    "__version__",
]

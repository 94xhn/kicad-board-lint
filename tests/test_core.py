import pytest

from kicad_board_lint.core import load_board


def wrap(*body: str) -> str:
    return (
        '(kicad_pcb (version 20241229) (generator "test")\n'
        + "\n".join(body)
        + "\n)"
    )


SIMPLE_FP = """
  (footprint "Lib:R_0603"
    (layer "F.Cu")
    (at 39 35 90)
    (property "Reference" "C1" (at 0 0 0))
    (attr smd)
    (pad "1" smd roundrect (at -0.775 0) (size 0.8 0.9) (layers "F.Cu") (net "+3V3"))
    (pad "2" smd roundrect (at 0.775 0) (size 0.8 0.9) (layers "F.Cu") (net "GND"))
  )
"""


def test_footprint_parsed():
    board = load_board(wrap(SIMPLE_FP))
    (fp,) = board.footprints
    assert fp.ref == "C1"
    assert fp.lib_id == "Lib:R_0603"
    assert fp.layer == "F.Cu"
    assert fp.rot_deg == 90
    assert fp.attrs == ("smd",)
    assert [p.net for p in fp.pads] == ["+3V3", "GND"]


def test_pad_absolute_position_with_rotation():
    # kicadrule #23 worked example: C_0603 at (39,35) rot=90,
    # pad1 local (-0.775, 0) lands at (39, 35.775).
    board = load_board(wrap(SIMPLE_FP))
    pad1, pad2 = board.footprints[0].pads
    assert (pad1.x_mm, pad1.y_mm) == (39.0, 35.775)
    assert (pad2.x_mm, pad2.y_mm) == (39.0, 34.225)


def test_kicad5_module_and_fp_text_reference():
    text = wrap(
        "  (net 0 \"\")",
        "  (net 1 GND)",
        '  (module Lib:SW (layer F.Cu) (at 10 10)',
        "    (fp_text reference SW9 (at 0 0))",
        '    (pad 1 thru_hole circle (at 0 0) (size 1.7 1.7) (drill 1) (net 1 GND))',
        "  )",
    )
    board = load_board(text)
    (fp,) = board.footprints
    assert fp.ref == "SW9"
    assert fp.pads[0].net == "GND"


def test_pad_net_id_only_resolved_via_net_table():
    text = wrap(
        '  (net 7 "SDA")',
        '  (footprint "L:X" (layer "F.Cu") (at 0 0)',
        '    (property "Reference" "U9" (at 0 0 0))',
        '    (pad "1" smd rect (at 0 0) (size 1 1) (net 7))',
        "  )",
    )
    assert load_board(text).footprints[0].pads[0].net == "SDA"


def test_pad_without_net_is_none_and_net0_is_empty():
    text = wrap(
        '  (net 0 "")',
        '  (footprint "L:X" (layer "F.Cu") (at 0 0)',
        '    (property "Reference" "U1" (at 0 0 0))',
        '    (pad "1" smd rect (at 0 0) (size 1 1))',
        '    (pad "2" smd rect (at 1 0) (size 1 1) (net 0 ""))',
        "  )",
    )
    pads = load_board(text).footprints[0].pads
    assert pads[0].net is None
    assert pads[1].net == ""


def test_segments_parsed_with_width_and_length():
    text = wrap(
        '  (segment (start 1 2) (end 4 6) (width 0.25) (layer "F.Cu") (net "VBAT"))'
    )
    (seg,) = load_board(text).segments
    assert seg.net == "VBAT"
    assert seg.width_mm == 0.25
    assert seg.length_mm == 5.0  # 3-4-5 triangle
    assert (seg.x_mm, seg.y_mm) == (1.0, 2.0)


def test_net_set_collects_all_sources():
    text = wrap(
        '  (net 1 "OLD_TABLE_NET")',
        '  (segment (start 0 0) (end 1 0) (width 0.2) (layer "F.Cu") (net "TRACK_NET"))',
        '  (footprint "L:X" (layer "F.Cu") (at 0 0)',
        '    (property "Reference" "U1" (at 0 0 0))',
        '    (pad "1" smd rect (at 0 0) (size 1 1) (net "PAD_NET"))',
        "  )",
    )
    assert load_board(text).net_set() == {"OLD_TABLE_NET", "TRACK_NET", "PAD_NET"}


def test_non_board_file_raises():
    with pytest.raises(ValueError, match="kicad_pcb"):
        load_board("(kicad_sch (version 1))")

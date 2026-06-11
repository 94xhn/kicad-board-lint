from __future__ import annotations

import pytest

from kicad_board_lint.checks import (
    build_expectations,
    check_duplicate_pad_nets,
    check_ghost_pads,
    check_power_width,
    ipc2221_min_width_mm,
)
from kicad_board_lint.core import load_board


def board_with(*body: str):
    return load_board(
        '(kicad_pcb (version 20241229) (generator "test")\n'
        + "\n".join(body)
        + "\n)"
    )


def fp(ref: str, *pads: str, attr: str = "smd") -> str:
    pad_lines = "\n".join(f"    {p}" for p in pads)
    return (
        f'  (footprint "L:{ref}" (layer "F.Cu") (at 50 50)\n'
        f'    (property "Reference" "{ref}" (at 0 0 0))\n'
        f"    (attr {attr})\n{pad_lines}\n  )"
    )


def pad(number: str, net: str | None, *, ptype: str = "smd") -> str:
    net_part = f' (net "{net}")' if net is not None else ""
    drill = " (drill 1)" if "thru" in ptype else ""
    return (
        f'(pad "{number}" {ptype} rect (at 0 0) (size 1 1){drill}'
        f' (layers "F.Cu"){net_part})'
    )


# ---------------------------------------------------------------- ghost pads


def test_connected_pads_are_clean():
    board = board_with(fp("R1", pad("1", "+5V"), pad("2", "GND")))
    assert check_ghost_pads(board) == []


def test_pad_without_net_reported():
    board = board_with(fp("U1", pad("1", "+5V"), pad("2", None)))
    (finding,) = check_ghost_pads(board)
    assert finding.rule == "ghost-pad"
    assert finding.severity == "error"
    assert "U1 pad 2" in finding.message


def test_explicit_net_zero_reported():
    board = board_with(
        '  (net 0 "")',
        fp("U1", '(pad "1" smd rect (at 0 0) (size 1 1) (net 0 ""))'),
    )
    assert len(check_ghost_pads(board)) == 1


def test_npth_and_unnumbered_pads_skipped():
    board = board_with(
        fp("H1", pad("", None), pad("1", None, ptype="np_thru_hole"))
    )
    assert check_ghost_pads(board) == []


def test_board_only_footprint_skipped():
    board = board_with(fp("MH1", pad("1", None), attr="board_only"))
    assert check_ghost_pads(board) == []


def test_ignore_refs_pattern():
    board = board_with(fp("LOGO1", pad("1", None)))
    assert check_ghost_pads(board, ignore_refs=("LOGO*",)) == []
    assert len(check_ghost_pads(board)) == 1


# ------------------------------------------------------------- dup pad nets


def test_duplicate_pads_disagreeing_reported():
    board = board_with(fp("SW1", pad("1", "COL1"), pad("1", None)))
    (finding,) = check_duplicate_pad_nets(board)
    assert finding.rule == "dup-pad-net"
    assert "COL1" in finding.message and "<none>" in finding.message


def test_duplicate_pads_with_same_net_are_clean():
    board = board_with(fp("U1", pad("2", "GND"), pad("2", "GND")))
    assert check_duplicate_pad_nets(board) == []


def test_duplicate_pads_with_two_real_nets_reported():
    board = board_with(fp("U1", pad("2", "GND"), pad("2", "+5V")))
    assert len(check_duplicate_pad_nets(board)) == 1


def test_duplicate_unconnected_nets_are_clean():
    # KiCad assigns each duplicate pad its own unconnected-(...)_N net —
    # different unconnected nets are not a conflict (official demo boards).
    board = board_with(
        fp(
            "J502",
            pad("MP", "unconnected-(J502-MountPin-PadMP)"),
            pad("MP", "unconnected-(J502-MountPin-PadMP)_1"),
        )
    )
    assert check_duplicate_pad_nets(board) == []


def test_real_net_vs_unconnected_still_reported():
    # one tab grounded, its twin left unconnected — that IS the bug class
    board = board_with(
        fp("U1", pad("2", "GND"), pad("2", "unconnected-(U1-Pad2)"))
    )
    assert len(check_duplicate_pad_nets(board)) == 1


def test_ignore_pads_pattern():
    board = board_with(fp("J601", pad("MP", None), pad("1", "GND")))
    assert check_ghost_pads(board, ignore_pads=("MP",)) == []
    assert len(check_ghost_pads(board)) == 1


# ----------------------------------------------------------------- IPC-2221


def test_ipc2221_matches_published_table():
    # kicadrule #54: 1 oz / 10 degC outer layer — 1.0mm carries ~2.5A,
    # 0.2mm carries ~0.5A.
    assert ipc2221_min_width_mm(2.5) == pytest.approx(1.06, abs=0.08)
    assert ipc2221_min_width_mm(0.5) == pytest.approx(0.115, abs=0.06)


def test_ipc2221_scales_with_copper_weight():
    one_oz = ipc2221_min_width_mm(2.0, copper_oz=1.0)
    two_oz = ipc2221_min_width_mm(2.0, copper_oz=2.0)
    assert two_oz == pytest.approx(one_oz / 2)


# ------------------------------------------------------- build_expectations


def test_expectations_from_pro_classes():
    pro = {
        "net_settings": {
            "classes": [
                {"name": "Default", "track_width": 0.2},
                {"name": "HighCurrent", "track_width": 1.5, "nets": ["+5V"]},
            ]
        }
    }
    exp, findings = build_expectations({"+5V", "GND"}, pro_data=pro)
    assert exp == {"+5V": (1.5, "netclass HighCurrent")}
    assert findings == []


def test_orphan_netclass_entry_warned_with_suggestion():
    pro = {
        "net_settings": {
            "classes": [{"name": "Power", "track_width": 0.5, "nets": ["+3V3"]}]
        }
    }
    exp, findings = build_expectations({"/+3V3", "GND"}, pro_data=pro)
    assert exp == {}
    (finding,) = findings
    assert finding.rule == "netclass-orphan"
    assert finding.severity == "warning"
    assert 'did you mean "/+3V3"' in finding.message


def test_netclass_patterns_assignment():
    pro = {
        "net_settings": {
            "classes": [{"name": "Power", "track_width": 0.8}],
            "netclass_patterns": [{"pattern": "VBUS*", "netclass": "Power"}],
        }
    }
    exp, _ = build_expectations({"VBUS", "VBUS_SENSE", "GND"}, pro_data=pro)
    assert exp["VBUS"] == (0.8, "netclass Power")
    assert exp["VBUS_SENSE"] == (0.8, "netclass Power")
    assert "GND" not in exp


def test_netclass_patterns_accept_regex():
    # KiCad patterns can be regular expressions, not just wildcards
    pro = {
        "net_settings": {
            "classes": [{"name": "Power", "track_width": 0.8}],
            "netclass_patterns": [{"pattern": "^/CP[0-9]+$", "netclass": "Power"}],
        }
    }
    exp, _ = build_expectations({"/CP1", "/CP12", "GND"}, pro_data=pro)
    assert set(exp) == {"/CP1", "/CP12"}


def test_rule_overrides_pro_and_current_overrides_rule():
    pro = {
        "net_settings": {
            "classes": [{"name": "P", "track_width": 0.5, "nets": ["VBAT"]}]
        }
    }
    exp, _ = build_expectations(
        {"VBAT"}, pro_data=pro, rules=["VBAT=0.8"], currents=["VBAT=2.5"]
    )
    width, source = exp["VBAT"]
    assert width == pytest.approx(1.06, abs=0.08)
    assert source.startswith("IPC-2221")


def test_invalid_rule_format_raises():
    with pytest.raises(ValueError, match="--rule"):
        build_expectations({"X"}, rules=["VBAT"])


# --------------------------------------------------------- check_power_width


def seg(net: str, width: float, x: float = 0.0) -> str:
    return (
        f"  (segment (start {x} 0) (end {x + 5} 0) (width {width}) "
        f'(layer "F.Cu") (net "{net}"))'
    )


def test_thin_power_track_reported_once_per_net():
    board = board_with(seg("+5V", 0.25), seg("+5V", 0.25, 10), seg("+5V", 1.5, 20))
    (finding,) = check_power_width(board, {"+5V": (1.5, "netclass HC")})
    assert finding.rule == "power-width"
    assert "2 of 3" in finding.message
    assert "0.25mm" in finding.message
    assert "netclass HC" in finding.message


def test_compliant_width_is_clean():
    board = board_with(seg("+5V", 1.5))
    assert check_power_width(board, {"+5V": (1.5, "x")}) == []


def test_exact_width_within_tolerance_is_clean():
    board = board_with(seg("+5V", 0.5))
    assert check_power_width(board, {"+5V": (0.5, "x")}) == []


def test_unrouted_net_not_reported():
    board = board_with(seg("GND", 0.2))
    assert check_power_width(board, {"+5V": (1.5, "x")}) == []


def test_min_segment_exempts_short_escape_stubs():
    # 1mm escape stub + 10mm long run, both thin.
    board = board_with(
        '  (segment (start 0 0) (end 1 0) (width 0.25) (layer "F.Cu") (net "+5V"))',
        '  (segment (start 1 0) (end 11 0) (width 0.25) (layer "F.Cu") (net "+5V"))',
    )
    expectations = {"+5V": (1.0, "x")}
    (both,) = check_power_width(board, expectations)
    assert "2 of 2" in both.message
    (long_only,) = check_power_width(board, expectations, min_segment_mm=2.0)
    assert "1 of 2" in long_only.message

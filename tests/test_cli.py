import json
from pathlib import Path

import pytest

from kicad_board_lint.cli import main

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo.kicad_pcb"

CLEAN_BOARD = (
    '(kicad_pcb (version 20241229) (generator "test")\n'
    '  (footprint "L:R" (layer "F.Cu") (at 0 0)\n'
    '    (property "Reference" "R1" (at 0 0 0))\n'
    '    (pad "1" smd rect (at 0 0) (size 1 1) (net "A"))\n'
    '    (pad "2" smd rect (at 1 0) (size 1 1) (net "B"))\n'
    "  )\n"
    '  (segment (start 0 0) (end 5 0) (width 0.5) (layer "F.Cu") (net "A"))\n'
    ")"
)


def test_demo_board_expected_findings(capsys):
    assert main([str(DEMO)]) == 1
    out = capsys.readouterr().out
    assert "ghost-pad" in out
    assert "dup-pad-net" in out
    assert "power-width" in out
    assert "netclass-orphan" in out
    assert "FAIL: 4 error(s), 1 warning(s)" in out


def test_clean_board_passes(tmp_path, capsys):
    board = tmp_path / "clean.kicad_pcb"
    board.write_text(CLEAN_BOARD, encoding="utf-8")
    assert main([str(board)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_check_filter_runs_only_selected(capsys):
    assert main([str(DEMO), "--check", "ghost-pads"]) == 1
    out = capsys.readouterr().out
    assert "ghost-pad" in out
    assert "power-width" not in out


def test_rule_flag_without_pro(tmp_path):
    board = tmp_path / "b.kicad_pcb"
    board.write_text(
        '(kicad_pcb (version 20241229)\n'
        '  (segment (start 0 0) (end 5 0) (width 0.2) (layer "F.Cu") (net "VBAT"))\n'
        ")",
        encoding="utf-8",
    )
    assert main([str(board), "--check", "power-width", "--rule", "VBAT=0.8"]) == 1
    assert main([str(board), "--check", "power-width", "--rule", "VBAT=0.2"]) == 0


def test_current_flag_uses_ipc2221(tmp_path, capsys):
    board = tmp_path / "b.kicad_pcb"
    board.write_text(
        '(kicad_pcb (version 20241229)\n'
        '  (segment (start 0 0) (end 5 0) (width 0.5) (layer "F.Cu") (net "VBAT"))\n'
        ")",
        encoding="utf-8",
    )
    assert main([str(board), "--check", "power-width", "--current", "VBAT=2.5"]) == 1
    assert "IPC-2221" in capsys.readouterr().out


def test_ignore_ref(capsys):
    code = main([str(DEMO), "--check", "ghost-pads", "--ignore-ref", "U1",
                 "--ignore-ref", "SW1"])
    assert code == 0


def test_strict_promotes_warnings(tmp_path):
    board = tmp_path / "b.kicad_pcb"
    board.write_text(
        '(kicad_pcb (version 20241229)\n'
        '  (segment (start 0 0) (end 5 0) (width 0.5) (layer "F.Cu") (net "A"))\n'
        ")",
        encoding="utf-8",
    )
    pro = tmp_path / "b.kicad_pro"
    pro.write_text(
        json.dumps(
            {"net_settings": {"classes": [
                {"name": "P", "track_width": 0.5, "nets": ["NOPE"]}
            ]}}
        ),
        encoding="utf-8",
    )
    assert main([str(board)]) == 0  # orphan is a warning
    assert main([str(board), "--strict"]) == 1


def test_json_output(capsys):
    main([str(DEMO), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_errors"] == 4
    assert payload["total_warnings"] == 1
    rules = {f["rule"] for f in payload["files"][0]["findings"]}
    assert rules == {"ghost-pad", "dup-pad-net", "power-width", "netclass-orphan"}


def test_unknown_check_exits_2(capsys):
    assert main([str(DEMO), "--check", "bogus"]) == 2
    assert "unknown check" in capsys.readouterr().err


def test_explicit_pro_with_multiple_boards_exits_2(tmp_path, capsys):
    board = tmp_path / "b.kicad_pcb"
    board.write_text(CLEAN_BOARD, encoding="utf-8")
    assert main([str(board), str(board), "--pro", "x.kicad_pro"]) == 2


def test_missing_file_exits_2(capsys):
    assert main(["nope.kicad_pcb"]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_bad_file_does_not_block_other_files(tmp_path, capsys):
    board = tmp_path / "clean.kicad_pcb"
    board.write_text(CLEAN_BOARD, encoding="utf-8")
    assert main(["nope.kicad_pcb", str(board)]) == 2
    captured = capsys.readouterr()
    assert "cannot read" in captured.err
    assert "clean.kicad_pcb" in captured.out  # the good file was still checked


def test_version_flag():
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0

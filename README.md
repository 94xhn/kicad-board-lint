# kicad-board-lint

[![CI](https://github.com/94xhn/kicad-board-lint/actions/workflows/ci.yml/badge.svg)](https://github.com/94xhn/kicad-board-lint/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](pyproject.toml)

A zero-dependency linter for the board problems **KiCad's DRC silently
accepts**: copper pads with no net, duplicate pads that disagree about their
net, and power tracks too thin for their current. No KiCad installation, no
pcbnew bindings — it parses `.kicad_pcb` / `.kicad_pro` directly, so it runs
anywhere Python runs, including CI.

[中文简介](#中文简介) below. Part of a small family of KiCad lint tools:
[kicad-corner-lint](https://github.com/94xhn/kicad-corner-lint) ·
[kicad-file-doctor](https://github.com/94xhn/kicad-file-doctor).

```text
$ kicad-board-lint examples/demo.kicad_pcb
examples/demo.kicad_pcb: 4 footprints, 4 segments - 4 error(s), 1 warning(s)
  ERROR   dup-pad-net     SW1: duplicate pads "1" disagree about their net: "COL1" vs <none>
  ERROR   ghost-pad       SW1 pad 1 has no net (DRC will not flag this)  at (122.900, 97.750) mm
  ERROR   ghost-pad       U1 pad 3 has no net (DRC will not flag this)  at (111.150, 100.000) mm
  ERROR   power-width     net "+5V": 2 of 3 segment(s) narrower than 1.5mm (worst 0.25mm at (100.0, 100.0) mm; netclass HighCurrent; DRC does not check current capacity)  at (100.000, 100.000) mm
  WARNING netclass-orphan netclass "HighCurrent" assigns net "+12V" but the board has no such net (it silently falls back to Default)
FAIL: 4 error(s), 1 warning(s) across 1 file(s)
```

## Why — three DRC blind spots

**A pad with no net passes DRC.** KiCad treats a netless copper pad as
standalone copper: it neither needs a connection nor counts as a short, so
the report stays green while the board is wrong. Real ways pads end up
netless:

- a **stale netlist** — you renamed a reference in the schematic, re-ran the
  PCB sync script without re-exporting the netlist, and every pad of that
  part silently lost its net;
- a **symbol with fewer pins than the footprint has pads** — a 2-pin crystal
  symbol on a 4-pad 3225 footprint leaves the housing-ground pads floating
  (the first real board we ran this on had exactly that);
- **duplicate pad numbers** — tactile switches, SOT-223 tabs and thermal
  pads repeat pad numbers, and some toolpaths assign the net to only one of
  the group; autorouters then treat the rest as `<no net>` obstacles and
  short against them.

`ghost-pad` and `dup-pad-net` catch all three.

**A 0.25 mm track carrying 3 A passes DRC.** DRC checks clearance, never
current capacity. `power-width` compares every segment of your power nets
against an expected width from (in increasing precedence): your `.kicad_pro`
net classes, explicit `--rule` patterns, or `--current` ratings converted
through the IPC-2221 outer-layer formula. As a bonus, `netclass-orphan`
flags net-class entries that match no net on the board — the classic
`+5V` vs `/+5V` prefix trap that makes a net class silently fall back to
Default, with a *did-you-mean* suggestion.

## Install

```bash
pip install git+https://github.com/94xhn/kicad-board-lint
```

## Usage

```bash
# run everything; netclass widths picked up from MAIN.kicad_pro automatically
kicad-board-lint MAIN.kicad_pcb

# only the pad checks
kicad-board-lint MAIN.kicad_pcb --check ghost-pads

# expected widths without a .kicad_pro: by pattern, or by current (IPC-2221)
kicad-board-lint MAIN.kicad_pcb --rule "VBAT=0.8" --current "MOTOR*=4.0"

# exempt pad-escape stubs shorter than 2 mm from the width check
kicad-board-lint MAIN.kicad_pcb --min-segment 2

# machine-readable; exit code 1 on any error
kicad-board-lint MAIN.kicad_pcb --format json
```

| Check | Severity | What it means |
|---|---|---|
| `ghost-pad` | error | copper pad with no net — DRC will never tell you |
| `dup-pad-net` | error | same-numbered pads in one footprint disagree about their net |
| `power-width` | error | segments of a power net narrower than expected (one finding per net, worst segment located) |
| `netclass-orphan` | warning | a net-class entry matches nothing on the board (silent fallback to Default) |

Exit codes: `0` clean, `1` errors found (warnings too with `--strict`),
`2` usage/file error.

### Notes on tuning

- **`--min-segment 2`** is the pragmatic switch: escape stubs out of
  fine-pitch IC pads are necessarily narrower than the net's bulk width, and
  a short neck is accepted practice. Without it you will see every escape;
  with it you see only long thin runs — the ones that actually heat up.
- Mounting holes, logos and other `board_only` footprints are skipped
  automatically; use `--ignore-ref "FID*"` for anything else.
- Some boards legitimately leave mechanically-named pads netless —
  connector mounting pins (`MP`), shields, BGA NC balls; KiCad's own demo
  boards include several. Silence them with `--ignore-pad MP` (matches the
  pad *number*). The highest-suspicion pattern remains a footprint where
  *some* pads have nets and others don't.
- IPC-2221 parameters: `--delta-t` (default 10 °C) and `--copper-oz`
  (default 1 oz). Vias and zone fills are not checked (see limitations).

### CI

```yaml
- name: Board lint
  run: |
    pip install git+https://github.com/94xhn/kicad-board-lint
    kicad-board-lint hardware/*.kicad_pcb --min-segment 2
```

### pre-commit

```yaml
repos:
  - repo: https://github.com/94xhn/kicad-board-lint
    rev: v0.1.0
    hooks:
      - id: kicad-board-lint
        args: ["--min-segment", "2"]
```

### Python API

```python
from kicad_board_lint import load_board, check_ghost_pads

board = load_board(open("MAIN.kicad_pcb", encoding="utf-8").read())
for f in check_ghost_pads(board):
    print(f.severity, f.message)
```

## Compatibility

- **KiCad 5 through 10**, including the KiCad 10 format change where pads
  and segments store the net *name* directly (older formats store a numeric
  id resolved through the board's net table — both are handled).
- Net-class expectations are read from `.kicad_pro`: `netclass_patterns`
  (the KiCad 7+ form — both wildcard and regex patterns are matched, like
  KiCad itself does) plus legacy `classes[].nets` arrays (pre-v3 schema,
  still written by some external tools; KiCad migrates them on load).
- Python ≥ 3.9, any OS, zero dependencies.

## Known limitations (v0.1)

- **Vias are not checked** for current capacity (different physics —
  planned).
- **Zone fills are not checked**; a net carried by a pour is judged only by
  its discrete segments.
- `power-width` needs an expectation source; without `.kicad_pro` classes,
  `--rule` or `--current`, it has nothing to compare against and stays
  silent.
- **Legacy boards over-report on `ghost-pads`**: on boards last saved by
  old KiCad versions (5.x era), pads the schematic legitimately leaves
  unconnected may carry no net at all — the per-pad `unconnected-(...)`
  net convention is newer. The check is calibrated for KiCad 7+ boards;
  on older ones expect noise or use `--check power-width` only.
  Measured on KiCad's own demo set: modern boards (StickHub, tiny_tapeout,
  sonde) report **zero** findings and recent boards report 1–2, while
  legacy-era boards (video, vme-wren) report dozens — that gap is the era
  difference, not parser noise.

## Related tools

- [kicad-corner-lint](https://github.com/94xhn/kicad-corner-lint) — flags
  right-angle and acute track corners (same zero-dependency family).
- [kicad-file-doctor](https://github.com/94xhn/kicad-file-doctor) — explains
  why KiCad rejects or mis-loads a file.
- [rjwalters/kicad-tools](https://github.com/rjwalters/kicad-tools) has a
  geometric `--trace-width` minimum check; this tool instead checks
  *per-net* expectations sourced from net classes or IPC-2221 current
  ratings.
- KiBot drives KiCad's own DRC — which is exactly the check that misses
  these problems.

## 中文简介

零依赖的 KiCad 板级 lint，专查 **DRC 静默放过**的三类问题：

- **幽灵焊盘**（`ghost-pad`/`dup-pad-net`）：焊盘没有网络时 KiCad 把它当
  "独立铜"，DRC 完全不报。netlist 过期后同步脚本静默跳过、符号引脚数少于
  封装焊盘数（如 2 脚晶振符号配 4 焊盘 3225 封装，外壳地悬空）、同号焊盘
  （轻触开关/SOT-223 散热脚）只有一个分到网络——三类真实事故一个检查全收。
- **电源线宽**（`power-width`）：DRC 只查间距不查载流。期望宽度三种来源：
  `.kicad_pro` netclass、`--rule` 通配、`--current` 电流值（IPC-2221 反算）。
  `--min-segment 2` 可豁免 IC 引脚逃逸短颈。
- **netclass 静默失效**（`netclass-orphan`）：netclass 里 net 名写错（典型
  `/+5V` 前缀坑）会静默回落 Default 细线——本工具直接给出 did-you-mean。

```bash
pip install git+https://github.com/94xhn/kicad-board-lint
kicad-board-lint 你的板.kicad_pcb --min-segment 2
```

兼容 KiCad 5–10；纯 Python 零依赖，可直接进 CI。同家族工具：
[kicad-corner-lint](https://github.com/94xhn/kicad-corner-lint)（直角/锐角
走线检测）、[kicad-file-doctor](https://github.com/94xhn/kicad-file-doctor)
（文件加载失败诊断）。

## License

[MIT](LICENSE)

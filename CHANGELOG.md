# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-06-11

### Added

- `ghost-pad`: copper pads with no net (DRC never flags these). Skips NPTH,
  unnumbered mechanical pads and `board_only` footprints; `--ignore-ref`
  for the rest.
- `dup-pad-net`: same-numbered pads within one footprint disagreeing about
  their net (tactile switches, SOT-223 tabs, thermal pads).
- `power-width`: per-net minimum track width sourced from `.kicad_pro` net
  classes (`nets` arrays and `netclass_patterns`), `--rule PATTERN=MM`, or
  `--current PATTERN=AMPS` via the IPC-2221 outer-layer formula
  (`--delta-t`, `--copper-oz`). One finding per net with the worst segment
  located; `--min-segment` exempts short pad-escape stubs.
- `netclass-orphan`: net-class entries matching no board net, with
  did-you-mean suggestions for the `/`-prefix trap.
- Zero-dependency `.kicad_pcb` parser for KiCad 5-10, including the
  KiCad 10 net-by-name format; pad positions computed with footprint
  rotation.
- CLI with text/JSON output, multi-file aggregation, `--strict`, and
  CI-friendly exit codes. 41-test pytest suite; smoke-tested on 4 real
  boards (found a real floating crystal-housing pad on the first run).

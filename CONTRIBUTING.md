# Contributing

Issues and PRs are welcome — especially reports of false positives with a
minimal `.kicad_pcb` snippet, and boards that parse wrong.

## Development setup

```bash
git clone https://github.com/94xhn/kicad-board-lint
cd kicad-board-lint
python -m venv .venv
.venv/bin/pip install -e .[dev]      # Windows: .venv\Scripts\pip install -e .[dev]
```

## Running checks

```bash
ruff check .
pytest
```

Both must pass; CI runs them on Python 3.9 / 3.11 / 3.13 plus a gitleaks
secret scan.

## Architecture conventions

- `kicad_board_lint/sexp.py` — S-expression parser. Knows nothing about PCBs.
- `kicad_board_lint/core.py` — board model (footprints/pads/segments). Pure
  parsing, no policy.
- `kicad_board_lint/checks.py` — lint rules and expectation building. Pure
  logic, no I/O; everything here must be unit-testable.
- `kicad_board_lint/cli.py` — argument parsing, file I/O, rendering.

New rules go in `checks.py` with tests in `tests/test_checks.py`. A rule
must hold the line on false positives: before adding one, run it against
real KiCad-saved boards — anything that fires on a healthy board needs a
severity downgrade, an exemption, or to be dropped.

The package stays **zero-dependency**; PRs adding runtime dependencies will
be asked to find another way.

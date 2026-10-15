# Contributing to AI Usage Clock

Thanks for your interest. AI Usage Clock is a small cross-platform desktop utility,
so most contributions fall into one of three buckets:

- **Provider layout fixes** — when Claude or Codex change their
  usage page and a tile starts showing `error · layout changed`. These are
  the most common and most welcome PRs.
- **Bug reports and small bug fixes** — anything around tray, widget,
  cookie storage, settings, or refresh logic.
- **New providers or new features** — please open an issue first so we can
  agree on scope before you write code.

## Development environment

Requirements: **Windows 10/11, macOS, or Linux** and **Python 3.11+**. The
test suite runs headlessly under `QT_QPA_PLATFORM=offscreen`; manual smoke
testing is still useful on each OS because tray/menu-bar behavior and native
credential storage are platform-specific.

```powershell
git clone https://github.com/AIUsageClock/ai-usage-clock.git
cd ai-usage-clock

py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
```

Run the app:

```powershell
.\.venv\Scripts\python.exe -m aiusageclock
```

On macOS or Linux, use `python3 -m venv .venv` and `./.venv/bin/python` in
place of the Windows commands, and quote the extras as `'.[dev]'`. A plain
source install (see [docs/build.md](docs/build.md)) omits the dev extras that
the tests need.

Run the tests:

```powershell
.\.venv\Scripts\python.exe -m pytest    # Windows
./.venv/bin/python -m pytest            # macOS / Linux
```

The automated suite covers provider parsing, configuration, UI behavior,
local usage tracking, MCP guards, credential storage, and platform
integration. Live Claude and Codex browser sessions are validated manually.

The version-sync check that gates CI:

```powershell
.\.venv\Scripts\python.exe tools\check_versions.py
```

Refresh the deterministic README screenshots without using live accounts:

```powershell
.\.venv\Scripts\python.exe tools\capture_readme_screenshots.py
```

This updates the full and compact floating-widget images using fixed demo data.

The README does not show a macOS screenshot at the moment. If you have a Mac,
you can capture the native menu-bar item from a logged-in desktop session and
add the image to the README:

```bash
./.venv/bin/python tools/capture_macos_menubar.py
```

It writes `docs/screenshots/mac-menubar.png` by default (`--output` picks
another path). The command renders only AI Usage Clock's own menu-bar button
with demo data, so it does not need Screen Recording permission or include
other desktop content.

## Pull request expectations

- Keep changes focused. One PR per logical change.
- Add or update tests when you change non-trivial logic.
- Run `python -m pytest` and `tools/check_versions.py` locally before opening the PR;
  both run in CI on push and pull request.
- If you bump the version, update `pyproject.toml`, `src/aiusageclock/__init__.py`,
  `README.md`, and add a `CHANGELOG.md` section. CI will fail otherwise.
- Avoid logging cookies, PATs, or full provider response bodies. The logger
  is rotated under the per-OS app-data directory, and users may attach those
  logs to issues.

## Reporting bugs

Use the issue templates under [.github/ISSUE_TEMPLATE/](.github/ISSUE_TEMPLATE/):

- **Bug report** — generic crashes, UI issues, settings glitches.
- **Provider layout broken** — a Claude or Codex tile started failing.
- **Feature request** — new ideas worth discussing before code.

For anything that exposes session cookies or tokens, please follow
[SECURITY.md](SECURITY.md) instead of opening a public issue.

## Code style

- Python: standard `from __future__ import annotations`, type hints encouraged,
  no formatter is enforced but please keep diffs minimal.
- Tests: use `pytest` and `pytest-qt`. Avoid mocking the database or the
  filesystem when an in-memory or `tmp_path` alternative works.
- Comments should explain *why*, not *what*. The repo's existing style favors
  short, sparse comments over docstring boilerplate.

## License

By contributing, you agree that your contributions are licensed under the
same MIT license that covers the rest of the project. See [LICENSE](LICENSE).

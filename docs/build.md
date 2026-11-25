# Run from source and build

[Back to the README](../README.md)

Most people should use the [pre-built downloads](../README.md#get-started-in-3-steps):
they do not need Python. This page is for running AI Usage Clock from a source
checkout, building a standalone binary locally, and maintainers cutting
releases.

## Run from source

Requires [uv](https://docs.astral.sh/uv/). The project builds with
**Python 3.14** (pinned in `.python-version`; uv fetches it when it is missing)
and supports Python 3.11+.

**Windows (PowerShell):**

```powershell
uv sync --frozen
.\.venv\Scripts\python.exe -m aiusageclock
```

**macOS / Linux (bash):**

```bash
uv sync --frozen
./.venv/bin/python -m aiusageclock
```

`uv sync --frozen` installs the versions pinned in `uv.lock` into `.venv`.

Then follow the [setup guide](setup.md) to connect your accounts. To run the
tests, see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Build a standalone binary

The build machine needs Python 3.14 and a `.venv` created with
`uv sync --frozen --extra dev` (PyInstaller comes from `uv.lock`). Windows builds also require PowerShell 7 (`pwsh`). The resulting
binary does **not** require Python or PowerShell on the target machine.

| OS      | Command                  | Output                                   |
| ------- | ------------------------ | ---------------------------------------- |
| Windows | `pwsh -File .\build.ps1` | `dist/ai-usage-clock/ai-usage-clock.exe` |
| macOS   | `./build.sh`             | `dist/ai-usage-clock.app`                |
| Linux   | `./build.sh`             | `dist/ai-usage-clock/ai-usage-clock`     |

Tagged commits matching `v*` run [the release workflow](../.github/workflows/release.yml),
which builds all three platforms and prepares a draft GitHub Release with SHA256
files. A separate maintainer-triggered test build uploads artifacts without
creating a release. Before publishing, the maintainer checks the draft artifacts
and the isolated GUI/MCP smoke results. CI does not validate live provider
accounts.

Bundles are large (several hundred MB unpacked) because the Chromium runtime
ships inside. User data still lives outside the bundle, under the per-OS app-data
directory (see [Where your data is stored](setup.md#where-your-data-is-stored)).

For a single-file binary (slower first launch), pass `-OneFile` (PowerShell) or
`--onefile` (bash). On macOS the `.app` bundle is recommended over the
single-file form.

## Pinned CI versions

Everything the CI workflows download or select is pinned to an exact version, so
that a new (possibly compromised) upstream release is never picked up
automatically. `tests/test_ci_pins.py` fails when a workflow uses a floating
reference.

| What | Where it is pinned |
| --- | --- |
| Python packages | `uv.lock` (installed with `uv sync --frozen`) |
| GitHub Actions | the 40-character commit SHA in each `uses:` line (Dependabot updates these) |
| Runner images | `windows-2025-vs2026`, `macos-26`, `ubuntu-22.04` in the `os` lists |
| CPython | `python-version` in `test.yml` and `release.yml`: 3.14.10 on every platform for builds and tests; the 3.11 floor is tested with 3.11.18 on Linux and 3.11.9 on Windows and macOS (see below). `.python-version` (3.14) is for local work only |
| uv | `version:` of `astral-sh/setup-uv` (0.13.9) |
| Node.js | `node-version` of `actions/setup-node` (24.22.2) |

The 3.11 patch version differs by platform on purpose. 3.11 only receives
security fixes, so python.org no longer publishes new Windows and macOS
binaries for it, and `actions/setup-python` can install only 3.11.9 there, while
the Linux runners have 3.11.18. `test.yml` therefore lists an exact
`python-version` per `os` and `python-series` in its matrix `include` entries
(every combination must have one; `tests/test_ci_pins.py` checks that each is
`X.Y.Z`). When you bump the 3.11 pin, check which patch versions each platform
can install.

Dependabot cannot update the last four rows, so upgrade them by hand:

1. Pick the new version (a runner image from the
   [runner-images README](https://github.com/actions/runner-images#available-images),
   a CPython release that `actions/setup-python` can install, a uv release, a
   Node.js 24.x release).
2. Change it in every place it appears: `git grep -n "3.14.10"` (and likewise
   for the other versions) lists them. Runner labels also appear in `if:`
   conditions in `release.yml`.
3. Run `tests/test_ci_pins.py` and `tests/test_license_bundling.py`.
4. Push to a branch and let the `test` workflow pass on all three systems
   before tagging a release.
## First-launch warnings on unsigned builds

Release artifacts are unsigned, and SHA256 sums are published next to each
archive. Each operating system may therefore warn the first time you start the
app:

- **Windows:** if SmartScreen warns, click **More info**, then **Run anyway**.
  Windows builds include product/version metadata, but unsigned low-prevalence
  binaries can still trigger SmartScreen or Microsoft Defender reputation
  warnings.
- **macOS:** Gatekeeper blocks the app on first launch. Do one of the following:
  - Try to open the app once, then go to **System Settings → Privacy & Security**,
    find the app in the Security section, click **Open**, then **Open Anyway**,
    enter your login password, and click **OK** (Apple's steps for an app it
    cannot check).
  - Or run `xattr -dr com.apple.quarantine ai-usage-clock.app` once.

  The optional MCP helper `ai-usage-clock-mcp` is a separate unsigned binary
  beside the app; clear its quarantine separately (see [MCP usage guard](mcp.md)).
- **Linux:** there is no signing layer. Just make `ai-usage-clock` executable if
  it isn't already (`chmod +x ai-usage-clock/ai-usage-clock`).

# Run from source and build

[Back to the README](../README.md)

Most people should use the [pre-built downloads](../README.md#get-started-in-3-steps):
they do not need Python. This page is for running AI Usage Clock from a source
checkout, building a standalone binary locally, and maintainers cutting
releases.

## Run from source

Requires **Python 3.11+**.

**Windows (PowerShell):**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m aiusageclock
```

**macOS / Linux (bash):**

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
./.venv/bin/python -m aiusageclock
```

Then follow the [setup guide](setup.md) to connect your accounts. To run the
tests, see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Build a standalone binary

The build machine needs Python 3.11+ and a `.venv` with `pip install -e .[dev]`
already run. Windows builds also require PowerShell 7 (`pwsh`). The resulting
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

# Releasing

This document is for maintainers publishing a public GitHub release of
AI Usage Clock.

## What GitHub Releases Are

A GitHub Release is a named snapshot of the repository, usually tied to a Git
tag such as `v0.4.2`. It gives users a stable page with release notes and
downloadable files.

For AI Usage Clock, the release page should include:

- The source code snapshot that GitHub attaches automatically.
- One build artifact per supported OS, each containing the GUI plus the
  `ai-usage-clock-mcp` helper:
  - Windows: zipped `dist/ai-usage-clock/` folder (helper inside it)
  - macOS: tar.gz of the `.app` bundle **and** `dist/ai-usage-clock-mcp` beside it
  - Linux: tar.gz of `dist/ai-usage-clock/` (helper inside it)
- SHA256 checksums for each downloadable artifact.
- A short note that the app is unsigned unless code signing has been added.
- Windows artifact SHA256 and Authenticode status for Defender triage.

## CI and release checklist

The test workflow runs on pull requests and pushes to `main`, across Windows,
macOS, and Ubuntu with Python 3.11 and 3.12. It runs the version consistency
check and test suite. A green local run does not substitute for checking the
actual Actions results on the target commit. The same matrix can also be run
manually for diagnostics:

```text
gh workflow run test.yml --ref main
```

Before tagging, confirm `pyproject.toml`, `src/aiusageclock/__init__.py`, README,
and CHANGELOG agree on the release version. The local preflight is:

```text
uv run tools/check_versions.py
uv run pytest
```

For a packaging trial, use the release workflow's `workflow_dispatch` test-build
path. It builds the three platform archives and SHA256 files as downloadable
workflow artifacts only; it must not create or alter a GitHub Release. Review
the artifacts and run the GUI and MCP helper from each extracted bundle in an
isolated smoke setup. Do not install over a user's existing AI Usage Clock copy or
use its live profile for this check. The CI and bundle smoke checks do not
prove that live Claude, Codex, or other provider accounts work, and do not
count as real-account testing on macOS or Linux.

Also read `THIRD_PARTY_NOTICES.txt` in the extracted Linux archive. The Linux
build copies shared libraries of the build machine into the bundle, and the
"System libraries bundled on Linux" section lists each one with its Debian
package and that package's copyright text, then the standard license texts
(LGPL, GPL, ...) that those copyright files refer to, under "Referenced license
texts". Only a Linux run can produce it, so this is where it is verified. Look
at every library marked "no Debian package owns this file" or "package
unknown", and at every "No copyright text was found" or "Not found at" line:
those need a decision before publishing.

After release preparation is committed to `main`, push the matching `v<version>`
tag. The `v*` release workflow builds Windows, macOS, and Linux bundles, creates
SHA256 files, and attaches each archive/checksum pair to a **draft** release on
the [Releases page](https://github.com/AIUsageClock/ai-usage-clock/releases):

- `ai-usage-clock-<version>-windows.zip` (+ `.sha256`)
- `ai-usage-clock-<version>-macos.tar.gz` (+ `.sha256`)
- `ai-usage-clock-<version>-linux.tar.gz` (+ `.sha256`)

Before publishing, verify the tag and version, all six asset names, hashes,
archive contents, unsigned-build notes, and isolated GUI/MCP smoke evidence.
Also read the "System libraries bundled on Linux" section of
`THIRD_PARTY_NOTICES.txt` in the Linux archive that is about to be published,
with the same checks as in the packaging trial above: a tag build can run on a
newer runner image than the trial did, and the libraries it copies into the
bundle come from that image.
Replace the generated commit summary with the matching CHANGELOG notes. Publish
the release from GitHub only after those checks pass. A draft build or a
successful workflow run alone is not approval to publish.

## Manual fallback

If the automated workflow is unavailable (e.g. you're publishing from a
repository without Actions enabled), the manual flow still works — but you'll
need access to a machine of each OS you intend to ship for, since
PyInstaller cross-compilation isn't supported.

1. On each target OS, run `uv run tools/check_versions.py` and `uv run pytest`,
   then create a fresh bundle with `pwsh -File ./build.ps1` on Windows or
   `./build.sh` on macOS/Linux. Run `tools/smoke_test_gui.py` against that bundle
   and `tools/smoke_test_mcp.py` against its helper, using the build virtualenv.
2. Package the verified build. `build.ps1` / `build.sh` place `ai-usage-clock-mcp` inside
   `dist/ai-usage-clock/` on Windows and Linux, but leave it at `dist/ai-usage-clock-mcp`
   on macOS — so the macOS archive must name it explicitly or it ships
   without the MCP helper. The same goes for `LICENSE` and
   `THIRD_PARTY_NOTICES.txt`: they sit inside `dist/ai-usage-clock/` on Windows
   and Linux, but beside the `.app` and the helper on macOS, so the macOS
   archive must name them too:
   - Windows: zip the full `dist\ai-usage-clock\` folder.
   - macOS: `tar -C dist -czf ai-usage-clock-<ver>-macos.tar.gz ai-usage-clock.app ai-usage-clock-mcp LICENSE THIRD_PARTY_NOTICES.txt`
   - Linux: `tar -C dist -czf ai-usage-clock-<ver>-linux.tar.gz ai-usage-clock`

   Confirm the helper and the two license files survived packaging before
   uploading, on all three platforms. The release workflow runs the same kind
   of check on the archives it builds. List the archive and require each entry
   (on macOS the entries sit at the top level; on Linux they carry the
   `ai-usage-clock/` prefix):

   ```powershell
   # Windows
   Add-Type -AssemblyName System.IO.Compression.FileSystem
   $zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path .\ai-usage-clock-<ver>-windows.zip).Path)
   try { $entries = @($zip.Entries | ForEach-Object { $_.FullName -replace '\\', '/' }) } finally { $zip.Dispose() }
   foreach ($required in @("ai-usage-clock/ai-usage-clock-mcp.exe", "ai-usage-clock/LICENSE", "ai-usage-clock/THIRD_PARTY_NOTICES.txt")) {
       if ($entries -notcontains $required) { throw "$required is missing from the zip" }
   }
   ```

   ```bash
   # macOS (prefix="") or Linux (prefix="ai-usage-clock/")
   # Meant to be pasted into an open terminal: it reports with echo and never
   # calls exit, which would close the terminal on a missing file.
   archive=ai-usage-clock-<ver>-macos.tar.gz
   prefix=""
   listing="$(tar -tzf "$archive")"
   missing=0
   for required in ai-usage-clock-mcp LICENSE THIRD_PARTY_NOTICES.txt; do
       if ! grep -qxF "${prefix}${required}" <<< "$listing"; then
           echo "${prefix}${required} is missing from $archive" >&2
           missing=1
       fi
   done
   if [ "$missing" -eq 0 ]; then echo "all required files are in $archive"; else echo "$archive is incomplete" >&2; fi
   ```
3. Create a checksum:

   ```powershell
   Get-FileHash .\ai-usage-clock-<ver>-windows.zip -Algorithm SHA256
   ```

   ```bash
   shasum -a 256 ai-usage-clock-<ver>-macos.tar.gz
   ```

4. Push the version tag, then in GitHub go to this repository's
   **Releases** → **Draft a new release**, select the tag, paste the changelog
   notes, and attach all archive + `.sha256` pairs. Publish only after checking
   all archives, hashes, and isolated GUI/MCP smoke results.

## Suggested Release Notes Shape

```markdown
## AI Usage Clock <version>

Compact monitor for Claude.ai, ChatGPT Codex, OpenCode, GitHub Copilot, and OpenRouter usage.
Native UI per OS: floating widget on Windows / Linux, menu-bar item on macOS.

### Highlights

- ...

### Download

- Windows: `ai-usage-clock-<ver>-windows.zip` → extract, run `ai-usage-clock.exe`.
- macOS: `ai-usage-clock-<ver>-macos.tar.gz` → drag `ai-usage-clock.app` to Applications.
  First launch needs `xattr -dr com.apple.quarantine ai-usage-clock.app` or right-click → Open.
- Linux: `ai-usage-clock-<ver>-linux.tar.gz` → extract, run `./ai-usage-clock/ai-usage-clock`.

Each archive also ships the optional `ai-usage-clock-mcp` usage-guard helper
(alongside `ai-usage-clock.app` on macOS, inside the folder elsewhere). It is only
needed by MCP clients — see the README. macOS users must clear quarantine on
the helper separately: `xattr -dr com.apple.quarantine ai-usage-clock-mcp`.

### Verification

SHA256: see the `.sha256` next to each archive.
```

## Windows Defender / Reputation Notes

Windows releases are built with PyInstaller metadata generated from
`pyproject.toml` so `ai-usage-clock.exe` has a stable ProductName, CompanyName,
FileDescription, FileVersion, ProductVersion, OriginalFilename, and license notice.
The app's Start at login setting uses a named Task Scheduler entry (`AI Usage Clock`)
instead of writing to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

### Why builds get flagged

The root cause is always the same: an **unsigned, low-prevalence PyInstaller
binary**. Until the artifact is code-signed (see Signing Notes), expect two
distinct kinds of Defender verdict, which are reported and submitted the same
way but mean different things:

- **Static file-reputation ML** — e.g. `Trojan:Win32/Bearfoos.A!ml`. A generic
  catch-all that fires on unsigned, packed Python executables almost regardless
  of their actual code. It is about the file's *reputation*, not its behavior.
- **Behavioral ML** — e.g. `Behavior:Win32/Persistence.A!ml`. Fires at runtime
  when the unsigned exe registers autostart (a Run-key value on older builds, or
  the Task Scheduler entry on 0.6.0+). The flagged items are the autostart
  artifacts, and the "executes commands from an attacker" text is generic
  boilerplate for the Persistence family, not a finding about our code.

Both collapse to the same fix — **code signing** — which is why it is the
priority over any change to the autostart mechanism. The heuristic mitigations
already in place (stable version metadata, `--noupx`, one-folder build, per-user
Task Scheduler autostart) reduce but do not eliminate these on unsigned builds.

### Recording artifact details

Before publishing a Windows release, record these from the built exe (needed for
the release page and for any false-positive submission):

```powershell
Get-FileHash ".\dist\ai-usage-clock\ai-usage-clock.exe" -Algorithm SHA256
Get-AuthenticodeSignature ".\dist\ai-usage-clock\ai-usage-clock.exe"
```

### Local development exclusion (your machine only)

Defender re-quarantines each fresh local build, which fights iterative work. On
your **own dev machine only**, add a Defender folder exclusion for the build
output (Windows Security → Virus & threat protection → Manage settings →
Exclusions → Add an exclusion → Folder → `C:\git\ai-usage-clock\dist`). Never put this
advice in user-facing docs or release notes — end users should not be told to
exclude folders.

### Submitting a Defender false positive

If Defender or SmartScreen flags a release, report the exact artifact to
Microsoft as a software-developer false positive. The portal is a web form
(there is no public API for indie submissions), but
[tools/wdsi_submission.py](tools/wdsi_submission.py) pre-fills everything it
asks for so the submission is copy-paste. Submit **once per distinct exe/hash**
that was flagged (e.g. a Run-key build under `C:\Tools` and a dev build under
`C:\git\...\dist` are two separate submissions).

1. Build (or locate) the flagged exe, then generate its submission sheet. Read
   the **detection name** and **security intelligence version** off the Defender
   alert ("Protection history" → expand the threat) and pass them in so the
   sheet has no placeholders:

   ```powershell
   # Default reads dist\ai-usage-clock\ai-usage-clock.exe:
   .venv\Scripts\python.exe tools\wdsi_submission.py `
       --detection "Behavior:Win32/Persistence.A!ml" --intel 1.0.0.0

   # Point --exe at any other flagged copy:
   .venv\Scripts\python.exe tools\wdsi_submission.py `
       --exe "C:\Tools\ai-usage-clock\ai-usage-clock.exe" `
       --detection "Trojan:Win32/Bearfoos.A!ml" --intel 1.0.0.0
   ```

   The sheet auto-fills the SHA256, Authenticode status, version, git tag/commit,
   repo URL, and contact (from `git config user.email`). Add `--out build\wdsi.txt`
   to also save it to a file.

2. Open the portal: <https://www.microsoft.com/en-us/wdsi/filesubmission>
   Sign in with a Microsoft account and choose **I'm a software developer**.
3. **Upload the exact exe** the sheet was generated from — the portal hashes it,
   so the SHA256 must match the sheet. Select **Incorrectly detected as
   malware/malware family** and enter the detection name from the sheet.
4. Paste the generated sheet into the **Additional information** box and submit.
   You will get a submission ID; Microsoft usually responds within hours to a
   couple of days, and you can check status on the same portal.
5. Once a signing certificate is in place (see Signing Notes), Microsoft can
   allow-list by **publisher** instead of per-file hash, so future signed builds
   are trusted without re-submitting each release.

## Signing Notes

Release artifacts are unsigned unless a maintainer provides signing material.
**Signing is the durable fix for both Defender verdict types above** — it gives
the file publisher reputation (static ML) and makes a persistence action by a
known publisher unremarkable (behavioral ML). A *self-signed* certificate does
**not** help; the certificate must chain to a CA Windows already trusts.

Per-OS situation:

- **Windows** — SmartScreen and Microsoft Defender warn on new or low-prevalence
  downloads. Authenticode signing with a consistent publisher certificate is the
  recommended fix before broad distribution. Note: since June 2023 all
  code-signing private keys must live on FIPS hardware (USB token or cloud HSM),
  so there are no cheap downloadable `.pfx` certs anymore. Options:
  - **SignPath Foundation** — free code signing for open-source projects. This is
    the intended path for AI Usage Clock. Apply at <https://about.signpath.io/open-source>,
    then the signing step can run in CI via SignPath's GitHub Action.
  - **Azure Trusted Signing** — Microsoft's own signing service (~$10/month).
    Best Defender/SmartScreen reputation for the cost; eligibility historically
    needs an organization with verifiable history, so check current terms.
  - **EV code-signing certificate** (~$250–600/yr, hardware token) — the only
    option that grants *immediate* SmartScreen reputation; overkill unless
    distributing at volume.
- **macOS** — Gatekeeper blocks first launch (quarantine attribute) until
  Developer ID signing/notarization is added.
- **Linux** — no OS signing layer, so no equivalent first-launch warning.

Code signing / notarization reduces friction but costs money and adds
maintenance. Until it is in place, lean on the false-positive submission flow
above. Unsigned internal builds should still come from CI, keep their SHA256
hashes, and avoid ad hoc binaries from developer machines.

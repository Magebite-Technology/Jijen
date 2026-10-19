# Fast Windows contour beta

This workflow reuses an already successful **Jijen Windows Beta** full build. It does not compile C++, change native binaries, install software on your PC, or publish a release. It uploads a tested portable ZIP as an Actions artifact, retained for 14 days. Existing full builds and installers are unchanged.

## Choose a base

1. Wait for a Jijen Windows Beta full-build run to finish successfully, including packaging and publication. A running, failed or cancelled build cannot be a base.
2. Open that run's prerelease. Download its `FreeCAD_beta-windows-...-Windows-x86_64.7z-SHA256.txt` and copy the 64-character checksum of the corresponding portable `.7z`.
3. Record the full **run ID** from the Actions URL, not the short run number. The workflow derives the exact base commit/release from that run and verifies the archive against your pinned checksum.

The base commit must be an ancestor of the selected source. Every changed runtime file since that commit must be in the exact Python overlay list. Native/C++ changes, dependency changes, build scripts, other modules, deletions of required overlay files and unapproved resources fail closed with **Full build required**. It never silently drops such changes or automatically launches an expensive full build. CI-only metadata and phase documentation are not copied into the application.

## Run on this feature branch now

Before the workflow exists on the default branch, GitHub may not show its manual Run workflow button. Create or update `.github/fast-contour-beta-request.json` in the desired supported branch using the GitHub web editor:

```json
{
  "base_run_id": "COPY_SUCCESSFUL_FULL_BUILD_RUN_ID",
  "base_sha256": "COPY_64_CHARACTER_PORTABLE_7Z_SHA256",
  "request": "Change this text to request another build from the current commit"
}
```

Commit the request file. Only a change to this request file requests packaging; workflow/script/doc edits run safety checks without downloading the large base. Ordinary contour commits still use the existing fast contour-test workflow. No base is selected implicitly and no floating latest release is used.

After this workflow reaches the default branch: Actions → **Jijen Fast Contour Beta** → **Run workflow** → choose the source branch and enter `base_run_id` and `base_sha256`. Dispatch inputs take precedence; the request file is read only for push-triggered packaging.

Supported push branches: main, feature/surface-contours-phase-1 and feature/surface-contours-progress-cancel. PR events run safety-rule self-tests only, never packaging or release publication.

## Validation and download

The workflow copies the four contour modules, their Part workbench Python registration and an explicit set of contour fixtures/tests into the base's `Mod/Part`. New files require a reviewed overlay-list change; resources compiled into Qt/native binaries require a full build.

It runs command-line startup and the full contour test runner against the staged application, then launches the real GUI on the Windows runner. The GUI smoke test activates Part, checks imports and command registration, detects six cube regions and creates a parametric preview. Native EXE/DLL/PYD hashes must remain unchanged. It tests the ZIP's integrity before uploading.

On success, download the **jijen-fast-contour-beta-...** artifact from the run summary. Extract the artifact, then extract the inner portable ZIP. Start `bin/FreeCAD.exe` inside the application folder. No new installer is produced. Logs are uploaded separately, including on failure.

`Jijen-contour-overlay.json` is included beside the ZIP and inside the application. It records the base commit/run/release/checksum, contour source commit, per-file overlay hashes, runtime versions and validation results. The native About/version remains the base version; the manifest identifies this contour beta accurately. Packages remain unsigned betas.

This avoids compilation, but downloading/extracting the base, testing, hashing and ZIP creation still take time. Measure a successful run before claiming a speedup. Passing this small GUI smoke test does not replace a manual large-model responsiveness/cancellation test.

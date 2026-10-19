# SPDX-License-Identifier: LGPL-2.1-or-later
[CmdletBinding()]
param(
    [string]$BaseRunId = $env:FAST_BASE_RUN_ID,
    [string]$BaseSha256 = $env:FAST_BASE_SHA256,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Deliberately exact: new runtime files must be explicitly reviewed and mapped.
$OverlayFiles = @(
    'InitGui.py', 'SurfaceContours.py', 'SurfaceRegions.py',
    'SurfaceSemantics.py', 'SurfaceContourGui.py',
    'parttests/TestSurfaceContours.py', 'parttests/TestSurfaceRegions.py',
    'parttests/TestRegionContours.py', 'parttests/TestSurfaceContourFixtures.py',
    'parttests/TestSurfaceContourGui.py', 'parttests/TestSurfaceContourParametric.py',
    'parttests/TestSurfaceSemantics.py', 'parttests/surface_contour_fixtures.py'
)
$MetadataFiles = @(
    '.github/fast-contour-beta-request.json', '.github/FAST_CONTOUR_BETA.md',
    '.github/scripts/build_fast_contour_beta.ps1',
    '.github/workflows/build_fast_contour_beta.yml',
    '.github/workflows/build_beta_windows.yml',
    '.github/workflows/test_surface_contours.yml',
    '.github/scripts/invoke_surface_contour_tests.ps1',
    '.github/scripts/run_surface_contour_tests.py',
    '.github/CONTOUR_TESTING.md', '.github/beta-build-request.txt'
)
function Test-AllowedChange([string]$Path) {
    return ($Path -cin @($OverlayFiles | ForEach-Object { "src/Mod/Part/$_" })) -or
        ($Path -cin $MetadataFiles) -or
        ($Path -cmatch '^src/Mod/Part/parttests/SurfaceContoursPhase[1-7]\.md$')
}
function Assert-Pins([string]$RunId, [string]$Hash) {
    if ($RunId -notmatch '^[1-9][0-9]{0,17}$') { throw 'A numeric full-build run ID is required' }
    if ($Hash -notmatch '^[a-fA-F0-9]{64}$') { throw 'An exact 64-character archive SHA256 is required' }
}
if ($SelfTest) {
    $allowed = @('src/Mod/Part/SurfaceContours.py', 'src/Mod/Part/InitGui.py',
        'src/Mod/Part/parttests/TestSurfaceRegions.py', '.github/FAST_CONTOUR_BETA.md')
    $blocked = @('src/Mod/Part/App/PartFeatures.cpp', 'pixi.lock', 'CMakePresets.json',
        'package/bundle/build.sh', '.gitmodules', 'src/Gui/Command.cpp',
        'src/Mod/Part/Other.py', 'src/Mod/Part/../Other.py', 'src/mod/part/SurfaceContours.py')
    foreach ($path in $allowed) { if (!(Test-AllowedChange $path)) { throw "Rejected allowed file: $path" } }
    foreach ($path in $blocked) { if (Test-AllowedChange $path) { throw "Accepted unsafe file: $path" } }
    Assert-Pins '39186045272' ('a' * 64)
    foreach ($pair in @(@('latest', ('a' * 64)), @('12', 'latest'), @('12;exit', ('a' * 64)))) {
        $rejected = $false
        try { Assert-Pins $pair[0] $pair[1] } catch { $rejected = $true }
        if (!$rejected) { throw 'Accepted invalid base pin' }
    }
    Write-Host 'FAST_BETA_SAFETY_OK (17 checks)'
    return
}

if (!$env:GITHUB_ACTIONS -or $env:GITHUB_REPOSITORY -ne 'Magebite-Technology/Jijen') {
    throw 'Packaging is restricted to the Jijen GitHub Actions repository'
}
if ($env:GITHUB_EVENT_NAME -eq 'push') {
    $request = Get-Content -Raw -LiteralPath .github/fast-contour-beta-request.json | ConvertFrom-Json
    $BaseRunId = [string]$request.base_run_id
    $BaseSha256 = [string]$request.base_sha256
}
Assert-Pins $BaseRunId $BaseSha256
function Get-GitHubJson([string]$Endpoint) {
    $json = & gh api $Endpoint
    if ($LASTEXITCODE -ne 0) { throw "GitHub lookup failed: $Endpoint" }
    return ($json | ConvertFrom-Json)
}
$repo = $env:GITHUB_REPOSITORY
$run = Get-GitHubJson "repos/$repo/actions/runs/$BaseRunId"
if ($run.status -ne 'completed' -or $run.conclusion -ne 'success' -or
    $run.path -ne '.github/workflows/build_beta_windows.yml' -or
    $run.head_repository.full_name -ne $repo -or $run.event -notin @('push', 'workflow_dispatch')) {
    throw 'Base must be a successful, same-repository Jijen Windows Beta full build'
}
$baseCommit = [string]$run.head_sha
if ($baseCommit -notmatch '^[0-9a-f]{40}$') { throw 'Invalid base commit' }
& git merge-base --is-ancestor $baseCommit HEAD
if ($LASTEXITCODE -ne 0) { throw 'Base is not an ancestor of this source; use a matching full build' }
$changed = @(& git -c core.quotepath=false diff --name-only --no-renames $baseCommit HEAD)
if ($LASTEXITCODE -ne 0) { throw 'Cannot compare complete base/source trees' }
$blocked = @($changed | Where-Object { !(Test-AllowedChange $_) })
if ($blocked.Count) { throw "Full build required. Non-overlay changes: $($blocked -join ', ')" }
foreach ($file in $OverlayFiles) {
    if (!(Test-Path -LiteralPath "src/Mod/Part/$file" -PathType Leaf)) {
        throw "Missing approved module: $file. Deletions require a full build."
    }
}

$tag = "beta-windows-$($run.run_number)-$($baseCommit.Substring(0, 7))"
$release = Get-GitHubJson "repos/$repo/releases/tags/$tag"
$tagCommit = Get-GitHubJson "repos/$repo/commits/$tag"
if ($release.draft -or $tagCommit.sha -ne $baseCommit) { throw 'Base release/tag does not match full-build source' }
$assetName = "FreeCAD_$tag-Windows-x86_64.7z"
$assets = @($release.assets | Where-Object { $_.name -ceq $assetName })
if ($assets.Count -ne 1) { throw 'Expected exactly one Windows x64 portable base archive' }
$work = Join-Path $env:RUNNER_TEMP "jijen-fast-$($env:GITHUB_RUN_ID)-$($env:GITHUB_RUN_ATTEMPT)"
if (Test-Path -LiteralPath $work) { throw 'Refusing to reuse an existing staging directory' }
New-Item -ItemType Directory -Path $work | Out-Null
New-Item -ItemType Directory -Path fast-beta-logs | Out-Null
& gh release download $tag --repo $repo --pattern $assetName --dir $work
if ($LASTEXITCODE -ne 0) { throw 'Base archive download failed' }
$archive = Join-Path $work $assetName
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $BaseSha256) {
    throw 'Pinned base archive SHA256 mismatch'
}
$extract = Join-Path $work 'extracted'
& 7z x $archive "-o$extract" -y | Out-File fast-beta-logs/extraction.log
if ($LASTEXITCODE -ne 0) { throw 'Base extraction failed' }
$executables = @(Get-ChildItem -LiteralPath $extract -Recurse -File -Filter FreeCADCmd.exe |
    Where-Object { $_.Directory.Name -eq 'bin' })
if ($executables.Count -ne 1) { throw 'Expected one native FreeCADCmd.exe in the portable base' }
$app = $executables[0].Directory.Parent.FullName
$cmd = $executables[0].FullName
$gui = Join-Path $app 'bin/FreeCAD.exe'
$part = Join-Path $app 'Mod/Part'
if (!(Test-Path -LiteralPath $gui) -or !(Test-Path -LiteralPath "$part/parttests/__init__.py")) {
    throw 'Unsupported portable application layout'
}
function Get-NativeHashes {
    $hashes = @{}
    Get-ChildItem -LiteralPath $app -Recurse -File |
        Where-Object { $_.Extension -in @('.exe', '.dll', '.pyd') } |
        ForEach-Object { $hashes[$_.FullName.Substring($app.Length)] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    return $hashes
}
$nativeBefore = Get-NativeHashes
$overlay = @()
foreach ($file in $OverlayFiles) {
    $source = "src/Mod/Part/$file"
    $destination = Join-Path $part $file
    if (!(Test-Path -LiteralPath (Split-Path -Parent $destination) -PathType Container)) {
        throw "Missing module directory for $file"
    }
    Copy-Item -LiteralPath $source -Destination $destination
    $hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $hash) { throw "Overlay copy mismatch: $file" }
    $overlay += [ordered]@{ source = $source; destination = "Mod/Part/$file"; sha256 = $hash }
    # Only delete bytecode for the exact overlaid module, inside this temporary app.
    $stem = [IO.Path]::GetFileNameWithoutExtension($destination)
    $parent = Split-Path -Parent $destination
    $cache = Join-Path $parent '__pycache__'
    if (Test-Path -LiteralPath $cache) {
        Get-ChildItem -LiteralPath $cache -File | Where-Object { $_.Name -like "$stem.*.pyc" } |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName }
    }
    foreach ($suffix in @('c', 'o')) {
        if (Test-Path -LiteralPath "$destination$suffix") { Remove-Item -LiteralPath "$destination$suffix" }
    }
}

# Run against the staged package, never the source module path.
& $cmd --safe-mode --version 2>&1 | Tee-Object fast-beta-logs/startup.log
if ($LASTEXITCODE -ne 0) { throw 'Packaged command-line startup failed' }
& ./.github/scripts/invoke_surface_contour_tests.ps1 -Executable $cmd -PartPath $part -LogPath fast-beta-logs/contour-tests.log

# Exercise the real GUI, Qt/Pivy and workbench registration, not just headless imports.
$macro = Join-Path $work 'fast-beta-smoke.FCMacro'
$env:JIJEN_SMOKE_RESULT = Join-Path $work 'gui-smoke.json'
$env:JIJEN_SMOKE_PART = $part
@'
import json, os, traceback
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

def smoke():
    result = {"ok": False}
    try:
        Gui.activateWorkbench("PartWorkbench")
        import Part
        from pivy import coin
        import SurfaceContours, SurfaceRegions, SurfaceSemantics, SurfaceContourGui
        expected = Path(os.environ["JIJEN_SMOKE_PART"]).resolve()
        for module in (SurfaceContours, SurfaceRegions, SurfaceSemantics, SurfaceContourGui):
            assert Path(module.__file__).resolve().parent == expected, module.__file__
        assert "Part_SurfaceContours" in Gui.listCommands()
        doc = App.newDocument("FastBetaSmoke")
        box = doc.addObject("Part::Feature", "Box")
        box.Shape = Part.makeBox(10, 20, 30)
        doc.recompute()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(box)
        panel = SurfaceContourGui.SurfaceContourTaskPanel()
        Gui.Control.showDialog(panel)
        QtWidgets.QApplication.processEvents()
        panel.refresh()
        assert len(panel.results) == 6, "Cube must expose six regions"
        created = panel.create_all()
        assert created and created[0].ContourStatus in ("ok", "partial")
        Gui.Control.closeDialog()
        App.closeDocument(doc.Name)
        result = {"ok": True, "regions": 6, "pivy": str(coin.SoDB.getVersion()),
                  "freecad": list(App.Version()), "occt": Part.OCC_VERSION}
    except BaseException:
        result["error"] = traceback.format_exc()
    finally:
        Path(os.environ["JIJEN_SMOKE_RESULT"]).write_text(json.dumps(result), encoding="utf-8")
        QtWidgets.QApplication.instance().quit()

QtCore.QTimer.singleShot(0, smoke)
'@ | Set-Content -LiteralPath $macro -Encoding utf8
$process = Start-Process -FilePath $gui -ArgumentList @('--safe-mode', "`"$macro`"") -WindowStyle Hidden -PassThru
if (!$process.WaitForExit(120000)) {
    Stop-Process -Id $process.Id -Force
    throw 'Packaged GUI smoke test timed out after two minutes'
}
if (!(Test-Path -LiteralPath $env:JIJEN_SMOKE_RESULT)) { throw 'GUI did not produce a smoke-test result' }
Copy-Item -LiteralPath $env:JIJEN_SMOKE_RESULT -Destination fast-beta-logs/gui-smoke.json
$smoke = Get-Content -Raw -LiteralPath $env:JIJEN_SMOKE_RESULT | ConvertFrom-Json
if ($process.ExitCode -ne 0 -or !$smoke.ok) { throw "GUI smoke test failed: $($smoke | ConvertTo-Json -Compress)" }
$nativeAfter = Get-NativeHashes
if ($nativeBefore.Count -ne $nativeAfter.Count) { throw 'Native binary inventory changed' }
foreach ($key in $nativeBefore.Keys) {
    if (!$nativeAfter.ContainsKey($key) -or $nativeBefore[$key] -ne $nativeAfter[$key]) {
        throw "Native binary unexpectedly modified: $key"
    }
}

$manifest = [ordered]@{
    schema = 1; kind = 'python-overlay-portable-beta'; source_commit = $env:GITHUB_SHA
    base_run_id = $BaseRunId; base_commit = $baseCommit; base_release = $tag
    base_asset = $assetName; base_sha256 = $BaseSha256.ToLowerInvariant()
    overlay_run = $env:GITHUB_RUN_ID; overlay_attempt = $env:GITHUB_RUN_ATTEMPT
    changed_files = $changed; overlay_files = $overlay
    validation = $smoke; native_files_verified = $nativeBefore.Count
    note = 'Native application version is the base version. See this manifest for contour overlay identity. Unsigned beta; not an installer.'
}
New-Item -ItemType Directory -Path fast-beta-output | Out-Null
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$app/Jijen-contour-overlay.json" -Encoding utf8
Copy-Item -LiteralPath "$app/Jijen-contour-overlay.json" -Destination fast-beta-output/Jijen-contour-overlay.json
Copy-Item -LiteralPath "$app/Jijen-contour-overlay.json" -Destination fast-beta-logs/Jijen-contour-overlay.json
$name = "Jijen-contours-$($env:GITHUB_SHA.Substring(0, 7))-$($env:GITHUB_RUN_ID)-$($env:GITHUB_RUN_ATTEMPT)-Windows-x64.zip"
$output = Join-Path (Resolve-Path -LiteralPath fast-beta-output).Path $name
Push-Location (Split-Path -Parent $app)
try {
    & 7z a -tzip -mx1 $output (Split-Path -Leaf $app) | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Portable ZIP creation failed' }
} finally { Pop-Location }
& 7z t $output | Out-File fast-beta-logs/archive-test.log
if ($LASTEXITCODE -ne 0) { throw 'Portable ZIP integrity test failed' }
$outputHash = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
"$outputHash  $name" | Set-Content -LiteralPath "$output-SHA256.txt" -Encoding ascii
@"
## Fast contour beta ready
- Source: $env:GITHUB_SHA
- Base: $baseCommit (full-build run $BaseRunId, release $tag)
- Base SHA256: $BaseSha256
- Passed: packaged startup, complete contour suite, real GUI cube/preview/Pivy smoke test, native binary hashes and ZIP integrity.
- Download the jijen-fast-contour-beta artifact below; extract the inner portable ZIP and run bin/FreeCAD.exe.
- This is a Python overlay, not a newly compiled application or installer. About/version still identifies the base.
"@ | Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY

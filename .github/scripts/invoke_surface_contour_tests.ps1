# SPDX-License-Identifier: LGPL-2.1-or-later
param(
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(Mandatory = $true)][string]$PartPath,
    [string]$LogPath = "contour-tests.log"
)
$ErrorActionPreference = "Stop"
$env:JIJEN_PART_PATH = (Resolve-Path -LiteralPath $PartPath).Path
$env:JIJEN_TEST_SCRIPT = Join-Path $PSScriptRoot "run_surface_contour_tests.py"
$testCode = 'import os; p=os.environ["JIJEN_TEST_SCRIPT"]; exec(compile(open(p, encoding="utf-8").read(), p, "exec"), {"__name__": "__main__", "__file__": p})'
$output = & $Executable --safe-mode --console $testCode 2>&1
$exitCode = $LASTEXITCODE
$output | Tee-Object -FilePath $LogPath
if ($exitCode -ne 0 -or @($output | ForEach-Object { $_.ToString().Trim() }) -notcontains "JIJEN_CONTOURS_OK") {
    throw "Contour validation failed. See $LogPath for test and feature diagnostics."
}

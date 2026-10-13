# Surface contour development

Pushes run Surface Contour Tests on the official FreeCAD 1.1.4 Windows portable runtime. The archive is verified against its published SHA256 and cached. Current source modules and tests are loaded explicitly without compiling C++ or creating an installer.

The shared runner executes 69 tests, including boundary-topology and angle-property regressions. Failed assertions print ContourStatus, Diagnostics, and LastError. Missing tests, failed imports, skipped tests, nonzero process exits, or a missing success marker fail validation. Logs are uploaded as artifacts.

Until this workflow is present on the default branch, GitHub does not show its Run workflow button. To request a full native build, edit `.github/beta-build-request.txt` on `feature/surface-contours-phase-1` and commit a new request. Other code changes do not trigger the full build. After the workflow is adopted on the default branch, Jijen Windows Beta can also be launched manually. The fast suite must pass first. Dependency and compiler caches are enabled; installed tests run before packaging, and staged application tests run before archive compression and installer creation. Superseded runs are canceled per branch.

The official runtime is an early compatibility check, not proof of compatibility with Jijen's locked OCCT 8 / Python 3.13 native build. Native C++ and dependency changes require full beta validation. The first native build remains expensive; later builds can reuse compiler cache entries.

To test with an existing Windows runtime:

```powershell
./.github/scripts/invoke_surface_contour_tests.ps1 -Executable C:/FreeCAD/bin/FreeCADCmd.exe -PartPath src/Mod/Part
```

Update EXPECTED_TESTS in the shared Python runner when the test inventory changes.

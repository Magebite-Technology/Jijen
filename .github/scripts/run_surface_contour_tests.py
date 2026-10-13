# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run contour tests against source, installed, or packaged modules."""
import importlib
import os
from pathlib import Path
import sys
import traceback
import unittest

import FreeCAD as App
import Part

MODULES = (
    "TestSurfaceContourFixtures", "TestSurfaceContours", "TestSurfaceRegions",
    "TestRegionContours", "TestSurfaceContourGui", "TestSurfaceContourParametric",
    "TestSurfaceSemantics",
)
EXPECTED_TESTS = 69


class DiagnosticResult(unittest.TextTestResult):
    def _dump_features(self, test):
        self.stream.writeln("FEATURE DIAGNOSTICS: " + test.id())
        for doc in App.listDocuments().values():
            for obj in doc.Objects:
                if "ContourStatus" in obj.PropertiesList:
                    self.stream.writeln(
                        "%s.%s: status=%r, LastError=%r, Diagnostics=%r"
                        % (doc.Name, obj.Name, obj.ContourStatus,
                           getattr(obj, "LastError", ""), getattr(obj, "Diagnostics", ""))
                    )

    def addFailure(self, test, error):
        self._dump_features(test)
        super().addFailure(test, error)

    def addError(self, test, error):
        self._dump_features(test)
        super().addError(test, error)


def main():
    part_path = Path(os.environ["JIJEN_PART_PATH"]).resolve()
    if not (part_path / "SurfaceContours.py").is_file():
        raise RuntimeError("Missing contour modules in " + str(part_path))
    sys.path.insert(0, str(part_path))
    for name in list(sys.modules):
        if name == "parttests" or name.startswith("parttests.") or name in (
            "SurfaceContours", "SurfaceRegions", "SurfaceSemantics", "SurfaceContourGui"
        ):
            del sys.modules[name]
    print("FreeCAD runtime:", App.Version())
    print("OCCT runtime:", Part.OCC_VERSION)
    print("Contour module directory:", part_path)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in MODULES:
        module = importlib.import_module("parttests." + name)
        if Path(module.__file__).resolve().parent != part_path / "parttests":
            raise RuntimeError("Tests imported from the wrong runtime: " + module.__file__)
        suite.addTests(loader.loadTestsFromTestCase(getattr(module, name)))
    if loader.errors or suite.countTestCases() != EXPECTED_TESTS:
        raise RuntimeError("Incomplete contour suite: %s tests; %s"
                           % (suite.countTestCases(), loader.errors))
    result = unittest.TextTestRunner(
        stream=sys.stdout, verbosity=2, resultclass=DiagnosticResult
    ).run(suite)
    ok = result.wasSuccessful() and result.testsRun == EXPECTED_TESTS and not result.skipped
    print("JIJEN_CONTOURS_OK" if ok else "JIJEN_CONTOURS_FAILED", flush=True)
    return ok


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc(file=sys.stdout)
        print("JIJEN_CONTOURS_FAILED", flush=True)

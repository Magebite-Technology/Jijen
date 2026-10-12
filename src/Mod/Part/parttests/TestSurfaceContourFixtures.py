# SPDX-License-Identifier: LGPL-2.1-or-later
"""Validate Phase 1 geometry and independent expected results.

These tests do not claim to test a contour extractor: that arrives in Phase 2.
"""

import math
import unittest

import FreeCAD as App
import Part
from parttests import surface_contour_fixtures as fixtures


class TestSurfaceContourFixtures(unittest.TestCase):
    def test_fixture_partition_and_boundaries(self):
        expected = {
            "Cube": (6, 6, 6), "SquarePyramid": (5, 5, 5),
            "SubdividedCube": (24, 6, 6), "Cylinder": (3, 3, 4),
            "Sphere": (1, 1, 0), "Annulus": (1, 1, 2),
            "SyntheticCurvedSole": (7, 3, 4), "DisconnectedCubes": (12, 12, 12),
        }
        for fixture in fixtures.all_fixtures():
            with self.subTest(fixture=fixture.name):
                self.assertTrue(fixture.shape.isValid())
                self.assertEqual((len(fixture.shape.Faces), len(fixture.regions),
                                  sum(len(r.boundaries) for r in fixture.regions)),
                                 expected[fixture.name])
                membership = [i for r in fixture.regions for i in r.face_indices]
                self.assertEqual(sorted(membership), list(range(len(fixture.shape.Faces))))
                for region in fixture.regions:
                    for wire in region.boundaries:
                        self.assertTrue(wire.isValid())
                        self.assertTrue(wire.isClosed())
                        self.assertLess(wire.distToShape(fixture.shape)[0], 1e-7)

    def test_analytic_measurements(self):
        for fixture in (fixtures.cube(), fixtures.cube(True)):
            self.assertAlmostEqual(fixture.shape.Volume, 8000, places=5)
            for region in fixture.regions:
                self.assertAlmostEqual(region.boundaries[0].Length, 80, places=5)
        pyramid = fixtures.pyramid()
        self.assertAlmostEqual(pyramid.shape.Volume, 8000 / 3, places=5)
        for region in pyramid.regions[1:]:
            self.assertAlmostEqual(region.boundaries[0].Length, 20 + 2 * math.sqrt(600))
        ring = fixtures.annulus()
        self.assertAlmostEqual(ring.shape.Area, math.pi * (400 - 64), places=5)

    def test_periodic_seams_are_not_oracle_boundaries(self):
        sphere = fixtures.sphere()
        self.assertGreater(len(sphere.shape.Edges), 0)
        self.assertEqual(sphere.regions[0].boundaries, ())
        cylinder = fixtures.cylinder()
        wall = next(r for r in cylinder.regions if r.name == "Wall")
        self.assertEqual(len(wall.boundaries), 2)
        for wire in wall.boundaries:
            self.assertAlmostEqual(wire.Length, 20 * math.pi, places=5)

    def test_curved_upper_boundary_and_internal_split(self):
        sole = fixtures.curved_sole()
        upper = sole.regions[0]
        self.assertEqual(len(upper.face_indices), 2)
        self.assertEqual(len(upper.boundaries), 1)
        wire = upper.boundaries[0]
        self.assertGreater(wire.BoundBox.ZLength, 1)
        self.assertTrue(any(isinstance(e.Curve, Part.BSplineCurve) for e in wire.Edges))
        a, b = (sole.shape.Faces[i] for i in upper.face_indices)
        self.assertTrue(any(x.isSame(y) for x in a.Edges for y in b.Edges))

    def test_document_creation_preserves_existing_document(self):
        existing = App.newDocument("SurfaceContourExisting")
        created = None
        try:
            created = fixtures.create_document()
            self.assertIs(App.getDocument(existing.Name), existing)
            self.assertEqual(len(created.RootObjects), 8)
        finally:
            if created is not None:
                App.closeDocument(created.Name)
            App.closeDocument(existing.Name)


if __name__ == "__main__":
    unittest.main()

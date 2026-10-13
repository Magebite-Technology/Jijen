# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest

import FreeCAD as App
import Part
import SurfaceContours as contours
import SurfaceRegions as regions
from parttests import surface_contour_fixtures as fixtures


class TestRegionContours(unittest.TestCase):
    def test_subdivided_cube_collapses_internal_edges(self):
        fixture = fixtures.cube(True)
        detection = regions.detect_surface_regions(fixture.shape)
        results = contours.extract_region_contours(fixture.shape, detection)
        self.assertEqual(len(results), 6)
        for result in results:
            self.assertEqual(result.status, "ok", result.diagnostics)
            self.assertEqual(len(result.wires), 1)
            self.assertTrue(result.wires[0].isClosed())
            self.assertEqual(len(result.wires[0].Edges), 4)
            self.assertAlmostEqual(result.wires[0].Length, 80)

    def test_region_boundary_keeps_shared_vertices_until_assembly(self):
        shape = fixtures.cube().shape
        before = shape.exportBrepToString()
        wires, status, diagnostics = contours._extract_region_boundary(shape, (0,))
        self.assertEqual(status, "ok", diagnostics)
        expected = contours.extract_face_contours(shape)[0]
        self.assertEqual(len(wires), len(expected.wires))
        self.assertEqual(len(wires[0].Edges), 4)
        self.assertTrue(wires[0].isClosed())
        self.assertAlmostEqual(wires[0].Length, expected.wires[0].Length)
        self.assertEqual(shape.exportBrepToString(), before)

    def test_cube_and_pyramid_keep_outer_boundaries(self):
        for fixture in (fixtures.cube(), fixtures.pyramid()):
            results = contours.extract_region_contours(fixture.shape)
            self.assertEqual(len(results), len(fixture.shape.Faces))
            self.assertTrue(all(r.status == "ok" for r in results))
            self.assertTrue(all(len(r.wires) == 1 for r in results))
            self.assertTrue(all(w.isClosed() for r in results for w in r.wires))

    def test_holes_are_preserved(self):
        result = contours.extract_region_contours(fixtures.annulus().shape)[0]
        self.assertEqual(result.status, "ok", result.diagnostics)
        self.assertEqual(len(result.wires), 2)
        self.assertTrue(all(w.isClosed() for w in result.wires))
        self.assertEqual(sorted(len(w.Edges) for w in result.wires), [1, 1])

    def test_individual_policy_matches_phase2(self):
        shape = fixtures.cube(True).shape
        detection = regions.detect_surface_regions(shape, policy="individual")
        grouped = contours.extract_region_contours(shape, detection)
        individual = contours.extract_face_contours(shape)
        self.assertEqual(len(grouped), len(individual))
        for result, expected in zip(grouped, individual):
            self.assertEqual(result.face_indices, (expected.face_index,))
            self.assertEqual(result.status, expected.status)
            self.assertEqual([w.Length for w in result.wires], [w.Length for w in expected.wires])

    def test_automatic_detection_uses_phase3_regions(self):
        shape = fixtures.cube(True).shape
        automatic = contours.extract_region_contours(shape)
        explicit = contours.extract_region_contours(shape, regions.detect_surface_regions(shape))
        self.assertEqual(
            [(r.face_indices, r.status, [w.Length for w in r.wires]) for r in automatic],
            [(r.face_indices, r.status, [w.Length for w in r.wires]) for r in explicit],
        )
        self.assertEqual([r.region_id for r in automatic], ["Region%d" % i for i in range(1, 7)])

    def test_disconnected_components_do_not_cross(self):
        shape = fixtures.disconnected_cubes().shape
        results = contours.extract_region_contours(shape)
        self.assertEqual(len(results), 12)
        self.assertTrue(all(r.status == "ok" for r in results))
        self.assertTrue(all(len(r.wires) == 1 for r in results))
        self.assertEqual(len({r.component_id for r in results}), 2)

    def test_curved_and_periodic_faces_keep_phase2_handling(self):
        for fixture in (fixtures.curved_sole(), fixtures.cylinder(), fixtures.sphere()):
            results = contours.extract_region_contours(fixture.shape)
            self.assertEqual(len(results), len(fixture.shape.Faces))
            self.assertTrue(all(r.status in ("ok", "no_boundary") for r in results))
        torus = contours.extract_region_contours(Part.makeTorus(20, 5))
        self.assertEqual(len(torus), 1)
        self.assertEqual(torus[0].status, "no_boundary")
        self.assertFalse(torus[0].wires)

    def test_explicit_region_subset_preserves_metadata(self):
        shape = fixtures.cube(True).shape
        detection = regions.detect_surface_regions(shape)
        selected = contours.extract_region_contours(shape, detection.regions[:2])
        self.assertEqual(len(selected), 2)
        self.assertEqual([r.region_id for r in selected], ["Region1", "Region2"])
        self.assertEqual([r.face_indices for r in selected], [r.face_indices for r in detection.regions[:2]])

    def test_input_and_region_validation(self):
        with self.assertRaises(contours.ContourInputError):
            contours.extract_region_contours(Part.Shape())
        shape = fixtures.cube().shape
        with self.assertRaises(ValueError):
            contours.extract_region_contours(shape, ((0,), (0,)))
        with self.assertRaises(ValueError):
            contours.extract_region_contours(shape, ((len(shape.Faces),),))
        with self.assertRaises(ValueError):
            contours.extract_region_contours(shape, ((),))

    def test_object_link_and_source_are_read_only(self):
        doc = App.newDocument("RegionContoursTest")
        try:
            source = doc.addObject("Part::Feature", "Source")
            source.Shape = fixtures.cube(True).shape
            link = doc.addObject("App::Link", "Link")
            link.setLink(source)
            link.LinkPlacement.Base = App.Vector(100, 0, 0)
            doc.recompute()
            before = source.Shape.exportBrepToString()
            results = contours.extract_region_contours(link)
            self.assertEqual(len(results), 6)
            self.assertEqual(len(doc.Objects), 2)
            self.assertEqual(source.Shape.exportBrepToString(), before)
        finally:
            App.closeDocument(doc.Name)

    def test_metadata_is_revision_local_and_deterministic(self):
        shape = fixtures.cube(True).shape
        first = contours.extract_region_contours(shape)
        second = contours.extract_region_contours(shape)
        self.assertEqual(
            [(r.region_id, r.face_indices, r.status, tuple(round(w.Length, 9) for w in r.wires)) for r in first],
            [(r.region_id, r.face_indices, r.status, tuple(round(w.Length, 9) for w in r.wires)) for r in second],
        )
        self.assertTrue(all(r.region_id.startswith("Region") for r in first))
        self.assertTrue(all(r.component_id == "Component1" for r in first))
        self.assertTrue(all(tuple(sorted(r.face_indices)) == r.face_indices for r in first))

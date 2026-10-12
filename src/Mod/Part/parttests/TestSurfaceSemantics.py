# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest

import FreeCAD as App

import SurfaceSemantics as semantics
from parttests import surface_contour_fixtures as fixtures


# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest

import FreeCAD as App

import SurfaceSemantics as semantics
from parttests import surface_contour_fixtures as fixtures


class TestSurfaceSemantics(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SurfaceSemantics")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _source(self, shape):
        source = self.doc.addObject("Part::Feature", "Source")
        source.Shape = shape
        self.doc.recompute()
        return source

    def test_cube_exposes_top_bottom_and_side_roles(self):
        detection = semantics.classify_surface_regions(fixtures.cube().shape)
        top = semantics.select_semantic_regions(detection, "top")
        bottom = semantics.select_semantic_regions(detection, "bottom")
        side = semantics.select_semantic_regions(detection, "side")
        self.assertTrue(top)
        self.assertTrue(bottom)
        self.assertEqual(len(side), 4)
        self.assertTrue(all(item.primary_role == "top" for item in top))
        self.assertTrue(all(item.primary_role == "bottom" for item in bottom))

    def test_reference_direction_changes_roles(self):
        upward = semantics.classify_surface_regions(
            fixtures.cube().shape, reference_direction=App.Vector(0, 0, 1)
        )
        downward = semantics.classify_surface_regions(
            fixtures.cube().shape, reference_direction=App.Vector(0, 0, -1)
        )
        self.assertEqual(
            {item.region_id for item in semantics.select_semantic_regions(upward, "top")},
            {item.region_id for item in semantics.select_semantic_regions(downward, "bottom")},
        )

    def test_sole_candidate_selects_lowest_downward_region(self):
        detection = semantics.classify_surface_regions(fixtures.pyramid().shape)
        sole = semantics.select_semantic_regions(detection, "sole_candidate")
        bottom = semantics.select_semantic_regions(detection, "bottom")
        self.assertTrue(sole)
        self.assertTrue(set(item.region_id for item in sole).issubset(
            item.region_id for item in bottom
        ))
        self.assertEqual(min(item.position_score for item in sole), 0.0)

    def test_pyramid_roles_are_surface_based(self):
        detection = semantics.classify_surface_regions(fixtures.pyramid().shape)
        side = semantics.select_semantic_regions(detection, "side")
        self.assertEqual(len(side), 4)
        self.assertTrue(all(item.orientation_score < 0.8 for item in side))

    def test_curved_sole_uses_sampled_normals(self):
        detection = semantics.classify_surface_regions(fixtures.curved_sole().shape)
        self.assertTrue(detection.regions)
        self.assertTrue(any(item.surface_types for item in detection.regions))
        self.assertTrue(all(0.0 <= item.position_score <= 1.0 for item in detection.regions))

    def test_parametric_semantic_feature_records_selection(self):
        source = self._source(fixtures.cube().shape)
        preview = semantics.create_semantic_region_contour(source, role="top")
        self.assertEqual(preview.TypeId, "Part::FeaturePython")
        self.assertIs(preview.Source, source)
        self.assertEqual(preview.SurfaceRole, "top")
        self.assertEqual(preview.ContourStatus, "ok")
        self.assertTrue(preview.ResolvedRegionIds)
        self.assertTrue(preview.SemanticRoles)
        self.assertTrue(preview.Shape.Wires)

    def test_source_recompute_updates_semantic_feature(self):
        source = self._source(fixtures.cube().shape)
        preview = semantics.create_semantic_region_contour(source, role="sole_candidate")
        before = preview.Shape.exportBrepToString()
        source.Shape = fixtures.pyramid().shape
        self.doc.recompute()
        self.assertNotEqual(preview.Shape.exportBrepToString(), before)
        self.assertEqual(preview.ContourStatus, "ok")
        self.assertTrue(preview.ResolvedRegionIds)

    def test_input_validation_and_repeatability(self):
        with self.assertRaises(ValueError):
            semantics.classify_surface_regions(fixtures.cube().shape, reference_direction=(0, 0, 0))
        with self.assertRaises(ValueError):
            semantics.classify_surface_regions(fixtures.cube().shape, orientation_tolerance=90)
        with self.assertRaises(ValueError):
            semantics.create_semantic_region_contour(
                self._source(fixtures.cube().shape), role="not-a-role"
            )
        first = semantics.classify_surface_regions(fixtures.cube().shape)
        second = semantics.classify_surface_regions(fixtures.cube().shape)
        self.assertEqual(
            [(item.region_id, item.primary_role) for item in first.regions],
            [(item.region_id, item.primary_role) for item in second.regions],
        )


if __name__ == "__main__":
    unittest.main()
class TestSurfaceSemantics(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SurfaceSemantics")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _source(self, shape):
        source = self.doc.addObject("Part::Feature", "Source")
        source.Shape = shape
        self.doc.recompute()
        return source

    def test_cube_exposes_top_bottom_and_side_roles(self):
        detection = semantics.classify_surface_regions(fixtures.cube().shape)
        top = semantics.select_semantic_regions(detection, "top")
        bottom = semantics.select_semantic_regions(detection, "bottom")
        side = semantics.select_semantic_regions(detection, "side")
        self.assertTrue(top)
        self.assertTrue(bottom)
        self.assertEqual(len(side), 4)
        self.assertTrue(all(item.primary_role == "top" for item in top))
        self.assertTrue(all(item.primary_role == "bottom" for item in bottom))

    def test_reference_direction_changes_roles(self):
        upward = semantics.classify_surface_regions(
            fixtures.cube().shape, reference_direction=App.Vector(0, 0, 1)
        )
        downward = semantics.classify_surface_regions(
            fixtures.cube().shape, reference_direction=App.Vector(0, 0, -1)
        )
        self.assertEqual(
            {item.region_id for item in semantics.select_semantic_regions(upward, "top")},
            {item.region_id for item in semantics.select_semantic_regions(downward, "bottom")},
        )

    def test_sole_candidate_selects_lowest_downward_region(self):
        detection = semantics.classify_surface_regions(fixtures.pyramid().shape)
        sole = semantics.select_semantic_regions(detection, "sole_candidate")
        bottom = semantics.select_semantic_regions(detection, "bottom")
        self.assertTrue(sole)
        self.assertTrue(set(item.region_id for item in sole).issubset(
            item.region_id for item in bottom
        ))
        self.assertEqual(min(item.position_score for item in sole), 0.0)

    def test_pyramid_roles_are_surface_based(self):
        detection = semantics.classify_surface_regions(fixtures.pyramid().shape)
        side = semantics.select_semantic_regions(detection, "side")
        self.assertEqual(len(side), 4)
        self.assertTrue(all(item.orientation_score < 0.8 for item in side))

    def test_curved_sole_uses_sampled_normals(self):
        detection = semantics.classify_surface_regions(fixtures.curved_sole().shape)
        self.assertTrue(detection.regions)
        self.assertTrue(any(item.surface_types for item in detection.regions))
        self.assertTrue(all(0.0 <= item.position_score <= 1.0 for item in detection.regions))

    def test_parametric_semantic_feature_records_selection(self):
        source = self._source(fixtures.cube().shape)
        preview = semantics.create_semantic_region_contour(source, role="top")
        self.assertEqual(preview.TypeId, "Part::FeaturePython")
        self.assertIs(preview.Source, source)
        self.assertEqual(preview.SurfaceRole, "top")
        self.assertEqual(preview.ContourStatus, "ok")
        self.assertTrue(preview.ResolvedRegionIds)
        self.assertTrue(preview.SemanticRoles)
        self.assertTrue(preview.Shape.Wires)

    def test_source_recompute_updates_semantic_feature(self):
        source = self._source(fixtures.cube().shape)
        preview = semantics.create_semantic_region_contour(source, role="sole_candidate")
        before = preview.Shape.exportBrepToString()
        source.Shape = fixtures.pyramid().shape
        self.doc.recompute()
        self.assertNotEqual(preview.Shape.exportBrepToString(), before)
        self.assertEqual(preview.ContourStatus, "ok")
        self.assertTrue(preview.ResolvedRegionIds)

    def test_input_validation_and_repeatability(self):
        with self.assertRaises(ValueError):
            semantics.classify_surface_regions(fixtures.cube().shape, reference_direction=(0, 0, 0))
        with self.assertRaises(ValueError):
            semantics.classify_surface_regions(fixtures.cube().shape, orientation_tolerance=90)
        with self.assertRaises(ValueError):
            semantics.create_semantic_region_contour(
                self._source(fixtures.cube().shape), role="not-a-role"
            )
        first = semantics.classify_surface_regions(fixtures.cube().shape)
        second = semantics.classify_surface_regions(fixtures.cube().shape)
        self.assertEqual(
            [(item.region_id, item.primary_role) for item in first.regions],
            [(item.region_id, item.primary_role) for item in second.regions],
        )


if __name__ == "__main__":
    unittest.main()

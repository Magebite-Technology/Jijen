# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest

import FreeCAD as App
import SurfaceContours as contours
from parttests import surface_contour_fixtures as fixtures


class TestSurfaceContourParametric(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ContourParametric")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _source(self, shape):
        source = self.doc.addObject("Part::Feature", "Source")
        source.Shape = shape
        self.doc.recompute()
        return source

    def test_factory_creates_linked_feature_with_metadata(self):
        source = self._source(fixtures.cube().shape)
        preview = contours.create_parametric_region_contour(source, policy="individual")
        self.assertEqual(preview.TypeId, "Part::FeaturePython")
        self.assertIs(preview.Source, source)
        self.assertEqual(preview.GroupingPolicy, "individual")
        self.assertEqual(preview.ContourStatus, "ok")
        self.assertEqual(preview.ResolvedRegionIds, list(preview.RegionIds))
        self.assertTrue(preview.SourceFaceIndices)
        self.assertTrue(preview.Shape.Wires)

    def test_empty_region_ids_tracks_all_current_regions(self):
        source = self._source(fixtures.pyramid().shape)
        preview = contours.create_parametric_region_contour(source)
        self.assertEqual(preview.RegionIds, [])
        self.assertEqual(len(preview.ResolvedRegionIds), len(source.Shape.Faces))
        self.assertEqual(preview.ContourStatus, "ok")

    def test_selected_region_ids_filter_recomputed_output(self):
        source = self._source(fixtures.cube(True).shape)
        preview = contours.create_parametric_region_contour(
            source, region_ids=["Region1"], policy="coplanar"
        )
        self.assertEqual(preview.ResolvedRegionIds, ["Region1"])
        self.assertEqual(len(preview.SourceFaceIndices), 4)

        preview.GroupingPolicy = "individual"
        self.doc.recompute()
        self.assertEqual(preview.ResolvedRegionIds, ["Region1"])
        self.assertEqual(len(preview.SourceFaceIndices), 1)

    def test_source_change_updates_shape_and_metadata(self):
        source = self._source(fixtures.cube().shape)
        preview = contours.create_parametric_region_contour(
            source, region_ids=["Region1"], policy="individual"
        )
        before = preview.Shape.exportBrepToString()
        source.Shape = fixtures.pyramid().shape
        self.doc.recompute()
        self.assertNotEqual(preview.Shape.exportBrepToString(), before)
        self.assertEqual(preview.ResolvedRegionIds, ["Region1"])
        self.assertEqual(preview.ContourStatus, "ok")

    def test_policy_change_rebuilds_region_partition(self):
        source = self._source(fixtures.cube(True).shape)
        preview = contours.create_parametric_region_contour(source, policy="coplanar")
        grouped_count = len(preview.ResolvedRegionIds)
        preview.GroupingPolicy = "individual"
        self.doc.recompute()
        self.assertLess(grouped_count, len(preview.ResolvedRegionIds))
        self.assertEqual(preview.ContourStatus, "ok")

    def test_missing_source_is_safe_and_diagnostic(self):
        source = self._source(fixtures.cube().shape)
        preview = contours.create_parametric_region_contour(source)
        preview.Source = None
        self.doc.recompute()
        self.assertEqual(preview.ContourStatus, "missing_source")
        self.assertEqual(preview.ResolvedRegionIds, [])
        self.assertTrue(preview.Shape.isNull())

    def test_parametric_factory_requires_document_object_and_preserves_source(self):
        fixture = fixtures.cube()
        with self.assertRaises(TypeError):
            contours.create_parametric_region_contour(fixture.shape)
        source = self._source(fixture.shape)
        before = source.Shape.exportBrepToString()
        contours.create_parametric_region_contour(source)
        self.assertEqual(source.Shape.exportBrepToString(), before)


if __name__ == "__main__":
    unittest.main()

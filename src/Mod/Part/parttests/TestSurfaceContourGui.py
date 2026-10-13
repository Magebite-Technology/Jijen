# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest

import FreeCAD as App
import Part
import SurfaceContourGui as gui
import SurfaceContours as contours
import SurfaceRegions as regions
from parttests import surface_contour_fixtures as fixtures


class TestSurfaceContourGui(unittest.TestCase):
    def test_selection_contract_requires_one_document_object(self):
        self.assertIsNone(gui.selected_document_object([]))
        self.assertIsNone(gui.selected_document_object([object(), object()]))
        self.assertIn("exactly one", gui.selection_message([]))
        self.assertIn("face-by-face", gui.selection_message([object(), object()]))

    def test_selection_contract_accepts_one_document_object(self):
        doc = App.newDocument("ContourGuiSelection")
        try:
            source = doc.addObject("Part::Feature", "Source")
            source.Shape = fixtures.cube().shape
            self.assertIs(gui.selected_document_object([source]), source)
            self.assertEqual(gui.selection_message([source]), "")
        finally:
            App.closeDocument(doc.Name)

    def test_single_region_preview_creates_metadata_and_link(self):
        doc = App.newDocument("ContourGuiPreview")
        try:
            source = doc.addObject("Part::Feature", "Source")
            source.Shape = fixtures.cube(True).shape
            detection = regions.detect_surface_regions(source)
            results = contours.extract_region_contours(source, detection)
            returned, created = contours.create_region_contour_preview(source, results[:1])
            self.assertEqual(returned, results[:1])
            self.assertEqual(len(created), 1)
            preview = created[0]
            self.assertEqual(preview.SourceRegionId, results[0].region_id)
            self.assertEqual(preview.ComponentId, results[0].component_id)
            self.assertEqual(preview.SourceFaceIndices, list(results[0].face_indices))
            self.assertIs(preview.Source, source)
            self.assertEqual(len(preview.Shape.Wires), len(results[0].wires))
        finally:
            App.closeDocument(doc.Name)

    def test_all_region_previews_are_separate_objects(self):
        doc = App.newDocument("ContourGuiAllPreview")
        try:
            source = doc.addObject("Part::Feature", "Source")
            source.Shape = fixtures.pyramid().shape
            results = contours.extract_region_contours(source)
            _, created = contours.create_region_contour_preview(source, results)
            self.assertEqual(len(created), len(results))
            self.assertEqual(
                [obj.SourceRegionId for obj in created],
                [result.region_id for result in results],
            )
        finally:
            App.closeDocument(doc.Name)

    def test_preview_does_not_modify_source_or_create_for_empty_boundary(self):
        doc = App.newDocument("ContourGuiReadOnly")
        try:
            source = doc.addObject("Part::Feature", "Source")
            source.Shape = Part.makeTorus(20, 5)
            before = source.Shape.exportBrepToString()
            results = contours.extract_region_contours(source)
            _, created = contours.create_region_contour_preview(source, results)
            self.assertFalse(created)
            self.assertEqual(source.Shape.exportBrepToString(), before)
            self.assertEqual(len(doc.Objects), 1)
        finally:
            App.closeDocument(doc.Name)

    def test_preview_validates_raw_shape_output_document(self):
        shape = fixtures.cube().shape
        results = contours.extract_region_contours(shape)
        with self.assertRaises(ValueError):
            contours.create_region_contour_preview(shape, results[:1])


if __name__ == "__main__":
    unittest.main()

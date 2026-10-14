# SPDX-License-Identifier: LGPL-2.1-or-later
import math
import unittest

import FreeCAD as App
import Part
import SurfaceContours as contours
from parttests import surface_contour_fixtures as fixtures


class TestSurfaceContours(unittest.TestCase):
    def test_cancel_detection_restores_progress_scope(self):
        import SurfaceRegions
        calls = []

        def cancel(stage, completed, total):
            calls.append(stage)
            if len(calls) == 20:
                raise contours.ContourCancelled()

        shape = fixtures.cube(True).shape
        before = shape.exportBrepToString()
        with self.assertRaises(contours.ContourCancelled):
            with contours.contour_operation(cancel):
                SurfaceRegions.detect_surface_regions(shape)
        self.assertEqual(len(calls), 20)
        self.assertEqual(shape.exportBrepToString(), before)
        self.assertEqual(len(SurfaceRegions.detect_surface_regions(shape).regions), 6)
        self.assertEqual(len(calls), 20)

    def test_cancel_extraction_and_classification_is_not_geometry_error(self):
        import SurfaceSemantics

        import SurfaceRegions
        shape = fixtures.cube(True).shape
        detection = SurfaceRegions.detect_surface_regions(shape)
        for operation in (contours.extract_region_contours,
                          SurfaceSemantics.classify_surface_regions):
            calls = []

            def cancel(stage, completed, total):
                calls.append(stage)
                if len(calls) == 30:
                    raise contours.ContourCancelled()

            with self.subTest(operation=operation.__name__):
                with self.assertRaises(contours.ContourCancelled):
                    with contours.contour_operation(cancel):
                        operation(shape, detection)
                self.assertEqual(len(calls), 30)

    def test_cancel_preview_rolls_back_document_transaction(self):
        import SurfaceSemantics

        doc = App.newDocument("ContourCancellation")
        try:
            source = doc.addObject("Part::Feature", "Source")
            source.Shape = fixtures.cube().shape
            doc.recompute()

            def cancel(stage, completed, total):
                if stage == "Finishing preview":
                    raise contours.ContourCancelled()

            for factory in (contours.create_parametric_region_contour,
                            SurfaceSemantics.create_semantic_region_contour):
                with self.subTest(factory=factory.__name__):
                    with self.assertRaises(contours.ContourCancelled):
                        with contours.contour_operation(cancel):
                            factory(source)
                    self.assertEqual([obj.Name for obj in doc.Objects], [source.Name])
            preview = contours.create_parametric_region_contour(source)
            self.assertEqual(preview.ContourStatus, "ok", preview.LastError)
        finally:
            App.closeDocument(doc.Name)

    def assertLoops(self, shape, counts):
        results = contours.extract_face_contours(shape)
        self.assertEqual(len(results), len(counts))
        for result, count in zip(results, counts):
            self.assertEqual(result.status, "ok" if count else "no_boundary", result.diagnostics)
            self.assertEqual(len(result.wires), count)
            for wire in result.wires:
                self.assertTrue(wire.isClosed())
                self.assertTrue(wire.isValid())
                for edge in wire.Edges:
                    for point in edge.discretize(Number=9):
                        self.assertLess(
                            Part.Vertex(point).distToShape(shape.Faces[result.face_index])[0], 1e-6
                        )
        return results

    def test_cube_and_pyramid(self):
        results = self.assertLoops(fixtures.cube().shape, [1] * 6)
        for result in results:
            self.assertAlmostEqual(result.wires[0].Length, 80)
            self.assertEqual(len(result.wires[0].Edges), 4)
        pyramid = fixtures.pyramid()
        results = self.assertLoops(pyramid.shape, [1] * 5)
        for result, region in zip(results, pyramid.regions):
            self.assertAlmostEqual(result.wires[0].Length, region.boundaries[0].Length)

    def test_subdivided_cube_stays_individual(self):
        results = self.assertLoops(fixtures.cube(True).shape, [1] * 24)
        for result in results:
            self.assertAlmostEqual(result.wires[0].Length, 40)

    def test_hole_and_native_circles(self):
        result = self.assertLoops(fixtures.annulus().shape, [2])[0]
        self.assertEqual(len(result.wires[0].Edges), 1)
        self.assertEqual(len(result.wires[1].Edges), 1)
        lengths = sorted(w.Length for w in result.wires)
        self.assertAlmostEqual(lengths[0], 16 * math.pi)
        self.assertAlmostEqual(lengths[1], 40 * math.pi)
        self.assertTrue(all(isinstance(w.Edges[0].Curve, Part.Circle) for w in result.wires))

    def test_periodic_seams_and_degenerate_poles(self):
        cylinder = fixtures.cylinder()
        results = self.assertLoops(cylinder.shape, [len(r.boundaries) for r in cylinder.regions])
        for result in results:
            for wire in result.wires:
                self.assertAlmostEqual(wire.Length, 20 * math.pi)
                self.assertEqual(len(wire.Edges), 1)
        self.assertLoops(fixtures.sphere().shape, [0])
        self.assertLoops(Part.makeTorus(20, 5), [0])
        cone = Part.makeCone(10, 0, 20)
        self.assertLoops(cone, [1] * len(cone.Faces))

    def test_curved_spline_boundaries(self):
        sole = fixtures.curved_sole()
        results = self.assertLoops(sole.shape, [1] * 7)
        for index in sole.regions[0].face_indices:
            wire = results[index].wires[0]
            self.assertGreater(wire.BoundBox.ZLength, 1)
            self.assertTrue(any(isinstance(e.Curve, Part.BSplineCurve) for e in wire.Edges))

    def test_reversed_faces_and_small_features(self):
        shape = fixtures.annulus().shape.copy()
        shape.reverse()
        self.assertLoops(shape, [2])
        results = self.assertLoops(Part.makeBox(0.001, 0.001, 0.001), [1] * 6)
        for result in results:
            self.assertAlmostEqual(result.wires[0].Length, 0.004)

    def test_extraction_is_read_only_and_has_no_gui_dependency(self):
        shape = fixtures.cube().shape
        before = shape.exportBrepToString()
        documents = set(App.listDocuments())
        contours.extract_face_contours(shape)
        self.assertEqual(shape.exportBrepToString(), before)
        self.assertEqual(set(App.listDocuments()), documents)

    def test_input_diagnostics(self):
        for source, status in (
            (None, "unsupported_input"),
            (Part.Shape(), "null_shape"),
            (Part.makeLine(App.Vector(), App.Vector(1, 0, 0)), "unsupported_input"),
        ):
            with self.subTest(status=status):
                with self.assertRaises(contours.ContourInputError) as caught:
                    contours.extract_face_contours(source)
                self.assertEqual(caught.exception.status, status)

    def test_broken_boundary_is_not_healed(self):
        edges = Part.makePolygon([App.Vector(), App.Vector(2, 0, 0), App.Vector(2, 2, 0)]).Edges
        wires, status, diagnostics = contours._assemble_wires(edges)
        self.assertEqual(status, "open_boundary")
        self.assertTrue(diagnostics)
        self.assertEqual(len(wires), 1)
        self.assertEqual(len(wires[0].Edges), 2)
        self.assertFalse(wires[0].isClosed())
        # Coincident endpoints on independently constructed edges are not sewn.
        edges = [
            Part.makeLine(App.Vector(), App.Vector(1, 0, 0)),
            Part.makeLine(App.Vector(1, 0, 0), App.Vector(1, 1, 0)),
        ]
        wires, status, _ = contours._assemble_wires(edges)
        self.assertEqual(status, "open_boundary")
        self.assertEqual(len(wires), 2)

    def test_branching_boundary_is_rejected(self):
        edge = Part.makeLine(App.Vector(), App.Vector(1, 0, 0))
        wires, status, diagnostics = contours._assemble_wires([edge, edge, edge])
        self.assertEqual(status, "non_manifold")
        self.assertFalse(wires)
        self.assertTrue(diagnostics)

    def test_disconnected_components_keep_all_face_results(self):
        self.assertLoops(fixtures.disconnected_cubes().shape, [1] * 12)

    def test_invalid_face_does_not_hide_other_results(self):
        points = [
            App.Vector(0, 0, 0),
            App.Vector(2, 2, 0),
            App.Vector(0, 2, 0),
            App.Vector(2, 0, 0),
            App.Vector(0, 0, 0),
        ]
        invalid = Part.Face(Part.makePolygon(points))
        self.assertFalse(invalid.isValid())
        shape = Part.makeCompound([Part.makeBox(20, 20, 20), invalid])
        results = contours.extract_face_contours(shape)
        self.assertEqual(len(results), 7)
        self.assertTrue(all(r.status == "ok" for r in results[:6]))
        self.assertEqual(results[6].status, "invalid_geometry")
        self.assertTrue(results[6].diagnostics)

    def test_preview_transaction_undo(self):
        doc = App.newDocument("SurfaceContoursUndoTest")
        doc.UndoMode = 1
        try:
            source = doc.addObject("Part::Feature", "Source")
            source.Shape = Part.makeBox(20, 20, 20)
            doc.recompute()
            results, created = contours.create_contour_preview(source)
            self.assertEqual(len(created), 6)
            self.assertEqual(len(results), 6)
            self.assertEqual(len(doc.Objects), 7)
            doc.undo()
            self.assertEqual(len(doc.Objects), 1)
            self.assertEqual(doc.Objects[0].Name, source.Name)
        finally:
            App.closeDocument(doc.Name)

    def test_object_placement_link_and_preview(self):
        doc = App.newDocument("SurfaceContoursTest")
        try:
            source = doc.addObject("Part::Feature", "Source")
            source.Shape = Part.makeBox(20, 20, 20)
            source.Placement = App.Placement(
                App.Vector(100, 30, 5), App.Rotation(App.Vector(1, 1, 1), 37)
            )
            link = doc.addObject("App::Link", "Link")
            link.setLink(source)
            link.LinkPlacement = App.Placement(
                App.Vector(200, 0, 0), App.Rotation(App.Vector(0, 0, 1), 20)
            )
            doc.recompute()
            for obj in (source, link):
                expected = Part.getShape(obj)
                results, created = contours.create_contour_preview(obj, [0])
                self.assertEqual(len(results), 6)
                self.assertEqual(len(created), 1)
                self.assertEqual(created[0].Source, obj)
                wire = created[0].Shape.Wires[0]
                self.assertAlmostEqual(wire.Length, 80)
                for edge in wire.Edges:
                    for point in edge.discretize(Number=5):
                        self.assertLess(Part.Vertex(point).distToShape(expected.Faces[0])[0], 1e-6)
            before = len(doc.Objects)
            with self.assertRaises(ValueError):
                contours.create_contour_preview(source, [-1])
            self.assertEqual(len(doc.Objects), before)
            sphere = Part.makeSphere(10)
            results, created = contours.create_contour_preview(sphere, document=doc)
            self.assertEqual(results[0].status, "no_boundary")
            self.assertFalse(created)
            self.assertEqual(len(doc.Objects), before)
        finally:
            App.closeDocument(doc.Name)

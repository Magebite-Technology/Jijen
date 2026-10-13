# SPDX-License-Identifier: LGPL-2.1-or-later
import math
import unittest

import FreeCAD as App
import Part
import SurfaceRegions as regions
from SurfaceContours import ContourInputError
from parttests import surface_contour_fixtures as fixtures


class TestSurfaceRegions(unittest.TestCase):
    def assertPartition(self, shape, expected, **settings):
        result = regions.detect_surface_regions(shape, **settings)
        actual = [r.face_indices for r in result.regions]
        self.assertEqual(sorted(i for group in actual for i in group), list(range(len(shape.Faces))))
        self.assertEqual(set(actual), {tuple(sorted(group)) for group in expected})
        self.assertTrue(all(r.status == "ok" for r in result.regions))
        return result

    def test_cube_and_pyramid(self):
        for fixture in (fixtures.cube(), fixtures.pyramid()):
            self.assertPartition(fixture.shape, [r.face_indices for r in fixture.regions])

    def test_subdivided_cube_has_six_regions(self):
        fixture = fixtures.cube(True)
        result = self.assertPartition(fixture.shape, [r.face_indices for r in fixture.regions])
        self.assertEqual(len(result.regions), 6)
        self.assertTrue(all(len(r.face_indices) == 4 for r in result.regions))
        self.assertTrue(result.adjacency)

    def test_individual_policy_keeps_all_faces(self):
        shape = fixtures.cube(True).shape
        result = self.assertPartition(shape, [(i,) for i in range(24)], policy="individual")
        self.assertEqual(result.settings.policy, "individual")

    def test_disconnected_and_touching_solids(self):
        for offset in (0, 20, 40):
            a, b = Part.makeBox(20, 20, 20), Part.makeBox(20, 20, 20)
            b.translate(App.Vector(offset, 0, 0))
            shape = Part.makeCompound([a, b])
            result = self.assertPartition(shape, [(i,) for i in range(12)])
            self.assertEqual(len({r.component_id for r in result.regions}), 2)

    def test_curved_and_periodic_faces_are_not_guessed(self):
        for fixture in (fixtures.curved_sole(), fixtures.cylinder(), fixtures.sphere(), fixtures.annulus()):
            shape = fixture.shape
            self.assertPartition(shape, [(i,) for i in range(len(shape.Faces))])

    def test_same_component_requires_native_shared_edges(self):
        # A shell container alone cannot make a gap into native adjacency.
        a = Part.makePlane(10, 10)
        b = Part.makePlane(10, 10, App.Vector(10.001, 0, 0))
        shape = Part.makeShell([a, b])
        result = self.assertPartition(shape, [(0,), (1,)])
        self.assertFalse(result.adjacency)
        # The kernel sews genuinely touching faces; detection can then merge.
        shape = Part.makeShell([a, Part.makePlane(10, 10, App.Vector(10, 0, 0))])
        self.assertPartition(shape, [(0, 1)])

    def test_component_barrier_even_with_shared_edge_identity(self):
        shape = Part.makeShell([Part.makePlane(10, 10), Part.makePlane(10, 10, App.Vector(10, 0, 0))])
        shape.sewShape()
        separate = Part.makeCompound(shape.Faces)
        result = self.assertPartition(separate, [(0,), (1,)])
        self.assertFalse(result.adjacency)

    def test_opposite_orientation_is_not_merged(self):
        shape = Part.makeShell([Part.makePlane(10, 10), Part.makePlane(10, 10, App.Vector(10, 0, 0))])
        shape.sewShape()
        faces = shape.Faces
        faces[1].reverse()
        self.assertPartition(Part.makeShell(faces), [(0,), (1,)])

    def test_plane_distance_and_angle_both_checked(self):
        n = App.Vector(0, 0, 1)
        settings = regions.DetectionSettings(angle_tolerance=0.01, distance_tolerance=0.0001)
        first = (App.Vector(), n)
        self.assertTrue(regions._coplanar(first, (App.Vector(100, 0, 0), n), settings))
        self.assertFalse(regions._coplanar(first, (App.Vector(0, 0, 0.001), n), settings))
        tilted = App.Rotation(App.Vector(1, 0, 0), 0.02).multVec(n)
        self.assertFalse(regions._coplanar(first, (App.Vector(), tilted), settings))
        self.assertFalse(regions._coplanar(first, (App.Vector(), -n), settings))

    def test_tolerance_chains_do_not_accumulate(self):
        faces = []
        z = 0.0
        for i, angle in enumerate((0, 0.00006, 0.00012)):
            next_z = z + math.tan(math.radians(angle))
            points = [App.Vector(i, 0, z), App.Vector(i + 1, 0, next_z),
                      App.Vector(i + 1, 1, next_z), App.Vector(i, 1, z)]
            faces.append(Part.Face(Part.makePolygon(points + [points[0]])))
            z = next_z
        shape = Part.makeShell(faces)
        shape.sewShape()
        result = regions.detect_surface_regions(shape, angle_tolerance=0.0001, distance_tolerance=1)
        self.assertEqual(sorted(len(r.face_indices) for r in result.regions), [1, 2])

    def test_invalid_settings_are_rejected(self):
        for name in ("angle_tolerance", "distance_tolerance"):
            for value in (0, -1, math.nan, math.inf, -math.inf, True, "1", None):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        regions.detect_surface_regions(Part.makeBox(1, 1, 1), **{name: value})
        for value in (90, 180):
            with self.assertRaises(ValueError):
                regions.DetectionSettings(angle_tolerance=value)
        with self.assertRaises(ValueError):
            regions.detect_surface_regions(Part.makeBox(1, 1, 1), policy="smooth")

    def test_invalid_input_and_face_are_isolated(self):
        with self.assertRaises(ContourInputError):
            regions.detect_surface_regions(Part.Shape())
        points = [App.Vector(0, 0, 0), App.Vector(2, 2, 0), App.Vector(0, 2, 0),
                  App.Vector(2, 0, 0), App.Vector(0, 0, 0)]
        invalid = Part.Face(Part.makePolygon(points))
        shape = Part.makeCompound([Part.makeBox(1, 1, 1), invalid])
        result = regions.detect_surface_regions(shape)
        self.assertEqual(len(result.regions), 7)
        self.assertTrue(all(r.status == "ok" for r in result.regions[:6]))
        self.assertEqual(result.regions[6].status, "invalid_geometry")
        self.assertTrue(result.regions[6].diagnostics)

    def test_non_manifold_edges_are_diagnosed(self):
        points = [[(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)],
                  [(10, 0, 0), (0, 0, 0), (0, -10, 0), (10, -10, 0)],
                  [(0, 0, 0), (10, 0, 0), (10, 0, 10), (0, 0, 10)]]
        faces = []
        for coords in points:
            vertices = [App.Vector(*p) for p in coords]
            faces.append(Part.Face(Part.makePolygon(vertices + [vertices[0]])))
        # GeneralFuse supplies an actual common native edge with three faces.
        shape = faces[0].generalFuse(faces[1:])[0]
        result = regions.detect_surface_regions(shape)
        self.assertEqual(len(result.regions), 3)
        self.assertTrue(all(r.status == "non_manifold" for r in result.regions))
        self.assertTrue(all(r.diagnostics for r in result.regions))

    def test_rotations_scale_and_read_only(self):
        for scale in (0.001, 1, 1000):
            fixture = fixtures.cube(True)
            shape = fixture.shape
            shape.scale(scale)
            shape.Placement = App.Placement(App.Vector(70, 30, 5), App.Rotation(App.Vector(1, 2, 3), 37))
            before = shape.exportBrepToString()
            documents = set(App.listDocuments())
            result = self.assertPartition(shape, [r.face_indices for r in fixture.regions])
            self.assertEqual(shape.exportBrepToString(), before)
            self.assertEqual(set(App.listDocuments()), documents)
            self.assertEqual(result, regions.detect_surface_regions(shape))

    def test_object_and_link_match_resolved_shape(self):
        doc = App.newDocument("SurfaceRegionTest")
        try:
            source = doc.addObject("Part::Feature", "Source")
            source.Shape = fixtures.cube(True).shape
            source.Placement = App.Placement(App.Vector(10, 20, 30), App.Rotation(App.Vector(1, 1, 0), 42))
            link = doc.addObject("App::Link", "Link")
            link.setLink(source)
            link.LinkPlacement.Base = App.Vector(100, 0, 0)
            doc.recompute()
            for obj in (source, link):
                self.assertEqual(regions.detect_surface_regions(obj), regions.detect_surface_regions(Part.getShape(obj)))
            self.assertEqual(len(doc.Objects), 2)
        finally:
            App.closeDocument(doc.Name)

    def test_region_metadata_and_adjacency(self):
        result = regions.detect_surface_regions(fixtures.cube(True).shape)
        self.assertEqual([r.region_id for r in result.regions], ["Region%d" % i for i in range(1, 7)])
        self.assertTrue(all(r.component_id == "Component1" for r in result.regions))
        self.assertEqual(result.settings, regions.DetectionSettings())
        for region in result.regions:
            self.assertEqual(region.face_names, tuple("Face%d" % (i + 1) for i in region.face_indices))
            visited = {region.face_indices[0]}
            while True:
                new = {b for a, b in result.adjacency if a in visited and b in region.face_indices}
                new |= {a for a, b in result.adjacency if b in visited and a in region.face_indices}
                if new <= visited:
                    break
                visited |= new
            self.assertEqual(visited, set(region.face_indices))

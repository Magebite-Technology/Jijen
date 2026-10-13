# SPDX-License-Identifier: LGPL-2.1-or-later
"""Labelled geometry for the surface-contour contract; no detection algorithm.

Run create_document() from the FreeCAD Python console to inspect the fixtures.
Lengths are millimetres. Face indices are zero-based and fixture-local.
"""

from dataclasses import dataclass

import FreeCAD as App
import Part


@dataclass
class Region:
    name: str
    face_indices: tuple
    boundaries: tuple


@dataclass
class Fixture:
    name: str
    shape: object
    regions: tuple


def _face(points):
    return Part.Face(Part.makePolygon(points + [points[0]]))


def _labelled_shell(name, faces, groups, solid=False):
    """Sew fixture patches, then recover labels from their known geometry.

    This matching only annotates fixtures; it is not region detection or a
    persistent reference scheme. Every input face must match exactly once.
    """
    shape = Part.makeShell(faces)
    shape.sewShape()
    if solid:
        shape = Part.makeSolid(shape)
    indices = {}
    for i, original in enumerate(faces):
        matches = [
            j for j, actual in enumerate(shape.Faces)
            if original.CenterOfMass.distanceToPoint(actual.CenterOfMass) < 1e-7
            and abs(original.Area - actual.Area) < 1e-7
        ]
        if len(matches) != 1:
            raise RuntimeError("Fixture face label is not unique")
        indices[i] = matches[0]
    return Fixture(name, shape, tuple(
        Region(label, tuple(indices[i] for i in members), tuple(boundaries))
        for label, members, boundaries in groups
    ))


def cube(subdivided=False):
    original = Part.makeBox(20, 20, 20)
    if not subdivided:
        return Fixture("Cube", original, tuple(
            Region("Side%d" % (i + 1), (i,), (f.OuterWire,))
            for i, f in enumerate(original.Faces)
        ))
    faces, groups = [], []
    for i, face in enumerate(original.Faces):
        u0, u1, v0, v1 = face.ParameterRange
        members = []
        for a in range(2):
            for b in range(2):
                points = [face.valueAt(
                    u0 + (u1 - u0) * u / 2,
                    v0 + (v1 - v0) * v / 2,
                ) for u, v in [(a, b), (a + 1, b), (a + 1, b + 1), (a, b + 1)]]
                patch = _face(points)
                if patch.normalAt(0, 0).dot(face.normalAt(u0, v0)) < 0:
                    patch.reverse()
                members.append(len(faces))
                faces.append(patch)
        groups.append(("Side%d" % (i + 1), members, [face.OuterWire]))
    return _labelled_shell("SubdividedCube", faces, groups, solid=True)


def pyramid():
    corners = [App.Vector(0, 0, 0), App.Vector(20, 0, 0),
               App.Vector(20, 20, 0), App.Vector(0, 20, 0)]
    apex = App.Vector(10, 10, 20)
    faces = [_face(list(reversed(corners)))]
    faces.extend(_face([corners[i], corners[(i + 1) % 4], apex]) for i in range(4))
    groups = [("Base" if i == 0 else "Slope%d" % i, [i], [f.OuterWire])
              for i, f in enumerate(faces)]
    return _labelled_shell("SquarePyramid", faces, groups, solid=True)


def cylinder():
    shape = Part.makeCylinder(10, 20)
    return Fixture("Cylinder", shape, tuple(
        Region("Wall" if isinstance(f.Surface, Part.Cylinder) else "Cap%d" % i,
               (i,), tuple(w for w in f.Wires) if not isinstance(f.Surface, Part.Cylinder)
               else tuple(Part.Wire([Part.makeCircle(10, App.Vector(0, 0, z))])
                          for z in (0, 20)))
        for i, f in enumerate(shape.Faces)
    ))


def sphere():
    shape = Part.makeSphere(10)
    return Fixture("Sphere", shape, (Region("ClosedSurface", (0,), ()),))


def annulus():
    outer = Part.Wire([Part.makeCircle(20)])
    inner = Part.Wire([Part.makeCircle(8)])
    shape = Part.Face(outer).cut(Part.Face(inner))
    return Fixture("Annulus", shape, (Region("Ring", (0,), (outer, inner)),))


def curved_sole():
    """Synthetic sole-like shell with a warped upper region split into patches.

    Deliberately constructed labels are an oracle, not evidence that a real
    footwear model can be segmented automatically.
    """
    points = []
    for i in range(5):
        x = i * 60.0
        width = (18, 25, 17, 29, 20)[i]
        points.append([App.Vector(x, (j - 2) * width / 2,
                                  12 + 0.0002 * x * x + 1.5 * (j - 2) ** 2)
                       for j in range(5)])
    surface = Part.BSplineSurface()
    surface.interpolate(points)
    upper = surface.toShape()
    u0, u1, v0, v1 = upper.ParameterRange
    patches = []
    for lo, hi in ((u0, (u0 + u1) / 2), ((u0 + u1) / 2, u1)):
        section = surface.copy()
        section.segment(lo, hi, v0, v1)
        patches.append(section.toShape())
    lower = upper.copy()
    lower.translate(App.Vector(0, 0, -8))
    walls = [Part.makeRuledSurface(a, b) for a, b in zip(upper.Edges, lower.Edges)]
    lower.reverse()
    faces = patches + [lower] + walls
    groups = [("Upper", [0, 1], [upper.OuterWire]),
              ("Lower", [2], [lower.OuterWire]),
              ("PerimeterWall", list(range(3, len(faces))),
               [upper.OuterWire, lower.OuterWire])]
    return _labelled_shell("SyntheticCurvedSole", faces, groups)


def disconnected_cubes():
    first = cube()
    second = cube()
    second.shape.translate(App.Vector(40, 0, 0))
    shape = Part.makeCompound([first.shape, second.shape])
    return Fixture("DisconnectedCubes", shape, tuple(
        Region("Component%dSide%d" % (i // 6 + 1, i % 6 + 1), (i,), (f.OuterWire,))
        for i, f in enumerate(shape.Faces)
    ))


def all_fixtures():
    return [cube(), pyramid(), cube(True), cylinder(), sphere(), annulus(),
            curved_sole(), disconnected_cubes()]


def create_document():
    """Create a new document without changing any existing document.

    Source objects are spaced apart; expected wires are hidden by default.
    Show a region's oracle object in the tree to inspect its expected boundary.
    """
    doc = App.newDocument("SurfaceContourFixtures")
    for i, fixture in enumerate(all_fixtures()):
        group = doc.addObject("App::DocumentObjectGroup", fixture.name)
        source = doc.addObject("Part::Feature", fixture.name + "Source")
        source.Shape = fixture.shape
        source.Placement.Base = App.Vector((i % 3) * 300, (i // 3) * 100, 0)
        group.addObject(source)
        for region in fixture.regions:
            oracle = doc.addObject("Part::Feature", fixture.name + region.name)
            oracle.Label = region.name + " (expected contour)"
            oracle.Shape = Part.makeCompound(list(region.boundaries))
            oracle.Placement = source.Placement
            oracle.addProperty("App::PropertyIntegerList", "SourceFaceIndices")
            oracle.SourceFaceIndices = list(region.face_indices)
            group.addObject(oracle)
            if App.GuiUp:
                oracle.ViewObject.Visibility = False
        if App.GuiUp:
            source.ViewObject.ShapeColor = (0.78, 0.80, 0.84)
    doc.recompute()
    return doc

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Physical 3D boundaries of individual BRep faces.

Extraction is read-only and independent of the GUI/camera. A seam is a
parameterisation cut, not a physical boundary. Region grouping is Phase 3.
"""

from dataclasses import dataclass

import FreeCAD as App
import Part


class ContourInputError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class FaceContour:
    """face_index is zero-based and valid only for this source revision."""

    face_index: int
    status: str
    wires: tuple = ()
    diagnostics: tuple = ()

    @property
    def face_name(self):
        return "Face%d" % (self.face_index + 1)


def _resolve_shape(source):
    if isinstance(source, Part.Shape):
        shape = source
    elif isinstance(source, App.DocumentObject):
        try:
            # The kernel composes object/link placement. Do not apply it again.
            shape = Part.getShape(source, needSubElement=False, transform=True)
        except Exception as error:
            raise ContourInputError("unsupported_input", str(error)) from error
    else:
        raise ContourInputError("unsupported_input", "Select a Part BRep object or shape")
    if shape.isNull():
        raise ContourInputError("null_shape", "The selected object has no resolved shape")
    if not shape.Faces:
        raise ContourInputError("unsupported_input", "The shape contains no faces")
    return shape


def _assemble_wires(edges):
    """Walk exact topological connections, preserving curves and all edges.

    Geometrically coincident but distinct vertices are never merged. Closed
    single-edge curves contribute two incidences to the same vertex.
    """
    vertices, ends, adjacency = [], [], []

    def vertex_id(vertex):
        for i, existing in enumerate(vertices):
            if vertex.isSame(existing):
                return i
        vertices.append(vertex)
        adjacency.append([])
        return len(vertices) - 1

    for i, edge in enumerate(edges):
        first, last = edge.firstVertex(True), edge.lastVertex(True)
        if first.isNull() or last.isNull():
            return (), "invalid_geometry", ("Boundary edge has no endpoint topology",)
        a, b = vertex_id(first), vertex_id(last)
        ends.append((a, b))
        adjacency[a].append(i)
        adjacency[b].append(i)
    if any(len(incident) > 2 for incident in adjacency):
        return (), "non_manifold", ("Boundary branches at a shared vertex",)

    unused = set(range(len(edges)))
    wires = []
    while unused:
        # Prefer an open endpoint so a broken chain is returned in full.
        seed = min(unused)
        component = {seed}
        pending = [seed]
        while pending:
            current = pending.pop()
            for vertex in ends[current]:
                for neighbour in adjacency[vertex]:
                    if neighbour in unused and neighbour not in component:
                        component.add(neighbour)
                        pending.append(neighbour)
        start = next(
            (v for i in sorted(component) for v in ends[i] if len(adjacency[v]) == 1), ends[seed][0]
        )
        current, ordered = start, []
        while True:
            following = next((i for i in adjacency[current] if i in unused), None)
            if following is None:
                break
            a, b = ends[following]
            edge = edges[following].copy()
            if current == b and a != b:
                edge.reverse()
            ordered.append(edge)
            unused.remove(following)
            current = b if current == a else a
        wire = Part.Wire(ordered)
        if not wire.isValid():
            return tuple(wires), "invalid_geometry", ("Kernel rejected an assembled wire",)
        wires.append(wire)
    if any(not wire.isClosed() for wire in wires):
        return (
            tuple(wires),
            "open_boundary",
            ("Boundary contains an open chain; no healing applied",),
        )
    return tuple(wires), "ok", ()


def _extract_face(face, index):
    try:
        if not face.isValid():
            return FaceContour(index, "invalid_geometry", diagnostics=("Invalid source face",))
        edges = []
        for wire in face.Wires:
            for edge in wire.OrderedEdges:
                if edge.Degenerated or edge.isSeam(face):
                    continue
                if any(edge.isSame(existing) for existing in edges):
                    return FaceContour(
                        index,
                        "non_manifold",
                        diagnostics=("A non-seam edge occurs more than once on this face",),
                    )
                edges.append(edge)
        if not edges:
            return FaceContour(index, "no_boundary")
        wires, status, diagnostics = _assemble_wires(edges)
        return FaceContour(index, status, wires, diagnostics)
    except Exception as error:
        return FaceContour(index, "invalid_geometry", diagnostics=(str(error),))


def extract_face_contours(source):
    """Return one FaceContour per face, including valid empty/failed results.

    Accept a shape or document object (including a link) and return native
    Part.Wire objects in resolved coordinates. Input errors raise
    ContourInputError; face errors remain attached to the corresponding result.
    No document objects are created and the source is not modified.
    """
    shape = _resolve_shape(source)
    return tuple(_extract_face(face, i) for i, face in enumerate(shape.Faces))


def create_contour_preview(source, face_indices=None, document=None):
    """Create static previews for successful faces in an explicit document.

    Returns (all extraction results, created objects). The source document is
    used when source is a document object; raw shapes require document=.
    Previews are snapshots, not parametric recompute features (Phase 6).
    """
    results = extract_face_contours(source)
    selected = set(range(len(results))) if face_indices is None else set(face_indices)
    if any(type(i) is not int or i < 0 or i >= len(results) for i in selected):
        raise ValueError("Face indices must be integers within the source face range")
    if document is None and isinstance(source, App.DocumentObject):
        document = source.Document
    if document is None:
        raise ValueError("An output document is required for a raw shape")
    if not isinstance(document, App.Document):
        raise TypeError("Output document must be a FreeCAD document")
    pending = [r for r in results if r.face_index in selected and r.status == "ok"]
    if not pending:
        return results, ()
    created = []
    document.openTransaction("Preview individual face contours")
    try:
        for result in pending:
            obj = document.addObject("Part::Feature", "FaceContour")
            obj.Label = result.face_name + " contour"
            obj.Shape = Part.makeCompound(list(result.wires))
            obj.addProperty("App::PropertyInteger", "SourceFaceIndex", "Contour")
            obj.SourceFaceIndex = result.face_index
            obj.addProperty("App::PropertyString", "ContourStatus", "Contour")
            obj.ContourStatus = result.status
            if isinstance(source, App.DocumentObject) and source.Document is document:
                obj.addProperty("App::PropertyLink", "Source", "Contour")
                obj.Source = source
            if App.GuiUp:
                obj.ViewObject.LineColor = (0.1, 0.55, 1.0)
                obj.ViewObject.LineWidth = 3.0
            created.append(obj)
        document.recompute()
        document.commitTransaction()
    except Exception:
        document.abortTransaction()
        raise
    return results, tuple(created)

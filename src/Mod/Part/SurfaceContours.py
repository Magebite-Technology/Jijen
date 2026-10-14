# SPDX-License-Identifier: LGPL-2.1-or-later
"""Physical 3D boundaries of individual BRep faces.

Extraction is read-only and independent of the GUI/camera. A seam is a
parameterisation cut, not a physical boundary. Region grouping is Phase 3.
"""

from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar

import FreeCAD as App
import Part


class ContourCancelled(Exception):
    """An interactive contour operation was cancelled at a safe checkpoint."""


_progress_callback = ContextVar("surface_contour_progress", default=None)


@contextmanager
def contour_operation(callback):
    """Scope progress/cancellation to one operation; restore even on failure.

    Core geometry remains GUI-independent. Callbacks may raise ContourCancelled.
    Interactive callers must prevent document edits while pumping GUI events.
    """
    token = _progress_callback.set(callback)
    try:
        _checkpoint("Reading geometry")
        yield
    finally:
        _progress_callback.reset(token)


def _checkpoint(stage, completed=None, total=None):
    callback = _progress_callback.get()
    if callback is not None:
        callback(stage, completed, total)


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
            shape = getattr(source, "Shape", None)
            if shape is None or shape.isNull():
                shape = Part.getShape(
                    source, needSubElement=False, transform=True
                )
        except ContourCancelled:
            raise
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
    vertex_index = _NativeShapeIndex()
    ends, adjacency = [], []

    def vertex_id(vertex):
        index = vertex_index.add(vertex)
        if index == len(adjacency):
            adjacency.append([])
        return index

    for i, edge in enumerate(edges):
        _checkpoint("Extracting contours")
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
        _checkpoint("Extracting contours")
        # Prefer an open endpoint so a broken chain is returned in full.
        seed = min(unused)
        component = {seed}
        pending = [seed]
        while pending:
            _checkpoint("Extracting contours")
            current = pending.pop()
            for vertex in ends[current]:
                _checkpoint("Extracting contours")
                for neighbour in adjacency[vertex]:
                    _checkpoint("Extracting contours")
                    if neighbour in unused and neighbour not in component:
                        component.add(neighbour)
                        pending.append(neighbour)
        start = next(
            (v for i in sorted(component) for v in ends[i] if len(adjacency[v]) == 1), ends[seed][0]
        )
        current, ordered = start, []
        while True:
            _checkpoint("Extracting contours")
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
            _checkpoint("Extracting contours")
            for edge in wire.OrderedEdges:
                _checkpoint("Extracting contours")
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
    except ContourCancelled:
        raise
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
            _checkpoint("Extracting contours")
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
        _checkpoint("Finishing preview")
        document.commitTransaction()
    except Exception:
        document.abortTransaction()
        raise
    return results, tuple(created)


@dataclass(frozen=True)
class RegionContour:
    """Physical boundary wires for one detected surface region."""

    region_id: str
    component_id: str
    face_indices: tuple
    status: str
    wires: tuple = ()
    diagnostics: tuple = ()


class _NativeShapeIndex:
    """Hash buckets accelerate topology identity lookup; collisions use isSame."""

    def __init__(self):
        self.shapes = []
        self.buckets = {}

    def add(self, shape):
        bucket = self.buckets.setdefault(shape.hashCode(), [])
        for index in bucket:
            _checkpoint("Extracting contours")
            if shape.isSame(self.shapes[index]):
                return index
        index = len(self.shapes)
        self.shapes.append(shape)
        bucket.append(index)
        return index


def _normalise_region_groups(regions, face_count):
    if hasattr(regions, "regions"):
        regions = regions.regions
    elif hasattr(regions, "face_indices"):
        regions = (regions,)
    if regions is None:
        raise ValueError("Surface regions are required")

    normalised = []
    claimed = set()
    for ordinal, region in enumerate(regions, 1):
        _checkpoint("Extracting contours")
        indices = getattr(region, "face_indices", region)
        try:
            indices = tuple(sorted(set(indices)))
        except TypeError as error:
            raise ValueError("Region face indices must be an iterable of integers") from error
        if not indices:
            raise ValueError("A surface region must contain at least one face")
        if any(type(index) is not int or index < 0 or index >= face_count for index in indices):
            raise ValueError("Region face indices must be within the resolved face range")
        overlap = claimed.intersection(indices)
        if overlap:
            raise ValueError("Surface regions must not assign a face more than once")
        claimed.update(indices)
        normalised.append(
            (
                getattr(region, "region_id", "Region%d" % ordinal),
                getattr(region, "component_id", "UnknownComponent"),
                indices,
                getattr(region, "status", "ok"),
                tuple(getattr(region, "diagnostics", ())),
            )
        )
    return tuple(normalised)


def _extract_region_boundary(shape, face_indices, faces=None):
    if faces is None:
        faces = shape.Faces
    edge_index = _NativeShapeIndex()
    occurrences = []
    diagnostics = set()
    try:
        for face_index in face_indices:
            _checkpoint("Extracting contours")
            face = faces[face_index]
            if not face.isValid():
                return (), "invalid_geometry", ("Invalid source face",)
            for wire in face.Wires:
                _checkpoint("Extracting contours")
                for edge in wire.OrderedEdges:
                    _checkpoint("Extracting contours")
                    if edge.Degenerated or edge.isSeam(face):
                        continue
                    edge_id = edge_index.add(edge)
                    # Keep shared native vertices until boundary assembly.
                    # Independently copying edges disconnects closed loops.
                    occurrences.append((edge_id, edge, face_index))
    except ContourCancelled:
        raise
    except Exception as error:
        return (), "invalid_geometry", (str(error),)

    grouped = {}
    for edge_id, edge, face_index in occurrences:
        _checkpoint("Extracting contours")
        grouped.setdefault(edge_id, []).append((edge, face_index))

    boundary_edges = []
    non_manifold = False
    for edge_id in sorted(grouped):
        _checkpoint("Extracting contours")
        members = grouped[edge_id]
        if len(members) == 1:
            boundary_edges.append(members[0][0])
        elif len(members) == 2:
            if members[0][1] == members[1][1]:
                non_manifold = True
                diagnostics.add("An edge occurs twice on one selected face")
        else:
            non_manifold = True
            diagnostics.add("Boundary edge has %d selected incidences" % len(members))

    if not boundary_edges:
        return (), "non_manifold" if non_manifold else "no_boundary", tuple(sorted(diagnostics))

    wires, assembly_status, assembly_diagnostics = _assemble_wires(boundary_edges)
    diagnostics.update(assembly_diagnostics)
    status = "non_manifold" if non_manifold else assembly_status
    return wires, status, tuple(sorted(diagnostics))


def extract_region_contours(source, regions=None):
    """Extract physical boundaries after internal region edges are removed.

    The regions argument may be a RegionDetection object, one SurfaceRegion,
    or a sequence of region-like objects/face-index iterables. When omitted,
    conservative Phase 3 coplanar detection runs automatically. Native edge
    identity, not geometric coincidence, decides which edges are internal.
    Curves, holes, and periodic seams retain Phase 2 handling. No source shape
    or document object is modified.
    """
    shape = _resolve_shape(source)
    if regions is None:
        from SurfaceRegions import detect_surface_regions

        regions = detect_surface_regions(shape)
    faces = shape.Faces
    groups = _normalise_region_groups(regions, len(faces))
    contours = []
    for ordinal, (region_id, component_id, face_indices, input_status, input_diagnostics) in enumerate(groups):
        _checkpoint("Extracting contours", ordinal, len(groups))
        wires, extracted_status, extracted_diagnostics = _extract_region_boundary(shape, face_indices, faces)
        diagnostics = tuple(sorted(set(input_diagnostics).union(extracted_diagnostics)))
        status = input_status if input_status != "ok" else extracted_status
        contours.append(
            RegionContour(
                region_id,
                component_id,
                face_indices,
                status,
                tuple(wires),
                diagnostics,
            )
        )
    return tuple(contours)


def create_region_contour_preview(source, region_contours, document=None):
    """Create one static preview object for each supplied surface region.

    ``region_contours`` is normally the output of
    :func:`extract_region_contours`; passing the selected subset is what lets
    the GUI choose a region without asking the user to pick faces manually.
    The source is never modified and the created objects are ordinary
    ``Part::Feature`` snapshots (this function stays static; use create_parametric_region_contour() for recomputable previews).
    """
    if region_contours is None:
        raise ValueError("Region contour results are required")
    try:
        pending = tuple(region_contours)
    except TypeError as error:
        raise TypeError("Region contour results must be iterable") from error
    if document is None and isinstance(source, App.DocumentObject):
        document = source.Document
    if document is None:
        raise ValueError("An output document is required for a raw shape")
    if not isinstance(document, App.Document):
        raise TypeError("Output document must be a FreeCAD document")

    # Validate the source before adding any output objects. This also keeps
    # raw-shape and document-object inputs on the same resolved-coordinate
    # contract as extraction.
    _resolve_shape(source)
    seen = set()
    for result in pending:
        _checkpoint("Extracting contours")
        region_id = getattr(result, "region_id", None)
        if not region_id or region_id in seen:
            raise ValueError("Region contour IDs must be present and unique")
        seen.add(region_id)
        if not hasattr(result, "face_indices") or not hasattr(result, "wires"):
            raise TypeError("Region results must expose face_indices and wires")

    valid = [result for result in pending if result.status == "ok" and result.wires]
    if not valid:
        return pending, ()

    created = []
    document.openTransaction("Preview surface region contours")
    try:
        for result in valid:
            _checkpoint("Extracting contours")
            obj = document.addObject("Part::Feature", "RegionContour")
            obj.Label = "%s contour" % result.region_id
            obj.Shape = Part.makeCompound(list(result.wires))
            obj.addProperty("App::PropertyString", "SourceRegionId", "Contour")
            obj.SourceRegionId = result.region_id
            obj.addProperty("App::PropertyString", "ComponentId", "Contour")
            obj.ComponentId = result.component_id
            obj.addProperty("App::PropertyIntegerList", "SourceFaceIndices", "Contour")
            obj.SourceFaceIndices = list(result.face_indices)
            obj.addProperty("App::PropertyString", "ContourStatus", "Contour")
            obj.ContourStatus = result.status
            obj.addProperty("App::PropertyString", "Diagnostics", "Contour")
            obj.Diagnostics = "; ".join(result.diagnostics)
            if isinstance(source, App.DocumentObject) and source.Document is document:
                obj.addProperty("App::PropertyLink", "Source", "Contour")
                obj.Source = source
            if App.GuiUp:
                obj.ViewObject.LineColor = (0.1, 0.55, 1.0)
                obj.ViewObject.LineWidth = 3.0
            created.append(obj)
        document.recompute()
        _checkpoint("Finishing preview")
        document.commitTransaction()
    except Exception:
        document.abortTransaction()
        raise
    return pending, tuple(created)


class RegionContourFeature:
    """Parametric proxy that rebuilds selected region contours on recompute.

    Region IDs and face indices are revision-local.  The proxy deliberately
    re-detects regions from the current source shape instead of trying to
    persist topology sub-element references across edits.
    """

    _POLICIES = ("coplanar", "individual")

    def __init__(self, obj):
        obj.Proxy = self
        self._ensure_property(obj, "App::PropertyLink", "Source")
        self._ensure_property(obj, "App::PropertyEnumeration", "GroupingPolicy")
        obj.GroupingPolicy = list(self._POLICIES)
        if obj.GroupingPolicy not in self._POLICIES:
            obj.GroupingPolicy = "coplanar"
        self._ensure_property(obj, "App::PropertyStringList", "RegionIds")
        self._ensure_property(obj, "App::PropertyStringList", "ResolvedRegionIds")
        self._ensure_property(obj, "App::PropertyStringList", "ComponentIds")
        self._ensure_property(obj, "App::PropertyIntegerList", "SourceFaceIndices")
        self._ensure_property(obj, "App::PropertyString", "ContourStatus")
        self._ensure_property(obj, "App::PropertyString", "Diagnostics")
        self._ensure_property(obj, "App::PropertyString", "LastError")
        for name in (
            "ResolvedRegionIds",
            "ComponentIds",
            "SourceFaceIndices",
            "ContourStatus",
            "Diagnostics",
            "LastError",
        ):
            try:
                obj.setEditorMode(name, 1)
            except Exception:
                pass

    @staticmethod
    def _ensure_property(obj, property_type, name):
        if name not in obj.PropertiesList:
            obj.addProperty(property_type, name, "Contour")

    @staticmethod
    def _set_result_metadata(obj, selected, diagnostics=()):
        obj.ResolvedRegionIds = [result.region_id for result in selected]
        obj.ComponentIds = [result.component_id for result in selected]
        obj.SourceFaceIndices = sorted(
            {index for result in selected for index in result.face_indices}
        )
        messages = set(diagnostics)
        for result in selected:
            _checkpoint("Extracting contours")
            messages.update(result.diagnostics)
        obj.Diagnostics = "; ".join(sorted(messages))

    def execute(self, obj):
        obj.LastError = ""
        source = getattr(obj, "Source", None)
        if source is None:
            obj.Shape = Part.Shape()
            obj.ResolvedRegionIds = []
            obj.ComponentIds = []
            obj.SourceFaceIndices = []
            obj.ContourStatus = "missing_source"
            obj.Diagnostics = "Choose a source document object"
            return

        try:
            from SurfaceRegions import detect_surface_regions

            detection = detect_surface_regions(
                source, policy=getattr(obj, "GroupingPolicy", "coplanar")
            )
            requested = set(getattr(obj, "RegionIds", ()))
            chosen = [region for region in detection.regions
                      if not requested or region.region_id in requested]
            results = extract_region_contours(source, chosen)
            selected = (
                [result for result in results if result.region_id in requested]
                if requested
                else list(results)
            )
            missing = requested.difference(result.region_id for result in selected)
            diagnostics = [
                "Requested region is not present in the current source revision: %s"
                % region_id
                for region_id in sorted(missing)
            ]
            self._set_result_metadata(obj, selected, diagnostics)
            valid = [
                result for result in selected if result.status == "ok" and result.wires
            ]
            wires = [wire for result in valid for wire in result.wires]
            obj.Shape = Part.makeCompound(wires) if wires else Part.Shape()
            if not selected:
                obj.ContourStatus = "no_region"
            elif not wires:
                obj.ContourStatus = "no_boundary"
            elif len(valid) == len(selected):
                obj.ContourStatus = "ok"
            else:
                obj.ContourStatus = "partial"
        except ContourCancelled:
            raise
        except Exception as error:
            obj.Shape = Part.Shape()
            obj.ResolvedRegionIds = []
            obj.ComponentIds = []
            obj.SourceFaceIndices = []
            obj.ContourStatus = "error"
            obj.Diagnostics = ""
            obj.LastError = str(error)


def create_parametric_region_contour(
    source, region_ids=None, policy="coplanar", document=None
):
    """Create a recomputable region-contour feature linked to ``source``.

    The source must be a document object so the dependency graph can trigger
    the proxy on recompute.  ``region_ids`` is empty/None for all regions;
    non-empty values select region IDs from the current detection revision.
    """
    if not isinstance(source, App.DocumentObject):
        raise TypeError("A document object is required for a parametric contour")
    if policy not in RegionContourFeature._POLICIES:
        raise ValueError("Policy must be 'individual' or 'coplanar'")
    if document is None:
        document = source.Document
    if not isinstance(document, App.Document):
        raise TypeError("Output document must be a FreeCAD document")
    if source.Document is not document:
        raise ValueError("The source and parametric output must share a document")
    requested = [] if region_ids is None else list(region_ids)
    if any(not isinstance(region_id, str) or not region_id for region_id in requested):
        raise ValueError("Region IDs must be non-empty strings")
    if len(set(requested)) != len(requested):
        raise ValueError("Region IDs must be unique")

    created_name = None
    document.openTransaction("Create parametric surface contour")
    try:
        obj = document.addObject("Part::FeaturePython", "RegionContourParametric")
        created_name = obj.Name
        obj.Label = "Surface contours (%s)" % source.Label
        RegionContourFeature(obj)
        obj.Source = source
        obj.GroupingPolicy = policy
        obj.RegionIds = requested
        if App.GuiUp:
            obj.ViewObject.LineColor = (0.1, 0.55, 1.0)
            obj.ViewObject.LineWidth = 3.0
        document.recompute()
        _checkpoint("Finishing preview")
        document.commitTransaction()
    except Exception:
        document.abortTransaction()
        if created_name and document.getObject(created_name) is not None:
            document.removeObject(created_name)
        raise
    return obj

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Read-only, conservative detection of connected BRep surface regions.

This module detects membership only. Grouped contours are Phase 4. Smooth
and semantic segmentation are deliberately not inferred by this policy.
"""

from dataclasses import dataclass
import math

import Part
from SurfaceContours import _resolve_shape, _checkpoint, ContourCancelled


@dataclass(frozen=True)
class DetectionSettings:
    policy: str = "coplanar"
    angle_tolerance: float = 0.0001  # degrees, oriented normals
    distance_tolerance: float = 0.0000001  # document units (mm)

    def __post_init__(self):
        if self.policy not in ("individual", "coplanar"):
            raise ValueError("Policy must be 'individual' or 'coplanar'")
        for name in ("angle_tolerance", "distance_tolerance"):
            _checkpoint("Detecting regions")
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(name + " must be a positive finite number")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(name + " must be a positive finite number")
        if self.angle_tolerance >= 90:
            raise ValueError("Angle tolerance must be less than 90 degrees")


@dataclass(frozen=True)
class SurfaceRegion:
    region_id: str
    component_id: str
    face_indices: tuple
    status: str = "ok"
    diagnostics: tuple = ()

    @property
    def face_names(self):
        return tuple("Face%d" % (i + 1) for i in self.face_indices)


@dataclass(frozen=True)
class RegionDetection:
    settings: DetectionSettings
    regions: tuple
    adjacency: tuple  # manifold, shared-edge face pairs within one component


class _TopologyIndex:
    """Hash buckets accelerate identity lookup; collisions still use isSame."""

    def __init__(self):
        self.shapes = []
        self.buckets = {}

    def add(self, shape):
        bucket = self.buckets.setdefault(shape.hashCode(), [])
        for index in bucket:
            _checkpoint("Detecting regions")
            if shape.isSame(self.shapes[index]):
                return index
        index = len(self.shapes)
        self.shapes.append(shape)
        bucket.append(index)
        return index


def _component_owners(shape, faces):
    """Respect independent solid/shell/face containers, including shared topology.

    Connectivity is additionally required when forming a region, so a shell
    container with disconnected faces cannot merge those faces either.
    """
    index = _TopologyIndex()
    for face in faces:
        _checkpoint("Detecting regions")
        index.add(face)
    owners = [set() for _ in faces]
    component = 0

    def visit(part):
        nonlocal component
        if part.ShapeType in ("Compound", "CompSolid"):
            for child in part.childShapes():
                _checkpoint("Detecting regions")
                visit(child)
        elif part.ShapeType in ("Solid", "Shell", "Face"):
            component += 1
            for face in part.Faces:
                _checkpoint("Detecting regions")
                owners[index.add(face)].add(component)

    visit(shape)
    return owners


def _plane(face):
    if not isinstance(face.Surface, Part.Plane):
        return None
    u0, u1, v0, v1 = face.ParameterRange
    u, v = (u0 + u1) / 2, (v0 + v1) / 2
    normal = face.normalAt(u, v)
    if normal.Length == 0:
        raise ValueError("Plane has an undefined oriented normal")
    normal.normalize()
    return face.valueAt(u, v), normal


def _coplanar(first, second, settings):
    if first is None or second is None:
        return False
    p, n = first
    q, m = second
    # atan2 remains accurate for tiny angles; opposite orientation stays split.
    angle = math.degrees(math.atan2(n.cross(m).Length, n.dot(m)))
    delta = q - p
    return (
        angle <= settings.angle_tolerance
        and abs(delta.dot(n)) <= settings.distance_tolerance
        and abs(delta.dot(m)) <= settings.distance_tolerance
    )


def detect_surface_regions(
    source, policy="coplanar", angle_tolerance=0.0001, distance_tolerance=0.0000001
):
    """Partition all resolved faces, without changing topology or the document.

    Coplanar grouping requires shared native edges, one component, analytic
    planes, compatible oriented normals, and bounded plane separation. Every
    added member must be compatible with every existing member: tolerance
    chains cannot accumulate drift. IDs and zero-based indices are revision-
    local, not persistent references. No GUI/camera state is consulted.
    """
    settings = DetectionSettings(policy, angle_tolerance, distance_tolerance)
    shape = _resolve_shape(source)
    _checkpoint("Reading geometry")
    faces = shape.Faces
    owners = _component_owners(shape, faces)
    messages = [set() for _ in faces]
    statuses = ["ok"] * len(faces)
    planes = [None] * len(faces)
    edges = _TopologyIndex()
    incidence = []
    for i, face in enumerate(faces):
        _checkpoint("Detecting regions")
        if len(owners[i]) != 1:
            statuses[i] = "non_manifold"
            messages[i].add("Face has ambiguous component ownership")
        try:
            if not face.isValid():
                raise ValueError("Invalid source face")
            planes[i] = _plane(face)
            for wire in face.Wires:
                _checkpoint("Detecting regions")
                for edge in wire.OrderedEdges:
                    _checkpoint("Detecting regions")
                    if edge.Degenerated or edge.isSeam(face):
                        continue
                    edge_id = edges.add(edge)
                    if edge_id == len(incidence):
                        incidence.append([])
                    incidence[edge_id].append(i)
        except ContourCancelled:
            raise
        except Exception as error:
            statuses[i] = "invalid_geometry"
            messages[i].add(str(error))

    adjacency = set()
    for edge_id, members in enumerate(incidence):
        _checkpoint("Detecting regions")
        if len(members) > 2 or len(set(members)) != len(members):
            for i in members:
                _checkpoint("Detecting regions")
                if statuses[i] == "ok":
                    statuses[i] = "non_manifold"
                messages[i].add("Non-manifold boundary incidence at Edge%d" % (edge_id + 1))
        elif len(members) == 2:
            a, b = sorted(members)
            if owners[a] == owners[b] and len(owners[a]) == 1:
                adjacency.add((a, b))

    neighbours = [set() for _ in faces]
    for a, b in sorted(adjacency):
        _checkpoint("Detecting regions")
        if statuses[a] == statuses[b] == "ok":
            neighbours[a].add(b)
            neighbours[b].add(a)
    remaining = set(range(len(faces)))
    regions = []
    while remaining:
        _checkpoint("Detecting regions")
        seed = min(remaining)
        remaining.remove(seed)
        members = [seed]
        pending = [seed]
        if policy == "coplanar" and statuses[seed] == "ok":
            while pending:
                _checkpoint("Detecting regions")
                current = pending.pop(0)
                for candidate in sorted(neighbours[current] & remaining):
                    _checkpoint("Detecting regions")
                    compatible = True
                    for member in members:
                        _checkpoint("Grouping connected faces")
                        if not _coplanar(planes[candidate], planes[member], settings):
                            compatible = False
                            break
                    if compatible:
                        remaining.remove(candidate)
                        members.append(candidate)
                        pending.append(candidate)
        component_id = "+".join("Component%d" % c for c in sorted(owners[seed]))
        regions.append(
            SurfaceRegion(
                "Region%d" % (len(regions) + 1),
                component_id or "UnresolvedComponent",
                tuple(sorted(members)),
                statuses[seed],
                tuple(sorted(messages[seed])),
            )
        )
    return RegionDetection(settings, tuple(regions), tuple(sorted(adjacency)))

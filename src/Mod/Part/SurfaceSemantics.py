# SPDX-License-Identifier: LGPL-2.1-or-later
"""Heuristic surface-role classification and parametric semantic contours.

The classifier intentionally works from an object, not manually picked faces. It
uses oriented face normals, sampled on curved faces, plus position along a user
reference direction. The result is a confidence-scored semantic hint: CAD
geometry does not contain a universal meaning for top, sole, or side.
"""

from dataclasses import dataclass
import math

import FreeCAD as App
import Part

from SurfaceContours import (
    resolve_shape, extract_region_contours, checkpoint as _checkpoint, ContourCancelled,
    GROUPING_POLICIES, STATUS_STALE_SELECTION, selection_is_current, shape_revision,
    current_analysis,
    DISTANCE_TOLERANCE,
)


_ROLES = ("all", "top", "bottom", "side", "sole_candidate", "unknown")
_POLICIES = GROUPING_POLICIES


@dataclass(frozen=True)
class SemanticSettings:
    reference_direction: object
    orientation_tolerance: float = 45.0
    sole_band: float = 0.35

    def __post_init__(self):
        direction = _normalise_direction(self.reference_direction)
        object.__setattr__(self, "reference_direction", direction)
        tolerance = _number(self.orientation_tolerance, "Orientation tolerance")
        if tolerance <= 0 or tolerance >= 90:
            raise ValueError("Orientation tolerance must be greater than 0 and less than 90 degrees")
        band = _number(self.sole_band, "Sole band")
        if band < 0 or band > 1:
            raise ValueError("Sole band must be between 0 and 1")
        object.__setattr__(self, "orientation_tolerance", tolerance)
        object.__setattr__(self, "sole_band", band)


@dataclass(frozen=True)
class SemanticRegion:
    region_id: str
    component_id: str
    face_indices: tuple
    primary_role: str
    roles: tuple
    orientation_score: float
    position_score: float
    area: float
    average_normal: object = None
    surface_types: tuple = ()
    confidence: float = 0.0
    diagnostics: tuple = ()

    @property
    def role(self):
        return self.primary_role


@dataclass(frozen=True)
class SemanticDetection:
    settings: SemanticSettings
    regions: tuple
    diagnostics: tuple = ()


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(label + " must be a finite number")
    if not math.isfinite(value):
        raise ValueError(label + " must be a finite number")
    return float(value)


def _normalise_direction(value):
    if value is None:
        value = App.Vector(0, 0, 1)
    try:
        direction = App.Vector(value.x, value.y, value.z)
    except AttributeError:
        try:
            if len(value) != 3:
                raise ValueError
            direction = App.Vector(float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError, IndexError) as error:
            raise ValueError("Reference direction must contain three coordinates") from error
    if not all(math.isfinite(float(coordinate)) for coordinate in (direction.x, direction.y, direction.z)):
        raise ValueError("Reference direction must be finite")
    if direction.Length <= 1e-12:
        raise ValueError("Reference direction must not be zero")
    direction.normalize()
    return direction


def _face_normal(face):
    """Trim-aware, Jacobian-weighted sampling with a coherence estimate.

    Confidence is a heuristic, not a calibrated probability. Mixed normals
    lower coherence instead of becoming a misleading high-confidence average.
    """
    try:
        u0, u1, v0, v1 = face.ParameterRange
        if isinstance(face.Surface, Part.Plane):
            normal = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
            if normal.Length > 1e-12:
                normal.normalize()
                return normal, (), 1.0
        if not all(math.isfinite(v) for v in (u0, u1, v0, v1)) or u1 <= u0 or v1 <= v0:
            return None, ("Unbounded or degenerate parameter domain",), 0.0
        samples = tuple(((i + 0.5) / 7, (j + 0.5) / 7)
                        for i in range(7) for j in range(7))
        total = App.Vector(0, 0, 0)
        count = 0
        weight_sum = 0.0
        hu, hv = (u1 - u0) * 1e-5, (v1 - v0) * 1e-5
        for u_fraction, v_fraction in samples:
            _checkpoint("Classifying surfaces")
            u, v = u0 + (u1 - u0) * u_fraction, v0 + (v1 - v0) * v_fraction
            point = face.valueAt(u, v)
            if not face.isInside(point, DISTANCE_TOLERANCE, True):
                continue
            normal = face.normalAt(u, v)
            du = (face.valueAt(u + hu, v) - face.valueAt(u - hu, v)) * (0.5 / hu)
            dv = (face.valueAt(u, v + hv) - face.valueAt(u, v - hv)) * (0.5 / hv)
            weight = du.cross(dv).Length
            if not math.isfinite(weight) or weight <= 0:
                continue
            if normal.Length > 1e-12:
                normal.normalize()
                total += normal * weight
                weight_sum += weight
                count += 1
        if count >= 3 and weight_sum > 0 and total.Length > 1e-12:
            coherence = min(1.0, total.Length / weight_sum)
            total.normalize()
            return total, (() if coherence >= 0.9 else ("Surface normals vary; confidence reduced",)), coherence
    except ContourCancelled:
        raise
    except Exception as error:
        return None, ("Normal sampling failed: %s" % error,), 0.0
    return None, ("Insufficient interior samples or cancelling surface normals",), 0.0


def _shape_projection_bounds(shape, direction):
    box = shape.BoundBox
    corners = (
        App.Vector(box.XMin, box.YMin, box.ZMin),
        App.Vector(box.XMin, box.YMin, box.ZMax),
        App.Vector(box.XMin, box.YMax, box.ZMin),
        App.Vector(box.XMin, box.YMax, box.ZMax),
        App.Vector(box.XMax, box.YMin, box.ZMin),
        App.Vector(box.XMax, box.YMin, box.ZMax),
        App.Vector(box.XMax, box.YMax, box.ZMin),
        App.Vector(box.XMax, box.YMax, box.ZMax),
    )
    projections = [corner.dot(direction) for corner in corners]
    return min(projections), max(projections)


def _region_measure(shape, region, faces=None):
    if faces is None:
        faces = shape.Faces
    total_area = 0.0
    weighted_center = App.Vector(0, 0, 0)
    normals = []
    sampled_quality = 0.0
    sampled_area = 0.0
    surface_types = set()
    diagnostics = set(region.diagnostics)
    for face_index in region.face_indices:
        _checkpoint("Classifying surfaces")
        face = faces[face_index]
        try:
            area = max(float(face.Area), 0.0)
            center = face.CenterOfMass
            total_area += area
            weighted_center += center * area
            surface_types.add(type(face.Surface).__name__)
        except ContourCancelled:
            raise
        except Exception as error:
            diagnostics.add("Face measurement failed: %s" % error)
        normal, normal_diagnostics, quality = _face_normal(face)
        if normal is not None:
            weight = max(float(getattr(face, "Area", 0.0)), 0.0)
            normals.append((normal, weight))
            sampled_quality += quality * weight
            sampled_area += weight
        diagnostics.update(normal_diagnostics)
    if total_area > 1e-12:
        center = weighted_center * (1.0 / total_area)
    else:
        center = faces[region.face_indices[0]].CenterOfMass
    if normals:
        normal_sum = App.Vector(0, 0, 0)
        for normal, weight in normals:
            _checkpoint("Classifying surfaces")
            normal_sum += normal * weight
        normal_coherence = normal_sum.Length / sampled_area if sampled_area > 0 else 0.0
        average_normal = normal_sum
        if average_normal.Length > 1e-12:
            average_normal.normalize()
        else:
            average_normal = None
    else:
        average_normal = None
    quality = sampled_quality / total_area if total_area > 0 else 0.0
    if normals and sampled_area > 0:
        quality *= min(1.0, normal_coherence)
    return total_area, center, average_normal, tuple(sorted(surface_types)), tuple(sorted(diagnostics)), quality


def _orientation_role(score, tolerance):
    facing = math.cos(math.radians(tolerance))
    side = math.sin(math.radians(tolerance))
    if score >= facing:
        return "top"
    if score <= -facing:
        return "bottom"
    if abs(score) <= side:
        return "side"
    return "unknown"


def classify_surface_regions(
    source,
    regions=None,
    reference_direction=None,
    orientation_tolerance=45.0,
    sole_band=0.35,
):
    """Classify automatically detected regions into semantic role hints.

    reference_direction defines up. A region is top/bottom when its
    area-weighted oriented normal is within orientation_tolerance degrees of
    +/- that direction. Side is the band near perpendicular. Curved faces are
    sampled, so a non-flat sole can still be identified as a low,
    downward-facing candidate. Results are deterministic for a source revision.
    """
    settings = SemanticSettings(
        _normalise_direction(reference_direction), orientation_tolerance, sole_band
    )
    shape = resolve_shape(source)
    if regions is None:
        from SurfaceRegions import detect_surface_regions
        regions = detect_surface_regions(source)
    if not hasattr(regions, "regions"):
        raise TypeError("regions must be a RegionDetection result")
    low, high = _shape_projection_bounds(shape, settings.reference_direction)
    span = high - low
    if span <= 1e-12:
        span = 1.0
    faces = shape.Faces
    classified = []
    diagnostics = set()
    for region in regions.regions:
        _checkpoint("Classifying surfaces")
        area, center, average_normal, surface_types, region_diagnostics, quality = _region_measure(shape, region, faces)
        score = 0.0 if average_normal is None else average_normal.dot(settings.reference_direction)
        elevation = max(0.0, min(1.0, (center.dot(settings.reference_direction) - low) / span))
        primary = _orientation_role(score, settings.orientation_tolerance)
        roles = ["all", primary]
        confidence = abs(score) if primary in ("top", "bottom") else 1.0 - abs(score)
        confidence = max(0.0, min(1.0, confidence))
        confidence *= quality
        if average_normal is None:
            primary = "unknown"
            roles = ["all", "unknown"]
            confidence = 0.0
        classified.append(
            SemanticRegion(
                region.region_id,
                region.component_id,
                tuple(region.face_indices),
                primary,
                tuple(roles),
                float(score),
                float(elevation),
                float(area),
                average_normal,
                surface_types,
                float(confidence),
                tuple(region_diagnostics),
            )
        )
        diagnostics.update(region_diagnostics)

    bottom = [item for item in classified if item.primary_role == "bottom"]
    if bottom:
        lowest = min(item.position_score for item in bottom)
        top_of_band = lowest + settings.sole_band
        marked = [item for item in bottom if item.position_score <= top_of_band + 1e-12]
        if not marked:
            marked = [min(bottom, key=lambda item: (item.position_score, item.region_id))]
        marked_ids = {item.region_id for item in marked}
        classified = [
            item if item.region_id not in marked_ids
            else SemanticRegion(
                item.region_id,
                item.component_id,
                item.face_indices,
                item.primary_role,
                tuple(item.roles) + ("sole_candidate",),
                item.orientation_score,
                item.position_score,
                item.area,
                item.average_normal,
                item.surface_types,
                item.confidence,
                item.diagnostics,
            )
            for item in classified
        ]
    else:
        diagnostics.add("No downward-facing region was found for sole_candidate")
    return SemanticDetection(settings, tuple(classified), tuple(sorted(diagnostics)))


def select_semantic_regions(detection, role="all"):
    if role not in _ROLES:
        raise ValueError("Unknown surface role: %s" % role)
    if role == "all":
        return tuple(detection.regions)
    return tuple(region for region in detection.regions if role in region.roles)


def _role_summary(region):
    roles = ",".join(role for role in region.roles if role != "all")
    return "%s:%s:%.3f:%.3f" % (
        region.region_id, roles, region.confidence, region.position_score
    )


class SemanticRegionContourFeature:
    """Parametric contour feature driven by a semantic role, not face picks."""

    def __init__(self, obj):
        obj.Proxy = self
        self._ensure(obj, "App::PropertyLink", "Source")
        self._ensure(obj, "App::PropertyEnumeration", "GroupingPolicy")
        obj.GroupingPolicy = list(_POLICIES)
        obj.GroupingPolicy = "coplanar"
        self._ensure(obj, "App::PropertyEnumeration", "SurfaceRole")
        obj.SurfaceRole = list(_ROLES)
        obj.SurfaceRole = "top"
        self._ensure(obj, "App::PropertyVector", "ReferenceDirection")
        obj.ReferenceDirection = App.Vector(0, 0, 1)
        self._ensure(obj, "App::PropertyAngle", "OrientationTolerance")
        obj.OrientationTolerance = 45.0
        self._ensure(obj, "App::PropertyFloat", "SoleBand")
        obj.SoleBand = 0.35
        self._ensure(obj, "App::PropertyStringList", "RegionIds")
        self._ensure(obj, "App::PropertyString", "SelectionRevision")
        self._ensure(obj, "App::PropertyStringList", "ResolvedRegionIds")
        self._ensure(obj, "App::PropertyIntegerList", "SourceFaceIndices")
        self._ensure(obj, "App::PropertyStringList", "SemanticRoles")
        self._ensure(obj, "App::PropertyString", "ContourStatus")
        self._ensure(obj, "App::PropertyString", "Diagnostics")
        self._ensure(obj, "App::PropertyString", "LastError")
        for name in ("SelectionRevision", "ResolvedRegionIds", "SourceFaceIndices", "SemanticRoles", "ContourStatus", "Diagnostics", "LastError"):
            _checkpoint("Classifying surfaces")
            try:
                obj.setEditorMode(name, 1)
            except Exception:
                pass

    @staticmethod
    def _ensure(obj, property_type, name):
        if name not in obj.PropertiesList:
            obj.addProperty(property_type, name, "Semantic contour")

    @staticmethod
    def _clear(obj, status, message=""):
        obj.Shape = Part.Shape()
        obj.ResolvedRegionIds = []
        obj.SourceFaceIndices = []
        obj.SemanticRoles = []
        obj.ContourStatus = status
        obj.Diagnostics = message

    def execute(self, obj):
        obj.LastError = ""
        source = getattr(obj, "Source", None)
        if source is None:
            self._clear(obj, "missing_source", "Choose a source document object")
            return
        try:
            from SurfaceRegions import detect_surface_regions
            if not selection_is_current(obj):
                self._clear(obj, STATUS_STALE_SELECTION, "Source geometry changed. Reselect the surface.")
                return
            cached = current_analysis(source, obj.GroupingPolicy)
            semantic = cached[2] if cached else None
            direction = _normalise_direction(obj.ReferenceDirection)
            if semantic is not None and (semantic.settings.reference_direction != direction or
                    semantic.settings.orientation_tolerance != obj.OrientationTolerance.Value or
                    semantic.settings.sole_band != obj.SoleBand):
                cached = semantic = None
            detection = cached[1] if cached else detect_surface_regions(source, policy=obj.GroupingPolicy)
            semantic = semantic or classify_surface_regions(
                source,
                detection,
                reference_direction=obj.ReferenceDirection,
                orientation_tolerance=obj.OrientationTolerance.Value,
                sole_band=obj.SoleBand,
            )
            wanted = select_semantic_regions(semantic, obj.SurfaceRole)
            requested = set(getattr(obj, "RegionIds", ()))
            selected = tuple(item for item in wanted if not requested or item.region_id in requested)
            missing = requested.difference(item.region_id for item in selected)
            diagnostics = list(semantic.diagnostics)
            diagnostics.extend(
                "Requested semantic region is not present in the current source revision: %s" % region_id
                for region_id in sorted(missing)
            )
            contour_by_id = {
                result.region_id: result
                for result in (cached[3] if cached else extract_region_contours(source, selected))
            }
            contours = [contour_by_id[item.region_id] for item in selected if item.region_id in contour_by_id]
            for result in contours:
                _checkpoint("Classifying surfaces")
                diagnostics.extend(result.diagnostics)
            self._set_metadata(obj, selected, diagnostics)
            valid = [result for result in contours if result.status == "ok" and result.wires]
            wires = [wire for result in valid for wire in result.wires]
            obj.Shape = Part.makeCompound(wires) if wires else Part.Shape()
            if not selected:
                obj.ContourStatus = "no_role_match"
            elif not wires:
                obj.ContourStatus = "no_boundary"
            elif len(valid) == len(contours) and not missing:
                obj.ContourStatus = "ok"
            else:
                obj.ContourStatus = "partial"
        except ContourCancelled:
            raise
        except Exception as error:
            self._clear(obj, "error")
            obj.LastError = str(error)

    @staticmethod
    def _set_metadata(obj, selected, diagnostics):
        obj.ResolvedRegionIds = [item.region_id for item in selected]
        obj.SourceFaceIndices = sorted({index for item in selected for index in item.face_indices})
        obj.SemanticRoles = [_role_summary(item) for item in selected]
        messages = set(diagnostics)
        for item in selected:
            _checkpoint("Classifying surfaces")
            messages.update(item.diagnostics)
        obj.Diagnostics = "; ".join(sorted(messages))


def create_semantic_region_contour(
    source,
    role="top",
    reference_direction=None,
    policy="coplanar",
    orientation_tolerance=45.0,
    sole_band=0.35,
    region_ids=None,
    document=None,
):
    """Create a recomputable contour selected by semantic role.

    Role classification remains heuristic and is recorded on the feature so
    users can inspect the decision and its confidence after recompute.
    """
    if not isinstance(source, App.DocumentObject):
        raise TypeError("A document object is required for a parametric contour")
    if role not in _ROLES:
        raise ValueError("Role must be one of all, top, bottom, side, sole_candidate, or unknown")
    if policy not in _POLICIES:
        raise ValueError("Policy must be 'individual' or 'coplanar'")
    direction = _normalise_direction(reference_direction)
    tolerance = _number(orientation_tolerance, "Orientation tolerance")
    band = _number(sole_band, "Sole band")
    SemanticSettings(direction, tolerance, band)
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
    document.openTransaction("Create semantic surface contour")
    try:
        obj = document.addObject("Part::FeaturePython", "SemanticRegionContour")
        created_name = obj.Name
        obj.Label = "%s contours (%s)" % (role.replace("_", " "), source.Label)
        SemanticRegionContourFeature(obj)
        obj.Source = source
        obj.GroupingPolicy = policy
        obj.SurfaceRole = role
        obj.ReferenceDirection = direction
        obj.OrientationTolerance = tolerance
        obj.SoleBand = band
        obj.RegionIds = requested
        obj.SelectionRevision = policy + ":" + shape_revision(source) if requested else ""
        if App.GuiUp:
            obj.ViewObject.LineColor = (0.95, 0.55, 0.1)
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


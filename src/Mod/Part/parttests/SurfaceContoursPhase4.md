# Phase 4: grouped-region physical boundaries

Status: implemented on feature/surface-contours-phase-1.

## Goal

Phase 3 detects which native BRep faces belong to one conservative connected coplanar surface region. Phase 4 converts each region into its physical boundary wires. Internal edges between two faces in the same region are removed, while the outside boundary and real holes remain.

This is independent of camera direction, view projection, object placement, and GUI selection. It works on any resolved Part BRep object or raw Part.Shape.

## API

SurfaceContours.extract_region_contours(source, regions=None)

When regions is omitted, the function runs Phase 3 coplanar detection automatically. Callers may also pass a RegionDetection result, one SurfaceRegion, or a sequence of region-like objects containing face_indices.

The result is one RegionContour per input region:

- region_id and component_id preserve Phase 3 metadata.
- face_indices are zero-based and valid only for the current source revision.
- wires contains native Part.Wire objects in resolved coordinates.
- status is ok, no_boundary, open_boundary, invalid_geometry, or non_manifold.
- diagnostics explain isolated failures without hiding successful regions.

## Boundary algorithm

1. Resolve the source shape without changing the document or applying placement twice.
2. Walk every non-seam, non-degenerate edge of every face in the region.
3. Match edges by native topology identity using hash buckets followed by isSame. Geometric coincidence alone is never treated as shared topology.
4. Keep edges occurring once in the region. Remove edges occurring twice because they are internal shared edges.
5. Diagnose repeated or more-than-two edge incidences as non-manifold.
6. Assemble retained edges into exact-topology wires using the Phase 2 wire walker.

This preserves curved edges, circular holes, multiple wires, periodic seam handling, and open-boundary diagnostics. No healing or geometric vertex merging is performed.

## Expected results

| Input | Phase 3 regions | Phase 4 wires |
| --- | ---: | ---: |
| Cube | 6 | 6 outer loops |
| Subdivided cube | 6 | 6 outer loops, internal patch edges removed |
| Square pyramid | 5 | 5 outer loops |
| Annulus face | 1 | 2 loops, outside plus hole |
| Disconnected cubes | 12 | 12 independent loops |
| Sphere | 1 | no_boundary because no physical edge exists |
| Curved sole | one region per spline patch | each patch boundary remains explicit |

## Validation

Eleven Phase 4 tests cover subdivided-face merging, cube and pyramid loops, holes, individual-policy compatibility, automatic detection, disconnected components, curved and periodic faces, explicit subsets, validation errors, links, immutability, and deterministic metadata. Together with Phases 1 to 3, the Windows beta gate requires 46 tests against the packaged application.

## Deliberate limits

Phase 4 does not infer smooth or semantic regions across non-planar faces. It does not create document preview objects or a selection panel; those belong to later GUI work. A caller must rerun detection and extraction after the source topology changes.

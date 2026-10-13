<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Phase 3: connected surface regions

Phase 3 detects region membership from one resolved BRep object. It does not
yet extract the boundary of a grouped region (Phase 4) or add a task panel
(Phase 5). Phase 2 individual-face extraction remains unchanged.

## Use from the FreeCAD Python console

Select an object in the tree, then run:

```python
import SurfaceRegions
source = Gui.Selection.getSelection()[0]
detection = SurfaceRegions.detect_surface_regions(source)
[(r.region_id, r.component_id, r.face_names, r.status) for r in detection.regions]
```

To highlight all constituent faces of the first detected region:

```python
region = detection.regions[0]
Gui.Selection.clearSelection()
for name in region.face_names:
    Gui.Selection.addSelection(source, name)
```

The user selects a region, not each member face manually. The future task panel
will perform this highlighting and region choice directly.

For individual faces, pass `policy="individual"`. The default is
`policy="coplanar"`. Detection accepts shapes, objects, and links, composes
placement through the Phase 2 resolver, and neither creates objects nor changes
source geometry. Camera orientation never participates.

## Conservative grouping rules

- Require a shared native CAD edge. Proximity, vertex-only contact, and equal
  normals do not establish adjacency.
- Keep independent solid, shell, and standalone-face containers separate,
  including when they touch or contain shared topology.
- Merge only analytic plane faces with compatible oriented normals and bounded
  plane separation. Oppositely oriented faces stay separate.
- Check each new member against every existing member. A chain of near-matches
  cannot accumulate angular or plane-offset drift across a region.
- Exclude periodic seams and degenerate edges from incidence analysis.
- Keep invalid or non-manifold faces as separate diagnostic regions rather than
  discarding them or applying the ordinary two-face grouping rule.

The defaults are `angle_tolerance=0.0001` degrees and
`distance_tolerance=0.0000001` document units (mm). Both must be positive and
finite; angle tolerance must also be less than 90 degrees. Detection records
the settings used. These are grouping tolerances, not healing tolerances.

## Expected results

| Model | Coplanar regions | Individual regions |
|---|---:|---:|
| Cube | 6 | 6 |
| Square pyramid | 5 | 5 |
| Cube with four patches per side | 6 | 24 |
| Two independent cubes, including touching cubes | 12 | 12 |
| Cylinder | 3 | 3 |
| Sphere | 1 | 1 |
| Synthetic curved sole | 7 | 7 |

Curved patches are intentionally not merged by this conservative policy.
Planar faces encoded as spline surfaces are also left separate. Smooth grouping
is not implemented: `policy="smooth"` is rejected. Geometry cannot universally
identify semantic upper/lower/wall splits across smooth blends. The real sole's
intended membership still needs its CAD file and acceptance reference.

## Result and validation

`RegionDetection` contains settings, regions, and manifold native-edge adjacency
pairs. Each `SurfaceRegion` contains a revision-local region ID, component ID,
zero-based face indices, one-based FreeCAD face names, status, and diagnostics.
Every resolved face occurs exactly once. IDs are not persistent across source
edits or face reordering; callers must rerun detection after a geometry change.

`ok` means membership detection succeeded, not that grouped contour extraction
has run. `invalid_geometry` and `non_manifold` identify isolated failed faces.
Input failures use the Phase 2 `ContourInputError` contract.

Sixteen new tests cover labelled partitions, native adjacency, component
barriers, touching solids, reversed orientation, distance/angle settings,
tolerance-chain drift, curved/periodic faces, invalid and non-manifold geometry,
scale, placement, links, determinism, metadata, and source immutability. Together
with Phases 1 and 2, the Windows beta gate requires all 35 tests to pass against
the packaged application before publication.

# Phase 5: object-level contour task panel

Phase 5 connects the Phase 3 region detector and Phase 4 physical-boundary
extractor to a first FreeCAD GUI workflow. The user selects one object, the
panel lists every detected region, and the user creates a contour preview by
choosing a row. No face-by-face picking and no camera/top-view projection are
involved.

## User workflow

1. Select exactly one Part object in the model tree.
2. Run **Part → Surface contours** in the Part workbench.
3. Choose either **Coplanar connected regions** or **Every individual face**.
4. Select one region and press **Create selected contour preview**, or create
   all detected previews.

The list shows region ID, connected component, face count, and extraction
status. The detail line reports boundary-wire count and diagnostics. A
successful preview is a separate `Part::Feature` with a blue line style and
metadata linking it back to the source object, region ID, component, and
source face indices.

## Implementation contract

- `SurfaceContourGui.py` owns only selection validation, task-panel widgets,
  and command registration.
- `SurfaceRegions.detect_surface_regions()` remains the only grouping policy.
- `SurfaceContours.extract_region_contours()` remains the only physical
  boundary algorithm.
- `SurfaceContours.create_region_contour_preview()` creates static snapshots
  from selected `RegionContour` results and never modifies the source.
- Headless imports stay safe; GUI-only classes are loaded behind
  `FreeCAD.GuiUp`.

## Deliberate limits

This phase does not make previews parametric, persist face references across
topology changes, or infer semantic regions such as “upper sole” versus
“lower sole”. Curved faces can be selected and previewed when their physical
boundary is available, but smooth/semantic segmentation remains a later
policy phase.

The packaged gate now runs 52 surface-contour tests: the 46 existing fixture,
individual-face, surface-region, and grouped-region tests plus six Phase 5
selection/preview tests.

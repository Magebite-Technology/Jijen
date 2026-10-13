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
4. Select one region and press **Create parametric preview**, or create all
   parametric previews.

The list shows region ID, connected component, face count, and extraction
status. The detail line reports boundary-wire count and diagnostics. Phase 5's
static `Part::Feature` preview API remains available for compatibility, while
the GUI now creates the Phase 6 `Part::FeaturePython` preview linked to the
source object.

## Implementation contract

- `SurfaceContourGui.py` owns only selection validation, task-panel widgets,
  and command registration.
- `SurfaceRegions.detect_surface_regions()` remains the only grouping policy.
- `SurfaceContours.extract_region_contours()` remains the only physical
  boundary algorithm.
- `SurfaceContours.create_region_contour_preview()` remains a static snapshot
  helper; `create_parametric_region_contour()` owns recomputable previews.
- Headless imports stay safe; GUI-only classes are loaded behind
  `FreeCAD.GuiUp`.

## Deliberate limits

Phase 6 recomputes from the current shape and stores revision-local region IDs;
it does not infer semantic regions such as “upper sole” versus “lower sole”.
Curved faces can be selected and previewed when their physical boundary is
available, but smooth/semantic segmentation remains a later policy phase.

The packaged gate now runs 59 surface-contour tests: the 46 existing fixture,
individual-face, surface-region, and grouped-region tests, six Phase 5
selection/preview tests, and seven Phase 6 parametric-feature tests.

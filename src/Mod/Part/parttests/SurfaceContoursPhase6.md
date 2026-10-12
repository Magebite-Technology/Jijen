# Phase 6: parametric contour previews

Phase 6 turns the Phase 5 object-level workflow into a recomputable FreeCAD
feature. The user still selects one object and never has to pick faces by
hand, but the created preview now stores its source link, grouping policy, and
optional region IDs.

## User workflow

1. Select exactly one Part object in the model tree.
2. Run **Part → Surface contours**.
3. Choose **Coplanar connected regions** or **Every individual face**.
4. Create one selected preview or all previews.
5. Continue editing the source and press **Recompute**. The preview rebuilds
   its contour geometry and metadata from the current source shape.

The preview is a `Part::FeaturePython` object. It exposes the source link,
grouping policy, requested region IDs, resolved region IDs, component IDs,
source face indices, contour status, diagnostics, and the last error. Region
IDs and face indices are intentionally revision-local: after a topology edit,
the proxy re-detects the current regions and reports missing requested IDs
instead of silently using stale face references.

## Implementation contract

- `RegionContourFeature.execute()` is the only recompute path.
- Detection remains delegated to `SurfaceRegions.detect_surface_regions()`.
- Physical boundary extraction remains delegated to
  `SurfaceContours.extract_region_contours()`.
- The source object is linked as a dependency and is never modified.
- `create_region_contour_preview()` remains available as a static snapshot API
  for compatibility; the GUI now calls `create_parametric_region_contour()`.
- Headless imports remain safe; the GUI task panel is still guarded by
  `FreeCAD.GuiUp`.

## Deliberate limits

This phase does not infer semantic regions such as upper sole versus lower
sole, and it does not promise persistent semantic IDs across arbitrary
topology edits. It recomputes a geometric policy (coplanar or individual)
against the current BRep. Smooth-face segmentation, feature-history-aware
references, and explicit region naming remain later phases.

The packaged gate now runs 59 surface-contour tests: the 52 tests through
Phase 5 plus seven parametric-feature tests.

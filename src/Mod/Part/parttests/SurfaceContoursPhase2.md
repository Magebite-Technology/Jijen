<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Phase 2: individual-face contours

Phase 2 implements read-only extraction and static previews of each CAD face's
physical 3D boundary. Selectable multi-face regions arrive in Phase 3; the final
task panel arrives in Phase 5. The implementation has no GUI or camera dependency.

## Usage in the FreeCAD Python console

Select an object in the tree, then run:

```python
import SurfaceContours
source = Gui.Selection.getSelection()[0]
results = SurfaceContours.extract_face_contours(source)
[(r.face_name, r.status, len(r.wires), r.diagnostics) for r in results]
```

To create previews of all successful faces:

```python
results, previews = SurfaceContours.create_contour_preview(source)
```

To preview only the first CAD face:

```python
results, previews = SurfaceContours.create_contour_preview(source, face_indices=[0])
```

Each preview is a separate `Part::Feature` containing all that face's physical
boundary loops. The source remains visible and unchanged. The blue preview lines
can be inspected in any view. Creation is one undoable transaction. Face indices
are zero-based; `face_name` exposes FreeCAD's one-based `Face1` naming.

Raw Part shapes are also accepted by extraction. For their previews, provide an
explicit output document with `document=doc`.

## Geometry guarantees

- Preserve native lines, circles, and splines; no flattening or tessellation.
- Keep every hole and separate boundary loop.
- Exclude kernel-classified parameter seams and degenerate pole edges.
- Connect edges using topological vertex identity; never merge independent
  vertices based only on their coordinates or invent missing segments.
- Return one result per face, including valid empty results and failed faces.
- Resolve document-object and link placement once through `Part.getShape`.
- Return static snapshots: source edits do not update previously created previews.

A full sphere or torus has `no_boundary`. A cylinder wall has two circular loops.
A square pyramid has five face results; a cube has six. A subdivided cube still
has 24 individual face results in Phase 2; combining them into six regions is
Phase 3. The curved sole fixture yields individual patch boundaries, not its
three labelled semantic regions.

## Diagnostics

Input resolution raises `ContourInputError` with `status` equal to
`unsupported_input` or `null_shape`. Per-face results use `ok`, `no_boundary`,
`invalid_geometry`, `open_boundary`, or `non_manifold`, with diagnostic text.
Preview creation only creates objects for `ok` results. It returns all results
so a caller can display failures and valid empty faces rather than hiding them.
Open chains are retained for diagnosis and are never silently healed.

## Validation

`parttests.TestSurfaceContours.TestSurfaceContours` is registered in the Part
test suite and installed with the application. Tests cover analytic perimeters,
holes/native circles, curved spline boundaries, cylinder/cone/sphere/torus seams,
reversed faces, small edges, source immutability, disconnected components,
invalid-face isolation, broken chains, branching, transformed objects/links,
preview selection, and undo. No test requires a GUI.

The Windows beta gate runs both Phase 1 fixture validation and Phase 2 extraction
tests against the packaged application. Publication requires both suites to pass.

## Remaining phases

The backend and console preview are usable now. Automatic grouping, grouped-region
boundaries, the user-facing command/panel, and parametric recompute remain in
Phases 3–6. The actual sole CAD model is still required to agree on and validate
its intended surface regions.

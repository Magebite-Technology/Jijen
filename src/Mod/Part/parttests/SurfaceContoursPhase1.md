<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Surface contours: Phase 1 geometry contract

Status: executable reference fixtures implemented; real-sole acceptance pending.
Repository baseline: `5d38845ba38919b8c84135c86d92549e90730ed3`.

## User outcome

Select one document object, obtain automatically detected surface regions,
preview one region or all regions, and create their true 3D boundary curves.
The user chooses a detected region without collecting its constituent faces.
Any orientation is supported. Camera direction does not participate in detection
or extraction. Projection to a drawing plane is a separate future operation.

Phase 1 establishes the contract and labelled test geometry. It does not add a
production extractor, grouping engine, command, or task panel.

## Input and terminology

The initial supported input is a non-null Part BRep shape resolved from one
selected object. It can contain a solid, shell, face, multiple solids, or a
compound of those. Resolve document links and compose placements exactly once
in later implementation. Disconnected components remain separate. A group
without a resolved shape must produce a clear unsupported-input result; mesh
segmentation and implicitly collecting every child object are outside scope.

A CAD face is a trimmed parametric surface patch. A surface region is one face
or a connected set of faces selected by the detection policy. A contour is the
physical boundary of that region in 3D, represented by ordered native curves.
A region may have zero, one, or multiple boundary loops. It is not necessarily
planar and is not required to have a single outer contour.

Two policies are planned:

1. Individual faces: each CAD face becomes a region. Parameter seams and
   degenerate edges still do not become physical contours.
2. Grouped surfaces: merge edge-connected coplanar patches first. Smooth
   grouping is a later opt-in policy using shared-edge continuity and oriented
   normals, with a recorded angle threshold. Never merge disconnected patches
   merely because their normals match or their underlying surfaces coincide.

Coplanar grouping is the conservative default. For analytic coplanar regions,
the eventual policy must check plane separation as well as normal alignment.
Use source topological adjacency; geometric closeness alone is insufficient.
Respect component boundaries, even when independent components touch.

Smooth grouping cannot promise semantic labels such as upper, lower, or wall.
If a blend is continuous across the intended split, geometry may offer no
unique boundary. Report the resulting connected region and the limitation.
Do not manufacture an edge using a camera direction or global height.

## Boundary rules

Evaluate each region independently. An ordinary edge incident to one member
face is a boundary; an edge joining two member faces is internal. An edge
between two different regions belongs to the contour of each region. Extracting
all regions must therefore not cancel all the edges of a closed cube.

Use oriented edge occurrences and topology, not rounded endpoint coordinates.
A periodic seam can occur twice on the same face and must be excluded using
the kernel's seam classification. Exclude degenerate edges with no physical
length. A sphere has no physical boundary, although its CAD representation
contains a seam and degenerate pole edges. A cylindrical wall has two circular
boundaries; its parameter seam is not a third contour.

Assemble remaining edges into ordered wires. Retain exact line, circle,
ellipse, and spline geometry; tessellation is allowed for display only.
Preserve holes and separate loops. Winding and outer/inner classification are
meaningful relative to an oriented surface, not a global XY plane. For curved
regions that classification can be unavailable: retain loops without forcing
one of them to be an outer planar contour. A perimeter wall can have two loops.

Closed wires are the normal success result for manifold trimmed surfaces.
Detect branching or non-manifold incidence before applying the two-face rule.
Return diagnostics for unsupported branching, invalid shape, or a broken/open
boundary. Do not silently heal gaps, invent closing segments, or discard failed
regions from an otherwise successful extraction.

## Proposed result contract for later phases

Each result contains source object/component identity, detection settings,
region identifier, source face references, boundary wires, and diagnostics.
Face indices used in these fixtures are zero-based labels of fixed geometry;
they are not persistent identifiers for edited source objects.

Region status must distinguish `ok`, `no_boundary`, `invalid_geometry`,
`open_boundary`, and `non_manifold`. Input resolution additionally reports
`unsupported_input` or `null_shape`. A failed region does not invalidate the
identity or diagnostics of the other regions. Zero contours is a valid success
for a closed surface and must not appear as extraction failure.

Geometry is in document units, with world placement applied once to outputs.
Joining uses existing topology and kernel edge/vertex tolerances. Later phases
must record grouping angle and distance settings, reject non-positive or
non-finite user values, and test scale sensitivity. The `1e-7` mm checks in
the fixture tests verify their clean constructed geometry; they are not a
universal production healing tolerance.

## Executable reference models

Builders and region labels live in
`src/Mod/Part/parttests/surface_contour_fixtures.py`.
All lengths below are millimetres. Expected boundaries are constructed from
the source's known geometry independently of any future detection algorithm.

| Model | CAD faces | Labelled regions | Expected boundary loops | Additional checks |
|---|---:|---:|---:|---|
| Cube, side 20 | 6 | 6 | 6 total; one per region | Each perimeter 80; volume 8000 |
| Square pyramid, base 20, height 20 | 5 | 5 | 5 total; one per region | Base perimeter 80; slope perimeter 20 + 2 sqrt(600); volume 8000/3 |
| Cube with four patches per side | 24 | 6 | 6 total; one per group | Shared patch edges are internal; same volume and contours as cube |
| Cylinder, radius 10, height 20 | 3 | 3 | 4 total | Wall has two circles, each length 20 pi; caps each have one circle |
| Sphere, radius 10 | 1 | 1 | 0 | Seam and pole edges are excluded |
| Annulus, radii 20 and 8 | 1 | 1 | 2 | Hole retained; area 336 pi |
| Synthetic curved sole shell | 7 | 3 oracle regions | 4 total | Upper: two spline patches, one nonplanar boundary; lower: one loop; wall: two loops |
| Two disconnected cubes | 12 | 12 | 12 total | Coplanar sides on different components remain separate |

For the subdivided cube, individual-face mode has 24 regions and 24 loops.
For the synthetic sole, individual-face mode has seven regions and one loop
per face. Its three grouped labels express the intended target partition;
the wall's corner transitions mean conservative coplanar grouping alone will
not recover that partition. This is deliberately not a claim of generic
smooth grouping success. The synthetic shell is an algorithm test object,
not a manufacturing model or a substitute for the real sole.

## Inspecting the fixtures

In FreeCAD's Python console, add the checkout's `src/Mod/Part` directory to
`sys.path`, then run:

```python
from parttests import surface_contour_fixtures as fixtures
doc = fixtures.create_document()
Gui.activeDocument().activeView().viewAxonometric()
Gui.activeDocument().activeView().fitAll()
```

This creates a new document with eight source objects and hidden expected
contour objects, grouped by fixture. Toggle an expected contour's visibility
to inspect it. Each stores its fixture-local source face indices. No existing
document is edited. Save the document to a new filename if a persistent CAD
sample is needed.

Tests are registered in `TestPartApp.py` and installed through the Part
`CMakeLists.txt`. To run only this suite in a Python runtime that supplies
FreeCAD and Part, from the checkout root:

```python
import sys, unittest
sys.path.insert(0, "src/Mod/Part")
from parttests.TestSurfaceContourFixtures import TestSurfaceContourFixtures
suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestSurfaceContourFixtures)
result = unittest.TextTestRunner(verbosity=2).run(suite)
```

The tests verify fixture validity, complete non-overlapping face labels,
reference wire closure, analytic measurements, seam expectations, a shared
edge between the upper sole patches, and creation of a separate document.
They validate inputs and expected results; they do not test production
extraction that has not yet been implemented.

## Acceptance cases for the following phases

| Case | Required result | First applicable phase |
|---|---|---|
| Rotate the view | Identical region membership and 3D curves | 2 |
| Individual cube/pyramid faces | Six/five regions and native closed wires | 2 |
| Annulus | Both loops retained | 2 |
| Cylinder/sphere | Correct seam exclusion and valid empty sphere result | 2 |
| Subdivided cube | Six connected coplanar groups | 3 |
| Disconnected cubes | Twelve groups | 3 |
| Grouped cube boundary | Six per-region loops, internal patch edges absent | 4 |
| Synthetic curved upper sole | One nonplanar native spline boundary | 4 |
| Non-manifold or broken input | Explicit region diagnostics, no silent healing | 4 |
| Object translated/rotated or linked | Placement composed once, unchanged measurements | 6 |
| Source face ordering changes | Selection preserved reliably or flagged for review | 6 |
| Real sole with multiple parts | Agreed region membership and physical boundary curves | 7 |

## Real-sole acceptance record: pending input

The screenshot is insufficient to identify BRep face membership, adjacency,
or intended region boundaries. Before calling the real-sole requirement done,
record a CAD file and checksum, units, selected source object/component scope,
named intended regions, face membership or annotated reference geometry,
outer and hole boundaries, and blends whose split is ambiguous. Include the
user's upper-region example where lower geometry extends beyond the upper
region: the extracted upper contour must follow the upper region alone.

The real-sole case remains pending until that file and intended partition can
be inspected. Synthetic acceptance must not be reported as real-sole approval.

## Phase 1 completion

The geometry contract, executable synthetic models, labelled boundary oracles,
and fixture validation are delivered. The remaining Phase 1 acceptance item is
agreement on the real sole's intended regions using its CAD geometry. Phase 2
can proceed against the synthetic contract while that item is pending.

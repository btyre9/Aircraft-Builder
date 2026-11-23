# Aircraft Builder

Parametric aircraft for Blender (4.2+, tested on 5.3), built on CAD-style
**live** lofts and sweeps. Surfaces stay linked to the curves they were made
from and rebuild the moment a curve moves, scales, or is edited, much like
Fusion 360's history. Find everything in the 3D Viewport sidebar (N) under
**Aircraft Builder**.

(Formerly "Loft & Sweep". Files saved with the old version keep working.)

## Tools

**Loft Selected**: skins a surface through two or more curves (all closed,
like fuselage rings, or all open). Profiles are ordered automatically along the
direction they are spread out, start points are matched to avoid twisting, and
the surface curves smoothly through every profile. Add **guide rails** in the
Surface panel to bend the surface between profiles, as Fusion's loft rails do
(for example, a wing-to-body fairing).

**Sweep Selected**: moves a profile along a path. Select the profile, the
path, and optionally a guide rail, with the **path active**.
- *Perpendicular* keeps the profile square to the path (pipes, ducts).
- *Parallel* keeps the profile facing its original direction (wings, fins).
- A *guide rail* scales and turns the profile so it stays on the rail. For a
  wing: path = leading edge, rail = trailing edge, profile = root airfoil. The
  chord then follows the planform automatically.

Surface settings: profile points, curve detail (more points where profiles
bend), caps (open, fan, strip, n-gon), sharp-corner shading, twist, end scale,
and **Mirror X** for building one side. **Convert to Plain Mesh** stops the
live link so you can edit vertices by hand.

**Add Airfoil**: NACA 4-digit (e.g. 2412 = 2% camber at 40% chord, 12% thick)
or a `.dat` file from an airfoil database such as the UIUC Airfoil Coordinates
Database (Selig and Lednicer formats). Change the code later in the Airfoil
panel; scale the curve object to change the chord.

## Aircraft

**Small Jet** builds a light business jet from a length (and optional wingspan
and body diameter), using conceptual-design rules of thumb: fuselage fineness
about 8.5, wingspan about equal to length, wing aspect ratio 8.5 with 0.4
taper, and tails sized with tail volume coefficients. Choose a T-tail or a
conventional tail, with or without rear engines. Every part is live:

- Fuselage and engines: loft through ellipse rings. Scale a ring in X (width)
  or Z (height), or move it in Z to droop the nose or raise the tail.
- Wing, tails, pylons: airfoil swept along a leading-edge line with the
  trailing-edge line as the guide rail. Move the line end points to change
  span, sweep, taper, or dihedral.

Wings start at the centerline, buried inside the fuselage, so the wing-to-body
intersection is always clean. The control curves live in the
"Small Jet Controls" collection (hidden from renders).

**Wing fairing**: the smooth bulge where the wing meets the belly (added to the
Small Jet by default; **Add Wing Fairing** adds one to the active wing). It
blends from the wing's cross-section, a little way out along the span, to a
larger outline on the centerline. The blend has zero slope at both ends, so it
leaves the wing without a crease and the mirrored halves meet smoothly. That
smooth blend does the job of the four guide rails used in Fusion. Settings:

- **Reach**: how far out along the wing it blends in; set it a little past the
  side of the fuselage.
- **Forward / Aft / Depth / Top**: the centerline outline, as fractions of the
  wing chord. **Fullness** keeps it fuller farther out.
- **Make Outline Editable** turns that outline into a smooth closed curve. Edit
  its points in side view (numpad 3) to draw the belly profile yourself, like
  sketching it on the symmetry plane in Fusion.

The fairing follows the wing: change the airfoil, span, or sweep and it
rebuilds with it.

**Single Engine** builds a four-seat single-engine piston aircraft from a
length (about 7 to 9 m for this class): high wing with struts, or low wing with
more dihedral; fixed tricycle gear with wheel fairings; 2- or 3-blade propeller.
Proportions: wingspan about 1.33 x length, aspect ratio 7.4 with a
constant-chord inner wing and tapered outer panel, cabin about 0.14 x length
wide, tail volumes 0.70 (horizontal) and 0.04 (vertical), propeller about
0.23 x length with the gear keeping its tips off the ground. New live parts:

- Fuselage rings are rounded boxes (Bezier handles longer than a circle's).
- Struts and gear legs: a streamlined airfoil swept along a line. Edit the
  line's end points to move them.
- Propeller: one blade (airfoil swept out from the hub with 30° of twist and
  tapering chord), repeated by an Array modifier around the "Propeller Hub"
  empty. Edit the blade line to change the diameter.

### Details on both builders

- **Windshield and windows**: glass patches projected onto the fuselage from
  outline curves, sitting a small gap above the skin with a dark glass
  material. Each outline's plane sets the projection direction: side windows
  are drawn in side view, the windshield outline is tilted to face the
  windshield slope. Move or edit an outline (or reshape the fuselage) and the
  glass follows. **Project Window** (Create panel) does the same for any body:
  select the outline curve, then the body last.
- **Dorsal fin**: a low strake from the spine up into the fin leading edge.
- **Wheels**: tires with hub caps, lofted around the axle; on fixed gear they
  sit inside the wheel fairings with the tire poking out below.
- **Retractable gear** (Single Engine option; the Small Jet's gear): main gear
  folds inward, nose gear folds forward, each leg pivoting at its top. Drag the
  **Landing Gear** slider in the Aircraft panel (0 down, 1 up), or keyframe it
  to animate. Left and right main gear are separate parts so each can swing.

**Add Fuselage** and **Add Wing** add the parts on their own.
**Set Up Blueprints** places side, top, and front images at real size with the
nose at the origin. Crop each image so the aircraft touches the edges (side:
nose left; top: nose up; front: wingtip to wingtip).

Axes: nose at the origin pointing -Y, body along +Y, span along X, Z up.

## Development

```bash
python3 -m unittest tests.test_core          # geometry, no Blender needed
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
    --python tests/blender_smoke.py -- /tmp/renders   # live checks + preview renders
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
    --python tests/blender_piston.py -- /tmp/renders  # single-engine builder checks
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
    --python tests/blender_details.py -- /tmp/renders # windows, wheels, retractable gear
/Applications/Blender.app/Contents/MacOS/Blender --command extension build \
    --source-dir aircraft_builder --output-dir dist   # installable zip
```

`core.py` (loft, sweep, resampling, airfoils, mesh assembly) and `design.py`
(jet proportions) are plain Python; the Blender modules are `build.py`
(sampling curves, live rebuilds), `aircraft.py`, `ops.py`, `props.py`, `ui.py`.

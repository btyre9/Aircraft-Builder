# Loft & Sweep

CAD-style **live** lofts and sweeps for Blender (4.2+, tested on 5.3), plus
airfoils and aircraft starters. Surfaces stay linked to the curves they were
made from and rebuild the moment a curve moves, scales, or is edited, much like
Fusion 360's history. Find everything in the 3D Viewport sidebar (N) under
**Loft & Sweep**.

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
/Applications/Blender.app/Contents/MacOS/Blender --command extension build \
    --source-dir loft_sweep --output-dir dist         # installable zip
```

`core.py` (loft, sweep, resampling, airfoils, mesh assembly) and `design.py`
(jet proportions) are plain Python; the Blender modules are `build.py`
(sampling curves, live rebuilds), `aircraft.py`, `ops.py`, `props.py`, `ui.py`.

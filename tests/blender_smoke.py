"""Headless Blender test. Run:

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
        --python tests/blender_smoke.py -- [render_dir]
"""

import math
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import loft_sweep  # noqa: E402
from loft_sweep import aircraft, build  # noqa: E402

loft_sweep.register()
failures = []


def check(condition, message):
    print(("PASS " if condition else "FAIL ") + message)
    if not condition:
        failures.append(message)


# Empty scene.
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj)
context = bpy.context

# --- Small jet -------------------------------------------------------------------
jet, objects = aircraft.build_small_jet(context, 14.0)
for obj in objects:
    check(not obj.lsw.status and len(obj.data.vertices) > 50,
          f"{obj.name}: {len(obj.data.vertices)} verts {obj.lsw.status!r}")

fuselage = bpy.data.objects["Fuselage"]
dims = fuselage.dimensions
check(abs(dims.y - 14.0) < 0.05, f"fuselage length {dims.y:.3f}")
wing = bpy.data.objects["Wing"]
depsgraph = context.evaluated_depsgraph_get()
wing_eval = wing.evaluated_get(depsgraph)
check(abs(wing_eval.dimensions.x - jet.span) < 0.05, f"mirrored wingspan {wing_eval.dimensions.x:.3f} vs {jet.span:.3f}")

# Watertight fuselage with outward normals.
edge_faces = {}
for poly in fuselage.data.polygons:
    for key in poly.edge_keys:
        edge_faces[key] = edge_faces.get(key, 0) + 1
check(all(v == 2 for v in edge_faces.values()), "fuselage is watertight")

# --- Live update: move a ring and the fuselage follows ---------------------------
ring = bpy.data.objects["Fuselage Ring 09"]
before = fuselage.dimensions.z
ring.scale.y *= 1.5  # local Y is world height
context.view_layer.update()
after = fuselage.dimensions.z
check(after > before + 0.1, f"live rebuild after scaling a ring: height {before:.3f} -> {after:.3f}")
ring.scale.y /= 1.5
context.view_layer.update()

# Live update: drag the wing tip leading edge outward (edit the line curve).
le = bpy.data.objects["Wing Leading Edge"]
te = bpy.data.objects["Wing Trailing Edge"]
for curve in (le, te):
    curve.data.splines[0].points[1].co.x += 1.0
context.view_layer.update()
wing_eval = wing.evaluated_get(context.evaluated_depsgraph_get())
check(abs(wing_eval.dimensions.x - (jet.span + 2.0)) < 0.05, f"span follows edited curve: {wing_eval.dimensions.x:.3f}")
for curve in (le, te):
    curve.data.splines[0].points[1].co.x -= 1.0
context.view_layer.update()

# Airfoil code change rebuilds the sweep.
airfoil = bpy.data.objects["Wing Airfoil"]
thin = wing.dimensions.z
airfoil.lsw_airfoil.naca = "2420"
context.view_layer.update()
check(wing.dimensions.z > thin + 0.05, f"NACA 2412 -> 2420 thickens wing: {thin:.3f} -> {wing.dimensions.z:.3f}")
airfoil.lsw_airfoil.naca = "2412"
context.view_layer.update()

# --- Generic operators -------------------------------------------------------------
scratch = bpy.data.collections.new("Scratch")
context.scene.collection.children.link(scratch)
layer_collection = context.view_layer.layer_collection.children["Scratch"]
context.view_layer.active_layer_collection = layer_collection
rings = [build.ring_curve(f"R{i}", scratch, (20.0, 3.0 * i, 0.0), 1 + (i % 2), 1.0) for i in range(3)]
for obj in context.selected_objects:
    obj.select_set(False)
for r in reversed(rings):  # selection order should not matter
    r.select_set(True)
context.view_layer.update()
with context.temp_override(selected_objects=rings, active_object=rings[0]):
    result = bpy.ops.lsw.loft()
loft_obj = context.view_layer.objects.active
check(result == {"FINISHED"} and loft_obj.lsw.kind == "LOFT", "Loft Selected operator")
check([p.obj.name for p in loft_obj.lsw.profiles] == ["R0", "R1", "R2"], "profiles sorted along their spread")

profile = build.ring_curve("Pipe Profile", scratch, (30.0, 0.0, 0.0), 0.4, 0.4)
path = build.line_curve("Pipe Path", scratch, [(30, 0, 0), (30, 4, 0), (33, 7, 0), (36, 7, 2)])
context.view_layer.update()
with context.temp_override(selected_objects=[profile, path], active_object=path):
    result = bpy.ops.lsw.sweep()
sweep_obj = context.view_layer.objects.active
check(result == {"FINISHED"} and sweep_obj.lsw.path == path and sweep_obj.lsw.profile == profile,
      "Sweep Selected picks profile and path")
check(not sweep_obj.lsw.status and len(sweep_obj.data.vertices) > 100, f"pipe sweep: {sweep_obj.lsw.status!r}")

with context.temp_override(selected_objects=[sweep_obj], active_object=sweep_obj):
    bpy.ops.lsw.freeze()
check(sweep_obj.lsw.kind == "NONE", "convert to plain mesh")
bpy.data.collections.remove(scratch)
for obj in list(bpy.data.objects):
    if obj.name.startswith(("R0", "R1", "R2", "Pipe", "Loft", "Sweep")):
        bpy.data.objects.remove(obj)

# --- Optional preview renders --------------------------------------------------------
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if args:
    out = Path(args[0])
    out.mkdir(parents=True, exist_ok=True)
    scene = context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "SINGLE"
    scene.display.shading.show_cavity = True
    scene.render.resolution_x, scene.render.resolution_y = 1200, 760
    scene.render.film_transparent = False
    bpy.data.collections["Small Jet Controls"].hide_render = True
    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    target = (0.0, 7.0, 0.5)
    for name, direction, lens in (
        ("three_quarter", (-1.0, -0.9, 0.55), 50),
        ("top", (0.0, 0.0001, 1.0), 50),
        ("side", (1.0, 0.0, 0.05), 50),
        ("front", (0.0, -1.0, 0.12), 50),
        ("junction", (-0.55, -0.4, -0.35), 50),
    ):
        length = math.sqrt(sum(c * c for c in direction))
        distance = 9.0 if name == "junction" else 32.0
        focus = (1.2, 7.0, -0.4) if name == "junction" else target
        camera.location = tuple(focus[i] + direction[i] / length * distance for i in range(3))
        look = bpy.data.objects.get("Look") or bpy.data.objects.new("Look", None)
        if look.name not in scene.collection.objects:
            scene.collection.objects.link(look)
        look.location = focus
        constraint = camera.constraints.get("Track") or camera.constraints.new("TRACK_TO")
        constraint.name = "Track"
        constraint.target = look
        camera.data.lens = lens
        scene.render.filepath = str(out / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        print("rendered", scene.render.filepath)

print("FAILURES:", len(failures))
sys.exit(1 if failures else 0)

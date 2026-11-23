"""Headless check of windows, dorsal fins, wheels, and retractable gear. Run:

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
        --python tests/blender_details.py -- [render_dir]
"""

import math
import sys
from pathlib import Path

import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aircraft_builder  # noqa: E402
from aircraft_builder import aircraft  # noqa: E402

aircraft_builder.register()
failures = []
context = bpy.context


def check(condition, message):
    print(("PASS " if condition else "FAIL ") + message)
    if not condition:
        failures.append(message)


def evaluated(obj):
    return obj.evaluated_get(context.evaluated_depsgraph_get())


def points(obj):
    e = evaluated(obj)
    return [e.matrix_world @ v.co for v in e.data.vertices]


def bounds(obj):
    pts = points(obj)
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def set_gear(control, value):
    """Like dragging the Gear slider: change the value and tag the control for re-evaluation."""
    control["retract"] = value
    control.update_tag()
    context.view_layer.update()


def find(objects, name):
    return next(o for o in objects if o.name.split(".")[0] == name)


def glass_gap(window, body):
    """Largest distance from the glass to the body surface."""
    e = evaluated(body)
    tree = BVHTree.FromObject(e, context.evaluated_depsgraph_get())
    inverse = e.matrix_world.inverted()
    gaps = []
    for p in points(window):
        nearest = tree.find_nearest(inverse @ p)[0]
        gaps.append(((e.matrix_world @ nearest) - p).length)
    return max(gaps)


for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj)
spots = {}

# --- Fixed-gear single: windows, dorsal fin, wheels in fairings --------------------------
plan, objects = aircraft.build_single_piston(context, 8.3, name="Fixed")
for obj in objects:
    check(not obj.lsw.status and len(obj.data.vertices) > 4, f"Fixed / {obj.name}: {obj.lsw.status!r}")
fuselage = find(objects, "Fuselage")
for name in ("Windshield", "Side Windows"):
    glass = find(objects, name)
    gap = glass_gap(glass, fuselage)
    check(gap < 0.016, f"{name} hugs the fuselage (max gap {gap * 1000:.1f} mm)")
    check(glass.data.materials and glass.data.materials[0].name == "Aircraft Builder Glass", f"{name} is glass")
low, high = bounds(find(objects, "Side Windows"))
check(low[0] < -0.4 and high[0] > 0.4, "side windows on both sides")
low, high = bounds(find(objects, "Windshield"))
check(high[0] - low[0] > 0.6, f"windshield wraps across the nose ({high[0] - low[0]:.2f} m wide)")
check(find(objects, "Dorsal Fin").lsw.status == "", "dorsal fin built")

for wheel_name, pant_name in (("Main Wheel", "Main Wheel Fairing"), ("Nose Wheel", "Nose Wheel Fairing")):
    w_low, w_high = bounds(find(objects, wheel_name))
    p_low, p_high = bounds(find(objects, pant_name))
    inside = all(p_low[i] <= w_low[i] and w_high[i] <= p_high[i] for i in (0, 1)) and w_high[2] <= p_high[2]
    check(inside, f"{wheel_name} sits inside its fairing")
    check(w_low[2] < p_low[2], f"{wheel_name} tire pokes out below the fairing ({(p_low[2] - w_low[2]) * 100:.1f} cm)")

# Live: moving the outline moves the glass; reshaping the fuselage reshapes the windshield.
outline = bpy.data.objects["Side Windows Outline"]
before = bounds(find(objects, "Side Windows"))[1][1]
outline.location.y += 0.3
context.view_layer.update()
after = bounds(find(objects, "Side Windows"))[1][1]
check(abs(after - before - 0.3) < 0.05, f"side windows follow their outline ({after - before:+.2f} m)")
outline.location.y -= 0.3
shield = find(objects, "Windshield")
before = [p.copy() for p in points(shield)]
ring = bpy.data.objects["Fuselage Ring 05"]
ring.location.z += 0.08
context.view_layer.update()
moved = max((a - b).length for a, b in zip(points(shield), before))
check(moved > 0.02, f"windshield follows the fuselage ({moved * 100:.1f} cm)")
ring.location.z -= 0.08
context.view_layer.update()
spots["fixed"] = (0.0, 0.0)

# --- Retractable single: the Gear slider folds the gear -----------------------------------
plan, objects = aircraft.build_single_piston(context, 8.3, wing="LOW", gear="RETRACTABLE", name="Retract")
for obj in objects:
    check(not obj.lsw.status, f"Retract / {obj.name}: {obj.lsw.status!r}")
control = bpy.data.objects["Retract Landing Gear"]
wheels = {n: find(objects, n) for n in ("Main Wheel Right", "Main Wheel Left", "Nose Wheel")}
down = {n: bounds(o) for n, o in wheels.items()}
leg = find(objects, "Main Gear Leg Right")
leg_top_down = max(points(leg), key=lambda p: p.z).copy()
set_gear(control, 1.0)
up = {n: bounds(o) for n, o in wheels.items()}
for n in wheels:
    rise = up[n][0][2] - down[n][0][2]
    check(rise > 0.3, f"{n} folds up {rise:.2f} m")
check(up["Main Wheel Right"][1][0] < down["Main Wheel Right"][1][0] - 0.3, "right main folds inward")
check(up["Main Wheel Left"][0][0] > down["Main Wheel Left"][0][0] + 0.3, "left main folds inward")
check(up["Nose Wheel"][0][1] < down["Nose Wheel"][0][1] - 0.3, "nose wheel folds forward")
pivot = bpy.data.objects["Main Gear Right Pivot"].matrix_world.translation
check((pivot - leg_top_down).length < 0.15, "leg stays attached at its pivot")

# A live rebuild while folded keeps everything where it is.
wheel = wheels["Main Wheel Right"]
folded = bounds(wheel)
from aircraft_builder import build  # noqa: E402
build.rebuild(wheel)
build.rebuild(leg)
context.view_layer.update()
after = bounds(wheel)
check(max(abs(a - b) for a, b in zip(folded[0] + folded[1], after[0] + after[1])) < 1e-4,
      "rebuilding while retracted keeps the folded position")
set_gear(control, 0.0)
back = bounds(wheel)
check(max(abs(a - b) for a, b in zip(back[0] + back[1], down["Main Wheel Right"][0] + down["Main Wheel Right"][1])) < 1e-4,
      "gear comes back down exactly")

# --- Small jet: gear, windows, dorsal --------------------------------------------------------
jet, objects = aircraft.build_small_jet(context, 14.0, name="Jet")
for obj in objects:
    check(not obj.lsw.status, f"Jet / {obj.name}: {obj.lsw.status!r}")
jet_fuselage = find(objects, "Fuselage")
for name in ("Windshield", "Cabin Windows"):
    gap = glass_gap(find(objects, name), jet_fuselage)
    check(gap < 0.016, f"jet {name} hugs the fuselage ({gap * 1000:.1f} mm)")
jet_control = bpy.data.objects["Jet Landing Gear"]
nose = find(objects, "Nose Wheel")
nose_down = bounds(nose)
set_gear(jet_control, 1.0)
check(bounds(nose)[0][2] > nose_down[0][2] + 0.4, "jet nose gear retracts")
set_gear(jet_control, 0.0)

# Spread the three aircraft out for renders.
for collection, dx in (("Retract", -13.0), ("Jet", 16.0)):
    for obj in bpy.data.collections[collection].all_objects:
        if obj.parent is None:
            obj.location.x += dx
context.view_layer.update()

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if args:
    out = Path(args[0])
    out.mkdir(parents=True, exist_ok=True)
    scene = context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_cavity = True
    scene.render.resolution_x, scene.render.resolution_y = 1200, 760
    for collection in bpy.data.collections:
        if collection.name.endswith("Controls"):
            collection.hide_render = True
    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    look = bpy.data.objects.new("Look", None)
    scene.collection.objects.link(look)
    camera.constraints.new("TRACK_TO").target = look
    shots = [
        ("fixed_front_quarter", (0.0, 3.0, 0.0), (-0.9, -1.2, 0.45), 11.0, None),
        ("fixed_side", (0.0, 4.0, -0.2), (1.0, 0.0, 0.02), 13.0, None),
        ("fixed_tail", (0.0, 6.0, 0.6), (-1.0, 0.4, 0.35), 5.5, None),
        ("retract_down", (-13.0, 3.5, -0.3), (-1.0, -0.8, -0.15), 11.0, 0.0),
        ("retract_half", (-13.0, 3.5, -0.3), (-1.0, -0.8, -0.15), 11.0, 0.5),
        ("retract_up", (-13.0, 3.5, -0.3), (-1.0, -0.8, -0.15), 11.0, 1.0),
        ("jet_front_quarter", (16.0, 5.0, 0.0), (-0.9, -1.1, 0.3), 19.0, None),
    ]
    for label, focus, direction, distance, retract in shots:
        if retract is not None:
            set_gear(control, retract)
        size = math.sqrt(sum(c * c for c in direction))
        look.location = focus
        camera.location = tuple(focus[i] + direction[i] / size * distance for i in range(3))
        scene.render.filepath = str(out / f"{label}.png")
        bpy.ops.render.render(write_still=True)

print("FAILURES:", len(failures))
sys.exit(1 if failures else 0)

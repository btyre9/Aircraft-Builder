"""Headless check of the single-engine builder. Run:

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
        --python tests/blender_piston.py -- [render_dir]
"""

import math
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aircraft_builder  # noqa: E402
from aircraft_builder import aircraft  # noqa: E402

aircraft_builder.register()
failures = []


def check(condition, message):
    print(("PASS " if condition else "FAIL ") + message)
    if not condition:
        failures.append(message)


def world_bounds(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    points = [evaluated.matrix_world @ v.co for v in evaluated.data.vertices]
    return [min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]


for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj)
context = bpy.context
renders = {}

for wing in ("HIGH", "LOW"):
    name = f"{wing.title()} Wing"
    plan, objects = aircraft.build_single_piston(context, 8.3, wing=wing, blades=2 if wing == "HIGH" else 3,
                                                 name=name)
    parts = {o.name.split(".")[0]: o for o in objects}
    for obj in objects:
        check(not obj.lsw.status and len(obj.data.vertices) > 20, f"{name} / {obj.name}: {obj.lsw.status!r}")

    prop = next(o for o in objects if o.name.startswith("Propeller"))
    low, high = world_bounds(prop)
    diameter = plan.summary["Propeller diameter (m)"]
    evaluated = prop.evaluated_get(context.evaluated_depsgraph_get())
    hub = evaluated.matrix_world.translation
    tip = max(math.hypot(*(evaluated.matrix_world @ v.co - hub).xz) for v in evaluated.data.vertices)
    check(abs(2 * tip - diameter) < 0.08, f"{name}: propeller diameter {2 * tip:.2f} vs {diameter:.2f}")
    blades = 2 if wing == "HIGH" else 3
    check(len(evaluated.data.vertices) == blades * len(prop.data.vertices), f"{name}: {blades} blades")

    fuselage = next(o for o in objects if o.name.startswith("Fuselage"))
    f_low, f_high = world_bounds(fuselage)
    check(abs((f_high[1] - f_low[1]) - (8.3 - 0.055 * 8.3)) < 0.05, f"{name}: fuselage length {f_high[1] - f_low[1]:.2f}")
    wing_obj = next(o for o in objects if o.name.startswith("Wing") and o.lsw.kind == "SWEEP"
                    and "Strut" not in o.name)
    w_low, w_high = world_bounds(wing_obj)
    check(abs((w_high[0] - w_low[0]) - plan.span) < 0.05, f"{name}: wingspan {w_high[0] - w_low[0]:.2f}")

    wheels = [o for o in objects if "Wheel Fairing" in o.name]
    ground = min(world_bounds(o)[0][2] for o in wheels)
    check(ground < low[2], f"{name}: wheels ({ground:.2f}) reach below the propeller tip ({low[2]:.2f})")

    if wing == "HIGH":
        strut = next(o for o in objects if o.name.startswith("Wing Strut"))
        s_low, s_high = world_bounds(strut)
        check(s_high[2] > f_high[2] - 0.3 and s_low[2] < 0, f"{name}: strut runs from body side up to the wing")

    # Live: lengthen the blade line and the propeller grows.
    line = bpy.data.objects[f"Propeller Blade Line" + ("" if wing == "HIGH" else ".001")]
    line.data.splines[0].points[1].co.z += 0.2
    context.view_layer.update()
    low2, high2 = world_bounds(prop)
    check((high2[2] - low2[2]) > (high[2] - low[2]) + 0.2, f"{name}: editing the blade line resizes the propeller")
    line.data.splines[0].points[1].co.z -= 0.2
    context.view_layer.update()

    # Park the low-wing plane beside the high-wing one for renders.
    if wing == "LOW":
        for obj in bpy.data.collections[name].all_objects:
            if obj.parent is None:
                obj.location.x -= 14.0
        context.view_layer.update()
        renders[name] = (-14.0, 4.0, 0.0)
    else:
        renders[name] = (0.0, 4.0, 0.0)

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if args:
    out = Path(args[0])
    out.mkdir(parents=True, exist_ok=True)
    scene = context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
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
    constraint = camera.constraints.new("TRACK_TO")
    constraint.target = look
    shots = [
        ("high_three_quarter", renders["High Wing"], (-1.0, -1.1, 0.5), 20.0),
        ("high_side", renders["High Wing"], (1.0, 0.0, 0.03), 18.0),
        ("high_front", renders["High Wing"], (0.0, -1.0, 0.08), 16.0),
        ("low_three_quarter", renders["Low Wing"], (-1.0, -1.1, 0.5), 20.0),
    ]
    for label, focus, direction, distance in shots:
        size = math.sqrt(sum(c * c for c in direction))
        look.location = focus
        camera.location = tuple(focus[i] + direction[i] / size * distance for i in range(3))
        scene.render.filepath = str(out / f"{label}.png")
        bpy.ops.render.render(write_still=True)

print("FAILURES:", len(failures))
sys.exit(1 if failures else 0)

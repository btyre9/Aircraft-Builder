"""Aircraft starters built from live lofts and sweeps.

Every part stays editable the Fusion way: move, scale, or edit the control
curves in the "<name> Controls" collection and the surfaces rebuild.
- Fuselage and engines: loft through ellipse rings. Scale a ring in X for
  width and Z for height; move it in Z to droop the nose or raise the tail.
- Wings and tails: an airfoil swept along a leading-edge line, with the
  trailing-edge line as the guide rail. Move line end points to change span,
  sweep, taper, or dihedral; change the NACA code on the airfoil.
"""

import math

import bpy
from mathutils import Matrix, Vector

from . import build, design


def _collection(name, parent):
    collection = bpy.data.collections.new(name)
    parent.children.link(collection)
    return collection


def add_body(body, parts, controls):
    rings = [
        build.ring_curve(f"{body.name} Ring {i + 1:02d}", controls, (ring.x, ring.y, ring.z), ring.width,
                         ring.height, ring.squareness, body.axis)
        for i, ring in enumerate(body.rings)
    ]
    obj = build.new_result(body.name, "LOFT", parts)
    s = obj.lsw
    for ring in rings:
        s.profiles.add().obj = ring
    s.resolution = 32 if body.mirror else 48
    s.steps = 5
    s.cap_start = s.cap_end = "FAN"
    s.mirror_x = body.mirror
    return obj


def add_surface(surface, parts, controls):
    thickness = (1, 0, 0) if surface.vertical else (0, 0, 1)
    profile = build.airfoil_curve(
        f"{surface.name} Airfoil", controls, surface.root_le, surface.root_chord, (0, 1, 0), thickness, surface.airfoil
    )
    path = build.line_curve(f"{surface.name} Leading Edge", controls, surface.le_points)
    rail = build.line_curve(f"{surface.name} Trailing Edge", controls, surface.te_points)
    obj = build.new_result(surface.name, "SWEEP", parts)
    s = obj.lsw
    s.orientation = "PARALLEL"
    s.resolution = 48
    s.path_steps = 24 if surface.kink > 0 else 16
    s.cap_start = "NONE" if surface.mirror else "STRIP"
    s.cap_end = "STRIP"
    s.twist = math.radians(surface.twist)
    s.mirror_x = surface.mirror
    s.profile, s.path, s.rail = profile, path, rail
    return obj


def add_strut(strut, parts, controls):
    """Streamlined strut or gear leg: airfoil swept along a straight line (edit the line to move it)."""
    start, end = Vector(strut.start), Vector(strut.end)
    direction = (end - start).normalized()
    forward = Vector((0.0, 1.0, 0.0))
    chord_dir = (forward - direction * forward.dot(direction)).normalized()
    thickness_dir = direction.cross(chord_dir)
    if strut.round:  # oleo strut: a circle across the line
        profile = build.ring_curve(f"{strut.name} Section", controls, tuple(start), strut.chord, strut.chord)
        basis = Matrix((chord_dir, thickness_dir, direction)).transposed().to_4x4()
        radius = strut.chord / 2
        profile.matrix_world = Matrix.Translation(start) @ basis @ Matrix.Diagonal((radius, radius, radius, 1.0))
    else:
        leading_edge = start - chord_dir * (0.4 * strut.chord)
        profile = build.airfoil_curve(f"{strut.name} Airfoil", controls, leading_edge, strut.chord,
                                      chord_dir, thickness_dir, strut.airfoil)
    path = build.line_curve(f"{strut.name} Line", controls, [strut.start, strut.end])
    obj = build.new_result(strut.name, "SWEEP", parts)
    s = obj.lsw
    s.resolution = 24
    s.path_steps = 4
    s.cap_start = s.cap_end = "FAN" if strut.round else "STRIP"
    s.mirror_x = strut.mirror
    s.profile, s.path = profile, path
    return obj


def add_window(window, parts, controls, target):
    """Glass patches projected onto `target` from an outline curve you can move and edit."""
    u, v = Vector(window.u_axis).normalized(), Vector(window.v_axis).normalized()
    basis = Matrix((u, v, u.cross(v))).transposed().to_4x4()
    outline = build.outline_curve(f"{window.name} Outline", controls, Matrix.Translation(window.origin) @ basis,
                                  window.ovals, window.corners)
    obj = build.new_result(window.name, "WINDOW", parts)
    s = obj.lsw
    s.resolution = 40
    s.steps = 5
    s.mirror_x = window.mirror
    s.target, s.outline = target, outline
    obj.data.materials.append(build.glass_material())
    return obj


def _keep_world(obj, parent):
    matrix = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_world = matrix


def gear_control(controls, name):
    """Empty whose "retract" property (0 down, 1 up) drives every gear pivot. Keyframe it to animate."""
    control = bpy.data.objects.new(f"{name} Landing Gear", None)
    control.empty_display_type = "PLAIN_AXES"
    control.empty_display_size = 0.2
    controls.objects.link(control)
    control["lsw_gear"] = True
    control["retract"] = 0.0
    control.id_properties_ui("retract").update(
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, description="0 = gear down, 1 = gear up"
    )
    return control


def add_gear(gear, parts, controls, control=None):
    """Leg, wheel, and (fixed gear) wheel fairing. Retractable gear hangs from a driven pivot."""
    from . import design as d

    leg = add_strut(
        d.Strut(gear.name.replace("Gear", "Gear Leg"), gear.pivot, gear.wheel, gear.leg_width, "0020",
                mirror=gear.mirror, round=bool(gear.retract_axis)),
        parts, controls,
    )
    wheel = add_body(gear.wheel_body(), parts, controls)
    wheel.lsw.resolution = 32
    wheel.lsw.steps = 3
    objects = [leg, wheel]
    if gear.fairing:
        objects.append(add_body(gear.fairing_body(), parts, controls))
    if gear.retract_axis and control is not None:
        pivot = bpy.data.objects.new(f"{gear.name} Pivot", None)
        pivot.empty_display_type = "SPHERE"
        pivot.empty_display_size = gear.leg_width
        controls.objects.link(pivot)
        pivot.location = gear.pivot
        index = 0 if gear.retract_axis == "X" else 1
        driver = pivot.driver_add("rotation_euler", index).driver
        driver.type = "SCRIPTED"
        variable = driver.variables.new()
        variable.name = "retract"
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = control
        variable.targets[0].data_path = '["retract"]'
        driver.expression = f"retract * {math.radians(gear.retract_angle):.6f}"
        bpy.context.view_layer.update()
        # The control curves ride along with the pivot so live rebuilds stay in step.
        sources = [leg.lsw.profile, leg.lsw.path] + [ref.obj for ref in wheel.lsw.profiles]
        for obj in [leg, wheel] + sources:
            _keep_world(obj, pivot)
    return objects


def add_propeller(prop, parts, controls):
    """One twisted, tapered blade, repeated around the hub by an Array modifier.

    Rotate the "<name> Hub" empty's Y angle to change the blade spacing; edit
    the blade line to change the diameter.
    """
    hub = Vector(prop.hub)
    pitch = math.radians(prop.root_pitch)
    chord_dir = Vector((-math.cos(pitch), math.sin(pitch), 0.0))
    thickness_dir = Vector((-math.sin(pitch), -math.cos(pitch), 0.0))
    start = hub + Vector((0.0, 0.0, prop.root_radius))
    end = hub + Vector((0.0, 0.0, prop.radius))
    leading_edge = start - chord_dir * (0.3 * prop.root_chord)
    profile = build.airfoil_curve(f"{prop.name} Airfoil", controls, leading_edge, prop.root_chord,
                                  chord_dir, thickness_dir, prop.airfoil)
    path = build.line_curve(f"{prop.name} Blade Line", controls, [tuple(start), tuple(end)])
    obj = build.new_result(prop.name, "SWEEP", parts)
    obj.matrix_world = Matrix.Translation(hub)  # array copies turn about the hub
    s = obj.lsw
    s.orientation = "PARALLEL"
    s.resolution = 32
    s.path_steps = 12
    s.cap_start = s.cap_end = "STRIP"
    s.twist = math.radians(prop.root_pitch - prop.tip_pitch)
    s.scale_end = prop.tip_chord / prop.root_chord
    s.profile, s.path = profile, path

    spacing = bpy.data.objects.new(f"{prop.name} Hub", None)
    spacing.empty_display_type = "ARROWS"
    spacing.empty_display_size = prop.root_radius
    controls.objects.link(spacing)
    spacing.matrix_world = Matrix.Translation(hub) @ Matrix.Rotation(2 * math.pi / prop.blades, 4, "Y")
    array = obj.modifiers.new("Blades", "ARRAY")
    array.count = prop.blades
    array.use_relative_offset = False
    array.use_object_offset = True
    array.offset_object = spacing
    return obj


def build_design(context, plan, name, fairing=False):
    """Create live parts for every body, surface, strut, and propeller in a design."""
    parts = _collection(name, context.scene.collection)
    controls = _collection(f"{name} Controls", parts)
    controls.hide_render = True
    objects = [add_body(body, parts, controls) for body in plan.bodies]
    objects += [add_surface(surface, parts, controls) for surface in plan.surfaces]
    objects += [add_strut(strut, parts, controls) for strut in plan.struts]
    objects += [add_propeller(prop, parts, controls) for prop in plan.propellers]
    if fairing:
        wing = next(obj for obj in objects if obj.name.startswith("Wing"))
        objects.append(add_fairing(wing, parts, 0.62 * plan.diameter))
    control = gear_control(controls, name) if any(g.retract_axis for g in plan.gear) else None
    for gear in plan.gear:
        objects += add_gear(gear, parts, controls, control)
    context.view_layer.update()
    for obj in objects:
        build.rebuild(obj)
    # Windows last: they project onto the finished fuselage.
    bodies = {body.name: obj for body, obj in zip(plan.bodies, objects)}
    windows = [add_window(w, parts, controls, bodies[w.target]) for w in plan.windows if w.target in bodies]
    context.view_layer.update()
    for obj in windows:
        build.rebuild(obj)
    return objects + windows


def build_single_piston(context, length=8.3, span=0.0, wing="HIGH", gear="FIXED", blades=2, windows=True,
                        dorsal=True, name="Single Engine"):
    plan = design.single_piston(length, span, wing, gear, blades, windows, dorsal)
    return plan, build_design(context, plan, name)


def add_fairing(wing, collection, reach):
    """Belly fairing that blends the wing root into the body, mirrored like the wing."""
    obj = build.new_result(f"{wing.name} Fairing", "FAIRING", collection)
    s = obj.lsw
    s.reach = reach
    s.steps = 8
    s.mirror_x = True
    s.wing = wing
    return obj


def root_chord(wing, depsgraph):
    _, section = build.wing_section(wing, depsgraph, 0.0)
    ys = [p[1] for p in section]
    return max(ys) - min(ys)


def editable_outline(fairing, depsgraph, points=16):
    """Turn the fairing's slider-made outline into a smooth closed curve to drag around."""
    from . import core

    s = fairing.lsw
    root_x, section = build.wing_section(s.wing, depsgraph, s.reach)
    outline = core.fairing_outline(section, s.forward, s.aft, s.depth, s.top)
    loop = core.resample([(root_x, y, z) for _, y, z in outline], points, closed=True, curvature_bias=1.0,
                         corner_angle=math.pi)
    collection = fairing.users_collection[0]
    curve_obj = build.new_curve(f"{fairing.name} Outline", collection)
    spline = curve_obj.data.splines.new("NURBS")
    spline.points.add(len(loop) - 1)
    for point, co in zip(spline.points, loop):
        point.co = (*co, 1.0)
    spline.use_cyclic_u = True
    spline.order_u = 4
    s.outline = curve_obj
    return curve_obj


def build_small_jet(context, length=14.0, span=0.0, diameter=0.0, tail="T", engines=True, fairing=True,
                    gear="RETRACTABLE", windows=True, dorsal=True, name="Small Jet"):
    jet = design.small_jet(length, span, diameter, tail, engines, gear, windows, dorsal)
    return jet, build_design(context, jet, name, fairing)


def build_wing(context, root_le, semi_span, root_chord, tip_chord, sweep, dihedral, airfoil, mirror=True, twist=0.0):
    x, y, z = root_le
    tip_le = (
        x + semi_span,
        y + semi_span * math.tan(math.radians(sweep)),
        z + semi_span * math.tan(math.radians(dihedral)),
    )
    surface = design.Surface("Wing", airfoil, tuple(root_le), root_chord, tip_le, tip_chord, mirror=mirror, twist=twist)
    parts = _collection("Wing", context.scene.collection)
    controls = _collection("Wing Controls", parts)
    controls.hide_render = True
    obj = add_surface(surface, parts, controls)
    context.view_layer.update()
    build.rebuild(obj)
    return obj


def build_fuselage(context, length, diameter):
    body = design.small_jet(length, diameter=diameter, engines=False).bodies[0]
    parts = _collection("Fuselage", context.scene.collection)
    controls = _collection("Fuselage Controls", parts)
    controls.hide_render = True
    obj = add_body(body, parts, controls)
    context.view_layer.update()
    build.rebuild(obj)
    return obj


# --- blueprints -------------------------------------------------------------------

def add_blueprint(name, filepath, view, length, span, collection, opacity=0.5):
    """Reference image scaled to the real aircraft, nose at the origin.

    Crop each image so the aircraft touches its edges: side view nose-left,
    top view nose-up, front view wingtip to wingtip.
    """
    image = bpy.data.images.load(bpy.path.abspath(filepath), check_existing=True)
    width, height = image.size
    if not width or not height:
        raise ValueError(f"Could not read {filepath}")
    longest = max(width, height)
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "IMAGE"
    empty.data = image
    if view == "SIDE":
        empty.empty_display_size = length * longest / width
        empty.rotation_euler = (math.radians(90), 0, math.radians(90))
        empty.location = (-(span / 2 + 1.0), length / 2, 0.0)
    elif view == "TOP":
        empty.empty_display_size = length * longest / height
        empty.rotation_euler = (0, 0, math.radians(180))
        empty.location = (0.0, length / 2, -3.0)
    else:
        empty.empty_display_size = span * longest / width
        empty.rotation_euler = (math.radians(90), 0, 0)
        empty.location = (0.0, length + 2.0, 0.0)
    empty.show_empty_image_perspective = False
    empty.show_empty_image_only_axis_aligned = True
    empty.use_empty_image_alpha = True
    empty.color[3] = opacity
    empty.hide_select = False
    collection.objects.link(empty)
    return empty

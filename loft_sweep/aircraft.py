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

from . import build, design


def _collection(name, parent):
    collection = bpy.data.collections.new(name)
    parent.children.link(collection)
    return collection


def add_body(body, parts, controls):
    rings = [
        build.ring_curve(f"{body.name} Ring {i + 1:02d}", controls, (ring.x, ring.y, ring.z), ring.width, ring.height)
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
    path = build.line_curve(f"{surface.name} Leading Edge", controls, [surface.root_le, surface.tip_le])
    rail = build.line_curve(f"{surface.name} Trailing Edge", controls, [surface.root_te, surface.tip_te])
    obj = build.new_result(surface.name, "SWEEP", parts)
    s = obj.lsw
    s.orientation = "PARALLEL"
    s.resolution = 48
    s.path_steps = 16
    s.cap_start = "NONE" if surface.mirror else "STRIP"
    s.cap_end = "STRIP"
    s.twist = math.radians(surface.twist)
    s.mirror_x = surface.mirror
    s.profile, s.path, s.rail = profile, path, rail
    return obj


def build_small_jet(context, length=14.0, span=0.0, diameter=0.0, tail="T", engines=True, name="Small Jet"):
    jet = design.small_jet(length, span, diameter, tail, engines)
    parts = _collection(name, context.scene.collection)
    controls = _collection(f"{name} Controls", parts)
    controls.hide_render = True
    objects = [add_body(body, parts, controls) for body in jet.bodies]
    objects += [add_surface(surface, parts, controls) for surface in jet.surfaces]
    context.view_layer.update()
    for obj in objects:
        build.rebuild(obj)
    return jet, objects


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

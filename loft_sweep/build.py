"""Bridge between Blender objects and the pure-Python geometry in core.py."""

import math
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

from . import core

_busy = False
MIRROR_NAME = "Loft & Sweep Mirror"


# --- reading source curves -----------------------------------------------------

def sample(obj, depsgraph):
    """World-space points of a curve (or edge loop mesh) in drawing order, and whether it is closed."""
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world
        verts = [tuple(matrix @ v.co) for v in mesh.vertices]
        neighbours = {i: [] for i in range(len(verts))}
        for edge in mesh.edges:
            a, b = edge.vertices
            neighbours[a].append(b)
            neighbours[b].append(a)
    finally:
        evaluated.to_mesh_clear()
    if not verts:
        raise ValueError(f"{obj.name} has no points")
    if not any(neighbours.values()):
        return verts, False

    start = 0
    if len(neighbours[start]) != 1:
        # Prefer an open end if this chain has one (vertex 0 may sit mid-way on a mesh).
        seen, stack = {start}, [start]
        while stack:
            for n in neighbours[stack.pop()]:
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        ends = sorted(i for i in seen if len(neighbours[i]) == 1)
        if ends:
            start = ends[0]
    order, previous, current, closed = [start], None, start, False
    while True:
        options = [n for n in neighbours[current] if n != previous]
        if not options:
            break
        nxt = min(options)
        if nxt == start:
            closed = True
            break
        if nxt in order:
            break
        order.append(nxt)
        previous, current = current, nxt
    return [verts[i] for i in order], closed


# --- writing results ------------------------------------------------------------

def write_mesh(obj, verts, faces, sharp):
    inverse = obj.matrix_world.inverted()
    local = [tuple(inverse @ Vector(v)) for v in verts]
    mesh = obj.data
    mesh.clear_geometry()
    mesh.from_pydata(local, [], faces)
    mesh.shade_smooth()
    if sharp:
        attribute = mesh.attributes.get("sharp_edge") or mesh.attributes.new("sharp_edge", "BOOLEAN", "EDGE")
        lookup = {tuple(sorted(edge.vertices)): edge.index for edge in mesh.edges}
        values = [False] * len(mesh.edges)
        for key in sharp:
            index = lookup.get(key)
            if index is not None:
                values[index] = True
        attribute.data.foreach_set("value", values)
    mesh.update()


def sync_mirror(obj):
    modifier = obj.modifiers.get(MIRROR_NAME)
    if obj.lsw.mirror_x and modifier is None:
        modifier = obj.modifiers.new(MIRROR_NAME, "MIRROR")
        modifier.use_axis = (True, False, False)
        modifier.use_clip = True
        modifier.use_mirror_merge = True
        modifier.merge_threshold = 0.0005
    elif not obj.lsw.mirror_x and modifier is not None:
        obj.modifiers.remove(modifier)


def sources_of(obj):
    s = obj.lsw
    if s.kind == "LOFT":
        refs = [r.obj for r in s.profiles] + [r.obj for r in s.rails]
    elif s.kind == "SWEEP":
        refs = [s.profile, s.path, s.rail]
    else:
        refs = []
    return [r for r in refs if r is not None]


def _loft(s, depsgraph):
    sampled = [sample(ref.obj, depsgraph) for ref in s.profiles if ref.obj]
    if len(sampled) < 2:
        raise ValueError("Add at least two profiles")
    closed_flags = {closed for _, closed in sampled}
    if len(closed_flags) > 1:
        raise ValueError("Profiles must be all closed or all open")
    closed = closed_flags.pop()
    sections = [core.resample(points, s.resolution, closed, curvature_bias=s.curvature * 0.5) for points, _ in sampled]
    rails = [core.resample(sample(r.obj, depsgraph)[0], 256, False) for r in s.rails if r.obj]
    rows = core.loft(sections, closed, s.steps, s.smooth, rails, s.align)
    return core.build_mesh(rows, closed, cap_start=s.cap_start, cap_end=s.cap_end, sharp_angle=s.sharp_angle)


def _sweep(s, depsgraph):
    if s.profile is None or s.path is None:
        raise ValueError("Pick a profile and a path")
    profile_points, profile_closed = sample(s.profile, depsgraph)
    path_points, path_closed = sample(s.path, depsgraph)
    profile = core.resample(profile_points, s.resolution, profile_closed, curvature_bias=s.curvature)
    path_count = s.path_steps if path_closed else s.path_steps + 1
    path = core.resample(path_points, path_count, path_closed)
    rail = None
    if s.rail is not None:
        rail = core.resample(sample(s.rail, depsgraph)[0], max(256, s.path_steps * 4), False)
    rows = core.sweep(
        profile,
        path,
        orientation=s.orientation,
        rail=rail,
        twist=math.degrees(s.twist),
        scale_end=s.scale_end,
        closed_path=path_closed,
    )
    return core.build_mesh(
        rows,
        profile_closed,
        closed_rows=path_closed,
        cap_start=s.cap_start,
        cap_end=s.cap_end,
        sharp_angle=s.sharp_angle,
    )


def rebuild(obj, depsgraph=None):
    s = getattr(obj, "lsw", None)
    if s is None or s.kind == "NONE" or obj.type != "MESH":
        return
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    try:
        verts, faces, sharp = _loft(s, depsgraph) if s.kind == "LOFT" else _sweep(s, depsgraph)
    except Exception as exc:  # shown in the panel instead of breaking the viewport
        if s.status != str(exc):
            s.status = str(exc)
        return
    if s.status:
        s.status = ""
    write_mesh(obj, verts, faces, sharp)
    sync_mirror(obj)


@persistent
def on_depsgraph_update(scene, depsgraph):
    """Rebuild lofts and sweeps whose source curves just changed (moved, scaled, or edited)."""
    global _busy
    if _busy:
        return
    changed = set()
    for update in depsgraph.updates:
        data = update.id
        if isinstance(data, bpy.types.Object):
            if update.is_updated_geometry or update.is_updated_transform:
                changed.add(data.original.as_pointer())
        elif isinstance(data, (bpy.types.Curve, bpy.types.Mesh)):
            changed.add(data.original.as_pointer())
    if not changed:
        return
    _busy = True
    try:
        for obj in scene.objects:
            settings = getattr(obj, "lsw", None)
            if settings is None or settings.kind == "NONE":
                continue
            for source in sources_of(obj):
                if source.as_pointer() in changed or (source.data and source.data.as_pointer() in changed):
                    rebuild(obj, depsgraph)
                    break
    finally:
        _busy = False


# --- creating objects -------------------------------------------------------------

def new_result(name, kind, collection):
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.lsw.kind = kind
    return obj


def new_curve(name, collection):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"  # 2D curves fill closed shapes with faces
    curve.resolution_u = 12
    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    return obj


def line_curve(name, collection, points):
    obj = new_curve(name, collection)
    spline = obj.data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, co in zip(spline.points, points):
        point.co = (*co, 1.0)
    return obj


def ring_curve(name, collection, center, width, height):
    """Bezier ellipse facing +Y. Scale X for width and Z for height to fit a blueprint."""
    obj = new_curve(name, collection)
    spline = obj.data.splines.new("BEZIER")
    spline.bezier_points.add(3)
    k = 0.5523
    layout = (
        ((1, 0), (1, -k), (1, k)),
        ((0, 1), (k, 1), (-k, 1)),
        ((-1, 0), (-1, k), (-1, -k)),
        ((0, -1), (-k, -1), (k, -1)),
    )
    for point, (co, left, right) in zip(spline.bezier_points, layout):
        point.co = (*co, 0.0)
        point.handle_left_type = point.handle_right_type = "ALIGNED"
        point.handle_left = (*left, 0.0)
        point.handle_right = (*right, 0.0)
    spline.use_cyclic_u = True
    obj.location = center
    obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    obj.scale = (max(width, 1e-4) / 2, max(height, 1e-4) / 2, 1.0)
    return obj


def airfoil_points(settings):
    if settings.source == "FILE":
        path = Path(bpy.path.abspath(settings.filepath))
        return core.parse_airfoil_dat(path.read_text(errors="replace"))
    return core.naca4(settings.naca, settings.points)


def write_airfoil(obj):
    settings = obj.lsw_airfoil
    if not settings.enabled or obj.type != "CURVE":
        return
    try:
        points = airfoil_points(settings)
    except (OSError, ValueError) as exc:
        settings.error = str(exc)
        return
    settings.error = ""
    curve = obj.data
    curve.splines.clear()
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, (x, y) in zip(spline.points, points):
        point.co = (x, y, 0.0, 1.0)
    spline.use_cyclic_u = True
    obj.update_tag()


def airfoil_curve(name, collection, leading_edge, chord, chord_dir=(0, 1, 0), thickness_dir=(0, 0, 1), naca="2412"):
    """Airfoil with chord 1 in local X, scaled by the object to the real chord."""
    obj = new_curve(name, collection)
    settings = obj.lsw_airfoil
    settings.enabled = True
    settings.naca = naca  # triggers write_airfoil
    write_airfoil(obj)
    x_axis = Vector(chord_dir).normalized()
    y_axis = Vector(thickness_dir).normalized()
    z_axis = x_axis.cross(y_axis)
    basis = Matrix((x_axis, y_axis, z_axis)).transposed().to_4x4()
    obj.matrix_world = Matrix.Translation(leading_edge) @ basis @ Matrix.Diagonal((chord, chord, chord, 1.0))
    return obj

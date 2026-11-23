"""Bridge between Blender objects and the pure-Python geometry in core.py."""

import math
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

from . import core

_busy = False
MIRROR_NAME = "Aircraft Builder Mirror"
OLD_MIRROR_NAMES = ("Loft & Sweep Mirror",)  # files saved before the add-on was renamed


# --- reading source curves -----------------------------------------------------

def sample_chains(obj, depsgraph):
    """Every connected chain of a curve (or edge mesh): world-space points in drawing order + closed flag.

    Chains come in the order of their first vertex, so a curve's first spline comes first.
    """
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
        return [(verts, False)]

    chains, used = [], set()
    for first in range(len(verts)):
        if first in used or not neighbours[first]:
            continue
        component, stack = {first}, [first]
        while stack:
            for n in neighbours[stack.pop()]:
                if n not in component:
                    component.add(n)
                    stack.append(n)
        used |= component
        start = first
        if len(neighbours[start]) != 1:
            # Prefer an open end if this chain has one (the first vertex may sit mid-way on a mesh).
            ends = sorted(i for i in component if len(neighbours[i]) == 1)
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
        chains.append(([verts[i] for i in order], closed))
    return chains


def sample(obj, depsgraph):
    """World-space points of a curve's first chain in drawing order, and whether it is closed."""
    return sample_chains(obj, depsgraph)[0]


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
    for old_name in OLD_MIRROR_NAMES:
        old = obj.modifiers.get(old_name)
        if old is not None and modifier is None:
            old.name = MIRROR_NAME
            modifier = old
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
    elif s.kind == "FAIRING":
        # The wing's own curves too, so the fairing rebuilds in the same pass as the wing.
        refs = [s.wing, s.outline] + (sources_of(s.wing) if s.wing and s.wing.lsw.kind == "SWEEP" else [])
    elif s.kind == "WINDOW":
        refs = [s.target, s.outline]
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
    rows, profile_closed, path_closed = sweep_rows(s, depsgraph)
    return core.build_mesh(
        rows,
        profile_closed,
        closed_rows=path_closed,
        cap_start=s.cap_start,
        cap_end=s.cap_end,
        sharp_angle=s.sharp_angle,
    )


def wing_section(wing, depsgraph, offset):
    """Cross-section of a swept wing (span along X), `offset` out from its root.

    Returns the root X and the section points.
    """
    rows, closed, _ = sweep_rows(wing.lsw, depsgraph)
    if not closed:
        raise ValueError(f"{wing.name} needs a closed airfoil profile")
    root_x, tip_x = rows[0][0][0], rows[-1][0][0]
    x = root_x + offset
    if not min(root_x, tip_x) - 1e-6 <= x <= max(root_x, tip_x) + 1e-6:
        raise ValueError(f"Reach is longer than {wing.name}'s span")
    return root_x, core.slice_columns(rows, 0, x)


def _fairing(s, depsgraph):
    if s.wing is None or s.wing.lsw.kind != "SWEEP":
        raise ValueError("Pick the wing to fair")
    root_x, section = wing_section(s.wing, depsgraph, s.reach)
    if s.outline is not None:
        points, closed = sample(s.outline, depsgraph)
        if not closed:
            raise ValueError("The outline curve must be closed")
        outline = core.match_outline(section, [(root_x, y, z) for _, y, z in points])
    else:
        outline = core.fairing_outline(section, s.forward, s.aft, s.depth, s.top)
    rows = core.fairing_rows(section, outline, s.steps * 2, root_x + s.reach, s.fullness, root_x)
    return core.build_mesh(rows, True, sharp_angle=s.sharp_angle)


def _window(s, depsgraph):
    """Project each closed outline shape onto the body and lay glass just above it."""
    from mathutils.bvhtree import BVHTree

    if s.target is None or s.outline is None:
        raise ValueError("Pick the body and the outline curve")
    target = s.target
    if target.modifiers:
        target = target.evaluated_get(depsgraph)
        bvh = BVHTree.FromObject(target, depsgraph)
    else:
        # Read the mesh as written, so a body rebuilt a moment ago is used right away.
        mesh = target.data
        bvh = BVHTree.FromPolygons([v.co for v in mesh.vertices], [p.vertices[:] for p in mesh.polygons])
    to_world = target.matrix_world
    to_local = to_world.inverted()
    normal_to_world = to_world.to_3x3().inverted().transposed()
    body_center = to_world @ (sum((Vector(corner) for corner in target.bound_box), Vector()) / 8.0)
    shapes = [points for points, closed in sample_chains(s.outline, depsgraph) if closed]
    if not shapes:
        raise ValueError("The outline needs at least one closed shape")

    verts, faces = [], []
    rings = max(2, s.steps)
    for shape in shapes:
        boundary = core.resample(shape, s.resolution, True, curvature_bias=0.5)
        normal = Vector(core.newell_normal(boundary))
        if normal.length < 1e-9:
            continue
        direction = normal if normal.dot(body_center - Vector(core.centroid(boundary))) > 0 else -normal
        direction_local = (to_local.to_3x3() @ direction).normalized()
        hits = []
        for point in core.radial_patch_points(boundary, rings):
            location, hit_normal, _, _ = bvh.ray_cast(to_local @ Vector(point), direction_local)
            if location is None:
                hits.append(None)
                continue
            outward = (normal_to_world @ hit_normal).normalized()
            if outward.dot(direction) > 0:
                outward = -outward
            hits.append(tuple(to_world @ location + outward * s.offset))
        if all(hit is None for hit in hits):
            raise ValueError("An outline shape misses the body: move it so it faces the surface")
        # Points that miss the body borrow their nearest neighbour inward, toward the center.
        count = len(boundary)
        for index, hit in enumerate(hits):
            if hit is None:
                inner = index - count if index > count else 0
                while inner > 0 and hits[inner] is None:
                    inner = inner - count if inner > count else 0
                hits[index] = hits[inner] if hits[inner] is not None else next(h for h in hits if h)
        base = len(verts)
        verts.extend(hits)
        shape_faces = core.radial_patch_faces(count, rings, base)
        a, b, c = (Vector(verts[i]) for i in shape_faces[count][:3])
        if (b - a).cross(c - a).dot(direction) > 0:  # should face out, against the projection
            shape_faces = [tuple(reversed(face)) for face in shape_faces]
        faces.extend(shape_faces)
    return verts, faces, set()


def glass_material():
    material = bpy.data.materials.get("Aircraft Builder Glass")
    if material is None:
        material = bpy.data.materials.new("Aircraft Builder Glass")
        material.diffuse_color = (0.03, 0.05, 0.07, 1.0)
        material.roughness = 0.05
        if hasattr(material, "use_nodes"):
            material.use_nodes = True
        tree = material.node_tree
        if tree is not None:
            shader = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if shader is not None:
                shader.inputs["Base Color"].default_value = (0.01, 0.015, 0.02, 1.0)
                shader.inputs["Roughness"].default_value = 0.04
    return material


def sweep_rows(s, depsgraph):
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
    return rows, profile_closed, path_closed


def rebuild(obj, depsgraph=None):
    s = getattr(obj, "lsw", None)
    if s is None or s.kind == "NONE" or obj.type != "MESH":
        return
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    try:
        builder = {"LOFT": _loft, "SWEEP": _sweep, "FAIRING": _fairing, "WINDOW": _window}[s.kind]
        verts, faces, sharp = builder(s, depsgraph)
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
        # Repeat until nothing new rebuilds, so parts built from other parts
        # (windows on a fuselage) follow in the same update.
        rebuilt = set()
        progress = True
        while progress:
            progress = False
            for obj in scene.objects:
                settings = getattr(obj, "lsw", None)
                if settings is None or settings.kind == "NONE" or obj.as_pointer() in rebuilt:
                    continue
                for source in sources_of(obj):
                    if source.as_pointer() in changed or (source.data and source.data.as_pointer() in changed):
                        rebuild(obj, depsgraph)
                        rebuilt.add(obj.as_pointer())
                        changed.add(obj.as_pointer())
                        progress = True
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


def ring_curve(name, collection, center, width, height, squareness=0.5523, axis="Y"):
    """Bezier ellipse facing +Y. Scale X for width and Z for height to fit a blueprint.

    squareness is the handle length: 0.5523 draws an ellipse, about 0.75 a
    rounded box like a light-aircraft cabin. axis "X" makes the ring face
    sideways (wheels): width then runs along Y.
    """
    obj = new_curve(name, collection)
    spline = obj.data.splines.new("BEZIER")
    spline.bezier_points.add(3)
    k = squareness
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
    if axis == "X":
        obj.rotation_euler = (0.0, math.radians(90.0), 0.0)  # local X -> world -Z, local Y -> world Y
        obj.scale = (max(height, 1e-4) / 2, max(width, 1e-4) / 2, 1.0)
    else:
        obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
        obj.scale = (max(width, 1e-4) / 2, max(height, 1e-4) / 2, 1.0)
    return obj


def outline_curve(name, collection, matrix, ovals=(), corners=()):
    """Closed Bezier shapes drawn in a plane (local XY, placed by `matrix`).

    ovals: (u, v, width, height, squareness) rounded rectangles / ellipses.
    corners: one rounded polygon (handles a quarter of the way to each neighbour).
    """
    obj = new_curve(name, collection)
    for u, v, width, height, k in ovals:
        spline = obj.data.splines.new("BEZIER")
        spline.bezier_points.add(3)
        a, b = width / 2, height / 2
        layout = (
            ((a, 0), (a, -k * b), (a, k * b)),
            ((0, b), (k * a, b), (-k * a, b)),
            ((-a, 0), (-a, k * b), (-a, -k * b)),
            ((0, -b), (-k * a, -b), (k * a, -b)),
        )
        for point, (co, left, right) in zip(spline.bezier_points, layout):
            point.co = (u + co[0], v + co[1], 0.0)
            point.handle_left_type = point.handle_right_type = "ALIGNED"
            point.handle_left = (u + left[0], v + left[1], 0.0)
            point.handle_right = (u + right[0], v + right[1], 0.0)
        spline.use_cyclic_u = True
    if corners:
        spline = obj.data.splines.new("BEZIER")
        spline.bezier_points.add(len(corners) - 1)
        count = len(corners)
        for i, point in enumerate(spline.bezier_points):
            here = Vector((*corners[i], 0.0))
            before = Vector((*corners[i - 1], 0.0))
            after = Vector((*corners[(i + 1) % count], 0.0))
            point.co = here
            point.handle_left_type = point.handle_right_type = "FREE"
            point.handle_left = here + (before - here) * 0.25
            point.handle_right = here + (after - here) * 0.25
        spline.use_cyclic_u = True
    obj.matrix_world = matrix
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

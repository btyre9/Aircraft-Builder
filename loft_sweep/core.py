"""Pure-Python geometry for lofts and sweeps.

Nothing here imports bpy, so it can be tested with a plain Python interpreter.
Points are (x, y, z) tuples. A "row" is one cross-section of the surface; a
surface is a list of rows that all have the same number of points.
"""

from __future__ import annotations

import math
from typing import Sequence

Vec = tuple[float, float, float]
EPS = 1e-9


# --- vector helpers ---------------------------------------------------------

def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def dist(a: Vec, b: Vec) -> float:
    return length(sub(a, b))


def normalize(a: Vec) -> Vec:
    size = length(a)
    return mul(a, 1.0 / size) if size > EPS else (0.0, 0.0, 0.0)


def lerp(a: Vec, b: Vec, t: float) -> Vec:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def centroid(points: Sequence[Vec]) -> Vec:
    count = max(len(points), 1)
    return (
        sum(p[0] for p in points) / count,
        sum(p[1] for p in points) / count,
        sum(p[2] for p in points) / count,
    )


def rotate(v: Vec, axis: Vec, angle: float) -> Vec:
    """Rodrigues rotation of v about a unit axis."""
    if abs(angle) < EPS:
        return v
    c, s = math.cos(angle), math.sin(angle)
    return add(add(mul(v, c), mul(cross(axis, v), s)), mul(axis, dot(axis, v) * (1.0 - c)))


def any_perpendicular(v: Vec) -> Vec:
    helper = (0.0, 0.0, 1.0) if abs(v[2]) < 0.9 else (1.0, 0.0, 0.0)
    return normalize(cross(v, helper))


def newell_normal(points: Sequence[Vec]) -> Vec:
    """Best-fit normal of a (roughly planar) loop; zero vector if degenerate."""
    nx = ny = nz = 0.0
    count = len(points)
    for i in range(count):
        a, b = points[i], points[(i + 1) % count]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    return normalize((nx, ny, nz))


def signed_angle(a: Vec, b: Vec, axis: Vec) -> float:
    """Angle that rotates a onto b around axis (both projected onto its plane)."""
    a = sub(a, mul(axis, dot(a, axis)))
    b = sub(b, mul(axis, dot(b, axis)))
    if length(a) < EPS or length(b) < EPS:
        return 0.0
    return math.atan2(dot(cross(a, b), axis), dot(a, b))


# --- polylines --------------------------------------------------------------

def turning_angles(points: Sequence[Vec], closed: bool) -> list[float]:
    """Direction change (radians) at each vertex; 0 at open ends."""
    count = len(points)
    angles = [0.0] * count
    for i in range(count):
        if not closed and (i == 0 or i == count - 1):
            continue
        prev_point, next_point = points[i - 1], points[(i + 1) % count]
        a = normalize(sub(points[i], prev_point))
        b = normalize(sub(next_point, points[i]))
        if length(a) < EPS or length(b) < EPS:
            continue
        angles[i] = math.acos(max(-1.0, min(1.0, dot(a, b))))
    return angles


def dedupe(points: Sequence[Vec], closed: bool) -> list[Vec]:
    result: list[Vec] = []
    for point in points:
        if not result or dist(point, result[-1]) > 1e-7:
            result.append(point)
    if closed and len(result) > 2 and dist(result[0], result[-1]) <= 1e-7:
        result.pop()
    return result


def _resample_piece(points: list[Vec], weights: list[float], count: int) -> list[Vec]:
    """Place `count` samples along an open piece by cumulative weight; includes start, excludes end."""
    total = sum(weights)
    if total < EPS:
        return [points[0]] * count
    result = []
    segment, consumed = 0, 0.0
    for k in range(count):
        target = total * k / count
        while segment < len(weights) - 1 and consumed + weights[segment] < target:
            consumed += weights[segment]
            segment += 1
        w = weights[segment]
        t = (target - consumed) / w if w > EPS else 0.0
        result.append(lerp(points[segment], points[segment + 1], max(0.0, min(1.0, t))))
    return result


def resample(
    points: Sequence[Vec],
    count: int,
    closed: bool,
    curvature_bias: float = 0.0,
    corner_angle: float = math.radians(40.0),
) -> list[Vec]:
    """Evenly respace a polyline to `count` points.

    Sharp corners (turning more than `corner_angle`) are kept exactly, so an
    airfoil trailing edge or a box corner never gets rounded off. With
    `curvature_bias` > 0, extra samples go where the line bends, which keeps
    leading edges and noses round.
    """
    pts = dedupe(points, closed)
    if len(pts) < 2:
        return [pts[0] if pts else (0.0, 0.0, 0.0)] * count
    if not closed:
        count = max(count, 2)
    turning = turning_angles(pts, closed)
    total_length = sum(dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts) - (0 if closed else 1)))
    bend_scale = total_length / (2.0 * math.pi) * curvature_bias

    corners = [i for i, angle in enumerate(turning) if angle > corner_angle]
    if closed:
        if 0 not in corners:
            corners = [0] + corners
    else:
        corners = sorted(set([0, len(pts) - 1] + corners))

    pieces: list[tuple[list[Vec], list[float]]] = []
    stops = corners + ([corners[0] + len(pts)] if closed else [])
    for a, b in zip(stops, stops[1:]):
        piece = [pts[i % len(pts)] for i in range(a, b + 1)]
        weights = []
        for i in range(len(piece) - 1):
            seg = dist(piece[i], piece[i + 1])
            bend = 0.0
            if 0 < i:
                bend += turning[(a + i) % len(pts)] * 0.5
            if i + 1 < len(piece) - 1:
                bend += turning[(a + i + 1) % len(pts)] * 0.5
            weights.append(seg + bend * bend_scale)
        pieces.append((piece, weights))

    available = count if closed else count - 1
    totals = [sum(w) for _, w in pieces]
    grand = sum(totals) or 1.0
    allocation = [max(1, round(available * t / grand)) for t in totals]
    while sum(allocation) > available and max(allocation) > 1:
        allocation[allocation.index(max(allocation))] -= 1
    while sum(allocation) < available:
        allocation[allocation.index(max(allocation))] += 1

    result: list[Vec] = []
    for (piece, weights), samples in zip(pieces, allocation):
        result.extend(_resample_piece(piece, weights, samples))
    if not closed:
        result.append(pts[-1])
    return result[:count] if closed else result


def polyline_point_at(points: Sequence[Vec], fraction: float) -> Vec:
    """Point at a fraction (0..1) of an open polyline's arc length."""
    lengths = [dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = sum(lengths)
    if total < EPS:
        return points[0]
    target = max(0.0, min(1.0, fraction)) * total
    for i, seg in enumerate(lengths):
        if target <= seg or i == len(lengths) - 1:
            return lerp(points[i], points[i + 1], target / seg if seg > EPS else 0.0)
        target -= seg
    return points[-1]


def closest_fraction(points: Sequence[Vec], target: Vec) -> float:
    """Arc-length fraction of the polyline point closest to target."""
    lengths = [dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = sum(lengths) or 1.0
    best, best_fraction, walked = float("inf"), 0.0, 0.0
    for i, seg in enumerate(lengths):
        a, b = points[i], points[i + 1]
        ab = sub(b, a)
        t = max(0.0, min(1.0, dot(sub(target, a), ab) / dot(ab, ab))) if seg > EPS else 0.0
        d = dist(lerp(a, b, t), target)
        if d < best:
            best, best_fraction = d, (walked + seg * t) / total
        walked += seg
    return best_fraction


def plane_intersections(points: Sequence[Vec], origin: Vec, normal: Vec) -> list[Vec]:
    hits = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        da, db = dot(sub(a, origin), normal), dot(sub(b, origin), normal)
        if abs(da) < EPS:
            hits.append(a)
        elif da * db < 0:
            hits.append(lerp(a, b, da / (da - db)))
    if points and abs(dot(sub(points[-1], origin), normal)) < EPS:
        hits.append(points[-1])
    return hits


# --- interpolation between sections -----------------------------------------

def _catmull_rom(p0: Vec, p1: Vec, p2: Vec, p3: Vec, u: float) -> Vec:
    """Centripetal Catmull-Rom point between p1 and p2 (u in 0..1)."""
    def knot(t: float, a: Vec, b: Vec) -> float:
        return t + max(dist(a, b), 1e-6) ** 0.5

    t0 = 0.0
    t1 = knot(t0, p0, p1)
    t2 = knot(t1, p1, p2)
    t3 = knot(t2, p2, p3)
    t = t1 + (t2 - t1) * u

    def blend(a: Vec, b: Vec, ta: float, tb: float) -> Vec:
        return lerp(a, b, (t - ta) / (tb - ta))

    a1, a2, a3 = blend(p0, p1, t0, t1), blend(p1, p2, t1, t2), blend(p2, p3, t2, t3)
    b1, b2 = blend(a1, a2, t0, t2), blend(a2, a3, t1, t3)
    return blend(b1, b2, t1, t2)


def interpolate_sections(sections: list[list[Vec]], steps: int, smooth: bool) -> tuple[list[list[Vec]], list[float]]:
    """Insert `steps - 1` rows between each pair of sections.

    Returns the rows and, for each row, its position in section units
    (row at section k has position k).
    """
    steps = max(1, steps)
    rows, positions = [], []
    count = len(sections)
    for k in range(count - 1):
        for s in range(steps):
            u = s / steps
            if smooth and count > 2:
                prev_row = sections[k - 1] if k > 0 else [sub(mul(a, 2.0), b) for a, b in zip(sections[0], sections[1])]
                next_row = sections[k + 2] if k + 2 < count else [sub(mul(a, 2.0), b) for a, b in zip(sections[-1], sections[-2])]
                row = [
                    _catmull_rom(prev_row[j], sections[k][j], sections[k + 1][j], next_row[j], u)
                    for j in range(len(sections[k]))
                ]
            else:
                row = [lerp(a, b, u) for a, b in zip(sections[k], sections[k + 1])]
            rows.append(row)
            positions.append(k + u)
    rows.append(list(sections[-1]))
    positions.append(float(count - 1))
    return rows, positions


# --- loft ---------------------------------------------------------------------

def align_loop(reference: list[Vec], loop: list[Vec]) -> list[Vec]:
    """Rotate/reverse a closed loop so its points line up with reference (minimal twist)."""
    def normalized(points: list[Vec]) -> list[Vec]:
        center = centroid(points)
        moved = [sub(p, center) for p in points]
        radius = math.sqrt(sum(dot(p, p) for p in moved) / len(moved)) or 1.0
        return [mul(p, 1.0 / radius) for p in moved]

    ref, count = normalized(reference), len(loop)
    best_cost, best = float("inf"), loop
    for candidate in (loop, [loop[0]] + loop[:0:-1]):
        norm = normalized(candidate)
        for shift in range(count):
            cost = 0.0
            for j in range(count):
                d = sub(norm[(j + shift) % count], ref[j])
                cost += dot(d, d)
                if cost >= best_cost:
                    break
            if cost < best_cost:
                best_cost = cost
                best = candidate[shift:] + candidate[:shift]
    return best


def _apply_rails(
    rows: list[list[Vec]],
    positions: list[float],
    sections: list[list[Vec]],
    rails: list[list[Vec]],
    closed: bool,
) -> list[list[Vec]]:
    """Bend the interpolated rows so the matching columns follow each guide rail."""
    columns = len(rows[0])
    rail_data = []
    for rail in rails:
        if len(rail) < 2:
            continue
        column = min(range(columns), key=lambda j: dist(sections[0][j], rail[0]))
        fractions = [closest_fraction(rail, section[column]) for section in sections]
        rail_data.append((column, rail, fractions))
    if not rail_data:
        return rows
    rail_data.sort(key=lambda item: item[0])
    rail_columns = [item[0] for item in rail_data]

    result = []
    for row, position in zip(rows, positions):
        k = min(int(position), len(sections) - 2)
        u = position - k
        deltas = []
        for column, rail, fractions in rail_data:
            fraction = fractions[k] + (fractions[k + 1] - fractions[k]) * u
            deltas.append(sub(polyline_point_at(rail, fraction), row[column]))

        new_row = []
        for j, point in enumerate(row):
            if len(rail_data) == 1:
                offset = abs(j - rail_columns[0])
                if closed:
                    offset = min(offset, columns - offset)
                    span = columns / 2.0
                else:
                    span = max(columns - 1, 1)
                weight = 0.5 * (1.0 + math.cos(math.pi * min(offset / span, 1.0)))
                new_row.append(add(point, mul(deltas[0], weight)))
                continue
            # Blend between the two rails on either side of this column.
            after = next((i for i, c in enumerate(rail_columns) if c >= j), None)
            if after is None or (after == 0 and rail_columns[0] != j):
                if not closed:
                    new_row.append(add(point, deltas[-1 if after is None else 0]))
                    continue
                left, right = len(rail_columns) - 1, 0
            else:
                if rail_columns[after] == j:
                    new_row.append(add(point, deltas[after]))
                    continue
                left, right = after - 1, after
            lc, rc = rail_columns[left], rail_columns[right]
            span = (rc - lc) % columns if closed else rc - lc
            span = span or columns
            t = ((j - lc) % columns if closed else j - lc) / span
            t = t * t * (3.0 - 2.0 * t)
            new_row.append(add(point, lerp(deltas[left], deltas[right], t)))
        result.append(new_row)
    return result


def loft(
    sections: list[list[Vec]],
    closed: bool,
    steps: int = 6,
    smooth: bool = True,
    rails: list[list[Vec]] | None = None,
    align: bool = True,
) -> list[list[Vec]]:
    """Skin a surface through cross-sections that each have the same point count."""
    if len(sections) < 2:
        raise ValueError("A loft needs at least two profiles")
    if len({len(s) for s in sections}) != 1:
        raise ValueError("Profiles must be resampled to the same point count")
    sections = [list(s) for s in sections]
    if align and closed:
        for i in range(1, len(sections)):
            sections[i] = align_loop(sections[i - 1], sections[i])
    elif align:
        for i in range(1, len(sections)):
            reverse = dist(sections[i][0], sections[i - 1][0]) > dist(sections[i][-1], sections[i - 1][0])
            if reverse:
                sections[i] = sections[i][::-1]
    rows, positions = interpolate_sections(sections, steps, smooth)
    if rails:
        rows = _apply_rails(rows, positions, sections, rails, closed)
    return rows


# --- sweep ----------------------------------------------------------------------

def _rotation_minimizing_frames(path: list[Vec], tangents: list[Vec]) -> list[tuple[Vec, Vec, Vec]]:
    """Double-reflection frames (r, s, t) that do not twist along the path."""
    r = any_perpendicular(tangents[0])
    frames = [(r, cross(tangents[0], r), tangents[0])]
    for i in range(1, len(path)):
        r_prev, _, t_prev = frames[-1]
        v1 = sub(path[i], path[i - 1])
        c1 = dot(v1, v1)
        if c1 < EPS:
            frames.append((r_prev, cross(tangents[i], r_prev), tangents[i]))
            continue
        r_l = sub(r_prev, mul(v1, 2.0 / c1 * dot(v1, r_prev)))
        t_l = sub(t_prev, mul(v1, 2.0 / c1 * dot(v1, t_prev)))
        v2 = sub(tangents[i], t_l)
        c2 = dot(v2, v2)
        r_i = sub(r_l, mul(v2, 2.0 / c2 * dot(v2, r_l))) if c2 > EPS else r_l
        r_i = normalize(sub(r_i, mul(tangents[i], dot(r_i, tangents[i]))))
        frames.append((r_i, cross(tangents[i], r_i), tangents[i]))
    return frames


def _rail_points(rail: list[Vec], path: list[Vec], normals: list[Vec]) -> list[Vec]:
    points = []
    previous = rail[0]
    for i, (origin, normal) in enumerate(zip(path, normals)):
        hits = plane_intersections(rail, origin, normal) if length(normal) > EPS else []
        if hits:
            previous = min(hits, key=lambda h: dist(h, previous))
        else:
            previous = polyline_point_at(rail, i / max(len(path) - 1, 1))
        points.append(previous)
    return points


def sweep(
    profile: list[Vec],
    path: list[Vec],
    *,
    orientation: str = "PERPENDICULAR",
    rail: list[Vec] | None = None,
    twist: float = 0.0,
    scale_end: float = 1.0,
    closed_path: bool = False,
) -> list[list[Vec]]:
    """Move a profile along a path.

    PERPENDICULAR keeps the profile square to the path (pipes, ducts).
    PARALLEL keeps it facing its original direction (wings: sections stay
    streamwise while the leading edge sweeps back and rises with dihedral).
    A guide rail scales and turns the profile so the profile point that
    starts on the rail stays on it, like Fusion's path + guide rail sweep:
    lead the path along the leading edge, the rail along the trailing edge,
    and the chord follows the planform.
    """
    count = len(path)
    if count < 2:
        raise ValueError("The sweep path needs at least two points")
    if closed_path:
        tangents = [normalize(sub(path[(i + 1) % count], path[i - 1])) for i in range(count)]
    else:
        tangents = [
            normalize(sub(path[min(i + 1, count - 1)], path[max(i - 1, 0)])) for i in range(count)
        ]
    p0 = path[0]
    if orientation == "PARALLEL":
        plane_normal = newell_normal(profile)
        if length(plane_normal) < EPS:
            plane_normal = tangents[0]
        if dot(plane_normal, tangents[0]) < 0:
            plane_normal = mul(plane_normal, -1.0)
        frames = None
        normals = [plane_normal] * count
    else:
        frames = _rotation_minimizing_frames(path, tangents)
        normals = tangents
        r0, s0, t0 = frames[0]
        local = [(dot(sub(q, p0), r0), dot(sub(q, p0), s0), dot(sub(q, p0), t0)) for q in profile]

    rail_targets = _rail_points(rail, path, normals) if rail and len(rail) >= 2 else None
    reference = None
    if rail_targets:
        reference = sub(rail_targets[0], p0)
        reference = sub(reference, mul(normals[0], dot(reference, normals[0])))
        if length(reference) < EPS:
            rail_targets = None

    rows = []
    for i in range(count):
        f = i / (count - 1) if count > 1 else 0.0
        origin, normal = path[i], normals[i]
        if frames is None:
            offsets = [sub(q, p0) for q in profile]
            expected = reference
        else:
            r, s, t = frames[i]
            offsets = [add(add(mul(r, lx), mul(s, ly)), mul(t, lz)) for lx, ly, lz in local]
            if reference is not None:
                r0, s0, _ = frames[0]
                expected = add(mul(r, dot(reference, r0)), mul(s, dot(reference, s0)))
        scale = 1.0 + (scale_end - 1.0) * f
        angle = math.radians(twist) * f
        if rail_targets:
            actual = sub(rail_targets[i], origin)
            actual = sub(actual, mul(normal, dot(actual, normal)))
            if length(actual) > EPS:
                scale *= length(actual) / length(reference)
                angle += signed_angle(expected, actual, normal)
        rows.append([add(origin, mul(rotate(o, normal, angle), scale)) for o in offsets])
    return rows


# --- mesh assembly ----------------------------------------------------------------

CAP_TYPES = ("NONE", "FAN", "STRIP", "NGON")


def _cap(base: int, count: int, kind: str, center_index: int | None) -> list[tuple[int, ...]]:
    if kind == "FAN":
        return [(center_index, base + (j + 1) % count, base + j) for j in range(count)]
    if kind == "NGON":
        return [tuple(base + j for j in reversed(range(count)))]
    if kind == "STRIP":
        faces = []
        for k in range(count // 2):
            quad = [base + k, base + k + 1, base + (count - k - 1) % count, base + (count - k) % count]
            unique = []
            for index in quad:
                if index not in unique:
                    unique.append(index)
            if len(unique) >= 3:
                faces.append(tuple(reversed(unique)))
        return faces
    return []


def build_mesh(
    rows: list[list[Vec]],
    closed_profile: bool,
    *,
    closed_rows: bool = False,
    cap_start: str = "NONE",
    cap_end: str = "NONE",
    sharp_angle: float = math.radians(35.0),
) -> tuple[list[Vec], list[tuple[int, ...]], set[tuple[int, int]]]:
    """Turn rows into vertices, quad faces, and the edges that should shade sharp."""
    columns = len(rows[0])
    row_count = len(rows)
    verts = [p for row in rows for p in row]
    faces: list[tuple[int, ...]] = []
    span_rows = row_count if closed_rows else row_count - 1
    span_cols = columns if closed_profile else columns - 1
    for i in range(span_rows):
        i2 = (i + 1) % row_count
        for j in range(span_cols):
            j2 = (j + 1) % columns
            faces.append((i * columns + j, i * columns + j2, i2 * columns + j2, i2 * columns + j))

    sharp: set[tuple[int, int]] = set()
    turning = turning_angles(rows[0], closed_profile)
    for j, angle in enumerate(turning):
        if angle > sharp_angle:
            for i in range(span_rows):
                a, b = i * columns + j, ((i + 1) % row_count) * columns + j
                sharp.add((min(a, b), max(a, b)))

    if closed_profile and not closed_rows:
        for kind, row_index, flip in ((cap_start, 0, False), (cap_end, row_count - 1, True)):
            if kind == "NONE":
                continue
            center_index = None
            if kind == "FAN":
                center_index = len(verts)
                verts.append(centroid(rows[row_index]))
            cap_faces = _cap(row_index * columns, columns, kind, center_index)
            if flip:
                cap_faces = [tuple(reversed(face)) for face in cap_faces]
            faces.extend(cap_faces)
            base = row_index * columns
            for j in range(columns):
                a, b = base + j, base + (j + 1) % columns
                sharp.add((min(a, b), max(a, b)))

    if _orientation_sign(verts, faces) < 0:
        faces = [tuple(reversed(face)) for face in faces]
    return verts, faces, sharp


def _orientation_sign(verts: list[Vec], faces: list[tuple[int, ...]]) -> float:
    """Positive when faces point outward (signed volume, or centroid test for open shells)."""
    center = centroid(verts)
    volume = 0.0
    outward = 0.0
    for face in faces:
        a = sub(verts[face[0]], center)
        for k in range(1, len(face) - 1):
            b, c = sub(verts[face[k]], center), sub(verts[face[k + 1]], center)
            volume += dot(a, cross(b, c))
            outward += dot(cross(sub(b, a), sub(c, a)), add(add(a, b), c))
    return volume if abs(volume) > 1e-9 else outward


# --- airfoils -------------------------------------------------------------------

def naca4(code: str, points: int = 61) -> list[tuple[float, float]]:
    """NACA 4-digit airfoil, chord 1, leading edge at (0, 0).

    Order: trailing edge, upper surface to the leading edge, lower surface
    back toward the trailing edge (closed trailing edge, no duplicate point).
    Cosine spacing clusters points at the leading edge.
    """
    code = code.strip()
    if len(code) != 4 or not code.isdigit():
        raise ValueError("NACA code must be 4 digits, e.g. 2412")
    m, p, t = int(code[0]) / 100.0, int(code[1]) / 10.0, int(code[2:]) / 100.0
    half = max(8, points // 2)

    def surface(x: float) -> tuple[float, float, float]:
        yt = 5.0 * t * (0.2969 * math.sqrt(x) - 0.1260 * x - 0.3516 * x**2 + 0.2843 * x**3 - 0.1036 * x**4)
        if m > 0 and p > 0:
            if x < p:
                yc = m / p**2 * (2 * p * x - x * x)
                slope = 2 * m / p**2 * (p - x)
            else:
                yc = m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * x - x * x)
                slope = 2 * m / (1 - p) ** 2 * (p - x)
        else:
            yc, slope = 0.0, 0.0
        return yt, yc, math.atan(slope)

    xs = [(1 - math.cos(math.pi * k / half)) / 2 for k in range(half + 1)]  # 0 (LE) .. 1 (TE)
    upper, lower = [], []
    for x in xs:
        yt, yc, theta = surface(x)
        upper.append((x - yt * math.sin(theta), yc + yt * math.cos(theta)))
        lower.append((x + yt * math.sin(theta), yc - yt * math.cos(theta)))
    trailing = (1.0, 0.0)
    return [trailing] + upper[::-1][1:] + lower[1:-1]


def parse_airfoil_dat(text: str) -> list[tuple[float, float]]:
    """Read Selig or Lednicer .dat coordinates into naca4's point order, chord 1."""
    rows = []
    for line in text.splitlines():
        parts = line.replace(",", " ").split()
        if len(parts) < 2:
            rows.append(None)
            continue
        try:
            rows.append((float(parts[0]), float(parts[1])))
        except ValueError:
            rows.append(None)
    numbers = [r for r in rows if r is not None]
    if len(numbers) < 5:
        raise ValueError("No airfoil coordinates found")
    if numbers[0][0] > 1.5 and numbers[0][1] > 1.5:
        upper_count, lower_count = int(numbers[0][0]), int(numbers[0][1])
        upper = numbers[1 : 1 + upper_count]
        lower = numbers[1 + upper_count : 1 + upper_count + lower_count]
        ordered = upper[::-1] + lower[1:]
    else:
        ordered = numbers
    x_min = min(p[0] for p in ordered)
    x_max = max(p[0] for p in ordered)
    chord = (x_max - x_min) or 1.0
    le_index = min(range(len(ordered)), key=lambda i: ordered[i][0])
    y_le = ordered[le_index][1]
    normalized = [((x - x_min) / chord, (y - y_le) / chord) for x, y in ordered]
    if len(normalized) > 2 and math.dist(normalized[0], normalized[-1]) < 1e-6:
        normalized.pop()
    # Start at the upper trailing edge: the first point should be above the last.
    if normalized[0][1] < normalized[-1][1]:
        normalized = normalized[::-1]
    return normalized

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aircraft_builder import core, design  # noqa: E402


def ellipse(y, width, height, count=24, start=0.0):
    return [
        (width / 2 * math.cos(start + 2 * math.pi * k / count), y, height / 2 * math.sin(start + 2 * math.pi * k / count))
        for k in range(count)
    ]


def airfoil_3d(code="2412", chord=1.0, x=0.0):
    return [(x, px * chord, py * chord) for px, py in core.naca4(code)]


class ResampleTests(unittest.TestCase):
    def test_closed_resample_keeps_count_and_corners(self):
        square = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        result = core.resample(square, 16, closed=True)
        self.assertEqual(len(result), 16)
        for corner in square:
            self.assertTrue(any(core.dist(corner, p) < 1e-9 for p in result), corner)

    def test_open_resample_keeps_endpoints(self):
        line = [(0, 0, 0), (2, 0, 0), (2, 3, 0)]
        result = core.resample(line, 11, closed=False)
        self.assertEqual(len(result), 11)
        self.assertEqual(result[0], (0, 0, 0))
        self.assertEqual(result[-1], (2, 3, 0))

    def test_airfoil_trailing_edge_survives_resampling(self):
        result = core.resample(airfoil_3d(), 40, closed=True, curvature_bias=1.0)
        self.assertLess(core.dist(result[0], (0.0, 1.0, 0.0)), 1e-9)


class AirfoilTests(unittest.TestCase):
    def test_naca_shape(self):
        points = core.naca4("0012", 61)
        self.assertEqual(points[0], (1.0, 0.0))
        le = min(points, key=lambda p: p[0])
        self.assertAlmostEqual(le[0], 0.0, places=6)
        thickness = max(p[1] for p in points) - min(p[1] for p in points)
        self.assertAlmostEqual(thickness, 0.12, delta=0.004)
        self.assertGreater(points[1][1], 0)  # upper surface comes first

    def test_bad_code(self):
        with self.assertRaises(ValueError):
            core.naca4("23015")

    def test_parse_selig_and_lednicer(self):
        selig = "TEST\n1.0 0.001\n0.5 0.06\n0.0 0.0\n0.5 -0.04\n1.0 -0.001\n"
        points = core.parse_airfoil_dat(selig)
        self.assertGreater(points[0][1], points[-1][1])
        self.assertEqual(min(p[0] for p in points), 0.0)
        lednicer = "TEST\n3. 3.\n\n0.0 0.0\n0.5 0.06\n1.0 0.0\n\n0.0 0.0\n0.5 -0.04\n1.0 0.0\n"
        points = core.parse_airfoil_dat(lednicer)
        self.assertEqual(len(points), 4)
        self.assertEqual(points[0], (1.0, 0.0))


class LoftTests(unittest.TestCase):
    def test_loft_aligns_rotated_and_reversed_profiles(self):
        a = ellipse(0, 2, 2)
        b = list(reversed(ellipse(1, 2, 2, start=0.7)))
        rows = core.loft([a, b], closed=True, steps=4)
        self.assertEqual(len(rows), 5)
        # Columns should run straight along Y: no twist after alignment.
        for j in range(len(a)):
            self.assertLess(abs(rows[0][j][0] - rows[-1][j][0]), 0.3)

    def test_smooth_loft_passes_through_sections(self):
        sections = [ellipse(0, 1, 1), ellipse(2, 2, 2), ellipse(4, 1, 1)]
        rows = core.loft(sections, closed=True, steps=5)
        self.assertEqual(len(rows), 11)
        for row, section in ((rows[0], sections[0]), (rows[5], sections[1]), (rows[10], sections[2])):
            self.assertLess(max(core.dist(p, q) for p, q in zip(row, section)), 1e-6)

    def test_rail_pulls_column_out(self):
        a, b = ellipse(0, 2, 2), ellipse(4, 2, 2)
        rail =[(1.0 + math.sin(math.pi * y / 8), y * 0.5, 0.0) for y in range(9)]
        rows = core.loft([a, b], closed=True, steps=8, smooth=False, rails=[rail])
        middle = rows[4]
        self.assertAlmostEqual(middle[0][0], 2.0, delta=0.05)  # column 0 starts at +X
        opposite = middle[len(a) // 2]
        self.assertAlmostEqual(opposite[0], -1.0, delta=0.05)  # far side untouched


class SweepTests(unittest.TestCase):
    def test_wing_sweep_with_guide_rail_tapers_chord(self):
        profile = airfoil_3d(chord=2.0)
        path = [(x * 0.5, x * 0.5 * 0.2, 0.0) for x in range(11)]  # leading edge, swept back
        rail = [(0.0, 2.0, 0.0), (5.0, 2.0, 0.0)]  # trailing edge, straight: chord shrinks
        rows = core.sweep(profile, path, orientation="PARALLEL", rail=rail)
        tip = rows[-1]
        self.assertTrue(all(abs(p[0] - 5.0) < 1e-6 for p in tip))  # sections stay streamwise
        tip_chord = max(p[1] for p in tip) - min(p[1] for p in tip)
        self.assertAlmostEqual(tip_chord, 1.0, delta=0.02)
        self.assertAlmostEqual(tip[0][1], 2.0, delta=1e-6)  # trailing edge sits on the rail

    def test_perpendicular_sweep_follows_bend(self):
        profile = [(0.1 * math.cos(a), 0.0, 0.1 * math.sin(a)) for a in [2 * math.pi * k / 12 for k in range(12)]]
        path = [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 2.0, 0.0), (2.0, 2.0, 0.0)]
        path = core.resample(path, 20, closed=False)
        rows = core.sweep(profile, path)
        end_center = core.centroid(rows[-1])
        self.assertLess(core.dist(end_center, (2.0, 2.0, 0.0)), 1e-6)
        radius = max(core.dist(p, end_center) for p in rows[-1])
        self.assertAlmostEqual(radius, 0.1, delta=1e-6)
        # The end ring faces +X: all its points share x.
        self.assertLess(max(abs(p[0] - 2.0) for p in rows[-1]), 1e-6)


class MeshTests(unittest.TestCase):
    def test_capped_loft_is_closed_and_outward(self):
        rows = core.loft([ellipse(0, 1, 1, 16), ellipse(2, 1, 1, 16)], closed=True, steps=2)
        verts, faces, sharp = core.build_mesh(rows, True, cap_start="FAN", cap_end="FAN")
        edges = {}
        for face in faces:
            for i in range(len(face)):
                key = tuple(sorted((face[i], face[(i + 1) % len(face)])))
                edges[key] = edges.get(key, 0) + 1
        self.assertTrue(all(count == 2 for count in edges.values()))  # watertight
        self.assertGreater(core._orientation_sign(verts, faces), 0)
        self.assertTrue(sharp)

    def test_strip_cap_on_airfoil_is_mostly_quads(self):
        profile = core.resample(airfoil_3d(), 40, closed=True, curvature_bias=1.0)
        rows = core.sweep(profile, [(0, 0, 0), (3, 0, 0)])
        verts, faces, sharp = core.build_mesh(rows, True, cap_start="STRIP", cap_end="STRIP")
        caps = faces[len(profile):]
        self.assertGreater(sum(1 for f in caps if len(f) == 4), sum(1 for f in caps if len(f) == 3))
        # Trailing-edge column is marked sharp.
        self.assertIn((0, len(profile)), sharp)


class FairingTests(unittest.TestCase):
    def setUp(self):
        profile = core.resample(airfoil_3d("2412", chord=2.0), 40, closed=True, curvature_bias=1.0)
        path = [(0.0, 0.0, -0.5), (6.0, 0.6, -0.2)]
        rail = [(0.0, 2.0, -0.5), (6.0, 1.4, -0.2)]
        self.rows = core.sweep(profile, core.resample(path, 13, False), orientation="PARALLEL", rail=rail)

    def test_slice_matches_row_at_station(self):
        section = core.slice_columns(self.rows, 0, 3.0)
        self.assertTrue(all(abs(p[0] - 3.0) < 1e-9 for p in section))
        self.assertLess(max(core.dist(a, b) for a, b in zip(section, self.rows[6])), 1e-9)

    def test_outline_encloses_section(self):
        section = core.slice_columns(self.rows, 0, 1.0)
        outline = core.fairing_outline(section, forward=0.35, aft=0.5, depth=0.2, top=0.1)
        ys, zs = [p[1] for p in section], [p[2] for p in section]
        chord = max(ys) - min(ys)
        self.assertAlmostEqual(min(p[1] for p in outline), min(ys) - 0.35 * chord, places=6)
        self.assertAlmostEqual(max(p[1] for p in outline), max(ys) + 0.5 * chord, places=6)
        self.assertLess(min(p[2] for p in outline), min(zs) - 0.1 * chord)
        self.assertGreater(max(p[2] for p in outline), max(zs))

    def test_rows_blend_from_wing_to_centerline_smoothly(self):
        section = core.slice_columns(self.rows, 0, 1.0)
        outline = core.fairing_outline(section, 0.35, 0.5, 0.2, 0.1)
        rows = core.fairing_rows(section, outline, 10, 1.0)
        self.assertEqual(rows[0], section)  # starts exactly on the wing
        self.assertTrue(all(abs(p[0]) < 1e-12 for p in rows[-1]))
        self.assertLess(max(core.dist((0.0, a[1], a[2]), (0.0, b[1], b[2])) for a, b in zip(rows[-1], outline)), 1e-9)
        # Zero slope at both ends: first and last steps change the shape far less than the middle.
        def change(a, b):
            return max(math.hypot(p[1] - q[1], p[2] - q[2]) for p, q in zip(a, b))
        self.assertLess(change(rows[0], rows[1]), change(rows[4], rows[5]) / 3)
        self.assertLess(change(rows[-2], rows[-1]), change(rows[4], rows[5]) / 3)

    def test_drawn_outline_is_matched_upper_to_upper(self):
        section = core.slice_columns(self.rows, 0, 1.0)
        drawn = [(0.0, 1.0 + 2.0 * math.cos(a), -0.5 + 0.6 * math.sin(a)) for a in [k * math.pi / 20 for k in range(40)]]
        drawn = drawn[::-1]  # draw it the "wrong" way round
        matched = core.match_outline(section, drawn)
        self.assertEqual(len(matched), len(section))
        aft, front = core._halves(section)
        for i, (p, q) in enumerate(zip(section, matched)):
            if i not in (aft, front) and abs(p[2] - section[front][2]) > 0.02:
                self.assertEqual(p[2] > section[front][2], q[2] > -0.5, i)


class DesignTests(unittest.TestCase):
    def test_small_jet_proportions_are_realistic(self):
        jet = design.small_jet(14.0)
        self.assertAlmostEqual(jet.diameter, 14 / 8.5)
        wing = next(s for s in jet.surfaces if s.name == "Wing")
        self.assertTrue(18 < jet.summary["Wing area (m²)"] < 30)
        self.assertLess(wing.tip_chord, wing.root_chord)
        fin = next(s for s in jet.surfaces if s.name == "Vertical Tail")
        self.assertLessEqual(fin.root_te[1], 14.0)
        tail = next(s for s in jet.surfaces if s.name == "Horizontal Tail")
        self.assertGreater(tail.root_le[2], 1.5)  # T-tail sits up on the fin
        fuselage = jet.bodies[0]
        self.assertAlmostEqual(fuselage.rings[-1].y, 14.0)

    def test_single_piston_proportions_match_light_aircraft(self):
        plane = design.single_piston(8.3)
        s = plane.summary
        self.assertTrue(10.0 < s["Wingspan (m)"] < 12.0)
        self.assertTrue(14.0 < s["Wing area (m²)"] < 19.0)
        self.assertTrue(1.7 < s["Propeller diameter (m)"] < 2.1)
        wing = next(x for x in plane.surfaces if x.name == "Wing")
        self.assertEqual(len(wing.le_points), 3)  # constant-chord inner panel
        self.assertAlmostEqual(wing.te_points[1][1] - wing.le_points[1][1], wing.root_chord)
        self.assertEqual({x.name for x in plane.struts}, {"Wing Strut"})
        self.assertEqual({g.name for g in plane.gear}, {"Main Gear", "Nose Gear"})
        self.assertTrue(all(g.fairing and not g.retract_axis for g in plane.gear))
        # Ground (bottom of the wheels) stays below the propeller tip.
        prop = plane.propellers[0]
        main = next(g for g in plane.gear if g.name == "Main Gear")
        self.assertLess(main.wheel[2] - main.wheel_radius, prop.hub[2] - prop.radius)
        nose = next(g for g in plane.gear if g.name == "Nose Gear")
        self.assertAlmostEqual(main.wheel[2] - main.wheel_radius, nose.wheel[2] - nose.wheel_radius)
        # The tail fits on the fuselage.
        for surface in plane.surfaces:
            self.assertLessEqual(surface.root_te[1], 8.3 + 1e-9, surface.name)

    def test_low_wing_has_no_struts_and_more_dihedral(self):
        high, low = design.single_piston(8.3, wing="HIGH"), design.single_piston(8.3, wing="LOW", gear=False)
        self.assertNotIn("Wing Strut", {x.name for x in low.struts})
        self.assertFalse(low.struts)
        rise = lambda p: next(x for x in p.surfaces if x.name == "Wing").tip_le[2] - next(
            x for x in p.surfaces if x.name == "Wing").root_le[2]
        self.assertGreater(rise(low), rise(high))

    def test_retractable_gear_splits_sides_and_folds_the_right_way(self):
        plane = design.single_piston(8.3, wing="LOW", gear="RETRACTABLE")
        gear = {g.name: g for g in plane.gear}
        self.assertEqual(set(gear), {"Main Gear Right", "Main Gear Left", "Nose Gear"})
        right, left, nose = gear["Main Gear Right"], gear["Main Gear Left"], gear["Nose Gear"]
        self.assertTrue(right.wheel[0] > 0 > left.wheel[0])
        self.assertEqual((right.retract_axis, left.retract_axis, nose.retract_axis), ("Y", "Y", "X"))
        self.assertEqual(right.retract_angle, -left.retract_angle)
        self.assertFalse(any(g.fairing or g.mirror for g in plane.gear))

        def fold(g):
            """Wheel position after full retraction (rotate about the pivot)."""
            a = math.radians(g.retract_angle)
            d = [w - p for w, p in zip(g.wheel, g.pivot)]
            if g.retract_axis == "Y":
                d = [d[0] * math.cos(a) + d[2] * math.sin(a), d[1], -d[0] * math.sin(a) + d[2] * math.cos(a)]
            else:
                d = [d[0], d[1] * math.cos(a) - d[2] * math.sin(a), d[1] * math.sin(a) + d[2] * math.cos(a)]
            return [p + c for p, c in zip(g.pivot, d)]

        self.assertLess(abs(fold(right)[0]), abs(right.wheel[0]))  # folds inward
        self.assertLess(abs(fold(left)[0]), abs(left.wheel[0]))
        self.assertLess(fold(nose)[1], nose.wheel[1])  # nose wheel folds forward
        for g in plane.gear:
            self.assertGreater(fold(g)[2], g.wheel[2] + 0.3)  # and up

    def test_wheel_and_fairing_bodies_enclose_the_tire(self):
        main = next(g for g in design.single_piston(8.3).gear if g.name == "Main Gear")
        wheel, pant = main.wheel_body(), main.fairing_body()
        self.assertEqual(wheel.axis, "X")
        self.assertEqual(wheel.name, "Main Wheel")
        self.assertAlmostEqual(max(r.height for r in wheel.rings), 2 * main.wheel_radius)
        widest = max(pant.rings, key=lambda r: r.width)
        self.assertGreater(widest.width, main.wheel_width)
        pant_bottom = widest.z - widest.height / 2
        tire_bottom = main.wheel[2] - main.wheel_radius
        self.assertTrue(tire_bottom < pant_bottom < main.wheel[2])  # the tire pokes out below

    def test_windows_and_dorsal_fin(self):
        for plane in (design.single_piston(8.3), design.small_jet(14.0)):
            shield = next(w for w in plane.windows if w.name == "Windshield")
            normal = core.cross(shield.u_axis, shield.v_axis)
            self.assertGreater(normal[2], 0.3)  # faces up and forward onto the nose
            self.assertLess(normal[1], 0.0)
            sides = next(w for w in plane.windows if w.name != "Windshield")
            self.assertTrue(sides.mirror and sides.ovals)
            dorsal = next(s for s in plane.surfaces if s.name == "Dorsal Fin")
            fin = next(s for s in plane.surfaces if s.name == "Vertical Tail")
            self.assertLess(dorsal.root_le[1], fin.root_le[1])
            self.assertGreater(dorsal.root_te[1], fin.root_le[1])  # ends inside the fin
        bare = design.single_piston(8.3, windows=False, dorsal=False, gear="NONE")
        self.assertFalse(bare.windows or bare.gear)
        self.assertNotIn("Dorsal Fin", {s.name for s in bare.surfaces})

    def test_conventional_tail_and_no_engines(self):
        jet = design.small_jet(12.0, tail="CONVENTIONAL", engines=False)
        self.assertEqual([b.name for b in jet.bodies], ["Fuselage"])
        tail = next(s for s in jet.surfaces if s.name == "Horizontal Tail")
        self.assertLess(tail.root_le[2], 1.0)


if __name__ == "__main__":
    unittest.main()

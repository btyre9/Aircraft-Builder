import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loft_sweep import core, design  # noqa: E402


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

    def test_conventional_tail_and_no_engines(self):
        jet = design.small_jet(12.0, tail="CONVENTIONAL", engines=False)
        self.assertEqual([b.name for b in jet.bodies], ["Fuselage"])
        tail = next(s for s in jet.surfaces if s.name == "Horizontal Tail")
        self.assertLess(tail.root_le[2], 1.0)


if __name__ == "__main__":
    unittest.main()

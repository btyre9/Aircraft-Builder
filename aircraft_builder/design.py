"""Realistic aircraft proportions from a few top-level numbers.

These are conceptual-design rules of thumb (the kind found in aircraft design
textbooks such as Raymer's). Tail areas come from tail volume coefficients,
which balance a tail's size against its distance from the wing.

Small jet (light business jet):
- fuselage fineness (length / diameter) about 8.5
- wingspan about equal to fuselage length, aspect ratio 8.5, taper 0.4
- tail volume: horizontal 0.85, vertical 0.08

Single-engine piston (four-seat light aircraft):
- wingspan about 1.33 x length, aspect ratio 7.4, constant-chord inner wing
  with a tapered outer panel
- cabin about 0.14 x length wide, 0.165 x length tall
- tail volume: horizontal 0.70, vertical 0.04
- propeller diameter about 0.23 x length, fixed tricycle gear

Axes match Blender: nose at the origin pointing -Y, the body runs along +Y,
span along X, up is Z. Units are metres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Vec = tuple[float, float, float]
CIRCLE = 0.5523  # Bezier handle length that draws a circle; larger is squarer


@dataclass
class Ring:
    y: float
    width: float
    height: float
    z: float = 0.0
    x: float = 0.0
    squareness: float = CIRCLE


@dataclass
class Surface:
    """A wing-like surface: an airfoil swept from root to tip.

    With `kink` > 0 the chord stays at root size out to that fraction of the
    span, then tapers to the tip (a typical light-aircraft wing).
    """

    name: str
    airfoil: str
    root_le: Vec
    root_chord: float
    tip_le: Vec
    tip_chord: float
    vertical: bool = False
    mirror: bool = True
    twist: float = 0.0
    kink: float = 0.0

    @property
    def root_te(self) -> Vec:
        x, y, z = self.root_le
        return (x, y + self.root_chord, z)

    @property
    def tip_te(self) -> Vec:
        x, y, z = self.tip_le
        return (x, y + self.tip_chord, z)

    def _kink_le(self) -> Vec:
        (rx, ry, rz), (tx, _, tz) = self.root_le, self.tip_le
        return (rx + (tx - rx) * self.kink, ry, rz + (tz - rz) * self.kink)

    @property
    def le_points(self) -> list[Vec]:
        if self.kink <= 0:
            return [self.root_le, self.tip_le]
        return [self.root_le, self._kink_le(), self.tip_le]

    @property
    def te_points(self) -> list[Vec]:
        if self.kink <= 0:
            return [self.root_te, self.tip_te]
        x, y, z = self._kink_le()
        return [self.root_te, (x, y + self.root_chord, z), self.tip_te]


@dataclass
class Body:
    """Loft through rings. axis "Y" rings face along the body; "X" rings face sideways (wheels)."""

    name: str
    rings: list[Ring]
    mirror: bool = False
    axis: str = "Y"


@dataclass
class Strut:
    """A streamlined rod (wing strut, gear leg): an airfoil swept along a line."""

    name: str
    start: Vec
    end: Vec
    chord: float
    airfoil: str = "0025"
    mirror: bool = True
    round: bool = False


@dataclass
class Window:
    """Glass projected onto a body from outlines drawn in a plane outside it.

    The plane is origin + u * u_axis + v * v_axis; projection runs along
    u_axis x v_axis toward the body. Ovals are (u, v, width, height,
    squareness); corners describe one rounded polygon (a windshield).
    """

    name: str
    origin: Vec
    u_axis: Vec
    v_axis: Vec
    ovals: list[tuple[float, float, float, float, float]] = field(default_factory=list)
    corners: list[tuple[float, float]] = field(default_factory=list)
    mirror: bool = True
    target: str = "Fuselage"


@dataclass
class Gear:
    """One landing gear leg with its wheel, optional fairing, and retraction.

    retract_axis "Y" folds a main gear sideways about the fore-aft axis;
    "X" folds a nose gear about the spanwise axis. retract_angle is the
    rotation in degrees at full retraction ("" axis means fixed gear).
    """

    name: str
    pivot: Vec
    wheel: Vec
    wheel_radius: float
    wheel_width: float
    leg_width: float
    retract_axis: str = ""
    retract_angle: float = 0.0
    fairing: bool = False
    mirror: bool = True

    def wheel_body(self) -> Body:
        x, y, z = self.wheel
        r, w = self.wheel_radius, self.wheel_width
        tire = ((-0.5, 0.6), (-0.44, 0.84), (-0.3, 0.97), (0.0, 1.0), (0.3, 0.97), (0.44, 0.84), (0.5, 0.6))
        return Body(
            self.name.replace("Gear", "Wheel"),
            [Ring(y, 2 * r * s, 2 * r * s, z, x + f * w) for f, s in tire],
            mirror=self.mirror,
            axis="X",
        )

    def fairing_body(self) -> Body:
        """Teardrop wheel fairing around the wheel; the tire pokes out of the bottom."""
        x, y, z = self.wheel
        r = self.wheel_radius
        length, width, height = 4.2 * r, max(1.5 * self.wheel_width, 0.9 * r), 2.3 * r
        center_z = z + 0.38 * r
        pant = ((-0.46, 0.04), (-0.36, 0.55), (-0.18, 0.92), (0.06, 1.0), (0.3, 0.7), (0.48, 0.08))
        return Body(
            self.name.replace("Gear", "Wheel Fairing"),
            [Ring(y + f * length, width * s, height * s, center_z, x) for f, s in pant],
            mirror=self.mirror,
        )


@dataclass
class Propeller:
    """Twisted, tapered blades around a hub; the propeller axis is Y."""

    name: str
    hub: Vec
    radius: float
    root_radius: float
    blades: int = 2
    root_chord: float = 0.13
    tip_chord: float = 0.07
    root_pitch: float = 45.0
    tip_pitch: float = 15.0
    airfoil: str = "4412"


@dataclass
class Design:
    length: float
    span: float
    diameter: float
    bodies: list[Body] = field(default_factory=list)
    surfaces: list[Surface] = field(default_factory=list)
    struts: list[Strut] = field(default_factory=list)
    propellers: list[Propeller] = field(default_factory=list)
    windows: list[Window] = field(default_factory=list)
    gear: list[Gear] = field(default_factory=list)
    summary: dict[str, float] = field(default_factory=dict)


JetDesign = Design


def _body_top(rings: list[Ring], y: float) -> float:
    """Height of the top of a ring loft at y (linear between rings)."""
    tops = [(ring.y, ring.z + ring.height / 2) for ring in sorted(rings, key=lambda r: r.y)]
    if y <= tops[0][0]:
        return tops[0][1]
    for (y0, z0), (y1, z1) in zip(tops, tops[1:]):
        if y <= y1:
            return z0 + (z1 - z0) * (y - y0) / ((y1 - y0) or 1.0)
    return tops[-1][1]


def _windshield(rings: list[Ring], y0: float, y1: float, half_bottom: float, half_top: float) -> Window:
    """Windshield outline in a plane tilted to face the windshield slope from y0 to y1."""
    z0, z1 = _body_top(rings, y0), _body_top(rings, y1)
    run = math.hypot(y1 - y0, z1 - z0)
    sy, sz = (y1 - y0) / run, (z1 - z0) / run
    lift = 0.5 * run
    origin = (0.0, y0 - sz * lift, z0 + sy * lift)  # out along the surface normal
    corners = [(-half_bottom, 0.04 * run), (half_bottom, 0.04 * run), (half_top, 0.95 * run), (-half_top, 0.95 * run)]
    return Window("Windshield", origin, (1.0, 0.0, 0.0), (0.0, sy, sz), corners=corners, mirror=False)


def _dorsal(rings: list[Ring], fin: Surface, length: float, height: float) -> Surface:
    """Low strake from the spine up into the fin leading edge.

    length is in fin root chords ahead of the fin; height is a fraction of
    the fin's height where the strake meets its leading edge.
    """
    fin_le_y, fin_z = fin.root_le[1], fin.root_le[2]
    fin_height = fin.tip_le[2] - fin_z
    front = fin_le_y - length * fin.root_chord
    root_end = fin_le_y + 0.35 * fin.root_chord
    root_z = min(_body_top(rings, front), _body_top(rings, root_end)) - 0.03 * fin.root_chord
    rise = height * fin_height
    tip_z = fin_z + rise
    tip_le_y = fin_le_y + (fin.tip_le[1] - fin_le_y) * rise / fin_height + 0.02 * fin.root_chord
    return Surface("Dorsal Fin", "0008", (0.0, front, root_z), root_end - front,
                   (0.0, tip_le_y, tip_z), 0.3 * fin.root_chord, vertical=True, mirror=False)


def _retractable(name: str, pivot: Vec, wheel: Vec, radius: float, width: float, leg: float,
                 axis: str) -> list[Gear]:
    """Gear legs that fold away. Main gear (axis "Y") becomes a left and a right leg."""
    if axis == "X":
        return [Gear(name, pivot, wheel, radius, width, leg, "X", -90.0, mirror=False)]
    gears = []
    for side, sign in (("Right", 1.0), ("Left", -1.0)):
        p = (pivot[0] * sign, pivot[1], pivot[2])
        w = (wheel[0] * sign, wheel[1], wheel[2])
        gears.append(Gear(f"{name} {side}", p, w, radius, width, leg, "Y", 90.0 * sign, mirror=False))
    return gears


def _trapezoid(area: float, aspect_ratio: float, taper: float) -> tuple[float, float, float]:
    """Span, root chord, tip chord of a trapezoidal surface."""
    span = math.sqrt(aspect_ratio * area)
    root = 2.0 * area / (span * (1.0 + taper))
    return span, root, root * taper


def _mac(root: float, taper: float) -> float:
    return 2.0 / 3.0 * root * (1 + taper + taper * taper) / (1 + taper)


def _mac_offset(span_one_side: float, taper: float, sweep_deg: float) -> float:
    """Distance the MAC leading edge sits behind the root leading edge."""
    y_mac = span_one_side / 3.0 * (1 + 2 * taper) / (1 + taper)
    return y_mac * math.tan(math.radians(sweep_deg))


def small_jet(
    length: float = 14.0,
    span: float = 0.0,
    diameter: float = 0.0,
    tail: str = "T",
    engines: bool = True,
    gear: str = "RETRACTABLE",
    windows: bool = True,
    dorsal: bool = True,
) -> JetDesign:
    """Build a light business jet layout. Zero span or diameter means "pick for me".

    gear is "RETRACTABLE" or "NONE".
    """
    if length <= 0:
        raise ValueError("Length must be positive")
    diameter = diameter or length / 8.5
    span = span or length * 1.0
    design = JetDesign(length=length, span=span, diameter=diameter)
    D, L = diameter, length

    # --- fuselage: rounded nose, constant cabin, upswept tail cone ---
    nose_len, tail_len = 1.6 * D, 2.8 * D
    height = 1.06 * D
    rings: list[Ring] = []
    for f in (0.0, 0.03, 0.1, 0.22, 0.4, 0.62, 0.82, 1.0):
        size = max(math.sqrt(1 - (1 - f) ** 2), 0.02)
        rings.append(Ring(y=f * nose_len, width=D * size, height=height * size, z=-0.12 * D * (1 - f) ** 2))
    cabin_end = L - tail_len
    rings.append(Ring(y=(nose_len + cabin_end) / 2, width=D, height=height))
    rings.append(Ring(y=cabin_end, width=D, height=height))
    upsweep = 0.32 * D
    for g in (0.2, 0.42, 0.64, 0.84, 1.0):
        shrink = g**1.5
        rings.append(
            Ring(
                y=cabin_end + g * tail_len,
                width=max(D * (1 - 0.93 * shrink), 0.02 * D),
                height=max(height * (1 - 0.88 * shrink), 0.02 * D),
                z=upsweep * shrink,
            )
        )
    design.bodies.append(Body("Fuselage", rings))

    # --- wing: low wing, quarter-MAC at 47% of length (aft engines move the CG back) ---
    aspect, taper, sweep, dihedral = 8.5, 0.4, 8.0, 3.0
    area = span * span / aspect
    root = 2 * area / (span * (1 + taper))
    tip = root * taper
    mac = _mac(root, taper)
    half = span / 2
    root_le_y = 0.47 * L - _mac_offset(half, taper, sweep) - 0.25 * mac
    wing_z = -0.3 * D
    design.surfaces.append(
        Surface(
            "Wing",
            "2412",
            (0.0, root_le_y, wing_z),
            root,
            (half, root_le_y + half * math.tan(math.radians(sweep)), wing_z + half * math.tan(math.radians(dihedral))),
            tip,
            twist=-2.0,
        )
    )
    wing_quarter = 0.47 * L

    # --- vertical tail, sized by tail volume ---
    vt_arm = 0.88 * L - wing_quarter
    vt_area = 0.08 * span * area / vt_arm
    vt_taper = 0.6 if tail == "T" else 0.45
    vt_height, vt_root, vt_tip = _trapezoid(vt_area, 1.3, vt_taper)
    vt_sweep = 35.0
    vt_root_z = 0.2 * D
    # Quarter-MAC at 88% of length, but keep the root trailing edge on the tail cone.
    vt_root_le_y = min(
        0.88 * L - _mac_offset(vt_height, vt_taper, vt_sweep) - 0.25 * _mac(vt_root, vt_taper),
        0.97 * L - vt_root,
    )
    vt_tip_le = (0.0, vt_root_le_y + vt_height * math.tan(math.radians(vt_sweep)), vt_root_z + vt_height)
    fin = Surface("Vertical Tail", "0010", (0.0, vt_root_le_y, vt_root_z), vt_root, vt_tip_le, vt_tip,
                  vertical=True, mirror=False)
    design.surfaces.append(fin)
    if dorsal:
        design.surfaces.append(_dorsal(rings, fin, 0.7, 0.22))

    # --- horizontal tail: on top of the fin (T-tail) or on the tail cone ---
    ht_arm = (0.93 if tail == "T" else 0.9) * L - wing_quarter
    ht_area = (0.8 if tail == "T" else 0.9) * mac * area / ht_arm
    ht_span, ht_root, ht_tip = _trapezoid(ht_area, 4.5, 0.5)
    ht_sweep = 25.0
    if tail == "T":
        ht_z = vt_root_z + vt_height * 0.95
        fin_le_at = vt_root_le_y + (ht_z - vt_root_z) * math.tan(math.radians(vt_sweep))
        ht_root_le_y = fin_le_at + 0.08 * ht_root
        ht_dihedral = -2.0
    else:
        ht_z = upsweep * 0.7
        ht_root_le_y = L - ht_root - 0.05 * L
        ht_dihedral = 3.0
    ht_half = ht_span / 2
    design.surfaces.append(
        Surface(
            "Horizontal Tail",
            "0009",
            (0.0, ht_root_le_y, ht_z),
            ht_root,
            (ht_half, ht_root_le_y + ht_half * math.tan(math.radians(ht_sweep)),
             ht_z + ht_half * math.tan(math.radians(ht_dihedral))),
            ht_tip,
        )
    )

    # --- rear-mounted engine pods on short pylons ---
    if engines:
        nacelle_len, nacelle_d = 0.19 * L, 0.55 * D
        r = nacelle_d / 2
        x = D / 2 + 0.75 * nacelle_d
        start = cabin_end - 0.25 * nacelle_len
        z = 0.12 * D
        profile = ((0.0, 0.84), (0.07, 0.97), (0.3, 1.0), (0.7, 0.92), (1.0, 0.62))
        design.bodies.append(
            Body(
                "Engine",
                [Ring(y=start + f * nacelle_len, width=2 * r * s, height=2 * r * s, z=z, x=x) for f, s in profile],
                mirror=True,
            )
        )
        pylon_chord = 0.5 * nacelle_len
        pylon_le_y = start + 0.3 * nacelle_len
        design.surfaces.append(
            Surface("Pylon", "0012", (0.0, pylon_le_y, z), pylon_chord, (x, pylon_le_y + 0.05 * pylon_chord, z), pylon_chord * 0.9)
        )

    # --- windshield and a row of oval cabin windows ---
    if windows:
        design.windows.append(_windshield(rings, 0.4 * nose_len, 0.9 * nose_len, 0.3 * D, 0.2 * D))
        spacing = 0.065 * L
        design.windows.append(
            Window("Cabin Windows", (0.8 * D, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                   ovals=[(nose_len + 0.35 * D + k * spacing, 0.1 * D, 0.022 * L, 0.027 * L, 0.62)
                          for k in range(5)])
        )

    # --- retractable tricycle gear: mains fold inward into the wing root, nose folds forward ---
    if gear == "RETRACTABLE":
        ground = -0.5 * height - 0.4 * D
        main_r, nose_r = 0.021 * L, 0.014 * L
        main_x = 0.107 * L
        local_chord = root - (root - tip) * main_x / half
        main_le_y = root_le_y + main_x * math.tan(math.radians(sweep))
        main_y = main_le_y + 0.45 * local_chord
        wing_z_at = wing_z + main_x * math.tan(math.radians(dihedral))
        design.gear += _retractable("Main Gear", (main_x, main_y, wing_z_at - 0.03 * root),
                                    (main_x, main_y, ground + main_r), main_r, 0.013 * L, 0.011 * L, "Y")
        nose_y = 0.13 * L
        design.gear += _retractable("Nose Gear", (0.0, nose_y, -0.36 * D), (0.0, nose_y, ground + nose_r),
                                    nose_r, 0.01 * L, 0.009 * L, "X")

    design.summary = {
        "Length (m)": L,
        "Wingspan (m)": span,
        "Fuselage diameter (m)": D,
        "Wing area (m²)": area,
        "Wing root chord (m)": root,
        "Wing tip chord (m)": tip,
        "Horizontal tail area (m²)": ht_area,
        "Vertical tail area (m²)": vt_area,
        "Vertical tail height (m)": vt_height,
    }
    return design


def _wing_z_at(surface: Surface, x: float) -> float:
    (rx, _, rz), (tx, _, tz) = surface.root_le, surface.tip_le
    return rz + (tz - rz) * (x - rx) / ((tx - rx) or 1.0)


def single_piston(
    length: float = 8.3,
    span: float = 0.0,
    wing: str = "HIGH",
    gear: str | bool = "FIXED",
    blades: int = 2,
    windows: bool = True,
    dorsal: bool = True,
) -> Design:
    """Four-seat single-engine light aircraft. Zero span means "pick for me".

    gear is "FIXED" (with wheel fairings), "RETRACTABLE", or "NONE".
    """
    if length <= 0:
        raise ValueError("Length must be positive")
    if isinstance(gear, bool):
        gear = "FIXED" if gear else "NONE"
    L = length
    span = span or 1.33 * L
    W, H = 0.14 * L, 0.165 * L  # cabin width and height
    design = Design(length=L, span=span, diameter=W)

    # --- fuselage: cowling, boxy cabin, tapering tail cone with a rising belly ---
    # (fraction of length, width factor, height factor, center z factor, squareness)
    stations = (
        (0.055, 0.55, 0.55, -0.05, 0.62),
        (0.09, 0.82, 0.78, -0.06, 0.66),
        (0.16, 0.95, 0.84, -0.06, 0.7),
        (0.22, 1.0, 0.86, -0.07, 0.74),  # low cowling top gives the windshield its slope
        (0.30, 1.0, 1.0, 0.04, 0.76),
        (0.40, 1.0, 1.02, 0.05, 0.76),
        (0.50, 0.95, 0.95, 0.06, 0.74),
        (0.62, 0.72, 0.72, 0.12, 0.7),
        (0.75, 0.5, 0.52, 0.18, 0.66),
        (0.88, 0.32, 0.36, 0.22, 0.62),
        (0.97, 0.16, 0.24, 0.24, 0.6),
        (1.0, 0.06, 0.16, 0.24, 0.6),
    )
    fuselage_rings = [Ring(f * L, w * W, h * H, z * H, squareness=k) for f, w, h, z, k in stations]
    design.bodies.append(Body("Fuselage", fuselage_rings))

    # --- spinner and propeller ---
    hub_z = -0.05 * H
    spinner_r = 0.146 * H
    design.bodies.append(
        Body(
            "Spinner",
            [Ring(f * L, 2 * spinner_r * s, 2 * spinner_r * s, hub_z)
             for f, s in ((0.0, 0.03), (0.012, 0.55), (0.03, 0.9), (0.05, 1.0), (0.065, 1.0))],
        )
    )
    prop_radius = 0.115 * L
    design.propellers.append(
        Propeller("Propeller", (0.0, 0.03 * L, hub_z), prop_radius, 0.6 * spinner_r, blades=blades,
                  root_chord=0.016 * L, tip_chord=0.0085 * L)
    )

    # --- wing: constant chord inboard, tapered outboard ---
    aspect, taper, kink = 7.4, 0.68, 0.45
    area = span * span / aspect
    half = span / 2
    root = area / (2 * half * (kink + (1 - kink) * (1 + taper) / 2))
    tip = root * taper
    mac = area / span
    root_le_y = 0.32 * L - 0.25 * root
    if wing == "HIGH":
        cabin_top = (0.05 + 0.51) * H
        wing_z, dihedral = cabin_top - 0.04 * root, 1.7
    else:
        wing_z, dihedral = -0.33 * H, 6.0
    tip_le = (half, root_le_y + 0.25 * (root - tip), wing_z + half * math.tan(math.radians(dihedral)))
    main_wing = Surface("Wing", "2412", (0.0, root_le_y, wing_z), root, tip_le, tip, twist=-3.0, kink=kink)
    design.surfaces.append(main_wing)
    wing_quarter = 0.32 * L

    # --- tails, sized by tail volume ---
    ht_arm = 0.87 * L - wing_quarter
    ht_area = 0.70 * mac * area / ht_arm
    ht_span, ht_root, ht_tip = _trapezoid(ht_area, 4.0, 0.7)
    ht_le_y = min(0.87 * L - 0.25 * ht_root, 0.995 * L - ht_root)
    ht_z = 0.22 * H
    design.surfaces.append(
        Surface("Horizontal Tail", "0012", (0.0, ht_le_y, ht_z), ht_root,
                (ht_span / 2, ht_le_y + 0.25 * (ht_root - ht_tip), ht_z), ht_tip)
    )
    vt_arm = 0.84 * L - wing_quarter
    vt_area = 0.04 * span * area / vt_arm
    vt_taper, vt_sweep = 0.55, 35.0
    vt_height, vt_root, vt_tip = _trapezoid(vt_area, 1.5, vt_taper)
    vt_le_y = min(
        0.84 * L - _mac_offset(vt_height, vt_taper, vt_sweep) - 0.25 * _mac(vt_root, vt_taper),
        0.995 * L - vt_root,
    )
    vt_z = 0.35 * H
    fin = Surface("Vertical Tail", "0010", (0.0, vt_le_y, vt_z), vt_root,
                  (0.0, vt_le_y + vt_height * math.tan(math.radians(vt_sweep)), vt_z + vt_height), vt_tip,
                  vertical=True, mirror=False)
    design.surfaces.append(fin)
    if dorsal:
        design.surfaces.append(_dorsal(fuselage_rings, fin, 1.1, 0.3))

    # --- windshield and side windows ---
    if windows:
        design.windows.append(_windshield(fuselage_rings, 0.22 * L, 0.30 * L, 0.4 * W, 0.34 * W))
        design.windows.append(
            Window("Side Windows", (0.9 * W, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                   ovals=[(0.345 * L, 0.3 * H, 0.105 * L, 0.3 * H, 0.72),
                          (0.455 * L, 0.3 * H, 0.08 * L, 0.27 * H, 0.72)])
        )

    # --- wing struts (high wing) ---
    if wing == "HIGH":
        attach_x = 0.45 * half
        attach_y = root_le_y + 0.3 * root
        design.struts.append(
            Strut("Wing Strut", (0.42 * W, attach_y + 0.02 * L, -0.25 * H),
                  (attach_x, attach_y, _wing_z_at(main_wing, attach_x) - 0.04 * root), 0.022 * L)
        )

    # --- tricycle gear: fixed with wheel fairings, or retractable ---
    if gear != "NONE":
        main_r, nose_r = 0.024 * L, 0.018 * L
        ground = hub_z - prop_radius - 0.028 * L  # keeps the propeller tips off the ground
        main_y, nose_y = 0.40 * L, 0.11 * L
        track = 0.30 * L
        if wing == "HIGH":
            main_top = (0.4 * W, main_y, -0.38 * H)
        else:
            main_top = (track / 2, main_y, _wing_z_at(main_wing, track / 2) - 0.03 * root)
        main_wheel = (track / 2, main_y, ground + main_r)
        nose_top, nose_wheel = (0.0, nose_y + 0.01 * L, -0.38 * H), (0.0, nose_y, ground + nose_r)
        if gear == "FIXED":
            design.gear.append(Gear("Main Gear", main_top, main_wheel, main_r, 0.018 * L, 0.014 * L, fairing=True))
            design.gear.append(Gear("Nose Gear", nose_top, nose_wheel, nose_r, 0.015 * L, 0.012 * L,
                                    fairing=True, mirror=False))
        else:
            design.gear += _retractable("Main Gear", main_top, main_wheel, main_r, 0.018 * L, 0.012 * L, "Y")
            design.gear += _retractable("Nose Gear", nose_top, nose_wheel, nose_r, 0.015 * L, 0.01 * L, "X")

    design.summary = {
        "Length (m)": L,
        "Wingspan (m)": span,
        "Cabin width (m)": W,
        "Wing area (m²)": area,
        "Wing root chord (m)": root,
        "Horizontal tail area (m²)": ht_area,
        "Vertical tail area (m²)": vt_area,
        "Propeller diameter (m)": 2 * prop_radius,
    }
    return design

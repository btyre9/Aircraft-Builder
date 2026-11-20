"""Realistic small-jet proportions from a few top-level numbers.

These are conceptual-design rules of thumb (the kind found in aircraft design
textbooks such as Raymer's), tuned to light business jets:

- fuselage fineness (length / diameter) about 8.5
- wingspan about equal to fuselage length, aspect ratio about 8.5, taper 0.4
- tail areas sized with tail volume coefficients (horizontal 0.85,
  vertical 0.08), which balance tail size against its distance from the wing

Axes match Blender: nose at the origin pointing -Y, the body runs along +Y,
span along X, up is Z. Units are metres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Ring:
    y: float
    width: float
    height: float
    z: float = 0.0
    x: float = 0.0


@dataclass
class Surface:
    """A wing-like surface: an airfoil swept from root to tip."""

    name: str
    airfoil: str
    root_le: tuple[float, float, float]
    root_chord: float
    tip_le: tuple[float, float, float]
    tip_chord: float
    vertical: bool = False
    mirror: bool = True
    twist: float = 0.0

    @property
    def root_te(self) -> tuple[float, float, float]:
        x, y, z = self.root_le
        return (x, y + self.root_chord, z)

    @property
    def tip_te(self) -> tuple[float, float, float]:
        x, y, z = self.tip_le
        return (x, y + self.tip_chord, z)


@dataclass
class Body:
    name: str
    rings: list[Ring]
    mirror: bool = False


@dataclass
class JetDesign:
    length: float
    span: float
    diameter: float
    bodies: list[Body] = field(default_factory=list)
    surfaces: list[Surface] = field(default_factory=list)
    summary: dict[str, float] = field(default_factory=dict)


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
) -> JetDesign:
    """Build a light business jet layout. Zero span or diameter means "pick for me"."""
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
    design.surfaces.append(
        Surface("Vertical Tail", "0010", (0.0, vt_root_le_y, vt_root_z), vt_root, vt_tip_le, vt_tip, vertical=True, mirror=False)
    )

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

import math

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


def _rebuild(self, context):
    from . import build

    build.rebuild(self.id_data)


def _airfoil_changed(self, context):
    from . import build

    build.write_airfoil(self.id_data)


def _is_shape(self, obj):
    return obj.type in {"CURVE", "MESH"} and obj != self.id_data


CAPS = [
    ("NONE", "Open", "Leave the end open"),
    ("FAN", "Fan", "Triangles to a center point (round ends, noses)"),
    ("STRIP", "Strip", "Quad strips across the section (wing tips)"),
    ("NGON", "N-gon", "One flat face"),
]


class LSW_ObjectRef(PropertyGroup):
    obj: PointerProperty(name="Object", type=bpy.types.Object, poll=_is_shape, update=_rebuild)


class LSW_Settings(PropertyGroup):
    kind: EnumProperty(
        items=[("NONE", "None", ""), ("LOFT", "Loft", ""), ("SWEEP", "Sweep", "")],
        default="NONE",
    )
    # Loft
    profiles: CollectionProperty(type=LSW_ObjectRef)
    profile_index: IntProperty()
    rails: CollectionProperty(type=LSW_ObjectRef)
    rail_index: IntProperty()
    steps: IntProperty(name="Steps Between", default=6, min=1, max=64, update=_rebuild,
                       description="Rows of faces between neighbouring profiles")
    smooth: BoolProperty(name="Smooth", default=True, update=_rebuild,
                         description="Curve smoothly through the profiles instead of straight between them")
    align: BoolProperty(name="Auto Align", default=True, update=_rebuild,
                        description="Match up profile start points and directions to avoid twisting")
    # Sweep
    profile: PointerProperty(name="Profile", type=bpy.types.Object, poll=_is_shape, update=_rebuild,
                             description="Cross-section to move along the path")
    path: PointerProperty(name="Path", type=bpy.types.Object, poll=_is_shape, update=_rebuild,
                          description="Curve the profile travels along")
    rail: PointerProperty(name="Guide Rail", type=bpy.types.Object, poll=_is_shape, update=_rebuild,
                          description="Optional curve that scales and turns the profile to follow it")
    path_steps: IntProperty(name="Path Steps", default=24, min=1, max=2048, update=_rebuild)
    orientation: EnumProperty(
        name="Orientation",
        items=[
            ("PERPENDICULAR", "Perpendicular", "Profile turns to stay square to the path (pipes, ducts)"),
            ("PARALLEL", "Parallel", "Profile keeps facing its original direction (wings, fins)"),
        ],
        default="PERPENDICULAR",
        update=_rebuild,
    )
    twist: FloatProperty(name="Twist", default=0.0, subtype="ANGLE", update=_rebuild,
                         description="Rotation added gradually from start to end")
    scale_end: FloatProperty(name="End Scale", default=1.0, min=0.0, soft_max=4.0, update=_rebuild,
                             description="Size of the profile at the end of the path")
    # Shared
    resolution: IntProperty(name="Profile Points", default=48, min=4, max=1024, update=_rebuild,
                            description="Points around each cross-section")
    curvature: FloatProperty(name="Curve Detail", default=1.0, min=0.0, max=4.0, update=_rebuild,
                             description="Put more points where profiles bend (round noses, leading edges)")
    cap_start: EnumProperty(name="Start Cap", items=CAPS, default="FAN", update=_rebuild)
    cap_end: EnumProperty(name="End Cap", items=CAPS, default="FAN", update=_rebuild)
    sharp_angle: FloatProperty(name="Sharp Corners", default=math.radians(35.0), min=0.0, max=math.pi,
                               subtype="ANGLE", update=_rebuild,
                               description="Profile corners sharper than this stay crisp when smooth shaded")
    mirror_x: BoolProperty(name="Mirror X", default=False, update=_rebuild,
                           description="Mirror across the center line (build one side of a wing)")
    status: StringProperty()


class LSW_Airfoil(PropertyGroup):
    enabled: BoolProperty(default=False)
    source: EnumProperty(
        name="Source",
        items=[("NACA", "NACA 4-digit", "Generate a standard NACA airfoil"),
               ("FILE", ".dat File", "Load coordinates from an airfoil database file")],
        default="NACA",
        update=_airfoil_changed,
    )
    naca: StringProperty(name="NACA", default="2412", maxlen=4, update=_airfoil_changed,
                         description="Camber, camber position, thickness: 2412 = 2% camber at 40%, 12% thick")
    filepath: StringProperty(name="File", subtype="FILE_PATH", update=_airfoil_changed)
    points: IntProperty(name="Points", default=81, min=21, max=401, update=_airfoil_changed)
    error: StringProperty()


CLASSES = (LSW_ObjectRef, LSW_Settings, LSW_Airfoil)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.lsw = PointerProperty(type=LSW_Settings)
    bpy.types.Object.lsw_airfoil = PointerProperty(type=LSW_Airfoil)


def unregister():
    del bpy.types.Object.lsw_airfoil
    del bpy.types.Object.lsw
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

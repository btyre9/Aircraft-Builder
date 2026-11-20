import math

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, StringProperty
from bpy.types import Operator

from . import aircraft, build, core


def _shapes(context):
    return [
        obj for obj in context.selected_objects
        if obj.type in {"CURVE", "MESH"} and obj.lsw.kind == "NONE"
    ]


def _select_only(context, obj):
    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _sort_along_spread(context, objects):
    """Order profiles along the axis where they are most spread out."""
    depsgraph = context.evaluated_depsgraph_get()
    centers = {obj: core.centroid(build.sample(obj, depsgraph)[0]) for obj in objects}
    spreads = [max(c[i] for c in centers.values()) - min(c[i] for c in centers.values()) for i in range(3)]
    axis = spreads.index(max(spreads))
    return sorted(objects, key=lambda obj: centers[obj][axis])


class LSW_OT_loft(Operator):
    bl_idname = "lsw.loft"
    bl_label = "Loft Selected"
    bl_description = "Skin a live surface through the selected curves (all closed or all open)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        shapes = _shapes(context)
        if len(shapes) < 2:
            self.report({"ERROR"}, "Select at least two profile curves")
            return {"CANCELLED"}
        ordered = _sort_along_spread(context, shapes)
        obj = build.new_result("Loft", "LOFT", context.collection)
        for shape in ordered:
            obj.lsw.profiles.add().obj = shape
        closed = build.sample(ordered[0], context.evaluated_depsgraph_get())[1]
        if not closed:
            obj.lsw.cap_start = obj.lsw.cap_end = "NONE"
        build.rebuild(obj)
        _select_only(context, obj)
        return {"FINISHED"}


class LSW_OT_sweep(Operator):
    bl_idname = "lsw.sweep"
    bl_label = "Sweep Selected"
    bl_description = (
        "Sweep a profile along a path. Select the profile (closed curve), the path, and optionally a "
        "guide rail; make the path the active object"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        shapes = _shapes(context)
        if not 2 <= len(shapes) <= 3:
            self.report({"ERROR"}, "Select a profile and a path (and optionally a guide rail)")
            return {"CANCELLED"}
        depsgraph = context.evaluated_depsgraph_get()
        closed = {obj: build.sample(obj, depsgraph)[1] for obj in shapes}
        active = context.active_object if context.active_object in shapes else None
        profiles = [o for o in shapes if closed[o] and o is not active]
        if profiles:
            profile = profiles[0]
        else:
            profile = next(o for o in shapes if o is not active)
        rest = [o for o in shapes if o is not profile]
        path = active if active in rest else rest[0]
        rail = next((o for o in rest if o is not path), None)
        obj = build.new_result("Sweep", "SWEEP", context.collection)
        s = obj.lsw
        if not closed[profile]:
            s.cap_start = s.cap_end = "NONE"
        if rail is not None:
            s.orientation = "PARALLEL"
        s.profile, s.path, s.rail = profile, path, rail
        build.rebuild(obj)
        _select_only(context, obj)
        self.report({"INFO"}, f"Profile: {profile.name}, path: {path.name}" + (f", rail: {rail.name}" if rail else ""))
        return {"FINISHED"}


class LSW_OT_list_edit(Operator):
    bl_idname = "lsw.list_edit"
    bl_label = "Edit List"
    bl_description = "Add selected curves, remove, or reorder profiles and rails"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    target: EnumProperty(items=[("PROFILES", "Profiles", ""), ("RAILS", "Rails", "")])
    action: EnumProperty(items=[("ADD", "Add Selected", ""), ("REMOVE", "Remove", ""),
                                ("UP", "Up", ""), ("DOWN", "Down", "")])

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.lsw.kind == "LOFT"

    def execute(self, context):
        obj = context.active_object
        s = obj.lsw
        items = s.profiles if self.target == "PROFILES" else s.rails
        index_name = "profile_index" if self.target == "PROFILES" else "rail_index"
        index = getattr(s, index_name)
        if self.action == "ADD":
            existing = {item.obj for item in items}
            for shape in _shapes(context):
                if shape not in existing and shape is not obj:
                    items.add().obj = shape
        elif self.action == "REMOVE" and 0 <= index < len(items):
            items.remove(index)
            setattr(s, index_name, max(0, index - 1))
        elif self.action in {"UP", "DOWN"} and 0 <= index < len(items):
            target = index - 1 if self.action == "UP" else index + 1
            if 0 <= target < len(items):
                items.move(index, target)
                setattr(s, index_name, target)
        build.rebuild(obj)
        return {"FINISHED"}


class LSW_OT_rebuild(Operator):
    bl_idname = "lsw.rebuild"
    bl_label = "Rebuild"
    bl_description = "Rebuild the active loft or sweep from its curves"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        for obj in context.selected_objects or [context.active_object]:
            if obj and obj.lsw.kind != "NONE":
                build.rebuild(obj)
        return {"FINISHED"}


class LSW_OT_freeze(Operator):
    bl_idname = "lsw.freeze"
    bl_label = "Convert to Plain Mesh"
    bl_description = (
        "Stop following the source curves so you can edit the mesh by hand. The mirror modifier is kept"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.lsw.kind != "NONE":
                obj.lsw.kind = "NONE"
                count += 1
        self.report({"INFO"}, f"Converted {count} object(s)")
        return {"FINISHED"}


class LSW_OT_add_airfoil(Operator):
    bl_idname = "lsw.add_airfoil"
    bl_label = "Add Airfoil"
    bl_description = "Add an airfoil curve at the 3D cursor (leading edge at the cursor)"
    bl_options = {"REGISTER", "UNDO"}

    naca: StringProperty(name="NACA", default="2412", maxlen=4)
    chord: FloatProperty(name="Chord", default=2.0, min=0.001, unit="LENGTH")
    plane: EnumProperty(
        name="Plane",
        items=[("WING", "Wing (side view)", "Chord along +Y, thickness up Z"),
               ("FIN", "Fin (top view)", "Chord along +Y, thickness along X")],
        default="WING",
    )

    def execute(self, context):
        try:
            core.naca4(self.naca)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        thickness = (0, 0, 1) if self.plane == "WING" else (1, 0, 0)
        obj = build.airfoil_curve(
            f"Airfoil {self.naca}", context.collection, tuple(context.scene.cursor.location), self.chord,
            (0, 1, 0), thickness, self.naca,
        )
        _select_only(context, obj)
        return {"FINISHED"}


class LSW_OT_small_jet(Operator):
    bl_idname = "lsw.small_jet"
    bl_label = "Small Jet"
    bl_description = "Build a live light-business-jet starter with realistic proportions"
    bl_options = {"REGISTER", "UNDO"}

    length: FloatProperty(name="Length", default=14.0, min=3.0, max=60.0, unit="LENGTH",
                          description="Nose to tail. Light business jets are about 13 to 17 m")
    span: FloatProperty(name="Wingspan", default=0.0, min=0.0, max=80.0, unit="LENGTH",
                        description="0 picks a wingspan equal to the length")
    diameter: FloatProperty(name="Body Diameter", default=0.0, min=0.0, max=8.0, unit="LENGTH",
                            description="0 picks length / 8.5")
    tail: EnumProperty(name="Tail", items=[("T", "T-Tail", "Horizontal tail on top of the fin"),
                                           ("CONVENTIONAL", "Conventional", "Horizontal tail on the tail cone")])
    engines: BoolProperty(name="Rear Engines", default=True)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        jet, objects = aircraft.build_small_jet(
            context, self.length, self.span, self.diameter, self.tail, self.engines
        )
        problems = [o.name for o in objects if o.lsw.status]
        if problems:
            self.report({"WARNING"}, "Some parts failed: " + ", ".join(problems))
        s = jet.summary
        self.report(
            {"INFO"},
            f"Span {s['Wingspan (m)']:.1f} m, wing area {s['Wing area (m²)']:.1f} m², "
            f"body diameter {s['Fuselage diameter (m)']:.2f} m",
        )
        return {"FINISHED"}


class LSW_OT_add_wing(Operator):
    bl_idname = "lsw.add_wing"
    bl_label = "Add Wing"
    bl_description = "Add a live swept wing (airfoil + leading edge + trailing edge) at the 3D cursor"
    bl_options = {"REGISTER", "UNDO"}

    semi_span: FloatProperty(name="Half Span", default=7.0, min=0.01, unit="LENGTH")
    root_chord: FloatProperty(name="Root Chord", default=2.4, min=0.01, unit="LENGTH")
    tip_chord: FloatProperty(name="Tip Chord", default=1.0, min=0.0, unit="LENGTH")
    sweep: FloatProperty(name="Leading Edge Sweep", default=8.0, min=-60, max=75, description="Degrees")
    dihedral: FloatProperty(name="Dihedral", default=3.0, min=-20, max=20, description="Degrees")
    twist: FloatProperty(name="Washout", default=-2.0, min=-10, max=10, description="Tip twist, degrees")
    naca: StringProperty(name="NACA", default="2412", maxlen=4)
    mirror: BoolProperty(name="Mirror", default=True)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            core.naca4(self.naca)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        obj = aircraft.build_wing(
            context, tuple(context.scene.cursor.location), self.semi_span, self.root_chord, self.tip_chord,
            self.sweep, self.dihedral, self.naca, self.mirror, self.twist,
        )
        _select_only(context, obj)
        return {"FINISHED"}


class LSW_OT_add_fuselage(Operator):
    bl_idname = "lsw.add_fuselage"
    bl_label = "Add Fuselage"
    bl_description = "Add a live fuselage lofted through editable rings"
    bl_options = {"REGISTER", "UNDO"}

    length: FloatProperty(name="Length", default=14.0, min=0.5, unit="LENGTH")
    diameter: FloatProperty(name="Diameter", default=0.0, min=0.0, unit="LENGTH",
                            description="0 picks length / 8.5")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = aircraft.build_fuselage(context, self.length, self.diameter)
        _select_only(context, obj)
        return {"FINISHED"}


class LSW_OT_blueprints(Operator):
    bl_idname = "lsw.blueprints"
    bl_label = "Set Up Blueprints"
    bl_description = (
        "Place side, top, and front reference images at real size with the nose at the origin. "
        "Crop each image so the aircraft touches its edges"
    )
    bl_options = {"REGISTER", "UNDO"}

    side: StringProperty(name="Side (nose left)", subtype="FILE_PATH")
    top: StringProperty(name="Top (nose up)", subtype="FILE_PATH")
    front: StringProperty(name="Front", subtype="FILE_PATH")
    length: FloatProperty(name="Real Length", default=14.0, min=0.01, unit="LENGTH")
    span: FloatProperty(name="Real Wingspan", default=14.0, min=0.01, unit="LENGTH")
    opacity: FloatProperty(name="Opacity", default=0.5, min=0.05, max=1.0)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        views = [("SIDE", self.side), ("TOP", self.top), ("FRONT", self.front)]
        if not any(path for _, path in views):
            self.report({"ERROR"}, "Choose at least one image")
            return {"CANCELLED"}
        collection = bpy.data.collections.new("Blueprints")
        context.scene.collection.children.link(collection)
        for view, path in views:
            if not path:
                continue
            try:
                aircraft.add_blueprint(f"Blueprint {view.title()}", path, view, self.length, self.span,
                                       collection, self.opacity)
            except (RuntimeError, ValueError) as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
        return {"FINISHED"}


CLASSES = (
    LSW_OT_loft,
    LSW_OT_sweep,
    LSW_OT_list_edit,
    LSW_OT_rebuild,
    LSW_OT_freeze,
    LSW_OT_add_airfoil,
    LSW_OT_small_jet,
    LSW_OT_add_wing,
    LSW_OT_add_fuselage,
    LSW_OT_blueprints,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

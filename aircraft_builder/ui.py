import bpy
from bpy.types import Panel, UIList

CATEGORY = "Aircraft Builder"


class LSW_UL_refs(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"{index + 1}.")
        row.prop(item, "obj", text="", emboss=False, icon="CURVE_DATA")


class _Base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY


class LSW_PT_create(_Base, Panel):
    bl_label = "Create"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("lsw.loft", icon="MOD_SKIN")
        col.operator("lsw.sweep", icon="CURVE_PATH")
        col.operator("lsw.window", icon="MOD_UVPROJECT")
        self.layout.label(text="Sweep: make the path the active object", icon="INFO")
        self.layout.label(text="Window: select outline, then the body", icon="INFO")


def _ref_list(layout, s, collection, index, target, label):
    layout.label(text=label)
    row = layout.row()
    row.template_list("LSW_UL_refs", target, s, collection, s, index, rows=3)
    col = row.column(align=True)
    for action, icon in (("ADD", "ADD"), ("REMOVE", "REMOVE"), ("UP", "TRIA_UP"), ("DOWN", "TRIA_DOWN")):
        op = col.operator("lsw.list_edit", text="", icon=icon)
        op.target, op.action = target, action


class LSW_PT_surface(_Base, Panel):
    bl_label = "Surface"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.lsw.kind != "NONE"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        s = context.active_object.lsw
        if s.status:
            layout.label(text=s.status, icon="ERROR")
        if s.kind == "WINDOW":
            layout.prop(s, "target")
            layout.prop(s, "outline")
            layout.prop(s, "offset")
            layout.prop(s, "resolution", text="Edge Points")
            layout.prop(s, "steps", text="Detail")
            layout.prop(s, "mirror_x")
            layout.label(text="Move or edit the outline to reshape", icon="INFO")
            row = layout.row(align=True)
            row.operator("lsw.rebuild", icon="FILE_REFRESH")
            row.operator("lsw.freeze", icon="MESH_DATA")
            return
        if s.kind == "FAIRING":
            layout.prop(s, "wing")
            layout.prop(s, "reach")
            layout.prop(s, "fullness")
            layout.prop(s, "steps", text="Smoothness")
            layout.separator()
            layout.prop(s, "outline")
            if s.outline is None:
                col = layout.column(align=True)
                for name in ("forward", "aft", "depth", "top"):
                    col.prop(s, name)
                layout.operator("lsw.fairing_outline", icon="CURVE_NCIRCLE")
            else:
                layout.label(text="Edit the outline curve in side view", icon="INFO")
            layout.prop(s, "mirror_x")
            row = layout.row(align=True)
            row.operator("lsw.rebuild", icon="FILE_REFRESH")
            row.operator("lsw.freeze", icon="MESH_DATA")
            return
        if s.kind == "LOFT":
            layout.use_property_split = False
            _ref_list(layout, s, "profiles", "profile_index", "PROFILES", "Profiles (in order)")
            _ref_list(layout, s, "rails", "rail_index", "RAILS", "Guide Rails (optional)")
            layout.use_property_split = True
            layout.prop(s, "steps")
            layout.prop(s, "smooth")
            layout.prop(s, "align")
        else:
            layout.prop(s, "profile")
            layout.prop(s, "path")
            layout.prop(s, "rail")
            layout.prop(s, "orientation")
            layout.prop(s, "path_steps")
            layout.prop(s, "twist")
            layout.prop(s, "scale_end")
        layout.separator()
        layout.prop(s, "resolution")
        layout.prop(s, "curvature")
        layout.prop(s, "cap_start")
        layout.prop(s, "cap_end")
        layout.prop(s, "sharp_angle")
        layout.prop(s, "mirror_x")
        row = layout.row(align=True)
        row.operator("lsw.rebuild", icon="FILE_REFRESH")
        row.operator("lsw.freeze", icon="MESH_DATA")


class LSW_PT_airfoil(_Base, Panel):
    bl_label = "Airfoil"

    def draw(self, context):
        layout = self.layout
        layout.operator("lsw.add_airfoil", icon="IPO_EASE_IN_OUT")
        obj = context.active_object
        if obj is None or not obj.lsw_airfoil.enabled:
            return
        a = obj.lsw_airfoil
        layout.use_property_split = True
        layout.prop(a, "source")
        if a.source == "NACA":
            layout.prop(a, "naca")
        else:
            layout.prop(a, "filepath")
        layout.prop(a, "points")
        if a.error:
            layout.label(text=a.error, icon="ERROR")
        layout.label(text="Scale the curve object to change chord", icon="INFO")


class LSW_PT_aircraft(_Base, Panel):
    bl_label = "Aircraft"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("lsw.small_jet", icon="AUTO")
        col.operator("lsw.single_piston", icon="FORCE_WIND")
        col.separator()
        col.operator("lsw.add_fuselage", icon="MESH_CAPSULE")
        col.operator("lsw.add_wing", icon="MOD_SIMPLEDEFORM")
        col.operator("lsw.add_fairing", icon="MOD_SMOOTH")
        self.layout.operator("lsw.blueprints", icon="IMAGE_REFERENCE")
        controls = [o for o in context.scene.objects if o.get("lsw_gear")]
        if controls:
            box = self.layout.box()
            box.label(text="Landing Gear (0 down, 1 up)", icon="ANIM")
            for control in controls:
                box.prop(control, '["retract"]', text=control.name.replace(" Landing Gear", ""), slider=True)


CLASSES = (LSW_UL_refs, LSW_PT_create, LSW_PT_surface, LSW_PT_airfoil, LSW_PT_aircraft)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

"""Aircraft Builder: CAD-style live surfaces and parametric aircraft for Blender.

Lofts and sweeps stay linked to their source curves and rebuild whenever a
curve moves or changes, much like Fusion 360's timeline.

core.py and design.py are plain Python (no bpy) so they can be unit tested
outside Blender; only import the Blender modules when Blender is present.
"""

try:
    import bpy
except ImportError:  # imported by plain-Python tests
    bpy = None


def register():
    from . import build, ops, props, ui

    props.register()
    ops.register()
    ui.register()
    if build.on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(build.on_depsgraph_update)


def unregister():
    from . import build, ops, props, ui

    if build.on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(build.on_depsgraph_update)
    ui.unregister()
    ops.unregister()
    props.unregister()

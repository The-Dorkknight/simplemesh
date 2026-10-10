# SimpleMesh - Clay mode: Blender's own sculpting, cut down to seven brushes
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 3. No warranty; see LICENSE.
#
# Blender already has a fast, good sculpting engine. What makes it hard for STL
# work is everything around it: thirty-odd brushes, sizes in screen pixels,
# mirror symmetry, and above all that an STL's big flat triangles have nothing
# to mould until "dynamic topology" is switched on. Clay mode does that set-up:
#   * brush size in millimetres, the same size at any zoom
#   * the model is first given small triangles everywhere (the shape does not
#     change), and more are added under the brush as you work (dynamic topology,
#     constant detail in mm), so a flat face can be pulled like clay; when you
#     press Done the untouched flat areas are merged back into big triangles
#   * symmetry off, front faces only
#   * seven brushes with plain names

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from . import base as B

# key, button text, Blender 2.8-4.2 tool name, Blender 4.3+ brush asset name, direction, hint
BRUSHES = (
    ("pull", "Pull", "Snake Hook", "Snake Hook", None,
     "press on the surface and drag: the clay follows the mouse and stretches out"),
    ("build", "Build up", "Draw", "Draw", "ADD",
     "rub over the surface to raise it"),
    ("push", "Push in", "Draw", "Draw", "SUBTRACT",
     "rub over the surface to press it in"),
    ("shift", "Shift", "Grab", "Grab", None,
     "drag to slide an area sideways without stretching it"),
    ("inflate", "Inflate", "Inflate", "Inflate/Deflate", "ADD",
     "rub to swell the surface outwards in all directions"),
    ("smooth", "Smooth", "Smooth", "Smooth", None,
     "rub to smooth out lumps"),
    ("flatten", "Flatten", "Flatten", "Flatten/Contrast", None,
     "rub to level an area flat"),
)
BRUSH_BY_KEY = {b[0]: b for b in BRUSHES}
KEYS_HINT = "Ctrl = the opposite   |   Shift = smooth   |   F then move = brush size   |   Ctrl+Z = undo   |   press Done when finished"

ESSENTIALS = "brushes/essentials_brushes-mesh_sculpt.blend/Brush/"

# Pull and Shift must be at full strength or the clay slips out from under the
# brush instead of following the mouse; the rubbing brushes are gentler.
STRENGTH = {"pull": 1.0, "shift": 1.0, "build": 0.5, "push": 0.5, "inflate": 0.5,
            "smooth": 0.5, "flatten": 0.6}
_current = {"key": None}

# What Blender calls each brush's kind (the name of the property and of "Flatten"
# changed between versions), used to check that the brush really was switched.
TYPES = {"pull": ("SNAKE_HOOK",), "build": ("DRAW",), "push": ("DRAW",), "shift": ("GRAB",),
         "inflate": ("INFLATE",), "smooth": ("SMOOTH",), "flatten": ("FLATTEN", "PLANE")}

# Which model has been made ready for moulding. Sculpt Mode can also be entered
# through Blender's own mode menu, a keyboard shortcut or the Sculpting workspace;
# then nothing has been set up (no small triangles, brush in screen pixels, the
# wrong brush) and dragging on a STL barely does anything. The strip notices
# that and runs the Clay set-up by itself.
_ready = {"name": None, "failed": None}
_auto = {"pending": False, "busy": False}


def brush_type(br):
    if br is None:
        return None
    return getattr(br, "sculpt_brush_type", None) or getattr(br, "sculpt_tool", None)


def actual_key(context):
    """Which of our seven brushes Blender is really using right now, or None."""
    try:
        br = context.scene.tool_settings.sculpt.brush
    except Exception:
        return None
    kind = brush_type(br)
    if kind is None:
        return None
    if kind == "DRAW":
        return "push" if getattr(br, "direction", "ADD") == "SUBTRACT" else "build"
    for key, kinds in TYPES.items():
        if kind in kinds:
            return key
    return None


def unified(context):
    """Blender's shared brush size/strength settings (moved in Blender 5)."""
    ts = context.scene.tool_settings
    return getattr(ts.sculpt, "unified_paint_settings", None) or getattr(ts, "unified_paint_settings", None)


def size_prop(ups):
    """Name of the scene-unit brush size property, and how many radii it holds."""
    if hasattr(ups, "unprojected_radius"):
        return "unprojected_radius", 1.0
    if hasattr(ups, "unprojected_size"):          # Blender 5: a diameter
        return "unprojected_size", 2.0
    return None, 1.0


def set_radius(context, radius_mm):
    ups = unified(context)
    if ups is None:
        return
    B._set(ups, "use_unified_size", True)
    B._set(ups, "use_locked_size", "SCENE")       # millimetres, not screen pixels
    name, k = size_prop(ups)
    if name:
        B._set(ups, name, radius_mm * k)


def get_radius(context):
    """Brush radius in mm, or None."""
    ups = unified(context)
    name, k = size_prop(ups) if ups is not None else (None, 1.0)
    try:
        return getattr(ups, name) / k if name else None
    except Exception:
        return None


# The smallest Detail allowed for a brush: with automatic detail every triangle
# under the brush is cut down to the Detail size at each step of a stroke, so a
# big brush with a tiny Detail makes hundreds of thousands of triangles in one
# drag and Blender stops answering. A thirtieth of the brush keeps it to a few
# thousand.
DETAIL_PER_RADIUS = 1.0 / 30.0
HEAVY = 400000            # triangles: from here on moulding gets slow on a laptop
PLAIN_ABOVE = 700000      # triangles: no automatic detail above this (it needs too much memory)


def min_detail(context):
    r = get_radius(context)
    return max(0.05, r * DETAIL_PER_RADIUS) if r else 0.05


def guard(context):
    """Keep Detail coarse enough for the brush. Returns True when it had to change it."""
    try:
        sm = context.scene.simplemesh
        low = min_detail(context)
        if sm.clay_detail < low - 1e-6:
            sm.clay_detail = low
            return True
    except Exception:
        B.note_error("clay: detail guard")
    return False


def _guard_timer():
    try:
        if bpy.context.mode == "SCULPT":
            guard(bpy.context)
    except Exception:
        pass
    return None


def request_guard():
    """Called while drawing when the brush has outgrown the Detail setting."""
    try:
        if not bpy.app.timers.is_registered(_guard_timer):
            bpy.app.timers.register(_guard_timer, first_interval=0.05)
    except Exception:
        pass


def resize(context, factor):
    """Make the brush bigger or smaller (and keep Detail safe for it)."""
    r = get_radius(context)
    if r:
        set_radius(context, min(max(r * factor, 0.2), 5000.0))
        guard(context)


_tris = {"t": 0.0, "n": 0, "name": ""}


def tri_count(context):
    """Triangles in the model being moulded (looked up at most once a second)."""
    import time
    ob = context.object
    if ob is None:
        return 0
    now = time.time()
    if now - _tris["t"] < 1.0 and _tris["name"] == ob.name:
        return _tris["n"]
    n = len(ob.data.polygons)
    try:                                        # while moulding the mesh itself is out of date
        txt = context.scene.statistics(context.view_layer)
        for part in txt.split("|"):
            part = part.strip()
            if part.startswith(("Tris", "Faces")):
                n = int(part.split(":")[1].split("/")[-1].replace(",", "").replace(".", "").strip())
                if part.startswith("Tris"):
                    break
    except Exception:
        pass
    _tris.update(t=now, n=n, name=ob.name)
    return n


def set_strength(context, strength):
    ups = unified(context)
    if ups is not None:
        B._set(ups, "use_unified_strength", True)
        B._set(ups, "strength", strength)


def set_detail(context, edge_mm):
    sc = context.scene.tool_settings.sculpt
    B._set(sc, "detail_type_method", "CONSTANT")
    B._set(sc, "detail_refine_method", "SUBDIVIDE")
    B._set(sc, "constant_detail_resolution", 1.0 / max(edge_mm, 0.02))   # 1 unit = 1 mm


def activate_brush(context, key):
    """Switch to one of the seven brushes. Returns True when Blender took it."""
    _key, _txt, tool_name, asset_name, direction, _hint = BRUSH_BY_KEY[key]
    sc = context.scene.tool_settings.sculpt
    ups = unified(context)
    if ups is not None and _current["key"] in STRENGTH and _current["key"] != key:
        STRENGTH[_current["key"]] = ups.strength       # remember what the user set for the old brush
    ok = False
    if not hasattr(bpy.ops.brush, "asset_activate"):          # Blender up to 4.2: brushes are tools
        try:
            ok = "FINISHED" in bpy.ops.wm.tool_set_by_id(name="builtin_brush." + tool_name)
        except Exception:
            ok = False
    if not ok:                                               # Blender 4.3+: brushes are assets
        try:
            ok = "FINISHED" in bpy.ops.brush.asset_activate(
                asset_library_type="ESSENTIALS", asset_library_identifier="",
                relative_asset_identifier=ESSENTIALS + asset_name)
        except Exception:
            ok = False
    if not ok:
        try:
            ok = "FINISHED" in bpy.ops.wm.tool_set_by_id(name="builtin_brush." + tool_name)
        except Exception:
            ok = False
    if brush_type(sc.brush) not in TYPES[key]:               # Blender did not take it: look for one ourselves
        ok = False
        for b in bpy.data.brushes:
            if getattr(b, "use_paint_sculpt", False) and brush_type(b) in TYPES[key]:
                try:
                    sc.brush = b
                except Exception:
                    pass
                break
    br = sc.brush
    ok = brush_type(br) in TYPES[key]
    if br is not None and ok:
        if direction is not None:
            B._set(br, "direction", direction)
        # Rubbing brushes only touch what faces you (so thin walls are not dented
        # from behind); the dragging brushes must also carry the far side along.
        B._set(br, "use_frontface", key not in ("pull", "shift"))
    if ok:
        set_strength(context, STRENGTH.get(key, 0.5))
        _current["key"] = key
    return ok


def _detail_update(self, context):
    if context.mode == "SCULPT":
        low = min_detail(context)
        if self.clay_detail < low - 1e-6:        # too fine for this brush (see DETAIL_PER_RADIUS)
            self.clay_detail = low               # (runs this function again with the safe value)
            return
        set_detail(context, self.clay_detail)


def target(context):
    ob = context.object
    if ob is not None and ob.type == "MESH" and (ob.select_get() or context.mode == "SCULPT"):
        return ob
    sel = [o for o in context.selected_objects if o.type == "MESH"]
    if sel:
        return sel[0]
    meshes = [o for o in context.view_layer.objects if o.type == "MESH" and o.visible_get()
              and not B.is_hole(o)]
    return meshes[0] if len(meshes) == 1 else None


def surface_area(me):
    return sum(p.area for p in me.polygons)


def enter(context, ob, edge_mm, budget, report=None):
    """Give the model enough triangles to mould (edges no longer than edge_mm,
    within a triangle budget), then switch Blender's sculpting on with our set-up."""
    sm = context.scene.simplemesh
    me = ob.data
    B.crumb("clay: %s, %d triangles" % (ob.name, len(me.polygons)))
    if len(me.polygons) < budget:
        # never finer than the budget allows for this much surface
        floor = (surface_area(me) / (0.43 * budget)) ** 0.5
        B.refine_mesh(me, max(edge_mm, floor), budget)
        B.crumb("clay: small triangles added, now %d" % len(me.polygons))
    plain = len(me.polygons) > PLAIN_ABOVE
    bpy.ops.object.mode_set(mode="SCULPT")
    B.crumb("clay: sculpt mode on")
    for ax in "xyz":                                # no mirror surprises (unless asked for)
        on = sm.clay_mirror and ax == "x"
        B._set(me, "use_mirror_" + ax, on)
        B._set(context.scene.tool_settings.sculpt, "use_symmetry_" + ax, on)
    try:
        if plain:
            if report:
                report({"INFO"}, "Very dense model (%s triangles): moulding the points it already has"
                       % format(len(me.polygons), ","))
        elif not context.sculpt_object.use_dynamic_topology_sculpting:
            bpy.ops.sculpt.dynamic_topology_toggle()
            B.crumb("clay: automatic detail on")
    except Exception:
        B.note_error("clay: automatic detail")
        if report:
            report({"WARNING"}, "Automatic detail could not be switched on")
    set_detail(context, sm.clay_detail)
    ups = unified(context)
    if ups is not None:
        B._set(ups, "use_unified_size", True)
        B._set(ups, "use_locked_size", "SCENE")
    _current["key"] = None
    _ready.update(name=ob.name, failed=None)
    if not activate_brush(context, sm.clay_brush) and report:
        report({"WARNING"}, "Could not pick the brush; choose one from Blender's brush list")
    # An undo step of our own, made now that sculpting is on. Without it (this code
    # is often run from another tool or a timer, where Blender records nothing)
    # the set-up is lumped together with the first brush stroke, and Ctrl+Z after
    # that stroke throws you out of Clay instead of taking back the stroke.
    try:
        bpy.ops.ed.undo_push(message="SimpleMesh: Clay")
    except Exception:
        B.note_error("clay: undo step")
    B.crumb("clay: ready")


def start(context, ob, report=None):
    """Everything the Clay button does. Also used when Sculpt Mode was entered some
    other way (Blender's mode menu, Ctrl+Tab, the Sculpting workspace)."""
    sm = context.scene.simplemesh
    if context.mode != "OBJECT":
        leave_clay(context)
    B.bake(ob)
    B.select_only(context, [ob])
    lo, hi = B.obj_bounds(ob)
    longest = max(hi - lo)
    new_model = sm.clay_for != ob.name
    if new_model:                               # sensible sizes for this model
        sm.clay_for = ob.name
        sm.clay_detail = max(longest / 60.0, 0.3)       # coarse enough that a few pulls do not make a huge file
    n0 = len(ob.data.polygons)
    with B.busy(context, "clay: getting %s ready" % ob.name):
        enter(context, ob, sm.clay_detail * 2.0, 120000, report)
    if new_model:
        set_radius(context, max(longest / 5.0, 2.0))     # a brush a fifth of the model: a real handful
    guard(context)
    return n0, len(ob.data.polygons)


def needs_setup(context):
    """True in Sculpt Mode on a model that has not had the Clay set-up."""
    try:
        if context.mode != "SCULPT":
            return False
        ob = context.object
        return ob is not None and ob.type == "MESH" and _ready["name"] != ob.name
    except Exception:
        return False


def _auto_timer():
    _auto["pending"] = False
    ctx = bpy.context
    name = None
    try:
        if not hasattr(ctx, "temp_override"):       # Blender before 3.2: the strip shows a button instead
            return None
        for w in ctx.window_manager.windows:
            for a in w.screen.areas:
                if a.type != "VIEW_3D":
                    continue
                r = next((q for q in a.regions if q.type == "WINDOW"), None)
                if r is None:
                    continue
                with ctx.temp_override(window=w, area=a, region=r):
                    c = bpy.context
                    if not needs_setup(c):
                        return None
                    name = c.object.name
                    if _ready["failed"] == name:        # tried once already: leave it to the button
                        return None
                    _auto["busy"] = True
                    try:
                        start(c, c.object)
                    finally:
                        _auto["busy"] = False
                    a.tag_redraw()
                return None
    except Exception:
        B.note_error("clay: automatic set-up")
        _ready["failed"] = name
    return None


def request_setup():
    """Ask for the Clay set-up to be run in a moment. Safe to call while drawing."""
    try:
        if _auto["busy"] or bpy.app.background or bpy.app.timers.is_registered(_auto_timer):
            return
        _auto["pending"] = True
        bpy.app.timers.register(_auto_timer, first_interval=0.05, persistent=True)
    except Exception:
        _auto["pending"] = False


def forget():
    """The model is no longer in Clay (mode left, file loaded)."""
    if not _auto["busy"]:
        _ready.update(name=None, failed=None)


class SIMPLEMESH_OT_clay_start(Operator):
    """Clay: mould the selected model like clay. Pull, push in, build up, smooth.
    The model is given small triangles first so that flat faces can be moulded too"""
    bl_idname = "simplemesh.clay_start"
    bl_label = "Clay"
    bl_options = {"REGISTER"}                 # the undo steps are made inside (see enter)

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" or needs_setup(context)

    def execute(self, context):
        from . import interactive
        if interactive.ACTIVE["name"] != "easy":      # Easy mode just sleeps while Clay is on
            interactive.stop_tool(context)
        ob = context.object if context.mode == "SCULPT" else target(context)
        if ob is None:
            self.report({"ERROR"}, "Click the model you want to mould first")
            return {"CANCELLED"}
        try:
            n0, n1 = start(context, ob, self.report)
        except Exception as ex:  # noqa: BLE001
            B.note_error("clay: start")
            _ready["failed"] = ob.name
            self.report({"ERROR"}, "Could not start Clay: %s" % ex)
            return {"CANCELLED"}
        if n0 > 400000:
            self.report({"INFO"}, "Large model (%s triangles): Clay may be slow. Repair > Simplify first helps"
                        % format(n0, ","))
        elif n1 > n0:
            self.report({"INFO"}, "Ready to mould: %s triangles (was %s). Flat areas are merged again when you press Done"
                        % (format(n1, ","), format(n0, ",")))
        return {"FINISHED"}


class SIMPLEMESH_OT_clay_brush(Operator):
    """Choose a clay brush"""
    bl_idname = "simplemesh.clay_brush"
    bl_label = "Clay brush"

    key: StringProperty(default="pull")

    @classmethod
    def description(cls, context, properties):
        b = BRUSH_BY_KEY.get(properties.key)
        return ("%s: %s" % (b[1], b[5])) if b else ""

    @classmethod
    def poll(cls, context):
        return context.mode == "SCULPT"

    def execute(self, context):
        if self.key not in BRUSH_BY_KEY:
            return {"CANCELLED"}
        context.scene.simplemesh.clay_brush = self.key
        if not activate_brush(context, self.key):
            self.report({"WARNING"}, "Blender would not switch to that brush")
        if context.area is not None:
            context.area.tag_redraw()
        return {"FINISHED"}


def leave_clay(context):
    forget()
    try:
        so = context.sculpt_object
        if so is not None and so.use_dynamic_topology_sculpting:
            bpy.ops.sculpt.dynamic_topology_toggle()
    except Exception:
        pass
    bpy.ops.object.mode_set(mode="OBJECT")


class SIMPLEMESH_OT_clay_done(Operator):
    """Finish moulding and go back to the normal tools"""
    bl_idname = "simplemesh.clay_done"
    bl_label = "Done"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "SCULPT"

    def execute(self, context):
        ob = context.object
        with B.busy(context, "clay: done"):
            leave_clay(context)
            if ob is not None and ob.type == "MESH":
                B.bake(ob)
                B.refresh(context)
                B.select_only(context, [ob])
                B.crumb("clay: back in object mode, %d triangles" % len(ob.data.polygons))
                if len(ob.data.polygons) <= PLAIN_ABOVE:      # (a dense scan has no big flat areas to merge)
                    B.tidy_flat(context, ob)                  # untouched flat areas back to big triangles
                B.shade_nicely(ob.data)
                B.bake(ob)
                B.refresh(context)
                B.select_only(context, [ob])
        if ob is not None and ob.type == "MESH":
            r = B.store_check(context, ob)
            msg = "%s triangles" % format(r["tris"], ",")
            if r["open"] or r["bad"] or r["inverted"]:
                self.report({"WARNING"}, msg + ". The model needs Repair (Repair > Repair) before printing")
            else:
                self.report({"INFO"}, msg + ", watertight")
        return {"FINISHED"}


class SIMPLEMESH_OT_back(Operator):
    """Leave this Blender mode and go back to the SimpleMesh tools"""
    bl_idname = "simplemesh.back"
    bl_label = "Back to the models"

    def execute(self, context):
        try:
            if context.mode == "SCULPT":
                leave_clay(context)
            else:
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception as ex:  # noqa: BLE001
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        return {"FINISHED"}


CLASSES = (SIMPLEMESH_OT_clay_start, SIMPLEMESH_OT_clay_brush,
           SIMPLEMESH_OT_clay_done, SIMPLEMESH_OT_back)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)

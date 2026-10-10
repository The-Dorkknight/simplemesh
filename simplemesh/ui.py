# SimpleMesh - the tool strip, pop-up panels, sidebar tab and start-up tidying
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 3. No warranty; see LICENSE.

import bpy
from bpy.types import Panel

from . import base as B
from . import clay as C
from . import deck as D
from . import easy as E
from . import interactive as I
from .version import __build_date__, __version__

ico = B.ico


# --------------------------------------------------------------------------
# The strip: one row of tools across the top of the 3D view
# --------------------------------------------------------------------------

STRIP_TOOLS = (
    ("layflat", "Lay flat", "SNAP_FACE"),
    ("move", "Move", "EMPTY_ARROWS"),
    ("turn", "Turn", "FILE_REFRESH"),
    ("size", "Size", "FULLSCREEN_ENTER"),
    ("pull", "Pull", "ORIENTATION_NORMAL"),
    ("cut", "Cut", "MOD_BOOLEAN"),
    ("hole", "Drill", "MESH_CIRCLE"),
    ("measure", "Measure", "DRIVER_DISTANCE"),
)


def draw_clay_strip(self, context, slim=False):
    lay = self.layout
    sm = context.scene.simplemesh
    if not slim:                              # (with the big-button panel on, Done and the brushes are there)
        row = lay.row(align=True)
        row.alert = True
        row.operator("simplemesh.clay_done", text="Done", icon=ico("CHECKMARK"))
        lay.separator()
        row = lay.row(align=True)
        using = C.actual_key(context)         # what Blender is really using, not what we asked for
        for key, label, _t, _a, _d, _h in C.BRUSHES:
            row.operator("simplemesh.clay_brush", text=label, depress=(using == key)).key = key
        lay.separator()
    ups = C.unified(context)
    row = lay.row(align=True)
    if ups is not None:
        name, _k = C.size_prop(ups)
        if name:
            row.prop(ups, name, text="Size")
        row.prop(ups, "strength", text="Strength", slider=True)
    row.prop(sm, "clay_mirror", text="Mirror", toggle=True)
    row.prop(sm, "clay_detail", text="Detail")
    lay.separator()
    draw_problem_button(lay)


def draw_problem_button(lay):
    if B.ERRORS:
        row = lay.row()
        row.alert = True
        row.operator("simplemesh.report", text="Report a problem", icon=ico("ERROR"))
        lay.separator()


def draw_strip(self, context):
    deck = D.shown(context)
    if context.mode == "SCULPT":
        if C.needs_setup(context):
            # Sculpt Mode was entered through Blender's own menus: nothing is set up
            # yet, so do what the Clay button does (in a moment; not while drawing).
            C.request_setup()
            lay = self.layout
            row = lay.row(align=True)
            row.alert = True
            row.operator("simplemesh.back", text="Back to the models", icon=ico("LOOP_BACK"))
            lay.separator()
            row = lay.row()
            row.operator("simplemesh.clay_start", text="Get this model ready to mould", icon=ico("SCULPTMODE_HLT"))
            lay.separator()
            draw_problem_button(lay)
            return
        draw_clay_strip(self, context, slim=deck)
        return
    C.forget()
    if context.mode != "OBJECT":
        row = self.layout.row()
        row.alert = True
        row.operator("simplemesh.back", text="Back to the models", icon=ico("LOOP_BACK"))
        self.layout.separator()
        return
    lay = self.layout
    active = I.ACTIVE["name"] if I.ACTIVE["token"] is not None else ""
    if deck:
        # The big-button panel holds the tools; only the pop-ups with number fields
        # (which need Blender's own widgets) stay in this row.
        row = lay.row(align=True)
        row.popover(panel="SM_PT_pop_numbers", text="Numbers")
        row.popover(panel="SM_PT_pop_shapes", text="Shapes")
        row.popover(panel="SM_PT_pop_repair", text="Repair")
        row.popover(panel="SM_PT_pop_view", text="View")
        lay.separator()
        draw_problem_button(lay)
        return
    if active == "easy" or (active != "" and context.scene.simplemesh.easy_on):
        # Easy mode: the picture buttons do the everyday things; only the extra
        # tools stay up here, so there is less to read.
        row = lay.row(align=True)
        row.operator("simplemesh.tool", text="Easy", icon=ico("FUND"), depress=True).name = "easy"
        lay.separator()
        row = lay.row(align=True)
        for name, label, icon in STRIP_TOOLS:
            if name in ("layflat", "pull", "cut", "hole", "measure"):
                row.operator("simplemesh.tool", text=label, icon=ico(icon), depress=(active == name)).name = name
        lay.separator()
        row = lay.row(align=True)
        row.popover(panel="SM_PT_pop_repair", text="Repair")
        row.popover(panel="SM_PT_pop_view", text="View")
        lay.separator()
        draw_problem_button(lay)
        return
    row = lay.row(align=True)
    row.operator("simplemesh.import_stl", text="Open", icon=ico("IMPORT"))
    row.operator("simplemesh.export_stl", text="Save", icon=ico("EXPORT"))
    lay.separator()
    row = lay.row(align=True)
    row.operator("simplemesh.frame", text="Find", icon=ico("ZOOM_SELECTED")).everything = False
    lay.separator()
    row = lay.row(align=True)
    row.operator("simplemesh.tool", text="Easy", icon=ico("FUND"), depress=False).name = "easy"
    row.operator("simplemesh.tool", text="Select", icon=ico("RESTRICT_SELECT_OFF"), depress=(active == "")).name = ""
    for name, label, icon in STRIP_TOOLS:
        row.operator("simplemesh.tool", text=label, icon=ico(icon), depress=(active == name)).name = name
    row.operator("simplemesh.clay_start", text="Clay", icon=ico("SCULPTMODE_HLT"))
    lay.separator()
    row = lay.row(align=True)
    row.popover(panel="SM_PT_pop_numbers", text="Numbers")
    row.popover(panel="SM_PT_pop_shapes", text="Shapes")
    row.popover(panel="SM_PT_pop_repair", text="Repair")
    row.popover(panel="SM_PT_pop_view", text="View")
    lay.separator()
    draw_problem_button(lay)


# --------------------------------------------------------------------------
# Section drawing, shared by the pop-ups and the sidebar tab
# --------------------------------------------------------------------------

def draw_numbers(lay, context):
    sm = context.scene.simplemesh
    if not B.units_are_mm(context.scene):
        box = lay.box()
        box.label(text="Scene is not in millimetres", icon=ico("ERROR"))
        box.operator("simplemesh.setup", text="Fix: use millimetres")
    col = lay.column(align=True)
    col.label(text="Wrong units? One click:")
    r = col.row(align=True)
    for txt, f in (("÷1000", 0.001), ("÷100", 0.01), ("÷10", 0.1), ("×10", 10.0), ("×1000", 1000.0)):
        r.operator("simplemesh.scale_by", text=txt).factor = f
    r = col.row(align=True)
    r.operator("simplemesh.scale_by", text="inch → mm").factor = 25.4
    r.operator("simplemesh.scale_by", text="mm → inch").factor = 1.0 / 25.4
    lay.separator()
    r = lay.row(align=True)
    r.prop(sm, "fit_size", text="Longest side")
    r.operator("simplemesh.fit_longest", text="Set").size = sm.fit_size
    r = lay.row(align=True)
    r.prop(sm, "scale_factor", text="Multiply by")
    r.operator("simplemesh.scale_by", text="Go").factor = sm.scale_factor
    ob = context.object
    if ob is not None and ob.type == "MESH":
        lay.label(text="Exact size in mm (X, Y, Z):")
        lay.prop(ob, "dimensions", text="")
    lay.separator()
    lay.label(text="On the bed:")
    r = lay.row(align=True)
    r.operator("simplemesh.place", text="Drop").center = False
    r.operator("simplemesh.place", text="Centre").center = True
    r.operator("simplemesh.lay_flat", text="Auto flat")
    lay.label(text="Turn 90° / mirror:")
    r = lay.row(align=True)
    for ax in ("X", "Y", "Z"):
        op = r.operator("simplemesh.rotate90", text="⟳ " + ax)
        op.axis, op.angle = ax, 90.0
    r = lay.row(align=True)
    for ax in ("X", "Y", "Z"):
        r.operator("simplemesh.mirror", text="Mirror " + ax).axis = ax
    lay.separator()
    lay.label(text="Hole tool:")
    lay.prop(sm, "hole_diameter", text="Diameter")
    lay.prop(sm, "hole_depth", text="Depth (0 = through)")
    lay.label(text="Cut tool:")
    lay.prop(sm, "cut_keep", text="Keep")
    lay.prop(sm, "cut_faces_down")


def draw_shapes(lay, context):
    lay.label(text="Add a shape (sizes appear bottom-left):")
    grid = lay.grid_flow(row_major=True, columns=2, align=True)
    for shape, txt, ic in (("BLOCK", "Block", "MESH_CUBE"), ("CYLINDER", "Cylinder", "MESH_CYLINDER"),
                           ("SPHERE", "Sphere", "MESH_UVSPHERE"), ("CONE", "Cone", "MESH_CONE")):
        grid.operator("simplemesh.add_shape", text=txt, icon=ico(ic)).shape = shape
    lay.separator()
    lay.label(text="Any shape can be a hole:")
    col = lay.column(align=True)
    col.operator("simplemesh.mark_hole", text="Make it a hole (red)", icon=ico("SELECT_SUBTRACT"))
    col.operator("simplemesh.apply_holes", text="Cut the holes out", icon=ico("CHECKMARK"))
    lay.separator()
    col = lay.column(align=True)
    col.operator("simplemesh.weld", text="Weld selected together", icon=ico("SELECT_EXTEND"))
    col.operator("simplemesh.split_loose", text="Separate loose pieces")
    r = lay.row(align=True)
    r.operator("simplemesh.duplicate", text="Copy", icon=ico("DUPLICATE"))
    r.operator("simplemesh.delete", text="Delete", icon=ico("TRASH"))


def draw_repair(lay, context):
    sm = context.scene.simplemesh
    r = lay.row(align=True)
    r.scale_y = 1.3
    r.operator("simplemesh.check", text="Check", icon=ico("INFO"))
    r.operator("simplemesh.repair", text="Repair", icon=ico("CHECKMARK"))
    if sm.chk_valid:
        box = lay.box()
        box.label(text=sm.chk_name)
        box.label(text="%s triangles" % format(sm.chk_tris, ","))
        box.label(text="Volume %.2f cm³" % (sm.chk_volume / 1000.0))
        box.label(text="Surface %.1f cm²" % (sm.chk_area / 100.0))
        if sm.chk_open == 0 and sm.chk_bad == 0 and not sm.chk_inverted:
            box.label(text="Watertight: good to print", icon=ico("CHECKMARK"))
        if sm.chk_open:
            box.label(text="%d open edges (holes)" % sm.chk_open, icon=ico("ERROR"))
        if sm.chk_bad:
            box.label(text="%d edges shared by 3+ faces" % sm.chk_bad, icon=ico("ERROR"))
        if sm.chk_inverted:
            box.label(text="Faces point inwards", icon=ico("ERROR"))
    lay.separator()
    lay.label(text="Fewer triangles (smaller file):")
    r = lay.row(align=True)
    r.prop(sm, "decimate_ratio", text="Keep")
    r.operator("simplemesh.simplify", text="Simplify").ratio = sm.decimate_ratio


def draw_view(lay, context):
    sm = context.scene.simplemesh
    grid = lay.grid_flow(row_major=True, columns=3, align=True)
    for d, txt in (("TOP", "Top"), ("FRONT", "Front"), ("RIGHT", "Right"),
                   ("BOTTOM", "Bottom"), ("BACK", "Back"), ("LEFT", "Left")):
        grid.operator("simplemesh.view", text=txt).direction = d
    r = lay.row(align=True)
    r.operator("simplemesh.frame", text="Show everything").everything = True
    r.operator("simplemesh.toggle_persp", text="Persp / flat")
    lay.label(text="Look:")
    lay.prop(sm, "look", text="")
    lay.prop(sm, "look_rainbow")
    lay.prop(sm, "show_edges")
    lay.prop(sm, "show_xray")
    lay.prop(sm, "show_flipped")
    lay.prop(sm, "show_dims")
    lay.separator()
    lay.operator("simplemesh.easy_nav", text="Laptop navigation (no middle button)")
    lay.operator("simplemesh.setup", text="Tidy this window")
    p = B.prefs(context)
    if not isinstance(p, B._DefaultPrefs):
        lay.separator()
        lay.label(text="Printer bed:")
        lay.prop(p, "preset", text="")
        r = lay.row(align=True)
        r.prop(p, "bed_x", text="X")
        r.prop(p, "bed_y", text="Y")
        r.prop(p, "bed_z", text="Z")
        lay.prop(p, "show_bed")
        lay.prop(p, "show_deck")
    lay.separator()
    lay.operator("simplemesh.report", text="Report a problem (copies the details)", icon=ico("ERROR"))
    lay.label(text="SimpleMesh v%s  •  %s" % (__version__, __build_date__))


class _Pop:
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 14


class SM_PT_pop_numbers(_Pop, Panel):
    bl_idname = "SM_PT_pop_numbers"
    bl_label = "Exact numbers"

    def draw(self, context):
        draw_numbers(self.layout, context)


class SM_PT_pop_shapes(_Pop, Panel):
    bl_idname = "SM_PT_pop_shapes"
    bl_label = "Shapes, holes and joining"

    def draw(self, context):
        draw_shapes(self.layout, context)


class SM_PT_pop_repair(_Pop, Panel):
    bl_idname = "SM_PT_pop_repair"
    bl_label = "Check and repair"

    def draw(self, context):
        draw_repair(self.layout, context)


class SM_PT_pop_view(_Pop, Panel):
    bl_idname = "SM_PT_pop_view"
    bl_label = "View and settings"

    def draw(self, context):
        draw_view(self.layout, context)


class _Side:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SimpleMesh"

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"


class SM_PT_main(_Side, Panel):
    bl_idname = "SM_PT_main"
    bl_label = "SimpleMesh " + __version__

    def draw(self, context):
        lay = self.layout
        lay.label(text="The tools are in the strip along")
        lay.label(text="the top of the 3D view.")
        lay.label(text="These panels hold the numbers.")


class SM_PT_numbers(_Side, Panel):
    bl_idname = "SM_PT_numbers"
    bl_label = "Exact numbers"
    bl_parent_id = "SM_PT_main"

    def draw(self, context):
        draw_numbers(self.layout, context)


class SM_PT_shapes(_Side, Panel):
    bl_idname = "SM_PT_shapes"
    bl_label = "Shapes, holes, joining"
    bl_parent_id = "SM_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        draw_shapes(self.layout, context)


class SM_PT_repair(_Side, Panel):
    bl_idname = "SM_PT_repair"
    bl_label = "Check & repair"
    bl_parent_id = "SM_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        draw_repair(self.layout, context)


class SM_PT_view(_Side, Panel):
    bl_idname = "SM_PT_view"
    bl_label = "View & settings"
    bl_parent_id = "SM_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        draw_view(self.layout, context)


PANELS = (SM_PT_pop_numbers, SM_PT_pop_shapes, SM_PT_pop_repair, SM_PT_pop_view,
          SM_PT_main, SM_PT_numbers, SM_PT_shapes, SM_PT_repair, SM_PT_view)


# --------------------------------------------------------------------------
# Start-up behaviour, menus, keymap
# --------------------------------------------------------------------------

_DEFAULT_NAMES = {"Cube", "Light", "Camera"}
_startup_tries = 0


def tidy_new_file(context=None):
    """Applied to a fresh, unsaved file: the standard start-up scene becomes an
    empty millimetre scene with one big, tidy 3D view."""
    ctx = context or bpy.context
    p = B.prefs(ctx)
    if not p.apply_on_startup:
        return
    sc = ctx.scene
    if bpy.data.filepath:
        return
    if {o.name for o in sc.objects} <= _DEFAULT_NAMES:
        for o in list(sc.objects):
            bpy.data.objects.remove(o, do_unlink=True)
    B.ensure_mm_units(sc)
    closed = B.simplify_screen(ctx) if getattr(p, "simplify_screen", True) else 0
    if closed and not bpy.app.background:
        # Blender must redraw once after editors are closed before the 3D view's
        # own regions may be touched (doing it straight away crashes Blender 4.0).
        bpy.app.timers.register(_tidy_views_later, first_interval=0.4)
    else:
        tidy_views(ctx)


def tidy_views(context=None):
    ctx = context or bpy.context
    B.declutter_viewports(ctx)
    B.apply_look(ctx)
    B.apply_view_flags(ctx)
    B.frame_model(ctx, everything=True)
    if getattr(B.prefs(ctx), "easy_start", True) and not bpy.app.background:
        E.start_easy(ctx)


def _tidy_views_later():
    try:
        tidy_views(bpy.context)
    except Exception:
        pass
    return None


def _startup_timer():
    global _startup_tries
    _startup_tries += 1
    try:
        if not bpy.context.window_manager.windows and _startup_tries < 20:
            return 0.5
        tidy_new_file(bpy.context)
        if bpy.data.filepath and bpy.context.scene.simplemesh.easy_on:
            E.start_easy(bpy.context)        # a saved Easy-mode project carries on in Easy mode
    except Exception:
        if _startup_tries < 20:
            return 0.5
    return None


@bpy.app.handlers.persistent
def _on_load_post(_dummy):
    global _startup_tries
    _startup_tries = 0
    try:
        I.stop_tool(None)        # a tool that was running belongs to the file that just closed
        C.forget()
        D.forget_keepers()       # (so does the big-button panel's keeper; drawing starts a new one)
    except Exception:
        pass
    try:
        if bpy.app.background:
            tidy_new_file(bpy.context)
        elif not bpy.app.timers.is_registered(_startup_timer):
            bpy.app.timers.register(_startup_timer, first_interval=0.2)
    except Exception:
        pass


def _heal_timer():
    """Undo can go all the way back to Blender's untouched start-up scene (metres,
    the default cube); put the millimetre scene back if that happened."""
    try:
        ctx = bpy.context
        sc = ctx.scene
        if bpy.data.filepath or B.units_are_mm(sc) or not B.prefs(ctx).apply_on_startup:
            return None
        if not {o.name for o in sc.objects} <= _DEFAULT_NAMES:
            return None
        for o in list(sc.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        B.ensure_mm_units(sc)
        if I.ACTIVE["name"] == "easy" and I.ACTIVE["token"] is not None:
            sc.simplemesh.easy_on = True          # that setting was undone too
        try:
            ctx.view_layer.update()               # forget the objects just removed
        except Exception:
            pass
        B.apply_look(ctx)
        B.apply_view_flags(ctx)
    except Exception:
        B.note_error("undo: tidy again")
    return None


@bpy.app.handlers.persistent
def _on_undo_post(*_args):
    try:
        if not bpy.app.background and not bpy.app.timers.is_registered(_heal_timer):
            bpy.app.timers.register(_heal_timer, first_interval=0.05)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Recovery copies
# --------------------------------------------------------------------------
# Blender saves a recovery copy every few minutes (File > Recover > Auto Save),
# but not while any add-on tool is watching the mouse. Easy mode and the
# big-button panel watch it all the time, so without this nothing would ever be
# saved. The copy goes where Blender's own would, under the same name, and
# follows Blender's own two settings (Preferences > Save & Load > Auto Save).

_RECOVER = {"t": 0.0, "path": ""}


def recovery_path():
    import os
    import tempfile
    try:
        base = os.path.dirname(os.path.normpath(bpy.app.tempdir))
    except Exception:
        base = ""
    return os.path.join(base or tempfile.gettempdir(), "%d_autosave.blend" % os.getpid())


def ours_running():
    return bool(D.KEEP) or I.ACTIVE["token"] is not None


def someone_busy(context):
    """True while a drag of any kind is going on (ours or one of Blender's own tools)."""
    if B.INPUT["down"]:
        return True
    tool = I._CURRENT["tool"]
    if tool is not None and (getattr(tool, "dragging", False) or getattr(tool, "state", "IDLE") != "IDLE"):
        return True
    try:
        for w in context.window_manager.windows:
            for op in getattr(w, "modal_operators", ()):         # (Blender 4.2 and later can tell us)
                if not op.bl_idname.startswith("SIMPLEMESH_OT"):
                    return True
    except Exception:
        pass
    return False


def save_recovery_copy(context):
    path = recovery_path()
    win = context.window_manager.windows[0]
    with context.temp_override(window=win):
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, check_existing=False)
    _RECOVER.update(t=__import__("time").time(), path=path)
    B.crumb("recovery copy saved: %s" % path)
    return path


def _recovery_timer():
    import time
    try:
        ctx = bpy.context
        fp = ctx.preferences.filepaths
        if not _RECOVER["t"]:
            _RECOVER["t"] = time.time()
        due = time.time() - _RECOVER["t"] >= max(1, fp.auto_save_time) * 60.0
        if due and fp.use_auto_save_temporary_files and ours_running() \
                and hasattr(ctx, "temp_override") and ctx.window_manager.windows and not someone_busy(ctx):
            save_recovery_copy(ctx)
    except Exception:
        B.note_error("recovery copy")
        _RECOVER["t"] = __import__("time").time()        # try again after the next interval, not every 20 s
    return 20.0


def menu_import(self, _context):
    self.layout.operator("simplemesh.import_stl", text="STL, auto-scaled (SimpleMesh)")


def menu_export(self, _context):
    self.layout.operator("simplemesh.export_stl", text="STL, mm (SimpleMesh)")


def status_draw(self, _context):
    self.layout.label(text="SimpleMesh v%s • %s" % (__version__, __build_date__))


_keymaps = []


def register():
    for c in PANELS:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)
    try:
        bpy.types.VIEW3D_HT_tool_header.prepend(draw_strip)
    except Exception:
        pass
    try:
        bpy.types.STATUSBAR_HT_header.append(status_draw)
    except Exception:
        pass
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if _on_undo_post not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(_on_undo_post)
    if not bpy.app.background and not bpy.app.timers.is_registered(_recovery_timer):
        _RECOVER["t"] = 0.0
        bpy.app.timers.register(_recovery_timer, first_interval=20.0, persistent=True)
    if not bpy.app.background:
        bpy.app.timers.register(_startup_timer, first_interval=0.5)
        kc = bpy.context.window_manager.keyconfigs.addon
        if kc:
            km = kc.keymaps.new(name="Object Mode", space_type="EMPTY")
            _keymaps.append((km, km.keymap_items.new("simplemesh.frame", "F", "PRESS")))


def unregister():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _keymaps.clear()
    try:
        if bpy.app.timers.is_registered(_startup_timer):
            bpy.app.timers.unregister(_startup_timer)
    except Exception:
        pass
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if _on_undo_post in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.remove(_on_undo_post)
    for t in (_heal_timer, C._auto_timer, _recovery_timer):
        try:
            if bpy.app.timers.is_registered(t):
                bpy.app.timers.unregister(t)
        except Exception:
            pass
    for fn, host in ((status_draw, "STATUSBAR_HT_header"), (draw_strip, "VIEW3D_HT_tool_header"),
                     (menu_export, "TOPBAR_MT_file_export"), (menu_import, "TOPBAR_MT_file_import")):
        try:
            getattr(bpy.types, host).remove(fn)
        except Exception:
            pass
    for c in reversed(PANELS):
        bpy.utils.unregister_class(c)

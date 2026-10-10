# SimpleMesh - core helpers, mesh operations and button operators
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 3. No warranty; see LICENSE.


import math
import os
import time

from array import array

import bmesh
import bpy

try:  # numpy ships with blender.org builds, but some distro packages leave it out
    if os.environ.get("SIMPLEMESH_NO_NUMPY"):
        raise ImportError("disabled for testing")
    import numpy as np
except ImportError:
    np = None
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       FloatProperty, IntProperty, StringProperty,
                       PointerProperty)
from bpy.types import AddonPreferences, Operator, PropertyGroup
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Matrix, Vector

PKG = __package__ or "simplemesh"

UNIT_TO_MM = {"MM": 1.0, "CM": 10.0, "M": 1000.0, "IN": 25.4, "UM": 0.001}
GAP_MM = 10.0          # spacing when several models are laid out side by side
AXES = {"X": 0, "Y": 1, "Z": 2}


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

class _DefaultPrefs:
    apply_on_startup = True
    bed_x = 220.0
    bed_y = 220.0
    bed_z = 220.0
    show_bed = True
    simplify_screen = True
    easy_start = True
    show_deck = True


def prefs(context=None):
    try:
        return (context or bpy.context).preferences.addons[PKG].preferences
    except Exception:
        return _DefaultPrefs()


# Problems that were caught instead of stopping Blender, kept so that "Report a
# problem" can show them: {where: [how many times, traceback text]}, oldest first.
ERRORS = {}
EVENTS = []            # the last few mouse/key events the tools saw (names only)


def note_error(where):
    """Remember the exception being handled (call inside an except block)."""
    try:
        import traceback
        txt = traceback.format_exc()
        got = ERRORS.get(where)
        if got is not None:
            got[0] += 1
            got[1] = txt
        elif len(ERRORS) < 30:
            ERRORS[where] = [1, txt]
    except Exception:
        pass


# A small log file of what SimpleMesh was doing, written line by line, so that
# after a freeze or a crash the next "Report a problem" can show where it stopped.
_LOG = {"f": None, "path": "", "prev": ""}


def log_path():
    """In Blender's own settings folder; the temporary folder if that cannot be used."""
    for d in (lambda: bpy.utils.user_resource("CONFIG"), lambda: bpy.app.tempdir, lambda: os.path.expanduser("~")):
        try:
            folder = d()
            if folder:
                os.makedirs(folder, exist_ok=True)
                if os.access(folder, os.W_OK):
                    # (Blender run without a window, as the installer does, keeps its own
                    # file so that it does not push a real session's log out)
                    return os.path.join(folder, "simplemesh-log%s.txt" % ("-nowindow" if bpy.app.background else ""))
        except Exception:
            continue
    return "simplemesh-log.txt"


def log_open():
    """Start this session's log; the last session's becomes simplemesh-log.prev.txt."""
    try:
        path = log_path()
        prev = path[:-4] + ".prev.txt"
        if os.path.isfile(path):
            try:
                os.replace(path, prev)
            except Exception:
                pass
        _LOG.update(f=open(path, "w", encoding="utf-8"), path=path, prev=prev)
        crumb("session start, Blender %s" % bpy.app.version_string)
    except Exception:
        _LOG["f"] = None


def log_close():
    try:
        if _LOG["f"] is not None:
            crumb("session end")
            _LOG["f"].close()
    except Exception:
        pass
    _LOG["f"] = None


def crumb(text):
    """One line in the log, written to disk straight away."""
    f = _LOG["f"]
    if f is None:
        return
    try:
        f.write("%s  %s\n" % (time.strftime("%H:%M:%S"), text))
        f.flush()
    except Exception:
        pass


class busy:
    """with busy(context, "what"): shows Blender's busy pointer and notes the start,
    the end and the time taken in the log."""

    def __init__(self, context, what):
        self.wm = getattr(context, "window_manager", None)
        self.what = what

    def __enter__(self):
        self.t = time.time()
        crumb("%s ..." % self.what)
        try:
            self.wm.progress_begin(0, 100)
            self.wm.progress_update(50)
        except Exception:
            pass
        return self

    def __exit__(self, kind, _val, _tb):
        try:
            self.wm.progress_end()
        except Exception:
            pass
        crumb("%s %s after %.1f s" % (self.what, "FAILED" if kind else "done", time.time() - self.t))
        return False


_PLAIN_KEYS = {"ESC", "RET", "NUMPAD_ENTER", "DEL", "BACK_SPACE", "TAB", "SPACE", "Z", "F", "X", "D"}


INPUT = {"down": False}


def note_input(event):
    """Called by everything of ours that watches the mouse, for every event it sees.
    "down" is True from a mouse button press until the next event we get to see.
    While one of Blender's own tools runs (a brush stroke, a box select, turning the
    view) it keeps the events to itself, so "down" stays True for as long as it lasts."""
    try:
        et = event.type
        if et.startswith("TIMER"):
            return
        INPUT["down"] = et in ("LEFTMOUSE", "RIGHTMOUSE", "MIDDLEMOUSE") and event.value in ("PRESS", "DOUBLE_CLICK")
    except Exception:
        pass


def note_event(event):
    """Keep the names of the last events for a problem report. Ordinary typing is
    recorded only as KEY, never as the letters themselves."""
    try:
        et, ev = event.type, event.value
        if et in ("MOUSEMOVE", "INBETWEEN_MOUSEMOVE") or et.startswith("TIMER"):
            if EVENTS and EVENTS[-1][0] == "move":
                EVENTS[-1][1] += 1
            else:
                EVENTS.append(["move", 1])
        else:
            if "MOUSE" not in et and "TRACKPAD" not in et and "PEN" not in et and "NDOF" not in et \
                    and "CTRL" not in et and "SHIFT" not in et and "ALT" not in et and "OSKEY" not in et \
                    and et not in _PLAIN_KEYS and not et.startswith("WINDOW"):
                et = "KEY"
            EVENTS.append(["%s %s" % (et, ev), 1])
        if len(EVENTS) > 60:
            del EVENTS[:20]
    except Exception:
        pass


_icons = None


def ico(name):
    """Return an icon name that exists in this Blender version, else NONE."""
    global _icons
    if _icons is None:
        try:
            fn = bpy.types.UILayout.bl_rna.functions["operator"]
            _icons = {i.identifier for i in fn.parameters["icon"].enum_items}
        except Exception:
            _icons = set()
    return name if (not _icons or name in _icons) else "NONE"


def _set(obj, attr, value):
    """setattr that never raises (Blender's viewport API drifts between versions)."""
    try:
        setattr(obj, attr, value)
        return True
    except Exception:
        return False


def mesh_objects(context):
    return [o for o in context.selected_objects if o.type == "MESH"]


def targets(context):
    objs = mesh_objects(context)
    if not objs and context.object is not None and context.object.type == "MESH":
        objs = [context.object]
    return objs


def ensure_object_mode(context):
    ob = context.object
    if ob is not None and ob.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass


def unparent(obj):
    if obj.parent is not None:
        w = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_basis = w


def obj_bounds(obj):
    """World-space (min, max) of an un-parented mesh object, exact, from vertices."""
    me = obj.data
    n = len(me.vertices)
    mb = obj.matrix_basis
    if n == 0:
        t = mb.translation.copy()
        return t, t.copy()
    if np is not None:
        a = np.empty(n * 3, dtype=np.float32)
        me.vertices.foreach_get("co", a)
        m = np.array(mb, dtype=np.float64)
        w = a.reshape(n, 3).astype(np.float64) @ m[:3, :3].T + m[:3, 3]
        return Vector(map(float, w.min(axis=0))), Vector(map(float, w.max(axis=0)))
    a = array("f", bytes(12 * n))
    me.vertices.foreach_get("co", a)
    m3 = mb.to_3x3()
    axis_aligned = all(abs(m3[i][j]) < 1e-9 for i in range(3) for j in range(3) if i != j)
    if axis_aligned:  # the usual case after bake(): fast C-level min/max
        lo = Vector((min(a[0::3]), min(a[1::3]), min(a[2::3])))
        hi = Vector((max(a[0::3]), max(a[1::3]), max(a[2::3])))
        p, q = mb @ lo, mb @ hi
        return (Vector((min(p.x, q.x), min(p.y, q.y), min(p.z, q.z))),
                Vector((max(p.x, q.x), max(p.y, q.y), max(p.z, q.z))))
    lo = Vector((1e30, 1e30, 1e30))
    hi = Vector((-1e30, -1e30, -1e30))
    for i in range(n):
        w = mb @ Vector((a[3 * i], a[3 * i + 1], a[3 * i + 2]))
        lo.x, lo.y, lo.z = min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)
        hi.x, hi.y, hi.z = max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)
    return lo, hi


def group_bounds(objs):
    los, his = zip(*[obj_bounds(o) for o in objs])
    lo = Vector((min(v.x for v in los), min(v.y for v in los), min(v.z for v in los)))
    hi = Vector((max(v.x for v in his), max(v.y for v in his), max(v.z for v in his)))
    return lo, hi


def _flip(me):
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()


def bake(obj):
    """Bake rotation/scale/location into the mesh, then put the origin at the
    centre of the bounding box. Afterwards: rotation 0, scale 1, location = centre."""
    unparent(obj)
    me = obj.data
    if me.users > 1:
        me = me.copy()
        obj.data = me
    m = obj.matrix_basis.copy()
    me.transform(m)
    if m.determinant() < 0:
        _flip(me)
    obj.matrix_basis = Matrix.Identity(4)
    lo, hi = obj_bounds(obj)
    c = (lo + hi) / 2.0
    me.transform(Matrix.Translation(-c))
    obj.location = c
    me.update()


def transform_group(objs, m):
    for o in objs:
        unparent(o)
        o.matrix_basis = m @ o.matrix_basis
        bake(o)


def about(pivot, m3):
    """4x4 matrix applying m3 (a 4x4 linear matrix) around a world pivot."""
    return Matrix.Translation(pivot) @ m3 @ Matrix.Translation(-pivot)


def refresh(context):
    try:
        context.view_layer.update()
    except Exception:
        pass


def select_only(context, objs, active=None):
    for o in context.view_layer.objects:
        try:
            o.select_set(False)
        except Exception:
            pass
    for o in objs:
        o.select_set(True)
    if objs:
        context.view_layer.objects.active = active or objs[-1]


def new_mesh_object(context, name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    context.collection.objects.link(ob)
    return ob


def eval_replace(context, obj, setup):
    """Add a modifier via setup(obj), bake its result into the mesh, remove it."""
    mod = setup(obj)
    dg = context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    new = bpy.data.meshes.new_from_object(ev, depsgraph=dg)
    obj.modifiers.remove(mod)
    old = obj.data
    name = old.name
    obj.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
    new.name = name


# --------------------------------------------------------------------------
# Viewport: units, clipping, looks, framing ("never lose the model")
# --------------------------------------------------------------------------

def each_view3d(context=None):
    """Yield (area, space) for every 3D view in the open windows (or, with no
    windows, e.g. headless, every stored screen)."""
    ctx = context or bpy.context
    screens = []
    try:
        screens = [w.screen for w in ctx.window_manager.windows]
    except Exception:
        pass
    if not screens:
        screens = list(bpy.data.screens)
    seen = set()
    for scr in screens:
        for area in scr.areas:
            if area.type != "VIEW_3D":
                continue
            for sp in area.spaces:
                if sp.type == "VIEW_3D" and sp.as_pointer() not in seen:
                    seen.add(sp.as_pointer())
                    yield area, sp


def ensure_mm_units(scene):
    """1 Blender unit = 1 mm, shown as mm."""
    u = scene.unit_settings
    u.system = "METRIC"
    u.scale_length = 0.001
    _set(u, "length_unit", "MILLIMETERS")
    _set(u, "mass_unit", "GRAMS")


def shade_nicely(me, angle_deg=30.0):
    """Show flat faces flat and curved areas smooth (the look of a slicer preview).
    Only the shading changes, never the shape. STL files carry no such information,
    and Blender shades a model with joined points fully smooth, which makes a
    bracket look like a pillow."""
    try:
        n = len(me.polygons)
        if n == 0:
            return
        me.polygons.foreach_set("use_smooth", [True] * n)
        if hasattr(me, "use_auto_smooth"):                   # Blender up to 4.0
            me.use_auto_smooth = True
            me.auto_smooth_angle = math.radians(angle_deg)
        elif hasattr(me, "set_sharp_from_angle"):            # Blender 4.1 and later
            me.set_sharp_from_angle(angle=math.radians(angle_deg))
        else:
            me.polygons.foreach_set("use_smooth", [False] * n)
        me.update()
    except Exception:
        note_error("shading")


def units_are_mm(scene):
    u = scene.unit_settings
    return u.system == "METRIC" and abs(u.scale_length - 0.001) < 1e-9


def set_clip(context, size):
    """Make the viewport clipping fit a model of the given size (this is what
    makes a huge model vanish, or a scaled-down one hide inside the near plane)."""
    size = max(float(size), 1.0)
    start = max(0.01, size / 2000.0)
    end = min(max(2000.0, size * 60.0), 1.0e6)
    for _a, sp in each_view3d(context):
        _set(sp, "clip_start", start)
        _set(sp, "clip_end", end)


def view_op(context, opname, **kw):
    """Run a view3d operator against the main region of a 3D view, from anywhere."""
    try:
        wm = context.window_manager
        wins = []
        if context.window is not None:
            wins.append(context.window)
        wins += [w for w in wm.windows if w not in wins]
        for w in wins:
            area = None
            if (context.area is not None and context.area.type == "VIEW_3D"
                    and w == context.window):
                area = context.area
            if area is None:
                area = next((a for a in w.screen.areas if a.type == "VIEW_3D"), None)
            if area is None:
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is None:
                continue
            op = getattr(bpy.ops.view3d, opname)
            if hasattr(context, "temp_override"):
                with context.temp_override(window=w, area=area, region=region):
                    op(**kw)
            else:  # Blender 3.0 / 3.1
                op({"window": w, "screen": w.screen, "area": area, "region": region}, **kw)
            return True
    except Exception:
        pass
    return False


def frame_bounds(context, lo, hi, margin=2.7):
    """Point every 3D view at the box lo..hi with room around it, and fit the
    clip range. Sets the view directly, so it works from any context."""
    centre = (lo + hi) / 2.0
    radius = max((hi - lo).length / 2.0, 1.0)
    set_clip(context, radius * 2.0)
    done = False
    for _a, sp in each_view3d(context):
        rv = sp.region_3d
        if rv is None:
            continue
        try:
            if rv.view_perspective == "CAMERA":
                rv.view_perspective = "PERSP"
            rv.view_location = centre
            lens = getattr(sp, "lens", 50.0) or 50.0
            # distance at which a sphere of this radius fills the view, plus margin
            rv.view_distance = radius * margin * max(lens / 50.0, 0.3) * 1.45
            done = True
        except Exception:
            pass
    return done


def frame_model(context, everything=False):
    """Centre the view on the selected models (or all of them, with the bed)."""
    objs = [] if everything else mesh_objects(context)
    if not objs:
        everything = True
        objs = [o for o in context.view_layer.objects
                if o.type == "MESH" and o.visible_get()]
    p = prefs(context)
    if not objs:
        return frame_bounds(context, Vector((-p.bed_x / 2, -p.bed_y / 2, 0.0)),
                            Vector((p.bed_x / 2, p.bed_y / 2, 0.0)), margin=1.5)
    for o in objs:
        unparent(o)
    lo, hi = group_bounds(objs)
    return frame_bounds(context, lo, hi)


def apply_look(context=None):
    """The look of every 3D view: background, model colour, outline.
    LUMINOUS = near-black background, glowing cyan models, orange outline;
    CLEAN = light grey background, soft blue-grey models; DEFAULT = Blender's own.
    Easy mode shows each shape in its own colour; "rainbow" gives every model a
    colour of its own, which helps to tell joined-up parts apart."""
    sm = getattr(bpy.context.scene, "simplemesh", None)
    look = sm.look if sm else "LUMINOUS"
    rainbow = bool(sm and sm.look_rainbow)
    easy = bool(sm and sm.easy_on)
    for _a, sp in each_view3d(context):
        sh = sp.shading
        colour = "RANDOM" if rainbow else ("OBJECT" if easy else None)
        if look == "DEFAULT":
            _set(sh, "color_type", colour or "MATERIAL")
            _set(sh, "background_type", "THEME")
            continue
        _set(sh, "type", "SOLID")
        _set(sh, "light", "STUDIO")
        _set(sh, "color_type", colour or "SINGLE")
        _set(sh, "show_object_outline", True)
        _set(sh, "background_type", "VIEWPORT")
        if look == "LUMINOUS":
            _set(sh, "single_color", (0.0, 0.85, 1.0))
            _set(sh, "background_color", (0.015, 0.02, 0.03))
            _set(sh, "object_outline_color", (1.0, 0.55, 0.0))
        else:
            _set(sh, "single_color", (0.62, 0.70, 0.80))
            _set(sh, "background_color", (0.93, 0.94, 0.95))
            _set(sh, "object_outline_color", (0.9, 0.35, 0.0))


def apply_view_flags(context=None):
    sm = bpy.context.scene.simplemesh
    for _a, sp in each_view3d(context):
        ov = sp.overlay
        _set(ov, "show_face_orientation", sm.show_flipped)
        _set(ov, "show_wireframes", sm.show_edges)          # the triangles of the STL, drawn on the model
        if sm.show_edges:
            _set(ov, "wireframe_threshold", 1.0)
            _set(ov, "wireframe_opacity", 0.6)
        _set(sp.shading, "show_xray", sm.show_xray)
        _set(sp, "show_gizmo_object_translate", sm.gizmo_move)
        _set(sp, "show_gizmo_object_rotate", sm.gizmo_rotate)
        _set(sp, "show_gizmo_object_scale", sm.gizmo_scale)


def declutter_viewports(context=None, open_sidebar=False):
    for area, sp in each_view3d(context):
        ov = sp.overlay
        _set(ov, "show_cursor", False)
        _set(ov, "show_stats", False)
        _set(ov, "show_extras", False)
        _set(ov, "show_relationship_lines", False)
        _set(ov, "show_text", False)
        _set(ov, "show_object_origins", False)
        _set(sp, "show_gizmo", True)
        _set(sp, "show_region_toolbar", False)
        _set(sp, "show_region_tool_header", True)
        _set(sp, "show_region_header", True)     # hiding it also hides the tool strip
        _set(sp, "show_region_ui", bool(open_sidebar))
        for r in area.regions:
            if r.type == "UI" and hasattr(r, "active_panel_category"):
                _set(r, "active_panel_category", "SimpleMesh")
    set_clip(context, 200.0)


def simplify_screen(context=None):
    """Close the timeline, outliner and properties editors of the open window so
    only the 3D view is left, and drop the workspace tabs made for animation,
    texturing, sculpting... The stock "Modeling" tab is kept, renamed "Full Blender",
    as the way back.
    Returns the number of editors closed."""
    ctx = context or bpy.context
    closed = 0
    if bpy.app.background:          # no real window to rearrange
        return 0
    try:
        wins = list(ctx.window_manager.windows)
    except Exception:
        wins = []
    for win in wins:
        scr = win.screen
        if not any(a.type == "VIEW_3D" for a in scr.areas):
            continue
        for _try in range(8):
            other = next((a for a in scr.areas if a.type != "VIEW_3D"), None)
            if other is None:
                break
            try:
                ov = {"window": win, "screen": scr, "area": other, "region": other.regions[0]}
                if hasattr(ctx, "temp_override"):
                    with ctx.temp_override(**ov):
                        bpy.ops.screen.area_close()
                else:
                    bpy.ops.screen.area_close(ov)
                closed += 1
            except Exception:
                break
        try:
            # Keep one untouched stock layout as the way back to full Blender.
            full = bpy.data.workspaces.get("Modeling")
            if full is not None and full != win.workspace:
                full.name = "Full Blender"
            if win.workspace.name == "Layout":
                win.workspace.name = "SimpleMesh"
            extra = [w for w in bpy.data.workspaces
                     if w != win.workspace and w.name in _STOCK_WORKSPACES]
            if extra:
                bpy.data.batch_remove(ids=extra)
        except Exception:
            pass
    return closed


_STOCK_WORKSPACES = {"Sculpting", "UV Editing", "Texture Paint", "Shading",
                     "Animation", "Rendering", "Compositing", "Geometry Nodes", "Scripting"}


def _look_update(self, context):
    apply_look(context)


def _flags_update(self, context):
    apply_view_flags(context)


def easy_navigation(context):
    """Laptop-friendly navigation: Alt+left-drag orbits, zoom to the mouse
    pointer, orbit around the selection, number row = standard views."""
    inp = context.preferences.inputs
    changed = []
    for attr in ("use_mouse_emulate_3_button", "use_zoom_to_mouse",
                 "use_rotate_around_active", "use_mouse_depth_navigate",
                 "use_emulate_numpad"):
        if hasattr(inp, attr) and _set(inp, attr, True):
            changed.append(attr)
    return changed


# --------------------------------------------------------------------------
# Print-volume outline drawn in the viewport
# --------------------------------------------------------------------------

_bed_handle = None
_bed_broken = False


def _draw_bed():
    global _bed_broken
    if _bed_broken:
        return
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
        p = prefs()
        if not getattr(p, "show_bed", True):
            return
        shader = None
        for name in ("UNIFORM_COLOR", "3D_UNIFORM_COLOR"):
            try:
                shader = gpu.shader.from_builtin(name)
                break
            except Exception:
                continue
        if shader is None:
            _bed_broken = True
            return
        hx, hy = p.bed_x / 2.0, p.bed_y / 2.0
        verts = [(-hx, -hy, 0.0), (hx, -hy, 0.0), (hx, hy, 0.0), (-hx, hy, 0.0)]
        batch = batch_for_shader(shader, "LINE_LOOP", {"pos": verts})
        gpu.state.blend_set("ALPHA")
        gpu.state.line_width_set(2.0)
        shader.bind()
        shader.uniform_float("color", (1.0, 0.72, 0.1, 0.95))
        batch.draw(shader)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set("NONE")
    except Exception:
        _bed_broken = True


# --------------------------------------------------------------------------
# Mesh analysis and repair
# --------------------------------------------------------------------------

def edge_stats(bm):
    open_e = bad = 0
    for e in bm.edges:
        n = len(e.link_faces)
        if n == 1:
            open_e += 1
        elif n > 2:
            bad += 1
    return open_e, bad


def compute_check(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    open_e, bad = edge_stats(bm)
    vol = bm.calc_volume(signed=True)
    area = sum(f.calc_area() for f in bm.faces)
    bm.free()
    det = abs(obj.matrix_basis.to_3x3().determinant())
    s = det ** (1.0 / 3.0) if det > 0 else 1.0
    return {"tris": tris, "open": open_e, "bad": bad,
            "volume": abs(vol) * s ** 3, "area": area * s * s,
            "inverted": vol < 0}


def store_check(context, obj):
    r = compute_check(obj)
    sm = context.scene.simplemesh
    sm.chk_name = obj.name
    sm.chk_tris = r["tris"]
    sm.chk_open = r["open"]
    sm.chk_bad = r["bad"]
    sm.chk_volume = r["volume"]
    sm.chk_area = r["area"]
    sm.chk_inverted = r["inverted"]
    sm.chk_valid = True
    return r


def weld_mesh(me, dist=1e-4):
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=dist)
    bm.to_mesh(me)
    bm.free()
    me.update()


def repair_mesh(me, dist=1e-4):
    """Weld, drop loose bits, fill holes, triangulate, point normals outwards."""
    bm = bmesh.new()
    bm.from_mesh(me)
    before_open, before_bad = edge_stats(bm)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=dist)
    loose_e = [e for e in bm.edges if not e.link_faces]
    if loose_e:
        bmesh.ops.delete(bm, geom=loose_e, context="EDGES")
    loose_v = [v for v in bm.verts if not v.link_edges]
    if loose_v:
        bmesh.ops.delete(bm, geom=loose_v, context="VERTS")
    try:
        bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges[:])
    except Exception:
        pass
    boundary = [e for e in bm.edges if len(e.link_faces) == 1]
    if boundary:
        try:
            bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
        except Exception:
            pass
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    after_open, after_bad = edge_stats(bm)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return before_open, before_bad, after_open, after_bad


def auto_factor(longest, bed_max):
    """Scale factor that brings an oversized/undersized import into range."""
    f = 1.0
    if longest <= 0:
        return f
    if longest < 1.0:                    # metres opened as millimetres
        while longest * f < 1.0 and f < 1e9:
            f *= 1000.0
    n = 0
    while longest * f > bed_max and n < 12:   # unit mix-ups are powers of ten
        f /= 10.0
        n += 1
    return f


def largest_flat_normal(obj):
    """Local-space normal of the biggest flat region (faces within ~2 degrees)."""
    me = obj.data
    n = len(me.polygons)
    if n == 0:
        return None
    if np is not None:
        nor = np.empty(n * 3, dtype=np.float32)
        area = np.empty(n, dtype=np.float32)
        me.polygons.foreach_get("normal", nor)
        me.polygons.foreach_get("area", area)
        nor = nor.reshape(n, 3)
        q = np.round(nor / 0.035).astype(np.int32)
        _keys, inv = np.unique(q, axis=0, return_inverse=True)
        inv = inv.ravel()
        sums = np.bincount(inv, weights=area.astype(np.float64))
        sel = inv == int(sums.argmax())
        avg = (nor[sel].astype(np.float64) * area[sel, None]).sum(axis=0)
        v = Vector(map(float, avg))
        return v.normalized() if v.length > 0 else None
    bins = {}
    for p in me.polygons:
        nr = p.normal
        key = (round(nr.x / 0.035), round(nr.y / 0.035), round(nr.z / 0.035))
        b = bins.get(key)
        if b is None:
            bins[key] = [p.area, nr * p.area]
        else:
            b[0] += p.area
            b[1] += nr * p.area
    best = max(bins.values(), key=lambda b: b[0])
    return best[1].normalized() if best[1].length > 0 else None


# --------------------------------------------------------------------------
# Properties
# --------------------------------------------------------------------------

BED_PRESETS = {
    "AD5M": (220.0, 220.0, 220.0),
    "A1": (256.0, 256.0, 256.0),
    "ENDER3V2": (220.0, 220.0, 250.0),
}


def _preset_update(self, context):
    if self.preset in BED_PRESETS:
        self.bed_x, self.bed_y, self.bed_z = BED_PRESETS[self.preset]


def _redraw_all(_self, context):
    try:
        for w in context.window_manager.windows:
            for a in w.screen.areas:
                a.tag_redraw()
    except Exception:
        pass


class SimpleMeshPrefs(AddonPreferences):
    bl_idname = PKG

    apply_on_startup: BoolProperty(
        name="Tidy Blender when it starts",
        description="On a new empty file: delete the default cube/camera/light, "
                    "switch to millimetres, hide scenery-style overlays and open the SimpleMesh tab",
        default=True)
    preset: EnumProperty(
        name="Printer",
        items=[("CUSTOM", "Custom", ""),
               ("AD5M", "FlashForge Adventurer 5M (220 mm)", ""),
               ("A1", "Bambu Lab A1 (256 mm)", ""),
               ("ENDER3V2", "Creality Ender 3 V2 (220 x 220 x 250)", "")],
        default="AD5M", update=_preset_update)
    bed_x: FloatProperty(name="Bed X (mm)", default=220.0, min=1.0)
    bed_y: FloatProperty(name="Bed Y (mm)", default=220.0, min=1.0)
    bed_z: FloatProperty(name="Max height (mm)", default=220.0, min=1.0)
    show_bed: BoolProperty(name="Draw the bed outline in the 3D view", default=True)
    simplify_screen: BoolProperty(
        name="One big 3D view (close timeline, outliner, properties)",
        description="On a new file, close the other editors and remove the animation / texturing / "
                    "sculpting workspace tabs. A 'Full Blender' tab stays as the way back",
        default=True)

    easy_start: BoolProperty(
        name="Start in Easy mode (picture buttons a child can use)",
        description="A new file opens with the big picture buttons on. The strip's Select button turns them off",
        default=True)

    show_deck: BoolProperty(
        name="Big-button panel across the top of the 3D view",
        description="The panel with the big red button, the tools and the look keys. "
                    "With it off, the tools are in the thin strip of Blender's own header",
        default=True, update=_redraw_all)

    def draw(self, context):
        lay = self.layout
        lay.prop(self, "apply_on_startup")
        lay.prop(self, "easy_start")
        lay.prop(self, "show_deck")
        lay.prop(self, "preset")
        row = lay.row()
        row.prop(self, "bed_x")
        row.prop(self, "bed_y")
        row.prop(self, "bed_z")
        lay.prop(self, "show_bed")
        lay.prop(self, "simplify_screen")
        lay.label(text="Printer sizes are from the makers' published specs; check yours.")


def _clay_mirror_update(self, context):
    ob = context.object
    if context.mode == "SCULPT" and ob is not None and ob.type == "MESH":
        _set(ob.data, "use_mirror_x", self.clay_mirror)
        _set(context.scene.tool_settings.sculpt, "use_symmetry_x", self.clay_mirror)


def _clay_detail_update(self, context):
    from . import clay
    clay._detail_update(self, context)


class SimpleMeshProps(PropertyGroup):
    scale_factor: FloatProperty(name="Factor", default=2.0, min=0.0001,
                                soft_max=1000.0, precision=4)
    fit_size: FloatProperty(name="Longest side (mm)", default=100.0, min=0.01,
                            soft_max=2000.0, precision=2)
    cut_axis: EnumProperty(name="Axis", default="Z",
                           items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z (height)", "")])
    cut_pos: FloatProperty(name="Position", default=50.0, min=0.0, max=100.0,
                           subtype="PERCENTAGE",
                           description="Where to cut, as a percentage along the chosen axis")
    cut_keep: EnumProperty(
        name="Keep", default="BOTH",
        items=[("BOTH", "Both halves (split)", ""),
               ("ABOVE", "Upper side only", ""),
               ("BELOW", "Lower side only", "")])
    decimate_ratio: FloatProperty(name="Keep", default=0.5, min=0.01, max=1.0,
                                  subtype="FACTOR")
    look: EnumProperty(
        name="Look", default="LUMINOUS", update=_look_update,
        items=[("LUMINOUS", "Luminous (dark, cyan)", ""),
               ("CLEAN", "Clean (light grey)", ""),
               ("DEFAULT", "Blender default", "")])
    show_flipped: BoolProperty(name="Show flipped faces (red)", default=False,
                               update=_flags_update,
                               description="Blue = outside faces, red = inside-out faces")
    show_xray: BoolProperty(name="See-through", default=False, update=_flags_update)
    show_edges: BoolProperty(name="Show the triangles", default=False, update=_flags_update,
                             description="Draw the edges of every triangle on the model")
    look_rainbow: BoolProperty(name="Rainbow: a colour for each model", default=False, update=_look_update,
                               description="Every model gets a colour of its own, to tell separate parts apart")
    gizmo_move: BoolProperty(name="Move arrows", default=False, update=_flags_update)
    gizmo_rotate: BoolProperty(name="Rotate rings", default=False, update=_flags_update)
    gizmo_scale: BoolProperty(name="Scale handles", default=False, update=_flags_update)

    hole_diameter: FloatProperty(name="Hole diameter (mm)", default=5.0, min=0.1, soft_max=100.0,
                                 precision=2)
    hole_depth: FloatProperty(name="Depth (mm, 0 = all the way through)", default=0.0, min=0.0,
                              precision=2)
    cut_faces_down: BoolProperty(name="Lay cut faces on the bed", default=False,
                                 description="After a cut, turn each piece so its cut face sits on the bed")
    show_dims: BoolProperty(name="Show size on the model", default=True)
    easy_on: BoolProperty(default=False)
    clay_mirror: BoolProperty(
        name="Mirror", default=False, update=_clay_mirror_update,
        description="Do the same on the left and the right side at once (good for faces and creatures)")
    clay_brush: StringProperty(default="pull")
    clay_for: StringProperty(default="")
    clay_detail: FloatProperty(
        name="Detail (mm)", default=1.0, min=0.05, soft_max=5.0, precision=2,
        update=_clay_detail_update,
        description="Size of the new triangles added under the brush. Smaller = finer clay, bigger file")
    last_dir: StringProperty(default="", subtype="DIR_PATH")
    chk_valid: BoolProperty(default=False)
    chk_name: StringProperty(default="")
    chk_tris: IntProperty(default=0)
    chk_open: IntProperty(default=0)
    chk_bad: IntProperty(default=0)
    chk_volume: FloatProperty(default=0.0)
    chk_area: FloatProperty(default=0.0)
    chk_inverted: BoolProperty(default=False)


# --------------------------------------------------------------------------
# Operators: file
# --------------------------------------------------------------------------

def raw_import_stl(path):
    try:
        bpy.ops.wm.stl_import(filepath=path)
    except AttributeError:
        bpy.ops.import_mesh.stl(filepath=path)


def raw_export_stl(path, selected_only):
    try:
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=selected_only,
                              ascii_format=False, apply_modifiers=True,
                              global_scale=1.0, use_scene_unit=False)
    except AttributeError:
        bpy.ops.export_mesh.stl(filepath=path, use_selection=selected_only,
                                global_scale=1.0, use_scene_unit=False,
                                ascii=False, use_mesh_modifiers=True)


class SIMPLEMESH_OT_import_stl(Operator, ImportHelper):
    """Import STL files at the right size: units converted to mm, oversized models
    shrunk to fit your bed, then centred on the bed and framed in the view"""
    bl_idname = "simplemesh.import_stl"
    bl_label = "Import STL"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".stl"
    filter_glob: StringProperty(default="*.stl", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement,
                              options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    units: EnumProperty(
        name="File units", default="MM",
        items=[("MM", "Millimetres (most STLs)", ""),
               ("CM", "Centimetres", ""),
               ("M", "Metres", ""),
               ("IN", "Inches", ""),
               ("UM", "Micrometres", "")])
    auto_fit: BoolProperty(
        name="Auto-fit to bed", default=True,
        description="Oversized models are divided by 10 until they fit the bed; "
                    "tiny ones (metres opened as mm) are multiplied by 1000")
    fit_size: FloatProperty(
        name="Or set longest side (mm)", default=0.0, min=0.0,
        description="0 = off. Overrides auto-fit")
    weld: BoolProperty(name="Join duplicate points", default=True)
    fresh: BoolProperty(name="Remove existing models first", default=False)

    def execute(self, context):
        ensure_object_mode(context)
        sc = context.scene
        paths = []
        if self.files:
            base = self.directory or os.path.dirname(self.filepath)
            paths = [os.path.join(base, f.name) for f in self.files if f.name]
        if not paths and self.filepath:
            paths = [self.filepath]
        if not paths:
            self.report({"ERROR"}, "No file chosen")
            return {"CANCELLED"}
        if self.fresh:
            for o in [o for o in sc.objects if o.type == "MESH"]:
                bpy.data.objects.remove(o, do_unlink=True)
        if not [o for o in sc.objects if o.type == "MESH"] and not units_are_mm(sc):
            ensure_mm_units(sc)
        p = prefs(context)
        bed_max = max(p.bed_x, p.bed_y, p.bed_z)

        new_objs, notes = [], []
        for path in paths:
            before = {o.name for o in bpy.data.objects}
            try:
                raw_import_stl(path)
            except Exception as ex:  # noqa: BLE001
                self.report({"ERROR"}, "Could not read %s: %s" % (os.path.basename(path), ex))
                continue
            made = [o for o in bpy.data.objects if o.name not in before and o.type == "MESH"]
            for o in made:
                unparent(o)
                o.matrix_basis = Matrix.Scale(UNIT_TO_MM[self.units], 4) @ o.matrix_basis
                bake(o)
                lo, hi = obj_bounds(o)
                longest = max(hi - lo)
                f, why = 1.0, ""
                if self.fit_size > 0 and longest > 0:
                    f = self.fit_size / longest
                    why = "set to %g mm" % self.fit_size
                elif self.auto_fit:
                    f = auto_factor(longest, bed_max)
                    if abs(f - 1.0) > 1e-9:
                        why = "auto-scaled x%g (was %.4g mm long)" % (f, longest)
                if abs(f - 1.0) > 1e-9:
                    o.matrix_basis = Matrix.Scale(f, 4) @ o.matrix_basis
                    bake(o)
                if self.weld:
                    weld_mesh(o.data)
                    bake(o)
                if why:
                    notes.append("%s: %s" % (o.name, why))
                shade_nicely(o.data)
                # its colour where each model shows its own (Easy mode): the look's colour, not plain white
                o.color = (0.0, 0.85, 1.0, 1.0) if sc.simplemesh.look == "LUMINOUS" else (0.62, 0.70, 0.80, 1.0)
                new_objs.append(o)
            sc.simplemesh.last_dir = os.path.dirname(path)
        if not new_objs:
            return {"CANCELLED"}

        dims = [obj_bounds(o)[1] - obj_bounds(o)[0] for o in new_objs]
        total = sum(d.x for d in dims) + GAP_MM * (len(dims) - 1)
        x = -total / 2.0
        for o, d in zip(new_objs, dims):
            o.location = Vector((x + d.x / 2.0, 0.0, d.z / 2.0))
            x += d.x + GAP_MM
        refresh(context)
        select_only(context, new_objs)
        store_check(context, new_objs[-1])
        frame_model(context)
        d = dims[-1]
        msg = "%s: %.1f x %.1f x %.1f mm" % (new_objs[-1].name, d.x, d.y, d.z)
        if notes:
            msg += "  |  " + "; ".join(notes)
        self.report({"INFO"}, msg)
        return {"FINISHED"}

    def draw(self, context):
        lay = self.layout
        lay.prop(self, "units")
        lay.prop(self, "auto_fit")
        lay.prop(self, "fit_size")
        lay.prop(self, "weld")
        lay.prop(self, "fresh")


class SIMPLEMESH_OT_export_stl(Operator, ExportHelper):
    """Export the selected models (or all of them) as a binary STL in millimetres"""
    bl_idname = "simplemesh.export_stl"
    bl_label = "Export STL"

    filename_ext = ".stl"
    filter_glob: StringProperty(default="*.stl", options={"HIDDEN"})

    def invoke(self, context, event):
        ob = context.object
        base = (ob.name if ob else "model").replace(" ", "_")
        d = context.scene.simplemesh.last_dir
        self.filepath = os.path.join(d, base + "_edited.stl") if d else base + "_edited.stl"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        ensure_object_mode(context)
        objs = mesh_objects(context)
        if not objs:
            objs = [o for o in context.view_layer.objects if o.type == "MESH" and o.visible_get()]
        if not objs:
            self.report({"ERROR"}, "Nothing to export")
            return {"CANCELLED"}
        # export exactly these objects
        select_only(context, objs)
        raw_export_stl(self.filepath, True)
        self.report({"INFO"}, "Saved %d model(s) to %s" % (len(objs), self.filepath))
        return {"FINISHED"}


class SIMPLEMESH_OT_frame(Operator):
    """Centre the view on the selected model (or everything) and fix the clipping.
    Shortcut: F"""
    bl_idname = "simplemesh.frame"
    bl_label = "Frame model"

    everything: BoolProperty(default=False, options={"SKIP_SAVE"})

    def execute(self, context):
        frame_model(context, everything=self.everything)
        return {"FINISHED"}


# --------------------------------------------------------------------------
# Operators: size and placement
# --------------------------------------------------------------------------

def _scale_group(context, objs, factor):
    lo, hi = group_bounds(objs)
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))   # bottom centre
    transform_group(objs, about(pivot, Matrix.Scale(factor, 4)))
    refresh(context)
    frame_model(context)


class SIMPLEMESH_OT_scale_by(Operator):
    """Scale the selected models by a factor, keeping them on the bed, then re-centre the view"""
    bl_idname = "simplemesh.scale_by"
    bl_label = "Scale"
    bl_options = {"REGISTER", "UNDO"}

    factor: FloatProperty(name="Factor", default=1.0, min=1e-6, precision=4)

    def execute(self, context):
        ensure_object_mode(context)
        objs = targets(context)
        if not objs:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        _scale_group(context, objs, self.factor)
        lo, hi = group_bounds(objs)
        d = hi - lo
        self.report({"INFO"}, "Now %.1f x %.1f x %.1f mm" % (d.x, d.y, d.z))
        return {"FINISHED"}


class SIMPLEMESH_OT_fit_longest(Operator):
    """Scale so the longest side is exactly this many millimetres"""
    bl_idname = "simplemesh.fit_longest"
    bl_label = "Fit"
    bl_options = {"REGISTER", "UNDO"}

    size: FloatProperty(name="Longest side (mm)", default=100.0, min=0.01)

    def execute(self, context):
        ensure_object_mode(context)
        objs = targets(context)
        if not objs:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        lo, hi = group_bounds(objs)
        longest = max(hi - lo)
        if longest <= 0:
            self.report({"ERROR"}, "Model has no size")
            return {"CANCELLED"}
        _scale_group(context, objs, self.size / longest)
        return {"FINISHED"}


class SIMPLEMESH_OT_place(Operator):
    """Put the selected models flat on the bed, optionally centred on it"""
    bl_idname = "simplemesh.place"
    bl_label = "Place on bed"
    bl_options = {"REGISTER", "UNDO"}

    center: BoolProperty(name="Centre on bed", default=False)

    def execute(self, context):
        ensure_object_mode(context)
        objs = targets(context)
        if not objs:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        for o in objs:
            unparent(o)
        lo, hi = group_bounds(objs)
        d = Vector((0.0, 0.0, -lo.z))
        if self.center:
            d.x = -(lo.x + hi.x) / 2.0
            d.y = -(lo.y + hi.y) / 2.0
        for o in objs:
            o.location = o.location + d
        refresh(context)
        frame_model(context)
        return {"FINISHED"}


class SIMPLEMESH_OT_rotate90(Operator):
    """Rotate the selection in 90 degree steps about its centre, then drop it on the bed"""
    bl_idname = "simplemesh.rotate90"
    bl_label = "Rotate 90"
    bl_options = {"REGISTER", "UNDO"}

    axis: EnumProperty(items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")], default="Z")
    angle: FloatProperty(default=90.0)

    def execute(self, context):
        ensure_object_mode(context)
        objs = targets(context)
        if not objs:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        for o in objs:
            unparent(o)
        lo, hi = group_bounds(objs)
        c = (lo + hi) / 2.0
        rot = Matrix.Rotation(math.radians(self.angle), 4, self.axis)
        transform_group(objs, about(c, rot))
        lo, hi = group_bounds(objs)
        for o in objs:
            o.location = o.location + Vector((0.0, 0.0, -lo.z))
        refresh(context)
        frame_model(context)
        return {"FINISHED"}


class SIMPLEMESH_OT_mirror(Operator):
    """Mirror the selection across its own centre"""
    bl_idname = "simplemesh.mirror"
    bl_label = "Mirror"
    bl_options = {"REGISTER", "UNDO"}

    axis: EnumProperty(items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")], default="X")

    def execute(self, context):
        ensure_object_mode(context)
        objs = targets(context)
        if not objs:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        for o in objs:
            unparent(o)
        lo, hi = group_bounds(objs)
        c = (lo + hi) / 2.0
        s = [1.0, 1.0, 1.0]
        s[AXES[self.axis]] = -1.0
        m = Matrix.Diagonal((s[0], s[1], s[2], 1.0))
        transform_group(objs, about(c, m))
        refresh(context)
        return {"FINISHED"}


def lay_on_normal(context, ob, normal_world):
    """Turn the object so this world-space direction points down, then rest it on the bed."""
    unparent(ob)
    rot = normal_world.normalized().rotation_difference(Vector((0.0, 0.0, -1.0))).to_matrix().to_4x4()
    lo, hi = obj_bounds(ob)
    transform_group([ob], about((lo + hi) / 2.0, rot))
    lo, hi = obj_bounds(ob)
    ob.location = ob.location + Vector((0.0, 0.0, -lo.z))
    refresh(context)


class SIMPLEMESH_OT_lay_flat(Operator):
    """Lay the selected model on its largest flat face"""
    bl_idname = "simplemesh.lay_flat"
    bl_label = "Auto lay flat"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_object_mode(context)
        objs = targets(context)
        if not objs:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        for ob in objs:
            normal = largest_flat_normal(ob)
            if normal is None:
                continue
            unparent(ob)
            lay_on_normal(context, ob, ob.matrix_basis.to_3x3() @ normal)
        frame_model(context)
        return {"FINISHED"}


# --------------------------------------------------------------------------
# Operators: cut, combine, shapes
# --------------------------------------------------------------------------

def cut_plane(obj, co_world, no_world, keep):
    """Cut obj with the plane through co_world facing no_world and cap the cut.
    keep: ABOVE keeps the side the normal points to, BELOW the other. True on success."""
    bake(obj)
    no = no_world.normalized()
    co = co_world - obj.location          # baked: local = world - location
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    res = bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-5, plane_co=co, plane_no=no,
                                 clear_inner=(keep == "ABOVE"),
                                 clear_outer=(keep == "BELOW"))
    cut_edges = [e for e in res["geom_cut"]
                 if isinstance(e, bmesh.types.BMEdge) and e.is_valid and len(e.link_faces) == 1]
    if not cut_edges or not bm.faces:
        bm.free()
        return False
    try:
        bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=cut_edges)
    except Exception:
        try:
            bmesh.ops.holes_fill(bm, edges=cut_edges, sides=0)
        except Exception:
            pass
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    bake(obj)
    return True


def cut_object(context, obj, axis, pct, keep):
    """Cut at a percentage along a world axis (kept for the numeric panel)."""
    bake(obj)
    idx = AXES[axis]
    lo, hi = obj_bounds(obj)
    co = (lo + hi) / 2.0
    co[idx] = lo[idx] + (hi[idx] - lo[idx]) * pct / 100.0
    no = Vector((0.0, 0.0, 0.0))
    no[idx] = 1.0
    return cut_plane(obj, co, no, keep)


def split_model(context, obj, co_world, no_world, keep="BOTH", faces_down=False):
    """Cut one model. keep BOTH makes two models side by side on the bed.
    Returns the list of resulting objects, or [] if the plane missed."""
    no = no_world.normalized()
    parts = []
    if keep == "BOTH":
        dup = obj.copy()
        dup.data = obj.data.copy()
        for c in obj.users_collection:
            c.objects.link(dup)
        dup.name = obj.name + "_b"
        ok1 = cut_plane(obj, co_world, no, "BELOW")
        ok2 = cut_plane(dup, co_world, no, "ABOVE")
        if not (ok1 and ok2):
            old = dup.data
            bpy.data.objects.remove(dup, do_unlink=True)
            if old.users == 0:
                bpy.data.meshes.remove(old)
            return []
        parts = [(obj, no), (dup, -no)]      # (piece, outward normal of its cut face)
    else:
        if not cut_plane(obj, co_world, no, keep):
            return []
        parts = [(obj, no if keep == "BELOW" else -no)]
    for part, cut_normal in parts:
        if faces_down:
            lay_on_normal(context, part, cut_normal)
        lo, _hi = obj_bounds(part)
        part.location = part.location + Vector((0.0, 0.0, -lo.z))
    refresh(context)
    if len(parts) == 2:
        a, b = parts[0][0], parts[1][0]
        _lo1, hi1 = obj_bounds(a)
        lo2, _hi2 = obj_bounds(b)
        b.location = b.location + Vector((hi1.x + GAP_MM - lo2.x, 0.0, 0.0))
        refresh(context)
    return [pp[0] for pp in parts]


class SIMPLEMESH_OT_cut(Operator):
    """Slice the selected models at the position set in the panel, and cap the cut"""
    bl_idname = "simplemesh.cut"
    bl_label = "Cut"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_object_mode(context)
        sm = context.scene.simplemesh
        objs = targets(context)
        if not objs:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        made = []
        idx = AXES[sm.cut_axis]
        for o in objs:
            bake(o)
            lo, hi = obj_bounds(o)
            co = (lo + hi) / 2.0
            co[idx] = lo[idx] + (hi[idx] - lo[idx]) * sm.cut_pos / 100.0
            no = Vector((0.0, 0.0, 0.0))
            no[idx] = 1.0
            got = split_model(context, o, co, no, sm.cut_keep, sm.cut_faces_down)
            if not got:
                self.report({"ERROR"}, "The cut plane does not pass through %s" % o.name)
                return {"CANCELLED"}
            made += got
        select_only(context, made)
        frame_model(context)
        return {"FINISHED"}


def region_vertices(bm, faces):
    """Indices of the vertices used by a set of face indices of a bmesh."""
    out = set()
    for i in faces:
        for v in bm.faces[i].verts:
            out.add(v.index)
    return sorted(out)


def offset_vertices(me, indices, origin_cos, direction, distance):
    """Move vertices to origin + direction * distance (local space) and refresh the mesh."""
    step = direction * distance
    vs = me.vertices
    for i, co in zip(indices, origin_cos):
        vs[i].co = co + step
    me.update()


def pull_face(obj, face_index, distance, tol_deg=3.0):
    """Push/pull the flat face containing polygon face_index by distance mm along
    its own direction (positive = outwards). Returns the number of faces moved."""
    from .interactive import flat_region
    bake(obj)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    faces, normal, _c = flat_region(bm, face_index, tol_deg)
    idx = region_vertices(bm, faces) if normal is not None else []
    bm.free()
    if not idx:
        return 0
    cos = [obj.data.vertices[i].co.copy() for i in idx]
    offset_vertices(obj.data, idx, cos, normal, distance)
    bake(obj)
    return len(faces)


def refine_mesh(me, max_edge, budget=150000, passes=12, seconds=6.0):
    """Split every edge longer than max_edge (mm) until none is left, the triangle
    budget is reached or the time is up. Only adds points on existing faces, so the
    shape is exactly unchanged. The budget is a real limit: when a pass would go
    over it, only the longest edges are split. Returns the triangle count."""
    t0 = time.time()
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3])
    lim2 = max_edge * max_edge
    for _p in range(passes):
        room = (budget - len(bm.faces)) // 3          # a split edge adds two or three triangles
        if room <= 0 or time.time() - t0 > seconds:
            break
        long_edges = []
        for e in bm.edges:
            d2 = (e.verts[0].co - e.verts[1].co).length_squared
            if d2 > lim2:
                long_edges.append((d2, e))
        if not long_edges:
            break
        if len(long_edges) > room:
            long_edges.sort(key=lambda t: t[0], reverse=True)
            del long_edges[room:]
        bmesh.ops.subdivide_edges(bm, edges=[t[1] for t in long_edges], cuts=1, use_grid_fill=True)
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3])
    n = len(bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return n


def tidy_flat(context, obj, angle_deg=0.5):
    """Merge the triangles of perfectly flat areas back into a few big ones
    (undoes refine_mesh where nothing was moulded). The result is kept only if
    the model is still closed; otherwise the mesh is left as it was.
    Returns (triangles before, triangles after)."""
    before = compute_check(obj)
    backup = obj.data.copy()

    def setup(ob):
        m = ob.modifiers.new("SimpleMeshTidy", "DECIMATE")
        m.decimate_type = "DISSOLVE"
        m.angle_limit = math.radians(angle_deg)
        _set(m, "use_dissolve_boundaries", False)
        return m
    try:
        eval_replace(context, obj, setup)
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
        after = compute_check(obj)
        vol_ok = abs(after["volume"] - before["volume"]) <= 1e-3 * max(before["volume"], 1.0)
        good = (after["open"] <= before["open"] and after["bad"] <= before["bad"]
                and after["inverted"] == before["inverted"] and vol_ok)
    except Exception:
        good = False
        after = before
    if not good:
        old = obj.data
        name = old.name
        obj.data = backup
        if old.users == 0:
            bpy.data.meshes.remove(old)
        backup.name = name
        return before["tris"], before["tris"]
    bpy.data.meshes.remove(backup)
    return before["tris"], after["tris"]


def drill_hole(context, obj, point, direction, diameter, depth=0.0, segments=64):
    """Cut a round hole into obj at a world point, going along direction.
    depth 0 = right through."""
    d = direction.normalized()
    lo, hi = obj_bounds(obj)
    length = (hi - lo).length + 4.0 if depth <= 0 else depth + 1.0
    bm = bmesh.new()
    try:
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                              radius1=diameter / 2.0, radius2=diameter / 2.0, depth=length)
    except TypeError:
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                              diameter1=diameter / 2.0, diameter2=diameter / 2.0, depth=length)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    cutter = new_mesh_object(context, "SimpleMeshDrill", bm)
    rot = Vector((0.0, 0.0, 1.0)).rotation_difference(d).to_matrix().to_4x4()
    start = point - d * 1.0                      # begin 1 mm outside the surface
    cutter.matrix_basis = Matrix.Translation(start + d * (length / 2.0)) @ rot
    bake(obj)
    refresh(context)

    def setup(ob):
        m = ob.modifiers.new("SimpleMeshDrill", "BOOLEAN")
        m.operation = "DIFFERENCE"
        m.object = cutter
        _set(m, "solver", "EXACT")
        return m
    try:
        eval_replace(context, obj, setup)
    finally:
        old = cutter.data
        bpy.data.objects.remove(cutter, do_unlink=True)
        if old.users == 0:
            bpy.data.meshes.remove(old)
    bake(obj)
    refresh(context)


def split_loose(context, obj):
    """Separate a model into its unconnected pieces. Returns all resulting objects."""
    bake(obj)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    seen = set()
    islands = []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, isl = [v], []
        seen.add(v.index)
        while stack:
            cur = stack.pop()
            isl.append(cur.index)
            for e in cur.link_edges:
                o2 = e.other_vert(cur)
                if o2.index not in seen:
                    seen.add(o2.index)
                    stack.append(o2)
        islands.append(set(isl))
    bm.free()
    if len(islands) < 2:
        return [obj]
    out = []
    for k, isl in enumerate(islands):
        part = obj if k == 0 else obj.copy()
        if k:
            part.data = obj.data.copy()
            for c in obj.users_collection:
                c.objects.link(part)
        out.append((part, isl))
    for part, isl in out:
        b2 = bmesh.new()
        b2.from_mesh(part.data)
        kill = [v for v in b2.verts if v.index not in isl]
        bmesh.ops.delete(b2, geom=kill, context="VERTS")
        b2.to_mesh(part.data)
        b2.free()
        part.data.update()
    res = [pp[0] for pp in out]
    for part in res:
        bake(part)
    refresh(context)
    return res


class SIMPLEMESH_OT_combine(Operator):
    """Combine models. The ACTIVE (last clicked) model is the base; the other
    selected models are the tools. Union adds, Subtract cuts them out of the base,
    Intersect keeps only where they overlap, Join just merges without boolean maths"""
    bl_idname = "simplemesh.combine"
    bl_label = "Combine"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(items=[("JOIN", "Join", ""), ("UNION", "Union", ""),
                              ("DIFFERENCE", "Subtract", ""),
                              ("INTERSECT", "Intersect", "")], default="UNION")

    def execute(self, context):
        ensure_object_mode(context)
        base = context.object
        if base is None or base.type != "MESH":
            self.report({"ERROR"}, "Click the base model last (it becomes the active one)")
            return {"CANCELLED"}
        tools = [o for o in mesh_objects(context) if o is not base]
        if not tools:
            self.report({"ERROR"}, "Select at least two models; the last one clicked is the base")
            return {"CANCELLED"}
        bake(base)
        for t in tools:
            bake(t)
        refresh(context)
        for t in tools:
            if self.mode == "JOIN":
                me2 = t.data.copy()
                me2.transform(base.matrix_basis.inverted() @ t.matrix_basis)
                bm = bmesh.new()
                bm.from_mesh(base.data)
                bm.from_mesh(me2)
                bm.to_mesh(base.data)
                bm.free()
                bpy.data.meshes.remove(me2)
                base.data.update()
            else:
                def setup(ob, tool=t):
                    m = ob.modifiers.new("SimpleMeshBool", "BOOLEAN")
                    m.operation = self.mode
                    m.object = tool
                    _set(m, "solver", "EXACT")
                    return m
                eval_replace(context, base, setup)
            old = t.data
            bpy.data.objects.remove(t, do_unlink=True)
            if old.users == 0:
                bpy.data.meshes.remove(old)
        bake(base)
        refresh(context)
        select_only(context, [base])
        frame_model(context)
        return {"FINISHED"}


class SIMPLEMESH_OT_add_shape(Operator):
    """Add a simple solid, sized in mm. Use it as a cutter (Combine > Subtract) or a block"""
    bl_idname = "simplemesh.add_shape"
    bl_label = "Add shape"
    bl_options = {"REGISTER", "UNDO"}

    shape: EnumProperty(items=[("BLOCK", "Block", ""), ("CYLINDER", "Cylinder", ""),
                               ("SPHERE", "Sphere", ""), ("CONE", "Cone", "")],
                        default="BLOCK")
    size_x: FloatProperty(name="Width X (mm)", default=20.0, min=0.01)
    size_y: FloatProperty(name="Depth Y (mm)", default=20.0, min=0.01)
    size_z: FloatProperty(name="Height Z (mm)", default=20.0, min=0.01)
    segments: IntProperty(name="Smoothness", default=48, min=8, max=256)
    at_model: BoolProperty(name="Centre inside the selected model", default=True)

    def execute(self, context):
        ensure_object_mode(context)
        bm = bmesh.new()
        n = self.segments
        if self.shape == "BLOCK":
            bmesh.ops.create_cube(bm, size=1.0)
        elif self.shape == "SPHERE":
            try:
                bmesh.ops.create_uvsphere(bm, u_segments=n, v_segments=max(n // 2, 4), radius=0.5)
            except TypeError:
                bmesh.ops.create_uvsphere(bm, u_segments=n, v_segments=max(n // 2, 4), diameter=0.5)
        else:
            r2 = 0.0 if self.shape == "CONE" else 0.5
            try:
                bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=n,
                                      radius1=0.5, radius2=r2, depth=1.0)
            except TypeError:
                bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=n,
                                      diameter1=0.5, diameter2=r2, depth=1.0)
        xs = [[v.co[k] for v in bm.verts] for k in range(3)]
        lo = [min(c) for c in xs]
        hi = [max(c) for c in xs]
        size = (self.size_x, self.size_y, self.size_z)
        for v in bm.verts:
            v.co = Vector([((v.co[k] - (lo[k] + hi[k]) / 2.0) / ((hi[k] - lo[k]) or 1.0)) * size[k]
                           for k in range(3)])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        ob = new_mesh_object(context, self.shape.title(), bm)
        sel = [o for o in mesh_objects(context)]
        if self.at_model and sel:
            lo2, hi2 = group_bounds(sel)
            ob.location = (lo2 + hi2) / 2.0
        else:
            ob.location = Vector((0.0, 0.0, self.size_z / 2.0))
        refresh(context)
        select_only(context, [ob])
        frame_model(context)
        return {"FINISHED"}


def is_hole(ob):
    return bool(ob.get("sm_hole", 0))


def set_hole(ob, flag):
    if flag:
        ob["sm_hole"] = 1
        ob.display_type = "WIRE"
        _set(ob, "show_in_front", True)
        ob.color = (1.0, 0.25, 0.2, 1.0)
    else:
        if "sm_hole" in ob:
            del ob["sm_hole"]
        ob.display_type = "TEXTURED"
        _set(ob, "show_in_front", False)
        ob.color = (1.0, 1.0, 1.0, 1.0)


def _overlap(a, b):
    (alo, ahi), (blo, bhi) = obj_bounds(a), obj_bounds(b)
    return all(alo[k] <= bhi[k] and blo[k] <= ahi[k] for k in range(3))


def _boolean(context, base, tool, op):
    def setup(ob):
        m = ob.modifiers.new("SimpleMeshBool", "BOOLEAN")
        m.operation = op
        m.object = tool
        _set(m, "solver", "EXACT")
        return m
    eval_replace(context, base, setup)


def _remove(ob):
    old = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    if old.users == 0:
        bpy.data.meshes.remove(old)


class SIMPLEMESH_OT_mark_hole(Operator):
    """Turn the selected shapes into HOLES (shown as red wire). Holes are cut out of
    every model they touch when you press 'Cut the holes out'. Press again to undo"""
    bl_idname = "simplemesh.mark_hole"
    bl_label = "Make it a hole"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_object_mode(context)
        objs = targets(context)
        if not objs:
            self.report({"ERROR"}, "Select a shape first")
            return {"CANCELLED"}
        flag = not all(is_hole(o) for o in objs)
        for o in objs:
            set_hole(o, flag)
        return {"FINISHED"}


class SIMPLEMESH_OT_apply_holes(Operator):
    """Cut every red hole shape out of the models it touches, then remove the hole shapes"""
    bl_idname = "simplemesh.apply_holes"
    bl_label = "Cut the holes out"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_object_mode(context)
        meshes = [o for o in context.view_layer.objects if o.type == "MESH" and o.visible_get()]
        holes = [o for o in meshes if is_hole(o)]
        solids = [o for o in meshes if not is_hole(o)]
        if not holes:
            self.report({"ERROR"}, "No holes yet: select a shape and press 'Make it a hole'")
            return {"CANCELLED"}
        for o in holes + solids:
            bake(o)
        refresh(context)
        n = 0
        for h in holes:
            for sld in solids:
                if _overlap(h, sld):
                    _boolean(context, sld, h, "DIFFERENCE")
                    bake(sld)
                    n += 1
        for h in holes:
            _remove(h)
        refresh(context)
        select_only(context, solids)
        self.report({"INFO"}, "%d hole(s) cut" % n)
        return {"FINISHED"}


class SIMPLEMESH_OT_weld(Operator):
    """Weld all the selected models into one solid (order does not matter)"""
    bl_idname = "simplemesh.weld"
    bl_label = "Weld together"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_object_mode(context)
        objs = [o for o in mesh_objects(context) if not is_hole(o)]
        if len(objs) < 2:
            self.report({"ERROR"}, "Select two or more models (Shift+click)")
            return {"CANCELLED"}
        base = context.object if context.object in objs else objs[0]
        for o in objs:
            bake(o)
        refresh(context)
        for t in [o for o in objs if o is not base]:
            _boolean(context, base, t, "UNION")
            _remove(t)
        bake(base)
        refresh(context)
        select_only(context, [base])
        return {"FINISHED"}


class SIMPLEMESH_OT_split_loose(Operator):
    """Split a model made of several unconnected pieces into separate models"""
    bl_idname = "simplemesh.split_loose"
    bl_label = "Separate loose pieces"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_object_mode(context)
        objs = targets(context)
        if not objs:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        res = []
        for o in objs:
            res += split_loose(context, o)
        select_only(context, res)
        self.report({"INFO"}, "%d piece(s)" % len(res))
        return {"FINISHED"}


class SIMPLEMESH_OT_delete(Operator):
    """Delete the selected models"""
    bl_idname = "simplemesh.delete"
    bl_label = "Delete"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_object_mode(context)
        objs = mesh_objects(context)
        for o in objs:
            _remove(o)
        return {"FINISHED"} if objs else {"CANCELLED"}


class SIMPLEMESH_OT_duplicate(Operator):
    """Make a copy of the selected models, placed beside the originals"""
    bl_idname = "simplemesh.duplicate"
    bl_label = "Copy"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_object_mode(context)
        objs = targets(context)
        if not objs:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        for o in objs:
            unparent(o)
        lo, hi = group_bounds(objs)
        new = []
        for o in objs:
            d = o.copy()
            d.data = o.data.copy()
            for c in o.users_collection:
                c.objects.link(d)
            d.location = d.location + Vector((hi.x - lo.x + GAP_MM, 0.0, 0.0))
            new.append(d)
        refresh(context)
        select_only(context, new)
        frame_model(context, everything=True)
        return {"FINISHED"}


# --------------------------------------------------------------------------
# Operators: repair, check, simplify
# --------------------------------------------------------------------------

class SIMPLEMESH_OT_repair(Operator):
    """One-click clean-up: join duplicate points, remove loose bits, fill holes,
    triangulate and point every face outwards"""
    bl_idname = "simplemesh.repair"
    bl_label = "Repair"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_object_mode(context)
        objs = targets(context)
        if not objs:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        msgs = []
        for o in objs:
            bake(o)
            bo, bb, ao, ab = repair_mesh(o.data)
            msgs.append("%s: open edges %d -> %d, bad edges %d -> %d" % (o.name, bo, ao, bb, ab))
            bake(o)
        store_check(context, objs[-1])
        self.report({"INFO"}, "; ".join(msgs))
        return {"FINISHED"}


class SIMPLEMESH_OT_check(Operator):
    """Measure triangles, volume and surface area and look for holes"""
    bl_idname = "simplemesh.check"
    bl_label = "Check"

    def execute(self, context):
        ensure_object_mode(context)
        ob = context.object
        if ob is None or ob.type != "MESH":
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        store_check(context, ob)
        return {"FINISHED"}


class SIMPLEMESH_OT_simplify(Operator):
    """Reduce the triangle count (smaller files, faster slicing)"""
    bl_idname = "simplemesh.simplify"
    bl_label = "Simplify"
    bl_options = {"REGISTER", "UNDO"}

    ratio: FloatProperty(name="Keep", default=0.5, min=0.01, max=1.0, subtype="FACTOR")

    def execute(self, context):
        ensure_object_mode(context)
        objs = targets(context)
        if not objs:
            self.report({"ERROR"}, "Select a model first")
            return {"CANCELLED"}
        for o in objs:
            bake(o)
            before = len(o.data.polygons)

            def setup(ob):
                m = ob.modifiers.new("SimpleMeshDecimate", "DECIMATE")
                m.decimate_type = "COLLAPSE"
                m.ratio = self.ratio
                _set(m, "use_collapse_triangulate", True)
                return m
            eval_replace(context, o, setup)
            bake(o)
            self.report({"INFO"}, "%s: %d -> %d triangles" % (o.name, before, len(o.data.polygons)))
        store_check(context, objs[-1])
        return {"FINISHED"}


# --------------------------------------------------------------------------
# Operators: workspace
# --------------------------------------------------------------------------

class SIMPLEMESH_OT_setup(Operator):
    """Tidy this Blender window for STL work: millimetres, no scenery overlays,
    big clip range, the SimpleMesh tab open"""
    bl_idname = "simplemesh.setup"
    bl_label = "Tidy workspace"

    def execute(self, context):
        ensure_mm_units(context.scene)
        closed = simplify_screen(context) if getattr(prefs(context), "simplify_screen", True) else 0

        def later():
            try:
                declutter_viewports(bpy.context)
                apply_look(bpy.context)
                apply_view_flags(bpy.context)
                frame_model(bpy.context, everything=True)
            except Exception:
                pass
            return None
        if closed and not bpy.app.background:
            bpy.app.timers.register(later, first_interval=0.4)   # see ui.tidy_new_file
        else:
            later()
        self.report({"INFO"}, "Scene is now in millimetres (1 unit = 1 mm)")
        return {"FINISHED"}


class SIMPLEMESH_OT_easy_nav(Operator):
    """Laptop-friendly navigation (changes your Blender preferences)"""
    bl_idname = "simplemesh.easy_nav"
    bl_label = "Easy navigation"

    def execute(self, context):
        done = easy_navigation(context)
        self.report({"INFO"}, "Alt+left-drag orbits, zoom goes to the pointer, number row = views "
                              "(%d settings changed)" % len(done))
        return {"FINISHED"}


class SIMPLEMESH_OT_view(Operator):
    """Snap the view to a standard direction and re-centre on the model"""
    bl_idname = "simplemesh.view"
    bl_label = "View"

    direction: EnumProperty(items=[("TOP", "Top", ""), ("FRONT", "Front", ""),
                                   ("RIGHT", "Right", ""), ("LEFT", "Left", ""),
                                   ("BACK", "Back", ""), ("BOTTOM", "Bottom", "")],
                            default="FRONT")

    def execute(self, context):
        view_op(context, "view_axis", type=self.direction)
        frame_model(context)
        return {"FINISHED"}


class SIMPLEMESH_OT_toggle_persp(Operator):
    """Switch between perspective and orthographic"""
    bl_idname = "simplemesh.toggle_persp"
    bl_label = "Perspective / Ortho"

    def execute(self, context):
        view_op(context, "view_persportho")
        return {"FINISHED"}


class SIMPLEMESH_OT_maximize(Operator):
    """Toggle a full-window 3D view, hiding the other editors"""
    bl_idname = "simplemesh.maximize"
    bl_label = "Maximise 3D view"

    def execute(self, context):
        try:
            bpy.ops.screen.screen_full_area(use_hide_panels=False)
        except Exception:
            self.report({"WARNING"}, "Could not toggle the full-window view here")
        return {"FINISHED"}


def problem_report(context):
    """Plain-text description of this Blender, the scene and anything that went
    wrong, for pasting into a bug report. No file contents, no typed text."""
    import platform
    import sys
    from .version import __build_date__, __version__
    out = []

    def add(label, fn):
        try:
            out.append("%s: %s" % (label, fn()))
        except Exception as ex:  # noqa: BLE001
            out.append("%s: ? (%s)" % (label, ex))

    out.append("SimpleMesh %s (built %s)" % (__version__, __build_date__))
    add("Blender", lambda: "%s  %s  %s" % (bpy.app.version_string, getattr(bpy.app, "build_date", b"").decode("ascii", "replace")
                                           if isinstance(getattr(bpy.app, "build_date", ""), bytes) else getattr(bpy.app, "build_date", ""),
                                           bpy.app.binary_path))
    add("System", lambda: "%s | Python %s" % (platform.platform(), sys.version.split()[0]))

    def gpu_line():
        import gpu
        bits = [gpu.platform.vendor_get(), gpu.platform.renderer_get(), gpu.platform.version_get()]
        if hasattr(gpu.platform, "backend_type_get"):
            bits.append(gpu.platform.backend_type_get())
        return " | ".join(bits)
    add("Graphics", gpu_line)
    add("numpy", lambda: "yes" if np is not None else "NO (fallback code)")
    add("Screen", lambda: "; ".join(
        "window %dx%d: %s" % (w.width, w.height, ", ".join("%s %dx%d" % (a.type, a.width, a.height) for a in w.screen.areas))
        for w in context.window_manager.windows))
    add("Interface scale", lambda: "%.2f (pixel size %s)" % (context.preferences.system.ui_scale,
                                                             getattr(context.preferences.system, "pixel_size", "?")))
    add("Workspace", lambda: context.window.workspace.name if context.window else "?")
    add("Mode", lambda: context.mode)

    def obj_line():
        ob = context.object
        if ob is None:
            return "none"
        txt = "%s (%s)" % (ob.name, ob.type)
        if ob.type == "MESH":
            lo, hi = obj_bounds(ob)
            d = hi - lo
            txt += ", %s triangles, %.1f x %.1f x %.1f mm, scale %s" % (
                format(len(ob.data.polygons), ","), d.x, d.y, d.z, tuple(round(v, 4) for v in ob.scale))
        return txt
    add("Active model", obj_line)
    add("Models", lambda: "%d meshes, %d selected" % (
        sum(1 for o in context.view_layer.objects if o.type == "MESH"), len(context.selected_objects)))
    add("Units", lambda: "%s, scale %g" % (context.scene.unit_settings.length_unit, context.scene.unit_settings.scale_length))

    def tool_line():
        from . import interactive
        a = interactive.ACTIVE
        return "%s%s" % (a["name"] or "none", "" if a["token"] is not None else " (not running)")
    add("SimpleMesh tool", tool_line)

    def clay_line():
        from . import clay
        sc = context.scene.tool_settings.sculpt
        br = sc.brush
        ups = clay.unified(context)
        so = context.sculpt_object
        bits = ["brush %s (%s)" % (br.name if br else None, clay.brush_type(br)),
                "wanted %s" % context.scene.simplemesh.clay_brush,
                "set up for %r" % clay._ready["name"],
                "automatic detail %s" % (so.use_dynamic_topology_sculpting if so else "-")]
        if ups is not None:
            name, _k = clay.size_prop(ups)
            bits.append("size %s=%s px=%s lock=%s strength=%.2f" % (
                name, round(getattr(ups, name), 3) if name else "?", getattr(ups, "size", "?"),
                getattr(ups, "use_locked_size", "?"), ups.strength))
        return ", ".join(bits)
    add("Clay", clay_line)

    def deck_line():
        from . import deck
        on = deck.shown(context)
        keepers = sum(1 for w in context.window_manager.windows if w.as_pointer() in deck.KEEP)
        return "%s, watching %d of %d windows, hover %s, pressed %s" % (
            "shown" if on else "off", keepers, len(context.window_manager.windows),
            deck.STATE["hover"][1] if deck.STATE["hover"] else None, deck.STATE["pressed"])
    add("Big-button panel", deck_line)

    def settings_line():
        sm = context.scene.simplemesh
        p = prefs(context)
        return "easy_on=%s easy_start=%s tidy=%s simplify_screen=%s bed=%gx%gx%g look=%s rainbow=%s triangles=%s" % (
            sm.easy_on, p.easy_start, p.apply_on_startup, p.simplify_screen, p.bed_x, p.bed_y, p.bed_z,
            sm.look, sm.look_rainbow, sm.show_edges)
    add("Settings", settings_line)

    def input_line():
        i = context.preferences.inputs
        return ", ".join("%s=%s" % (k, getattr(i, k)) for k in (
            "use_mouse_emulate_3_button", "use_emulate_numpad", "tablet_api", "drag_threshold_mouse",
            "use_mouse_continuous") if hasattr(i, k))
    add("Input", input_line)
    add("Other add-ons", lambda: ", ".join(sorted(k for k in context.preferences.addons.keys()
                                                  if not k.startswith(("io_", "bl_", "cycles")) and k != PKG)) or "none")
    out.append("")
    out.append("Last events seen by the tools: " + (", ".join(
        ("%s x%d" % (n, c)) if c > 1 else n for n, c in EVENTS[-40:]) or "none"))
    out.append("")
    for title, path in (("This session's log", _LOG["path"]), ("The session before (did it end?)", _LOG["prev"])):
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            out.append("%s, last %d lines:" % (title, min(len(lines), 30)))
            out.extend("  " + l for l in lines[-30:])
        except Exception:
            out.append("%s: none" % title)
    out.append("")
    if ERRORS:
        out.append("Problems caught (%d):" % len(ERRORS))
        for where, (count, txt) in ERRORS.items():
            out.append("--- %s (x%d)" % (where, count))
            out.append(txt.rstrip())
    else:
        out.append("Problems caught: none")
    return "\n".join(out) + "\n"


class SIMPLEMESH_OT_report(Operator):
    """Collect the details needed to look into a problem (Blender version, graphics
    card, what mode you are in, any errors SimpleMesh caught). They are copied so you
    can paste them into a message, and saved as simplemesh-report.txt in your home
    folder. Nothing is sent anywhere"""
    bl_idname = "simplemesh.report"
    bl_label = "Report a problem"

    def execute(self, context):
        text = problem_report(context)
        try:
            context.window_manager.clipboard = text
        except Exception:
            pass
        path = os.path.join(os.path.expanduser("~"), "simplemesh-report.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.report({"INFO"}, "Copied. Paste it into your message (Ctrl+V). Also saved as %s" % path)
        except Exception:
            self.report({"INFO"}, "Copied. Paste it into your message (Ctrl+V)")
        return {"FINISHED"}


CLASSES = (
    SimpleMeshPrefs, SimpleMeshProps,
    SIMPLEMESH_OT_import_stl, SIMPLEMESH_OT_export_stl, SIMPLEMESH_OT_frame,
    SIMPLEMESH_OT_scale_by, SIMPLEMESH_OT_fit_longest, SIMPLEMESH_OT_place,
    SIMPLEMESH_OT_rotate90, SIMPLEMESH_OT_mirror, SIMPLEMESH_OT_lay_flat,
    SIMPLEMESH_OT_cut, SIMPLEMESH_OT_combine, SIMPLEMESH_OT_add_shape,
    SIMPLEMESH_OT_mark_hole, SIMPLEMESH_OT_apply_holes, SIMPLEMESH_OT_weld,
    SIMPLEMESH_OT_split_loose, SIMPLEMESH_OT_delete, SIMPLEMESH_OT_duplicate,
    SIMPLEMESH_OT_repair, SIMPLEMESH_OT_check, SIMPLEMESH_OT_simplify,
    SIMPLEMESH_OT_setup, SIMPLEMESH_OT_easy_nav, SIMPLEMESH_OT_view,
    SIMPLEMESH_OT_toggle_persp, SIMPLEMESH_OT_maximize, SIMPLEMESH_OT_report,
)


def register():
    global _bed_handle, _bed_broken
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.simplemesh = PointerProperty(type=SimpleMeshProps)
    if not bpy.app.background:
        _bed_broken = False
        _bed_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_bed, (), "WINDOW", "POST_VIEW")


def unregister():
    global _bed_handle
    if _bed_handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_bed_handle, "WINDOW")
        except Exception:
            pass
        _bed_handle = None
    del bpy.types.Scene.simplemesh
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)

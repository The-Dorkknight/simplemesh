# SimpleMesh - click-in-the-view tools and on-screen read-outs
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 3. No warranty; see LICENSE.
#
# Design rules (borrowed from slicers and Tinkercad, see docs/DESIGN.md):
#   * you work on the model, in the 3D view, not in a side panel
#   * hovering shows exactly what a click will do; nothing changes until you click
#   * no edit mode, no selection order, no gizmo rings
#   * the size in millimetres is always on screen
#   * orbit / pan / zoom keep working while a tool is on; Esc or right-click leaves it

import math

import bmesh
import bpy
from bpy.types import Operator
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector
from mathutils.geometry import intersect_line_line, intersect_line_plane

from . import base as B

AMBER = (1.0, 0.72, 0.1)
RED = (1.0, 0.25, 0.2)
GREEN = (0.35, 1.0, 0.55)
WHITE = (1.0, 1.0, 1.0)
AXIS_COL = {"X": (1.0, 0.33, 0.33), "Y": (0.45, 0.9, 0.3), "Z": (0.35, 0.6, 1.0)}
AXIS_VEC = {"X": Vector((1, 0, 0)), "Y": Vector((0, 1, 0)), "Z": Vector((0, 0, 1))}

# what the strip and the on-screen text show about the running tool
ACTIVE = {"token": None, "name": "", "title": "", "hint": "", "keys": ""}
_CURRENT = {"tool": None}

DIGITS = {"ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4", "FIVE": "5",
          "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
          "NUMPAD_0": "0", "NUMPAD_1": "1", "NUMPAD_2": "2", "NUMPAD_3": "3", "NUMPAD_4": "4",
          "NUMPAD_5": "5", "NUMPAD_6": "6", "NUMPAD_7": "7", "NUMPAD_8": "8", "NUMPAD_9": "9",
          "PERIOD": ".", "NUMPAD_PERIOD": "."}
NAV_EVENTS = {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "WHEELINMOUSE", "WHEELOUTMOUSE",
              "TRACKPADPAN", "TRACKPADZOOM", "MOUSEROTATE", "MOUSESMARTZOOM",
              "NUMPAD_PLUS", "NUMPAD_MINUS", "HOME", "F", "ACCENT_GRAVE"}
NUMPAD_NAV = {"NUMPAD_%d" % i for i in range(10)} | {"NUMPAD_PERIOD", "NUMPAD_SLASH", "NUMPAD_ASTERIX"}


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------

_shader = None
_draw_failed = False


def _get_shader():
    global _shader
    if _shader is None:
        import gpu
        for name in ("UNIFORM_COLOR", "3D_UNIFORM_COLOR"):
            try:
                _shader = gpu.shader.from_builtin(name)
                break
            except Exception:
                continue
    return _shader


def _batch(kind, verts, color, width=1.0, depth=False):
    import gpu
    from gpu_extras.batch import batch_for_shader
    sh = _get_shader()
    if sh is None or not verts:
        return
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL" if depth else "NONE")
    if kind != "TRIS":
        gpu.state.line_width_set(width)
    b = batch_for_shader(sh, kind, {"pos": verts})
    sh.bind()
    sh.uniform_float("color", color)
    b.draw(sh)
    gpu.state.line_width_set(1.0)
    gpu.state.depth_test_set("NONE")
    gpu.state.blend_set("NONE")


def ui_scale():
    try:
        v = bpy.context.preferences.system.ui_scale
        return v if v > 0.01 else 1.0          # (0 when Blender runs without a window)
    except Exception:
        return 1.0


BOX = [0.62]         # darkness of the box behind view text (deeper on a light background)


def text(x, y, s, size=14, color=WHITE, alpha=1.0, centre=False, box=True):
    import blf
    px = int(size * ui_scale())
    try:
        blf.size(0, px)
    except TypeError:
        blf.size(0, px, 72)
    w, h = blf.dimensions(0, s)
    if centre:
        x -= w / 2.0
    if box:
        pad = 5 * ui_scale()
        _batch("TRIS", [(x - pad, y - pad, 0), (x + w + pad, y - pad, 0), (x + w + pad, y + h + pad, 0),
                        (x - pad, y - pad, 0), (x + w + pad, y + h + pad, 0), (x - pad, y + h + pad, 0)],
               (0.0, 0.0, 0.0, BOX[0]))
    blf.position(0, x, y, 0)
    blf.color(0, color[0], color[1], color[2], alpha)
    blf.draw(0, s)
    return w, h


def to_2d(region, rv3d, p):
    return view3d_utils.location_3d_to_region_2d(region, rv3d, p)


def fmt(v):
    return ("%.2f" % v).rstrip("0").rstrip(".") if abs(v) < 100 else "%.1f" % v


def quick_bounds(objs):
    """Fast world bounds from Blender's cached bounding boxes (for drawing only)."""
    lo = Vector((1e30, 1e30, 1e30))
    hi = Vector((-1e30, -1e30, -1e30))
    for o in objs:
        mw = o.matrix_world
        for c in o.bound_box:
            w = mw @ Vector(c)
            lo.x, lo.y, lo.z = min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)
            hi.x, hi.y, hi.z = max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)
    return lo, hi


def headers_height(area):
    """Pixels hidden under the headers at the top of a 3D view."""
    try:
        if not bpy.context.preferences.system.use_region_overlap:
            return 0
        return sum(r.height for r in area.regions
                   if r.type in {"HEADER", "TOOL_HEADER"} and r.alignment == "TOP" and r.height > 1)
    except Exception:
        return 0


# Filled in by deck.py (the big-button panel across the top of the view):
# height(area, region) in pixels, and over(area, region, x, y) -> is that point on it.
DECK = {"height": None, "over": None}


def top_offset(context):
    """Pixels at the top of the 3D view that are taken: headers and the big-button panel."""
    off = headers_height(context.area)
    try:
        if DECK["height"] is not None:
            region = next((r for r in context.area.regions if r.type == "WINDOW"), None)
            off += DECK["height"](context.area, region)
    except Exception:
        pass
    return off


def top_offset_for_test(area):
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    return headers_height(area) + (DECK["height"](area, region) if DECK["height"] is not None else 0)


def over_deck(area, region, x, y):
    """True when region pixel (x, y) is on the big-button panel (tools leave it alone)."""
    try:
        return bool(DECK["over"] is not None and DECK["over"](area, region, x, y))
    except Exception:
        return False


# --------------------------------------------------------------------------
# Always-on read-out: size of the selection in mm, does it fit the bed
# --------------------------------------------------------------------------

def _selection(context):
    try:
        if context.mode == "SCULPT":
            ob = context.object
            return [ob] if ob is not None and ob.type == "MESH" else []
        if context.mode != "OBJECT":
            return []
        objs = [o for o in context.selected_objects if o.type == "MESH"]
        if not objs and context.object is not None and context.object.type == "MESH" \
                and context.object.select_get():
            objs = [context.object]
        return objs
    except Exception:
        return []


def _dims_on(context):
    sm = getattr(context.scene, "simplemesh", None)
    return bool(sm and sm.show_dims)


def overlay_3d():
    global _draw_failed
    if _draw_failed:
        return
    try:
        context = bpy.context
        if context.mode != "OBJECT":
            return
        objs = _selection(context)
        if not objs or not _dims_on(context):
            return
        lo, hi = quick_bounds(objs)
        c = [Vector((x, y, z)) for z in (lo.z, hi.z) for y in (lo.y, hi.y) for x in (lo.x, hi.x)]
        edges = [(0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
        _batch("LINES", [c[i] for e in edges for i in e], (1.0, 1.0, 1.0, 0.16))
        _batch("LINES", [c[0], c[1]], AXIS_COL["X"] + (1.0,), 2.5)
        _batch("LINES", [c[1], c[3]], AXIS_COL["Y"] + (1.0,), 2.5)
        _batch("LINES", [c[3], c[7]], AXIS_COL["Z"] + (1.0,), 2.5)
    except Exception:
        B.note_error("drawing the read-out")
        _draw_failed = True


def overlay_2d():
    global _draw_failed
    if _draw_failed:
        return
    try:
        context = bpy.context
        region, rv3d = context.region, context.region_data
        if region is None or rv3d is None:
            return
        BOX[0] = 0.85 if context.scene.simplemesh.look == "CLEAN" else 0.62
        s = ui_scale()
        x0 = 16 * s
        y = region.height - top_offset(context) - 28 * s
        objs = _selection(context)
        if context.mode == "SCULPT" and objs:
            from . import clay
            lo, hi = quick_bounds(objs)
            d = hi - lo
            n = clay.tri_count(context)
            w, _h = text(x0, y, "%s    %s x %s x %s mm    %s triangles"
                         % (objs[0].name, fmt(d.x), fmt(d.y), fmt(d.z), format(n, ",")), 15)
            if n > clay.HEAVY:
                text(x0 + w + 22 * s, y, "getting heavy: strokes will be slow. Press Done, then Repair > Simplify", 15, RED)
            r = clay.get_radius(context)
            if r and context.scene.simplemesh.clay_detail < r * clay.DETAIL_PER_RADIUS - 1e-6:
                clay.request_guard()                 # the brush was made bigger: Detail must follow
            if clay.needs_setup(context):
                clay.request_setup()
                text(x0, y - 31 * s, "CLAY  -  getting the model ready to mould...", 16, AMBER)
                return
            b = clay.BRUSH_BY_KEY.get(clay.actual_key(context))
            if b:
                text(x0, y - 31 * s, "CLAY  -  %s: %s" % (b[1], b[5]), 16, AMBER)
            else:
                br = context.scene.tool_settings.sculpt.brush
                text(x0, y - 31 * s, "CLAY  -  Blender's own brush (%s). Click a brush in the strip above"
                     % (br.name if br else "none"), 16, AMBER)
            text(x0, y - 58 * s, clay.KEYS_HINT, 12, (0.85, 0.85, 0.85))
            return
        if context.mode != "OBJECT":
            # Edit Mode, Vertex Paint...: reached through Blender's own mode menu
            text(x0, y - 31 * s, "This is one of Blender's own modes  -  the SimpleMesh tools are not in it", 16, AMBER)
            text(x0, y - 58 * s, "press 'Back to the models' (top left) to return   |   to mould a model, use Clay",
                 12, (0.85, 0.85, 0.85))
            return
        if context.mode == "OBJECT":
            if objs:
                lo, hi = quick_bounds(objs)
                d = hi - lo
                p = B.prefs(context)
                name = objs[0].name if len(objs) == 1 else "%d models" % len(objs)
                over = [n for n, v, lim in (("X", d.x, p.bed_x), ("Y", d.y, p.bed_y), ("height", d.z, p.bed_z))
                        if v > lim + 1e-3]
                w, _h = text(x0, y, "%s    %s x %s x %s mm" % (name, fmt(d.x), fmt(d.y), fmt(d.z)), 15)
                if over:
                    text(x0 + w + 22 * s, y, "TOO BIG for the bed (%s)" % ", ".join(over), 15, RED)
                else:
                    text(x0 + w + 22 * s, y, "fits the bed", 15, GREEN)
                if _dims_on(context):
                    for a, b, val, col in (((lo.x, lo.y, lo.z), (hi.x, lo.y, lo.z), d.x, AXIS_COL["X"]),
                                           ((hi.x, lo.y, lo.z), (hi.x, hi.y, lo.z), d.y, AXIS_COL["Y"]),
                                           ((hi.x, hi.y, lo.z), (hi.x, hi.y, hi.z), d.z, AXIS_COL["Z"])):
                        mid = to_2d(region, rv3d, (Vector(a) + Vector(b)) / 2.0)
                        if mid is not None:
                            text(mid.x, mid.y - 6 * s, fmt(val), 14, col, centre=True)
            elif ACTIVE["name"] != "easy":
                text(x0, y, "Click a model to select it.  Open STL to load one.", 14, (0.8, 0.8, 0.8))
        if ACTIVE["token"] is not None:
            text(x0, y - 31 * s, "%s  -  %s" % (ACTIVE["title"].upper(), ACTIVE["hint"]), 16, AMBER)
            keys = ACTIVE["keys"]
            if ACTIVE["name"] != "easy":
                keys = (keys + "   |   " if keys else "") + "Esc or right-click = finish"
            text(x0, y - 58 * s, keys, 12, (0.85, 0.85, 0.85))
    except Exception:
        B.note_error("drawing the read-out")
        _draw_failed = True


# --------------------------------------------------------------------------
# Mesh look-up for hovering (flat regions)
# --------------------------------------------------------------------------

class MeshCache:
    def __init__(self):
        self.bms = {}

    def get(self, obj):
        key = obj.name
        got = self.bms.get(key)
        if got is not None and got[1] == len(obj.data.polygons) and got[0].is_valid:
            return got[0]
        if got is not None:
            try:
                got[0].free()
            except Exception:
                pass
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.normal_update()
        self.bms[key] = (bm, len(obj.data.polygons))
        return bm

    def clear(self):
        for bm, _n in self.bms.values():
            try:
                bm.free()
            except Exception:
                pass
        self.bms = {}


def flat_region(bm, index, tol_deg=3.0, cap=60000):
    """Connected faces around face `index` that share its direction.
    Returns (set of face indices, area-weighted normal, area-weighted centre) in local space."""
    if index < 0 or index >= len(bm.faces):
        return set(), None, None
    seed = bm.faces[index]
    n0 = seed.normal.copy()
    cos_tol = math.cos(math.radians(tol_deg))
    seen = {index}
    stack = [seed]
    nsum = Vector((0.0, 0.0, 0.0))
    csum = Vector((0.0, 0.0, 0.0))
    asum = 0.0
    while stack and len(seen) < cap:
        f = stack.pop()
        a = f.calc_area()
        nsum += f.normal * a
        csum += f.calc_center_median() * a
        asum += a
        for e in f.edges:
            for g in e.link_faces:
                if g.index not in seen and g.normal.dot(n0) >= cos_tol:
                    seen.add(g.index)
                    stack.append(g)
    normal = nsum.normalized() if nsum.length > 0 else n0
    centre = csum / asum if asum > 0 else seed.calc_center_median()
    return seen, normal, centre


def region_tris(bm, faces, mw, lift, limit=20000):
    out = []
    for k, i in enumerate(faces):
        if k >= limit:
            break
        f = bm.faces[i]
        vs = [mw @ (v.co + f.normal * lift) for v in f.verts]
        for j in range(1, len(vs) - 1):
            out += [vs[0], vs[j], vs[j + 1]]
    return out


# --------------------------------------------------------------------------
# Base class for the tools
# --------------------------------------------------------------------------

class ToolBase:
    tool_name = ""
    title = ""
    hint = ""
    takes_numbers = False
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.area is not None and context.area.type == "VIEW_3D"

    # ---- life cycle ------------------------------------------------------
    def invoke(self, context, event):
        if ACTIVE["name"] == self.tool_name and ACTIVE["token"] is not None:
            ACTIVE.update(token=None, name="", title="", hint="", keys="")   # same button again = off
            context.area.tag_redraw()
            return {"CANCELLED"}
        self.token = object()
        self.area_ptr = context.area.as_pointer()
        self.mx = self.my = -1
        self.typed = ""
        self.label = ""
        self.cache = MeshCache()
        self.dragging = False
        self.region = next((r for r in context.area.regions if r.type == "WINDOW"), None)
        self.rv3d = getattr(context.area.spaces.active, "region_3d", None)
        self.keys = getattr(self, "keys", "")
        prev = _CURRENT["tool"]
        if prev is not None and prev is not self:
            try:
                prev.remove_draw()      # the old tool's modal ends on its next event
            except Exception:
                pass
        _CURRENT["tool"] = self
        ACTIVE.update(token=self.token, name=self.tool_name, title=self.title, hint=self.hint, keys=self.keys)
        self.setup(context)
        sv = bpy.types.SpaceView3D
        self._h3 = sv.draw_handler_add(self._safe3d, (), "WINDOW", "POST_VIEW")
        self._h2 = sv.draw_handler_add(self._safe2d, (), "WINDOW", "POST_PIXEL")
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def say(self, hint, keys=""):
        """Set the two instruction lines shown at the top of the view."""
        self.hint, self.keys = hint, keys
        if ACTIVE["token"] is getattr(self, "token", None):
            ACTIVE.update(hint=hint, keys=keys)

    def execute(self, context):          # called without a mouse (search menu, scripts)
        return self.invoke(context, None)

    def _area(self, context):
        for win in context.window_manager.windows:
            for a in win.screen.areas:
                if a.as_pointer() == self.area_ptr:
                    return a
        return None

    def remove_draw(self):
        for h in (getattr(self, "_h3", None), getattr(self, "_h2", None)):
            if h is not None:
                try:
                    bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
                except Exception:
                    pass
        self._h3 = self._h2 = None

    def finish(self, context):
        self.remove_draw()
        self.cache.clear()
        if _CURRENT["tool"] is self:
            _CURRENT["tool"] = None
        if ACTIVE["token"] is self.token:
            ACTIVE.update(token=None, name="", title="", hint="", keys="")
        area = self._area(context)
        if area is not None:
            area.tag_redraw()
        if self.tool_name != "easy":             # give the mouse back to Easy mode if it was on
            try:
                from . import easy
                easy.restart_soon()
            except Exception:
                pass

    def commit(self, context, message):
        self.cache.clear()
        try:
            bpy.ops.ed.undo_push(message="SimpleMesh: " + message)
        except Exception:
            pass

    # ---- geometry helpers ------------------------------------------------
    def ray(self, context, mx=None, my=None):
        mx = self.mx if mx is None else mx
        my = self.my if my is None else my
        origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, (mx, my))
        direction = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, (mx, my))
        return origin, direction

    def hit(self, context, mx=None, my=None):
        """What is under the mouse: dict(obj, point, normal, index) or None."""
        origin, direction = self.ray(context, mx, my)
        try:
            dg = context.evaluated_depsgraph_get()
            ok, loc, nor, idx, obj, _m = context.scene.ray_cast(dg, origin, direction)
        except Exception:
            return None
        if not ok or obj is None:
            return None
        obj = getattr(obj, "original", obj) or obj
        if obj.type != "MESH":
            return None
        return {"obj": obj, "point": loc.copy(), "normal": nor.copy(), "index": idx}

    def target(self, context):
        """The model a typed number applies to: the active selected mesh."""
        ob = context.object
        if ob is not None and ob.type == "MESH" and ob.select_get():
            return ob
        sel = [o for o in context.selected_objects if o.type == "MESH"]
        return sel[0] if sel else None

    # ---- event loop ------------------------------------------------------
    def modal(self, context, event):
        if ACTIVE["token"] is not self.token:
            self.finish(context)
            return {"FINISHED", "PASS_THROUGH"}
        B.note_input(event)
        B.note_event(event)
        area = self._area(context)
        if area is None or context.mode != "OBJECT":
            self.finish(context)
            return {"FINISHED", "PASS_THROUGH"}
        self.region = next((r for r in area.regions if r.type == "WINDOW"), None)
        space = area.spaces.active
        self.rv3d = getattr(space, "region_3d", None)
        if self.region is None or self.rv3d is None:
            self.finish(context)
            return {"FINISHED", "PASS_THROUGH"}
        area.tag_redraw()

        et, ev = event.type, event.value
        if et in {"ESC", "RIGHTMOUSE"} and ev == "PRESS":
            if self.dragging:
                self.cancel_drag(context)
                self.dragging = False
                return {"RUNNING_MODAL"}
            if self.typed:
                self.typed = ""
                return {"RUNNING_MODAL"}
            self.finish(context)
            return {"FINISHED"}

        if not self.dragging:
            if et in NAV_EVENTS or et.startswith("NDOF") or (event.alt and et == "LEFTMOUSE"):
                return {"PASS_THROUGH"}
            if et in NUMPAD_NAV and not self.takes_numbers:
                return {"PASS_THROUGH"}
            if et == "Z" and (event.ctrl or event.oskey):
                self.cache.clear()
                return {"PASS_THROUGH"}

        mx, my = event.mouse_x - self.region.x, event.mouse_y - self.region.y
        inside = 0 <= mx < self.region.width and 0 <= my < self.region.height
        if inside:
            for r in area.regions:      # header / sidebar / toolbar drawn over the view
                if r.type != "WINDOW" and r.width > 1 and r.height > 1 and \
                        r.x <= event.mouse_x < r.x + r.width and r.y <= event.mouse_y < r.y + r.height:
                    inside = False
                    break
        if inside and not self.dragging and over_deck(area, self.region, mx, my):
            inside = False                       # the big-button panel handles its own clicks
        if not inside and not self.dragging:
            self.mx = self.my = -1
            self.on_leave(context)
            return {"PASS_THROUGH"}
        self.mx, self.my = mx, my

        if et == "MOUSEMOVE" or et == "INBETWEEN_MOUSEMOVE":
            self.on_move(context, event)
            return {"RUNNING_MODAL"}
        if et == "LEFTMOUSE":
            if ev in ("PRESS", "DOUBLE_CLICK"):     # Blender reports a quick second click as DOUBLE_CLICK
                self.on_move(context, event)
                return {"RUNNING_MODAL"} if self.on_press(context, event) else {"PASS_THROUGH"}
            if ev == "RELEASE":
                was = self.dragging
                self.on_release(context, event)
                self.dragging = False
                return {"RUNNING_MODAL"} if was else {"PASS_THROUGH"}
        if ev == "PRESS":
            if self.takes_numbers:
                if et in DIGITS:
                    self.typed += DIGITS[et]
                    return {"RUNNING_MODAL"}
                if et == "BACK_SPACE":
                    self.typed = self.typed[:-1]
                    return {"RUNNING_MODAL"}
                if et in {"RET", "NUMPAD_ENTER"} and self.typed:
                    try:
                        val = float(self.typed)
                    except ValueError:
                        val = None
                    self.typed = ""
                    if val is not None:
                        self.on_number(context, val)
                    return {"RUNNING_MODAL"}
            if et in {"RET", "NUMPAD_ENTER"}:
                self.finish(context)
                return {"FINISHED"}
            if self.on_key(context, event):
                return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    # ---- drawing wrappers --------------------------------------------------
    def _safe3d(self):
        try:
            if ACTIVE["token"] is not self.token:
                return
            if bpy.context.area is not None and bpy.context.area.as_pointer() == self.area_ptr:
                self.draw3d(bpy.context)
        except Exception:
            B.note_error("drawing the %s tool (3D)" % self.tool_name)

    def _safe2d(self):
        try:
            if ACTIVE["token"] is not self.token:
                return
            if bpy.context.area is None or bpy.context.area.as_pointer() != self.area_ptr:
                return
            self.draw2d(bpy.context)
            s = ui_scale()
            lines = [l for l in (self.label, ("typing: %s  (Enter)" % self.typed) if self.typed else "") if l]
            if self.mx >= 0:
                for k, l in enumerate(lines):
                    text(self.mx + 22 * s, self.my - (26 + 24 * k) * s, l, 15, AMBER if k == 0 else WHITE)
        except Exception:
            B.note_error("drawing the %s tool" % self.tool_name)

    # ---- to override -------------------------------------------------------
    def setup(self, context):
        pass

    def on_move(self, context, event):
        pass

    def on_leave(self, context):
        self.label = ""

    def on_press(self, context, event):
        return False

    def on_release(self, context, event):
        pass

    def on_key(self, context, event):
        return False

    def on_number(self, context, value):
        pass

    def cancel_drag(self, context):
        pass

    def draw3d(self, context):
        pass

    def draw2d(self, context):
        pass


# --------------------------------------------------------------------------
# LAY FLAT - hover a face, click, it sits on the bed (PrusaSlicer "Place on face")
# --------------------------------------------------------------------------

class SIMPLEMESH_OT_tool_layflat(ToolBase, Operator):
    """Lay flat: move the mouse over the model, the flat face under it lights up; click and that face sits on the bed"""
    bl_idname = "simplemesh.tool_layflat"
    bl_label = "Lay flat"
    tool_name = "layflat"
    title = "Lay flat"
    hint = "move over the model and click the face that should sit on the bed"
    keys = "the face under the mouse lights up first"

    def setup(self, context):
        self.hi = None

    def on_leave(self, context):
        self.hi = None
        self.label = ""

    def on_move(self, context, event):
        h = self.hit(context)
        if h is None:
            self.hi = None
            self.label = ""
            return
        ob = h["obj"]
        if self.hi and self.hi["name"] == ob.name and h["index"] in self.hi["faces"]:
            return
        bm = self.cache.get(ob)
        faces, normal, _c = flat_region(bm, h["index"])
        if normal is None:
            self.hi = None
            return
        mw = ob.matrix_world
        lift = max(self.rv3d.view_distance * 0.0015, 0.01)
        self.hi = {"name": ob.name, "faces": faces, "tris": region_tris(bm, faces, mw, lift),
                   "normal": (mw.to_3x3() @ normal).normalized()}
        self.label = "click: put this face on the bed"

    def on_press(self, context, event):
        if not self.hi:
            return False
        ob = bpy.data.objects.get(self.hi["name"])
        if ob is None:
            return False
        B.select_only(context, [ob])
        B.lay_on_normal(context, ob, self.hi["normal"])
        self.hi = None
        self.label = ""
        self.commit(context, "lay flat")
        return True

    def draw3d(self, context):
        if self.hi:
            _batch("TRIS", self.hi["tris"], AMBER + (0.6,), depth=True)


# --------------------------------------------------------------------------
# MOVE - drag a model across the bed (it stays on the bed)
# --------------------------------------------------------------------------

class SIMPLEMESH_OT_tool_move(ToolBase, Operator):
    """Move: drag a model and it slides across the bed. Shift+drag lifts it up or down. Arrow keys nudge 1 mm"""
    bl_idname = "simplemesh.tool_move"
    bl_label = "Move"
    tool_name = "move"
    title = "Move"
    hint = "drag a model to slide it across the bed"
    keys = "Shift+drag = lift up/down   |   arrow keys = 1 mm (Shift 10, Ctrl 0.1)   |   D = drop to bed   |   C = centre on bed"

    def setup(self, context):
        self.drag = None

    def on_move(self, context, event):
        if not self.dragging or not self.drag:
            h = self.hit(context)
            self.label = ("drag to move %s" % h["obj"].name) if h else ""
            return
        ob = bpy.data.objects.get(self.drag["name"])
        if ob is None:
            return
        origin, direction = self.ray(context)
        d = self.drag
        if event.shift:
            n = Vector((direction.x, direction.y, 0.0))
            if n.length < 1e-4:
                return
            p = intersect_line_plane(origin, origin + direction, d["grab"], n.normalized())
            if p is None:
                return
            dz = p.z - d["grab"].z
            if event.ctrl:
                dz = round(dz)
            ob.location = d["loc"] + Vector((0.0, 0.0, dz))
            self.label = "up %s mm" % fmt(dz)
        else:
            p = intersect_line_plane(origin, origin + direction, d["grab"], Vector((0, 0, 1)))
            if p is None:
                return
            dx, dy = p.x - d["grab"].x, p.y - d["grab"].y
            if event.ctrl:
                dx, dy = round(dx), round(dy)
            ob.location = d["loc"] + Vector((dx, dy, 0.0))
            self.label = "X %s   Y %s mm" % (fmt(dx), fmt(dy))

    def on_press(self, context, event):
        h = self.hit(context)
        if h is None:
            return False
        ob = h["obj"]
        B.unparent(ob)
        B.select_only(context, [ob])
        self.drag = {"name": ob.name, "loc": ob.location.copy(), "grab": h["point"]}
        self.dragging = True
        return True

    def on_release(self, context, event):
        if self.dragging and self.drag:
            B.refresh(context)
            self.commit(context, "move")
        self.drag = None

    def cancel_drag(self, context):
        if self.drag:
            ob = bpy.data.objects.get(self.drag["name"])
            if ob is not None:
                ob.location = self.drag["loc"]
        self.drag = None

    def on_key(self, context, event):
        ob = self.target(context)
        if ob is None:
            return False
        step = 10.0 if event.shift else (0.1 if event.ctrl else 1.0)
        moves = {"LEFT_ARROW": (-step, 0, 0), "RIGHT_ARROW": (step, 0, 0),
                 "UP_ARROW": (0, step, 0), "DOWN_ARROW": (0, -step, 0),
                 "PAGE_UP": (0, 0, step), "PAGE_DOWN": (0, 0, -step)}
        if event.type in moves:
            ob.location = ob.location + Vector(moves[event.type])
            B.refresh(context)
            self.commit(context, "nudge")
            return True
        if event.type == "D":
            bpy.ops.simplemesh.place(center=False)
            return True
        if event.type == "C":
            bpy.ops.simplemesh.place(center=True)
            return True
        return False


# --------------------------------------------------------------------------
# TURN - drag left/right to spin, 15 degree steps
# --------------------------------------------------------------------------

class SIMPLEMESH_OT_tool_turn(ToolBase, Operator):
    """Turn: drag a model left or right to spin it in 15 degree steps. X / Y / Z pick the direction. Arrow keys turn 90 degrees. Or type an angle"""
    bl_idname = "simplemesh.tool_turn"
    bl_label = "Turn"
    tool_name = "turn"
    title = "Turn"
    takes_numbers = True

    def setup(self, context):
        self.axis = "Z"
        self.drag = None
        self._hint()

    def _hint(self):
        self.say("drag a model sideways to spin it about %s" % self.axis,
                 "X Y Z = direction   |   arrow keys = 90 degrees   |   type an angle + Enter   |   "
                 "steps of 15, Shift = fine")

    def _apply(self, ob, angle):
        d = self.drag
        ob.matrix_basis = Matrix.Translation(d["loc"]) @ Matrix.Rotation(math.radians(angle), 4, self.axis)

    def on_move(self, context, event):
        if not self.dragging or not self.drag:
            h = self.hit(context)
            self.label = ("drag to turn %s about %s" % (h["obj"].name, self.axis)) if h else ""
            return
        ob = bpy.data.objects.get(self.drag["name"])
        if ob is None:
            return
        raw = (self.mx - self.drag["mx"]) * 0.5
        step = 1.0 if event.shift else 15.0
        ang = round(raw / step) * step
        self.drag["angle"] = ang
        self._apply(ob, ang)
        self.label = "%s  %g degrees" % (self.axis, ang)

    def on_press(self, context, event):
        h = self.hit(context)
        if h is None:
            return False
        ob = h["obj"]
        B.select_only(context, [ob])
        B.bake(ob)
        self.drag = {"name": ob.name, "loc": ob.location.copy(), "mx": self.mx, "angle": 0.0}
        self.dragging = True
        return True

    def _settle(self, context, ob):
        B.bake(ob)
        lo, _hi = B.obj_bounds(ob)
        ob.location = ob.location + Vector((0.0, 0.0, -lo.z))
        B.refresh(context)

    def on_release(self, context, event):
        if self.dragging and self.drag:
            ob = bpy.data.objects.get(self.drag["name"])
            if ob is not None and abs(self.drag["angle"]) > 1e-6:
                self._settle(context, ob)
                self.commit(context, "turn")
        self.drag = None

    def cancel_drag(self, context):
        if self.drag:
            ob = bpy.data.objects.get(self.drag["name"])
            if ob is not None:
                self._apply(ob, 0.0)
        self.drag = None

    def _turn(self, context, angle):
        ob = self.target(context)
        if ob is None:
            return
        B.bake(ob)
        ob.matrix_basis = Matrix.Translation(ob.location) @ Matrix.Rotation(math.radians(angle), 4, self.axis)
        self._settle(context, ob)
        self.commit(context, "turn")

    def on_number(self, context, value):
        self._turn(context, value)

    def on_key(self, context, event):
        if event.type in AXIS_VEC:
            self.axis = event.type
            self._hint()
            return True
        if event.type in {"LEFT_ARROW", "RIGHT_ARROW"}:
            self._turn(context, -90.0 if event.type == "LEFT_ARROW" else 90.0)
            return True
        return False

    def draw3d(self, context):
        ob = bpy.data.objects.get(self.drag["name"]) if self.drag else self.target(context)
        if ob is None:
            return
        lo, hi = quick_bounds([ob])
        c = (lo + hi) / 2.0
        r = (hi - lo).length * 0.75
        v = AXIS_VEC[self.axis]
        _batch("LINES", [c - v * r, c + v * r], AXIS_COL[self.axis] + (0.95,), 2.5)


# --------------------------------------------------------------------------
# SIZE - drag to resize, or type the size you want
# --------------------------------------------------------------------------

class SIMPLEMESH_OT_tool_size(ToolBase, Operator):
    """Size: drag away from a model to make it bigger, towards it to make it smaller, or type the size in mm and press Enter. X / Y / Z stretch one direction only"""
    bl_idname = "simplemesh.tool_size"
    bl_label = "Size"
    tool_name = "size"
    title = "Size"
    takes_numbers = True

    def setup(self, context):
        self.axis = None
        self.drag = None
        self._hint()

    def _hint(self):
        what = ("the %s size" % self.axis) if self.axis else "the longest side"
        self.say("drag on a model: away = bigger, towards = smaller.  Or type %s in mm + Enter" % what,
                 "X Y Z = stretch one direction only (now: %s)   |   Ctrl = whole mm" % (self.axis or "off"))

    def _factors(self, f):
        if self.axis is None:
            return Vector((f, f, f))
        v = Vector((1.0, 1.0, 1.0))
        v[B.AXES[self.axis]] = f
        return v

    def _preview(self, ob, f):
        d = self.drag
        fv = self._factors(f)
        ob.scale = fv
        size = d["hi"] - d["lo"]
        ob.location = Vector((d["loc"].x, d["loc"].y, d["lo"].z + size.z * fv.z / 2.0))
        return Vector((size.x * fv.x, size.y * fv.y, size.z * fv.z))

    def on_move(self, context, event):
        if not self.dragging or not self.drag:
            h = self.hit(context)
            self.label = ("drag to resize %s" % h["obj"].name) if h else ""
            return
        ob = bpy.data.objects.get(self.drag["name"])
        if ob is None:
            return
        d = self.drag
        dist = (Vector((self.mx, self.my)) - d["c2d"]).length
        f = max(dist / d["dist0"], 0.01)
        size = d["hi"] - d["lo"]
        if event.ctrl:
            k = B.AXES[self.axis] if self.axis else max(range(3), key=lambda i: size[i])
            if size[k] > 0:
                f = max(round(size[k] * f), 1.0) / size[k]
        d["f"] = f
        now = self._preview(ob, f)
        self.label = "%s x %s x %s mm   (%d%%)" % (fmt(now.x), fmt(now.y), fmt(now.z), round(f * 100))

    def on_press(self, context, event):
        h = self.hit(context)
        if h is None:
            return False
        ob = h["obj"]
        B.select_only(context, [ob])
        B.bake(ob)
        lo, hi = B.obj_bounds(ob)
        c2d = to_2d(self.region, self.rv3d, (lo + hi) / 2.0) or Vector((self.mx, self.my))
        dist0 = max((Vector((self.mx, self.my)) - c2d).length, 25.0)
        self.drag = {"name": ob.name, "loc": ob.location.copy(), "lo": lo, "hi": hi,
                     "c2d": c2d, "dist0": dist0, "f": 1.0}
        self.dragging = True
        return True

    def on_release(self, context, event):
        if self.dragging and self.drag:
            ob = bpy.data.objects.get(self.drag["name"])
            if ob is not None and abs(self.drag["f"] - 1.0) > 1e-6:
                B.bake(ob)
                B.refresh(context)
                self.commit(context, "resize")
        self.drag = None

    def cancel_drag(self, context):
        if self.drag:
            ob = bpy.data.objects.get(self.drag["name"])
            if ob is not None:
                ob.scale = (1.0, 1.0, 1.0)
                ob.location = self.drag["loc"]
        self.drag = None

    def on_number(self, context, value):
        ob = self.target(context)
        if ob is None or value <= 0:
            return
        B.bake(ob)
        lo, hi = B.obj_bounds(ob)
        size = hi - lo
        k = B.AXES[self.axis] if self.axis else max(range(3), key=lambda i: size[i])
        if size[k] <= 0:
            return
        fv = self._factors(value / size[k])
        ob.scale = fv
        ob.location = Vector((ob.location.x, ob.location.y, lo.z + size.z * fv.z / 2.0))
        B.bake(ob)
        B.refresh(context)
        self.commit(context, "resize")
        B.frame_model(context)

    def on_key(self, context, event):
        if event.type in AXIS_VEC:
            self.axis = None if self.axis == event.type else event.type
            self._hint()
            return True
        return False


# --------------------------------------------------------------------------
# PULL - drag a flat face in or out (SketchUp "Push/Pull", Fusion "Press Pull")
# --------------------------------------------------------------------------

class SIMPLEMESH_OT_tool_pull(ToolBase, Operator):
    """Pull: move over a flat face (it lights up), then drag it outwards to make the part longer or inwards to make it shorter. Or type a distance in mm"""
    bl_idname = "simplemesh.tool_pull"
    bl_label = "Pull face"
    tool_name = "pull"
    title = "Pull"
    hint = "drag a flat face out or in to make the part longer or shorter.  Or type mm + Enter"
    keys = "steps of 0.5 mm, Ctrl = whole mm, Shift = free   |   minus key = inwards when typing"
    takes_numbers = True

    def setup(self, context):
        self.hi = None
        self.drag = None

    def on_leave(self, context):
        if not self.dragging:
            self.hi = None
            self.label = ""

    def _region(self, context, h):
        ob = h["obj"]
        bm = self.cache.get(ob)
        faces, normal, centre = flat_region(bm, h["index"])
        if normal is None:
            return None
        mw = ob.matrix_world
        lift = max(self.rv3d.view_distance * 0.0015, 0.01)
        return {"name": ob.name, "index": h["index"], "faces": faces,
                "tris": region_tris(bm, faces, mw, lift),
                "normal": (mw.to_3x3() @ normal).normalized(), "centre": mw @ centre}

    def on_move(self, context, event):
        if self.dragging and self.drag:
            d = self.drag
            ob = bpy.data.objects.get(d["name"])
            if ob is None:
                return
            origin, direction = self.ray(context)
            pts = intersect_line_line(d["grab"], d["grab"] + d["normal"], origin, origin + direction)
            if pts is None:
                return
            t = (pts[0] - d["grab"]).dot(d["normal"])
            if event.ctrl:
                t = round(t)
            elif not event.shift:
                t = round(t * 2.0) / 2.0
            d["t"] = t
            B.offset_vertices(ob.data, d["idx"], d["cos"], d["normal"], t)
            self.label = "%s%s mm" % ("+" if t >= 0 else "", fmt(t))
            return
        h = self.hit(context)
        if h is None:
            self.hi = None
            self.label = ""
            return
        if self.hi and self.hi["name"] == h["obj"].name and h["index"] in self.hi["faces"]:
            return
        self.hi = self._region(context, h)
        self.label = "drag this face out or in" if self.hi else ""

    def on_press(self, context, event):
        h = self.hit(context)
        if h is None:
            return False
        ob = h["obj"]
        B.select_only(context, [ob])
        B.bake(ob)                      # scale 1, no rotation: local directions = world directions
        self.cache.clear()
        reg = self._region(context, h)
        if reg is None:
            return False
        bm = self.cache.get(ob)
        idx = B.region_vertices(bm, reg["faces"])
        self.drag = {"name": ob.name, "idx": idx, "cos": [ob.data.vertices[i].co.copy() for i in idx],
                     "normal": reg["normal"], "grab": h["point"].copy(), "t": 0.0}
        self.hi = None
        self.dragging = True
        return True

    def on_release(self, context, event):
        if self.dragging and self.drag:
            ob = bpy.data.objects.get(self.drag["name"])
            if ob is not None and abs(self.drag["t"]) > 1e-9:
                B.bake(ob)
                B.refresh(context)
                self.commit(context, "pull face")
        self.drag = None
        self.cache.clear()

    def cancel_drag(self, context):
        if self.drag:
            ob = bpy.data.objects.get(self.drag["name"])
            if ob is not None:
                B.offset_vertices(ob.data, self.drag["idx"], self.drag["cos"], self.drag["normal"], 0.0)
        self.drag = None

    def on_number(self, context, value):
        if not self.hi:
            self.report({"WARNING"}, "Point at the face first, then type the distance")
            return
        ob = bpy.data.objects.get(self.hi["name"])
        if ob is None:
            return
        B.pull_face(ob, self.hi["index"], value)
        B.refresh(context)
        self.hi = None
        self.commit(context, "pull face")

    def on_key(self, context, event):
        if event.type == "MINUS":
            self.typed = self.typed[1:] if self.typed.startswith("-") else "-" + self.typed
            return True
        return False

    def draw3d(self, context):
        if self.dragging and self.drag:
            d = self.drag
            a = d["grab"] + d["normal"] * d["t"]
            _batch("LINES", [d["grab"], a], AMBER + (1.0,), 3.0)
            return
        if self.hi:
            _batch("TRIS", self.hi["tris"], AMBER + (0.6,), depth=True)
            n, c = self.hi["normal"], self.hi["centre"]
            ln = max(self.rv3d.view_distance * 0.07, 1.0)
            _batch("LINES", [c, c + n * ln], AMBER + (1.0,), 3.0)


# --------------------------------------------------------------------------
# CUT - a plane follows the mouse; click cuts there. Or drag a line across.
# --------------------------------------------------------------------------

KEEP_ORDER = ["BOTH", "ABOVE", "BELOW"]
KEEP_TEXT = {"BOTH": "both pieces", "ABOVE": "one side only (far side)", "BELOW": "one side only (near side)"}


class SIMPLEMESH_OT_tool_cut(ToolBase, Operator):
    """Cut: a cutting plane follows the mouse over the model; click to cut there. Or drag a line across the model to cut along it. X / Y / Z change the direction, type a height in mm for an exact cut"""
    bl_idname = "simplemesh.tool_cut"
    bl_label = "Cut"
    tool_name = "cut"
    title = "Cut"
    takes_numbers = True

    def setup(self, context):
        self.axis = context.scene.simplemesh.cut_axis
        self.prev = None
        self.press = None
        self._hint(context)

    def _hint(self, context):
        sm = context.scene.simplemesh
        self.say("move over the model and click to cut there  -  or drag a line across it",
                 "X Y Z = direction (now %s)   |   type mm + Enter = exact height   |   K = keep: %s   |   "
                 "L = lay cut faces on the bed: %s" % (self.axis, KEEP_TEXT[sm.cut_keep],
                                                        "on" if sm.cut_faces_down else "off"))

    def on_leave(self, context):
        self.prev = None
        self.label = ""

    def _preview_at(self, ob, pos):
        idx = B.AXES[self.axis]
        lo, hi = quick_bounds([ob])
        pos = min(max(pos, lo[idx]), hi[idx])
        self.prev = {"name": ob.name, "pos": pos, "lo": lo, "hi": hi}
        self.label = "cut %s at %s mm  (click)" % (self.axis, fmt(pos - lo[idx]))

    def on_move(self, context, event):
        if self.dragging:
            if self.press and (Vector((self.mx, self.my)) - self.press).length > 8:
                self.label = "release to cut along this line"
            return
        h = self.hit(context)
        if h is None:
            self.prev = None
            self.label = ""
            return
        idx = B.AXES[self.axis]
        lo, _hi = quick_bounds([h["obj"]])
        pos = h["point"][idx]
        if event.ctrl:
            pos = lo[idx] + round(pos - lo[idx])
        self._preview_at(h["obj"], pos)

    def on_press(self, context, event):
        self.press = Vector((self.mx, self.my))
        self.dragging = True
        return True

    def _do_cut(self, context, ob, co, no):
        sm = context.scene.simplemesh
        parts = B.split_model(context, ob, co, no, sm.cut_keep, sm.cut_faces_down)
        if not parts:
            self.report({"WARNING"}, "That cut does not pass through the model")
            return False
        B.select_only(context, parts)
        self.prev = None
        self.label = ""
        self.commit(context, "cut")
        B.frame_model(context)
        return True

    def on_release(self, context, event):
        if not self.dragging or self.press is None:
            return
        end = Vector((self.mx, self.my))
        start = self.press
        self.press = None
        if (end - start).length <= 8:                       # a click: cut at the previewed plane
            if not self.prev:
                return
            ob = bpy.data.objects.get(self.prev["name"])
            if ob is None:
                return
            idx = B.AXES[self.axis]
            co = (self.prev["lo"] + self.prev["hi"]) / 2.0
            co[idx] = self.prev["pos"]
            self._do_cut(context, ob, co, AXIS_VEC[self.axis].copy())
            return
        # a drag: cut along the drawn line, straight into the screen
        ob = None
        for k in range(11):
            p = start.lerp(end, k / 10.0)
            h = self.hit(context, p.x, p.y)
            if h is not None:
                ob = h["obj"]
                break
        if ob is None:
            ob = self.target(context)
        if ob is None:
            self.report({"WARNING"}, "Draw the line across a model")
            return
        lo, hi = quick_bounds([ob])
        depth = (lo + hi) / 2.0
        p1 = view3d_utils.region_2d_to_location_3d(self.region, self.rv3d, start, depth)
        p2 = view3d_utils.region_2d_to_location_3d(self.region, self.rv3d, end, depth)
        view = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, (start + end) / 2.0)
        no = (p2 - p1).cross(view)
        if no.length < 1e-9:
            return
        self._do_cut(context, ob, p1, no.normalized())

    def cancel_drag(self, context):
        self.press = None

    def on_number(self, context, value):
        ob = bpy.data.objects.get(self.prev["name"]) if self.prev else self.target(context)
        if ob is None:
            return
        B.bake(ob)
        idx = B.AXES[self.axis]
        lo, hi = B.obj_bounds(ob)
        co = (lo + hi) / 2.0
        co[idx] = lo[idx] + value
        self._do_cut(context, ob, co, AXIS_VEC[self.axis].copy())

    def on_key(self, context, event):
        sm = context.scene.simplemesh
        if event.type in AXIS_VEC:
            self.axis = event.type
            sm.cut_axis = self.axis
            self.prev = None
        elif event.type == "K":
            sm.cut_keep = KEEP_ORDER[(KEEP_ORDER.index(sm.cut_keep) + 1) % 3]
        elif event.type == "L":
            sm.cut_faces_down = not sm.cut_faces_down
        else:
            return False
        self._hint(context)
        return True

    def draw3d(self, context):
        if not self.prev or (self.dragging and self.press is not None
                             and (Vector((self.mx, self.my)) - self.press).length > 8):
            return
        idx = B.AXES[self.axis]
        lo, hi, pos = self.prev["lo"], self.prev["hi"], self.prev["pos"]
        a, b = [k for k in range(3) if k != idx]
        ma, mb = (hi[a] - lo[a]) * 0.18 + 2.0, (hi[b] - lo[b]) * 0.18 + 2.0
        quad = []
        for ua, ub in ((lo[a] - ma, lo[b] - mb), (hi[a] + ma, lo[b] - mb), (hi[a] + ma, hi[b] + mb), (lo[a] - ma, hi[b] + mb)):
            v = Vector((0.0, 0.0, 0.0))
            v[idx], v[a], v[b] = pos, ua, ub
            quad.append(v)
        _batch("TRIS", [quad[0], quad[1], quad[2], quad[0], quad[2], quad[3]], RED + (0.10,))
        _batch("TRIS", [quad[0], quad[1], quad[2], quad[0], quad[2], quad[3]], RED + (0.30,), depth=True)
        _batch("LINE_LOOP", quad, RED + (1.0,), 2.0)

    def draw2d(self, context):
        if self.dragging and self.press is not None:
            end = Vector((self.mx, self.my))
            if (end - self.press).length > 8:
                _batch("LINES", [(self.press.x, self.press.y, 0), (end.x, end.y, 0)], RED + (1.0,), 3.0)


# --------------------------------------------------------------------------
# HOLE - a circle follows the mouse on the surface; click drills it
# --------------------------------------------------------------------------

class SIMPLEMESH_OT_tool_hole(ToolBase, Operator):
    """Hole: a circle follows the mouse on the model's surface; click to drill a round hole there. Type the diameter in mm, + and - change it"""
    bl_idname = "simplemesh.tool_hole"
    bl_label = "Hole"
    tool_name = "hole"
    title = "Hole"
    takes_numbers = True

    def setup(self, context):
        self.prev = None
        self._hint(context)

    def _hint(self, context):
        sm = context.scene.simplemesh
        depth = "right through" if sm.hole_depth <= 0 else "%s mm deep" % fmt(sm.hole_depth)
        self.say("click on the model to drill a %s mm hole, %s" % (fmt(sm.hole_diameter), depth),
                 "type a diameter + Enter   |   + / - = 1 mm   |   T = through / blind   |   [ ] = depth   |   "
                 "Ctrl = centre of the face")

    def on_leave(self, context):
        self.prev = None
        self.label = ""

    def on_move(self, context, event):
        h = self.hit(context)
        if h is None:
            self.prev = None
            self.label = ""
            return
        ob = h["obj"]
        sm = context.scene.simplemesh
        n = h["normal"].normalized()
        point = h["point"]
        if event.ctrl:
            bm = self.cache.get(ob)
            _faces, fn, centre = flat_region(bm, h["index"])
            if fn is not None:
                mw = ob.matrix_world
                n = (mw.to_3x3() @ fn).normalized()
                point = mw @ centre
        for v in AXIS_VEC.values():                 # straighten nearly-straight holes
            for sgn in (1.0, -1.0):
                if n.dot(v * sgn) > math.cos(math.radians(8.0)):
                    n = v * sgn
        self.prev = {"name": ob.name, "point": point, "normal": n}
        self.label = "hole %s mm, %s  (click)" % (fmt(sm.hole_diameter),
                                                 "through" if sm.hole_depth <= 0 else "%s deep" % fmt(sm.hole_depth))

    def on_press(self, context, event):
        if not self.prev:
            return False
        ob = bpy.data.objects.get(self.prev["name"])
        if ob is None:
            return False
        sm = context.scene.simplemesh
        try:
            B.drill_hole(context, ob, self.prev["point"], -self.prev["normal"], sm.hole_diameter, sm.hole_depth)
        except Exception as ex:  # noqa: BLE001
            self.report({"ERROR"}, "Could not drill here: %s" % ex)
            return True
        B.select_only(context, [ob])
        self.prev = None
        self.commit(context, "hole")
        return True

    def on_number(self, context, value):
        if value > 0:
            context.scene.simplemesh.hole_diameter = value
            self._hint(context)

    def on_key(self, context, event):
        sm = context.scene.simplemesh
        step = 0.1 if event.shift else 1.0
        if event.type in {"EQUAL", "PLUS"}:
            sm.hole_diameter += step
        elif event.type == "MINUS":
            sm.hole_diameter = max(0.1, sm.hole_diameter - step)
        elif event.type == "T":
            sm.hole_depth = 0.0 if sm.hole_depth > 0 else 10.0
        elif event.type == "RIGHT_BRACKET":
            sm.hole_depth += step
        elif event.type == "LEFT_BRACKET":
            sm.hole_depth = max(0.0, sm.hole_depth - step)
        else:
            return False
        self._hint(context)
        if self.prev:
            self.label = "hole %s mm" % fmt(sm.hole_diameter)
        return True

    def draw3d(self, context):
        if not self.prev:
            return
        sm = context.scene.simplemesh
        n, p = self.prev["normal"], self.prev["point"]
        u = n.orthogonal().normalized()
        v = n.cross(u)
        r = sm.hole_diameter / 2.0
        lift = max(self.rv3d.view_distance * 0.0015, 0.01)
        ring = [p + n * lift + (u * math.cos(t) + v * math.sin(t)) * r
                for t in (2 * math.pi * k / 48 for k in range(48))]
        fan = []
        for k in range(48):
            fan += [p + n * lift, ring[k], ring[(k + 1) % 48]]
        _batch("TRIS", fan, RED + (0.45,))
        _batch("LINE_LOOP", ring, RED + (1.0,), 2.5)
        ob = bpy.data.objects.get(self.prev["name"])
        length = sm.hole_depth
        if length <= 0 and ob is not None:
            lo, hi = quick_bounds([ob])
            length = (hi - lo).length
        _batch("LINES", [p + n * 4.0, p - n * length], RED + (0.9,), 1.5)


# --------------------------------------------------------------------------
# MEASURE - click two points
# --------------------------------------------------------------------------

class SIMPLEMESH_OT_tool_measure(ToolBase, Operator):
    """Measure: click two points on the model to read the distance between them in mm (snaps to corners)"""
    bl_idname = "simplemesh.tool_measure"
    bl_label = "Measure"
    tool_name = "measure"
    title = "Measure"
    hint = "click two points on the model"
    keys = "snaps to corners   |   click again to start a new measurement"

    def setup(self, context):
        self.pts = []
        self.hover = None

    def _snap(self, context, h):
        ob = h["obj"]
        try:
            poly = ob.data.polygons[h["index"]]
        except Exception:
            return h["point"]
        mw = ob.matrix_world
        best, bd = h["point"], 14.0 * ui_scale()
        for vi in poly.vertices:
            w = mw @ ob.data.vertices[vi].co
            p2 = to_2d(self.region, self.rv3d, w)
            if p2 is None:
                continue
            dist = (p2 - Vector((self.mx, self.my))).length
            if dist < bd:
                best, bd = w, dist
        return best

    def on_leave(self, context):
        self.hover = None

    def on_move(self, context, event):
        h = self.hit(context)
        self.hover = self._snap(context, h) if h else None
        if len(self.pts) == 1 and self.hover is not None:
            self.label = "%s mm" % fmt((self.hover - self.pts[0]).length)
        elif len(self.pts) != 2:
            self.label = "click the first point" if not self.pts else ""

    def on_press(self, context, event):
        if self.hover is None:
            return False
        if len(self.pts) >= 2:
            self.pts = []
        self.pts.append(self.hover.copy())
        if len(self.pts) == 2:
            d = self.pts[1] - self.pts[0]
            self.label = "%s mm" % fmt(d.length)
            self.report({"INFO"}, "Distance %s mm  (X %s  Y %s  Z %s)"
                        % (fmt(d.length), fmt(abs(d.x)), fmt(abs(d.y)), fmt(abs(d.z))))
        return True

    def draw3d(self, context):
        pts = list(self.pts)
        if len(pts) == 1 and self.hover is not None:
            pts.append(self.hover)
        if len(pts) == 2:
            _batch("LINES", pts, AMBER + (1.0,), 3.0)

    def draw2d(self, context):
        s = ui_scale()
        for p in self.pts + ([self.hover] if self.hover is not None and len(self.pts) < 2 else []):
            p2 = to_2d(self.region, self.rv3d, p)
            if p2 is not None:
                r = 5 * s
                _batch("TRIS", [(p2.x - r, p2.y, 0), (p2.x, p2.y - r, 0), (p2.x + r, p2.y, 0),
                                (p2.x - r, p2.y, 0), (p2.x + r, p2.y, 0), (p2.x, p2.y + r, 0)], AMBER + (1.0,))
        if len(self.pts) == 2:
            d = self.pts[1] - self.pts[0]
            mid = to_2d(self.region, self.rv3d, (self.pts[0] + self.pts[1]) / 2.0)
            if mid is not None:
                text(mid.x, mid.y + 12 * s, "%s mm" % fmt(d.length), 17, AMBER, centre=True)
                text(mid.x, mid.y - 16 * s, "X %s   Y %s   Z %s" % (fmt(abs(d.x)), fmt(abs(d.y)), fmt(abs(d.z))),
                     13, WHITE, centre=True)


def stop_tool(context=None):
    ACTIVE.update(token=None, name="", title="", hint="", keys="")
    prev = _CURRENT["tool"]
    if prev is not None:
        try:
            prev.remove_draw()          # its modal ends by itself on the next event
        except Exception:
            pass
        _CURRENT["tool"] = None
    if context is not None and context.area is not None:
        context.area.tag_redraw()


TOOL_TIPS = {
    "": "Plain selecting: click a model to select it (Shift+click adds). Turns Easy mode off",
    "easy": "Easy mode: big picture buttons. Add shapes, stack them, pull the dots to change them, draw, write, colour, glue, print",
    "layflat": "Lay flat: move over the model, the flat face under the mouse lights up; click and it sits on the bed",
    "move": "Move: drag a model to slide it across the bed. Shift+drag lifts it. Arrow keys nudge 1 mm",
    "turn": "Turn: drag a model sideways to spin it in 15 degree steps. X / Y / Z pick the direction, arrow keys turn 90",
    "size": "Size: drag away from a model to grow it, towards it to shrink it, or type the size in mm and press Enter",
    "pull": "Pull: point at a flat face and drag it out or in to make the part longer or shorter. Or type mm",
    "cut": "Cut: a cutting plane follows the mouse, click to cut there. Or drag a line across the model",
    "hole": "Hole: a circle follows the mouse on the surface, click to drill. Type the diameter in mm",
    "measure": "Measure: click two points to read the distance in mm",
}


class SIMPLEMESH_OT_tool(Operator):
    """Switch tool"""
    bl_idname = "simplemesh.tool"
    bl_label = "SimpleMesh tool"

    name: bpy.props.StringProperty(default="")

    @classmethod
    def description(cls, context, properties):
        return TOOL_TIPS.get(properties.name, "")

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        name = self.name
        same = ACTIVE["token"] is not None and ACTIVE["name"] == name
        sm = getattr(context.scene, "simplemesh", None)
        if sm is not None and (not name or (same and name == "easy")):
            sm.easy_on = False                   # Select, or Easy pressed again: really leave Easy mode
            try:
                B.apply_look(context)
            except Exception:
                pass
        stop_tool(context)
        if not name or same:            # "Select", or the active tool's button pressed again
            return {"FINISHED"}
        if name not in TOOL_TIPS:
            return {"CANCELLED"}
        # Start the tool with the 3D view itself (not the header the button sits
        # in) as its region, so its mouse coordinates and redraws belong to the view.
        area, win = context.area, context.window
        region = next((q for q in area.regions if q.type == "WINDOW"), None)
        if region is None:
            return {"CANCELLED"}
        op = getattr(bpy.ops.simplemesh, "tool_" + name)
        try:
            if hasattr(context, "temp_override"):
                with context.temp_override(window=win, area=area, region=region):
                    op("INVOKE_DEFAULT")
            else:   # Blender 3.0 / 3.1
                op({"window": win, "screen": win.screen, "area": area, "region": region}, "INVOKE_DEFAULT")
        except Exception as ex:  # noqa: BLE001
            self.report({"ERROR"}, "Could not start the tool: %s" % ex)
            return {"CANCELLED"}
        return {"FINISHED"}


class SIMPLEMESH_OT_tool_stop(Operator):
    """Leave the current tool and go back to plain selecting"""
    bl_idname = "simplemesh.tool_stop"
    bl_label = "Select"

    def execute(self, context):
        stop_tool(context)
        return {"FINISHED"}


TOOLS = (SIMPLEMESH_OT_tool_layflat, SIMPLEMESH_OT_tool_move, SIMPLEMESH_OT_tool_turn,
         SIMPLEMESH_OT_tool_size, SIMPLEMESH_OT_tool_pull, SIMPLEMESH_OT_tool_cut, SIMPLEMESH_OT_tool_hole,
         SIMPLEMESH_OT_tool_measure, SIMPLEMESH_OT_tool, SIMPLEMESH_OT_tool_stop)

_handles = []


def register():
    global _draw_failed, _shader
    _draw_failed = False
    _shader = None
    for c in TOOLS:
        bpy.utils.register_class(c)
    if not bpy.app.background:
        sv = bpy.types.SpaceView3D
        _handles.append(sv.draw_handler_add(overlay_3d, (), "WINDOW", "POST_VIEW"))
        _handles.append(sv.draw_handler_add(overlay_2d, (), "WINDOW", "POST_PIXEL"))


def unregister():
    ACTIVE.update(token=None, name="", title="", hint="", keys="")
    for h in _handles:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
        except Exception:
            pass
    _handles.clear()
    for c in reversed(TOOLS):
        bpy.utils.unregister_class(c)

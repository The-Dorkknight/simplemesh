# SimpleMesh - the deck: a panel of big buttons across the top of the 3D view
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 3. No warranty; see LICENSE.
#
# The same idea as the deck of the SimpleCAD workbench for FreeCAD: one panel that
# is always there, whatever mode Blender is in, with
#   * a big red button in caution tape that does the next obvious thing
#     (MOULD LIKE CLAY / DONE / FINISH the tool / BACK TO THE MODELS),
#   * a green badge that says what is active,
#   * FIND MODEL, the everyday tools (or the clay brushes while moulding),
#   * small system keys: Easy, Luminous, Hide clutter, More tools.
#
# Blender's headers have a fixed height, so big buttons cannot live there. The
# deck is drawn inside the 3D view instead, and a small "keeper" operator that
# stays switched on watches the mouse: it takes the clicks that land on the deck
# and lets everything else through untouched.

import math
import time

import bpy
from bpy.types import Menu, Operator

from . import base as B
from . import clay as C
from . import interactive as I

HEIGHT = 92.0          # panel height, in pixels at interface scale 1
ROOM_RIGHT = 118.0     # left free at the right for Blender's view ball
NEEDS = 1330.0         # width the keys need at full size; narrower views shrink them

STATE = {"hover": None, "pressed": None, "msg": "", "msg_t": 0.0, "x": 0.0}
KEEP = {}              # window pointer -> token of the keeper operator watching that window

TOOL_KEYS = (("layflat", "Lay flat"), ("move", "Move"), ("turn", "Turn"), ("size", "Size"),
             ("open", "Open"), ("undo", "Undo"),
             ("pull", "Pull face"), ("cut", "Cut"), ("hole", "Drill"), ("measure", "Measure"),
             ("save", "Save"), ("redo", "Redo"))
CLAY_KEYS = (("b:pull", "Pull"), ("b:build", "Build up"), ("b:push", "Push in"), ("b:shift", "Shift"),
             ("bigger", "Brush +"), ("undo", "Undo"),
             ("b:inflate", "Inflate"), ("b:smooth", "Smooth"), ("b:flatten", "Flatten"), ("mirror", "Mirror"),
             ("smaller", "Brush -"), ("redo", "Redo"))
SYSTEM_KEYS = (("easy", "Easy"), ("luminous", "Luminous"), ("clutter", "Hide clutter"), ("more", "More tools"))

TIPS = {
    "find": "centre the view on the model (F)",
    "open": "open a STL file; it arrives at its real size, on the bed",
    "save": "save the selected models as a STL in millimetres",
    "undo": "take back the last step (Ctrl+Z)",
    "redo": "do it again (Ctrl+Shift+Z)",
    "bigger": "a bigger brush",
    "smaller": "a smaller brush",
    "mirror": "do the same on the left and the right at once",
    "easy": "picture buttons for building with shapes",
    "luminous": "dark, high-contrast look / light, clean look",
    "clutter": "hide Blender's own menus and bars (press again to bring them back)",
    "more": "exact numbers, shapes, repair, view, look, report a problem",
}


# --------------------------------------------------------------------------
# Is it on, how big is it
# --------------------------------------------------------------------------

TEST = {"on": False}    # the windowless tests switch this on to lay the deck out without a window


def shown(context=None):
    if TEST["on"]:
        return True
    if bpy.app.background or not hasattr(bpy.context, "temp_override"):     # (needs Blender 3.2)
        return False
    return bool(getattr(B.prefs(context), "show_deck", True))


def fit(region):
    """Shrink factor for a narrow view."""
    s = I.ui_scale()
    try:
        k = (region.width - ROOM_RIGHT * s) / (NEEDS * s)
    except Exception:
        k = 1.0
    return max(0.55, min(1.0, k))


def height(area, region):
    if region is None or not shown():
        return 0
    return HEIGHT * I.ui_scale() * fit(region)


def plate(area, region):
    """(x, y, w, h) of the panel in region pixels."""
    h = height(area, region)
    return 0.0, region.height - I.headers_height(area) - h, region.width - ROOM_RIGHT * I.ui_scale(), h


def over(area, region, x, y):
    if not shown():
        return False
    px, py, pw, ph = plate(area, region)
    return px <= x < px + pw and py <= y < py + ph


# --------------------------------------------------------------------------
# What is on it right now
# --------------------------------------------------------------------------

def active_tool():
    return I.ACTIVE["name"] if I.ACTIVE["token"] is not None else ""


def red_state(context):
    """(label, small line under it, tip) of the big red button."""
    mode = context.mode
    if mode == "SCULPT":
        if C.needs_setup(context):
            return "GET READY TO MOULD", "give the model small triangles", "set this model up for moulding"
        return "DONE", "finish moulding", "finish moulding and go back to the tools"
    if mode != "OBJECT":
        return "BACK TO THE MODELS", "leave this Blender mode", "leave this Blender mode"
    name = active_tool()
    if name and name != "easy":
        return "FINISH " + I.ACTIVE["title"].upper(), "or press Esc", "finish this tool"
    return "MOULD LIKE CLAY", "pull, push, smooth", "mould the chosen model like clay"


def badge_text(context):
    mode = context.mode
    if mode == "SCULPT":
        b = C.BRUSH_BY_KEY.get(C.actual_key(context))
        return "CLAY: " + (b[1].upper() if b else "BLENDER BRUSH")
    if mode != "OBJECT":
        return "BLENDER: " + mode.replace("_", " ")
    name = active_tool()
    if name == "easy":
        return "EASY"
    if name:
        return I.ACTIVE["title"].upper()
    return "SELECT"


def clutter_hidden(context):
    try:
        return any(not sp.show_region_header for _a, sp in B.each_view3d(context))
    except Exception:
        return False


def layout(area, region, context):
    """The buttons as a list of dicts: id, kind, rect (x, y, w, h), label, sub, on, enabled, tip."""
    px, py, pw, ph = plate(area, region)
    u = I.ui_scale() * fit(region)
    mode = context.mode
    sm = context.scene.simplemesh
    items = []
    big_h = ph - 26 * u
    by = py + 9 * u
    x = px + 14 * u

    label, sub, tip = red_state(context)
    items.append(dict(id="red", kind="red", rect=(x, by, 220 * u, big_h), label=label, sub=sub, tip=tip,
                      on=False, enabled=True, module="MODE", mx=x))
    x += 220 * u + 10 * u
    items.append(dict(id="badge", kind="badge", rect=(x, by + 5 * u, 170 * u, big_h - 10 * u), label=badge_text(context),
                      sub="ACTIVE", tip="", on=True, enabled=False))
    x += 170 * u + 18 * u
    items.append(dict(id="find", kind="find", rect=(x, by + 3 * u, 120 * u, big_h - 6 * u), label="FIND", sub="MODEL",
                      tip=TIPS["find"], on=False, enabled=True, module="VIEW", mx=x))
    x += 120 * u + 18 * u

    keys = CLAY_KEYS if mode == "SCULPT" else TOOL_KEYS
    kw, kh, kg = 84 * u, (big_h - 4 * u) / 2.0, 4 * u
    tool = active_tool()
    brush = C.actual_key(context) if mode == "SCULPT" else None
    ready = mode == "SCULPT" and not C.needs_setup(context)
    for i, (key, text) in enumerate(keys):
        col, row = i % 6, i // 6
        rect = (x + col * (kw + kg), by + (1 - row) * (kh + kg), kw, kh)
        on, enabled, tip = False, True, TIPS.get(key, "")
        if key.startswith("b:"):
            on = brush == key[2:]
            enabled = ready
            tip = C.BRUSH_BY_KEY[key[2:]][5]
        elif key in ("bigger", "smaller"):
            enabled = ready
        elif key == "mirror":
            on, enabled = bool(sm.clay_mirror), ready
        elif key in ("undo", "redo"):
            enabled = mode in ("OBJECT", "SCULPT")
        elif key in ("open", "save"):
            enabled = mode == "OBJECT"
        else:
            on = tool == key
            enabled = mode == "OBJECT"
            tip = I.TOOL_TIPS.get(key, "")
        d = dict(id=key, kind="key", rect=rect, label=text, sub="", tip=tip, on=on, enabled=enabled)
        if i == 0:
            d.update(module="BRUSHES" if mode == "SCULPT" else "TOOLS", mx=x)
        items.append(d)
    x += 6 * kw + 5 * kg + 18 * u

    sw = 96 * u
    for i, (key, text) in enumerate(SYSTEM_KEYS):
        col, row = i % 2, i // 2
        rect = (x + col * (sw + kg), by + (1 - row) * (kh + kg), sw, kh)
        on, enabled = False, True
        if key == "easy":
            on, enabled = tool == "easy", mode == "OBJECT"
        elif key == "luminous":
            on = sm.look == "LUMINOUS"
        elif key == "clutter":
            on = clutter_hidden(context)
        d = dict(id=key, kind="key", rect=rect, label=text, sub="", tip=TIPS.get(key, ""), on=on, enabled=enabled)
        if i == 0:
            d.update(module="SYSTEM", mx=x)
        items.append(d)
    return items


def over_from_tool(area, region, x, y):
    """The question a tool or Easy mode asks for every mouse event it is about to
    handle. A tool that was started after the keeper sees the mouse first and keeps
    the moves to itself, so this is also where a button stops being lit when the
    mouse has left the deck."""
    on = over(area, region, x, y)
    if not on and STATE["hover"] is not None:
        STATE["hover"] = None
        try:
            area.tag_redraw()
        except Exception:
            pass
    return on


def key_at(items, x, y):
    for it in items:
        rx, ry, rw, rh = it["rect"]
        if rx <= x < rx + rw and ry <= y < ry + rh:
            return it
    return None


# --------------------------------------------------------------------------
# What the buttons do
# --------------------------------------------------------------------------

def say(text):
    STATE.update(msg=text, msg_t=time.time())


def set_clutter(context, hide):
    """Hide or show Blender's own header rows and status bar (the deck stays)."""
    for _a, sp in B.each_view3d(context):
        B._set(sp, "show_region_header", not hide)        # the tool strip goes with it
        if not hide:
            B._set(sp, "show_region_tool_header", True)
    B._set(context.screen, "show_statusbar", not hide)


def run(context, key):
    """Do what the button with this id does. Returns True when something was done."""
    sm = context.scene.simplemesh
    mode = context.mode
    B.crumb("deck: %s (%s)" % (key, mode))
    try:
        if key == "red":
            if mode == "SCULPT":
                if C.needs_setup(context):
                    bpy.ops.simplemesh.clay_start()
                else:
                    bpy.ops.simplemesh.clay_done()
            elif mode != "OBJECT":
                bpy.ops.simplemesh.back()
            elif active_tool() and active_tool() != "easy":
                bpy.ops.simplemesh.tool(name=active_tool())          # the same tool again = finish it
            elif C.target(context) is None:
                say("Click the model you want to mould first")
                return False
            else:
                bpy.ops.simplemesh.clay_start()
        elif key == "find":
            bpy.ops.simplemesh.frame(everything=False)
        elif key == "open":
            bpy.ops.simplemesh.import_stl("INVOKE_DEFAULT")
        elif key == "save":
            bpy.ops.simplemesh.export_stl("INVOKE_DEFAULT")
        elif key == "undo":
            bpy.ops.ed.undo()
        elif key == "redo":
            bpy.ops.ed.redo()
        elif key.startswith("b:"):
            bpy.ops.simplemesh.clay_brush(key=key[2:])
        elif key == "bigger":
            C.resize(context, 1.25)
            say("brush %.4g mm" % (C.get_radius(context) or 0.0))
        elif key == "smaller":
            C.resize(context, 0.8)
            say("brush %.4g mm" % (C.get_radius(context) or 0.0))
        elif key == "mirror":
            sm.clay_mirror = not sm.clay_mirror
        elif key == "easy":
            bpy.ops.simplemesh.tool(name="easy")
        elif key == "luminous":
            sm.look = "CLEAN" if sm.look == "LUMINOUS" else "LUMINOUS"
        elif key == "clutter":
            set_clutter(context, not clutter_hidden(context))
        elif key == "more":
            bpy.ops.wm.call_menu(name="SM_MT_more")
        elif key in I.TOOL_TIPS:
            bpy.ops.simplemesh.tool(name=key)
        else:
            return False
    except Exception as ex:  # noqa: BLE001
        B.note_error("panel button %s" % key)
        text = str(ex).strip().splitlines()[-1] if str(ex).strip() else "that did not work"
        say(text.replace("Error: ", "")[:90])
        return False
    return True


class SM_MT_look(Menu):
    bl_idname = "SM_MT_look"
    bl_label = "Look"

    def draw(self, context):
        lay = self.layout
        sm = context.scene.simplemesh
        lay.prop_enum(sm, "look", "LUMINOUS")
        lay.prop_enum(sm, "look", "CLEAN")
        lay.prop_enum(sm, "look", "DEFAULT")
        lay.separator()
        lay.prop(sm, "look_rainbow")
        lay.prop(sm, "show_edges")
        lay.prop(sm, "show_xray")
        lay.prop(sm, "show_flipped")
        lay.prop(sm, "show_dims")


class SM_MT_more(Menu):
    bl_idname = "SM_MT_more"
    bl_label = "More tools"

    def draw(self, context):
        lay = self.layout
        lay.operator_context = "INVOKE_DEFAULT"
        for panel, text, icon in (("SM_PT_pop_numbers", "Exact numbers...", "DRIVER_DISTANCE"),
                                  ("SM_PT_pop_shapes", "Shapes, holes, joining...", "MESH_CUBE"),
                                  ("SM_PT_pop_repair", "Check and repair...", "CHECKMARK"),
                                  ("SM_PT_pop_view", "View and settings...", "HIDE_OFF")):
            op = lay.operator("wm.call_panel", text=text, icon=B.ico(icon))
            op.name = panel
            op.keep_open = True
        lay.separator()
        lay.menu("SM_MT_look", text="Look", icon=B.ico("SHADING_RENDERED"))
        p = B.prefs(context)
        if not isinstance(p, B._DefaultPrefs):
            lay.prop(p, "show_deck", text="Big-button panel")
        lay.separator()
        lay.operator("simplemesh.setup", text="Tidy this window")
        lay.operator("simplemesh.report", text="Report a problem (copies the details)", icon=B.ico("ERROR"))


# --------------------------------------------------------------------------
# The keeper: takes the clicks that land on the deck
# --------------------------------------------------------------------------

def _redraw(context):
    try:
        for w in context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == "VIEW_3D":
                    a.tag_redraw()
    except Exception:
        pass


class SIMPLEMESH_OT_deck(Operator):
    """Watches the mouse for the big-button panel at the top of the 3D view"""
    bl_idname = "simplemesh.deck"
    bl_label = "SimpleMesh panel"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        if context.window is None:
            return {"CANCELLED"}
        self.wptr = context.window.as_pointer()
        self.token = object()
        KEEP[self.wptr] = self.token
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        return self.invoke(context, None)

    def find(self, context, event):
        """(area, region, x, y) when the mouse is on the deck of a 3D view of this window."""
        try:
            areas = context.window.screen.areas
        except Exception:
            return None
        ex, ey = event.mouse_x, event.mouse_y
        for area in areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is None:
                continue
            x, y = ex - region.x, ey - region.y
            if not (0 <= x < region.width and 0 <= y < region.height):
                continue
            for r in area.regions:          # a sidebar or header drawn over the view comes first
                if r.type != "WINDOW" and r.width > 1 and r.height > 1 and \
                        r.x <= ex < r.x + r.width and r.y <= ey < r.y + r.height:
                    return None
            return (area, region, x, y) if over(area, region, x, y) else None
        return None

    def modal(self, context, event):
        if KEEP.get(self.wptr) is not self.token:
            return {"FINISHED", "PASS_THROUGH"}
        et, ev = event.type, event.value
        B.note_input(event)
        if et.startswith("TIMER") or not shown(context):
            return {"PASS_THROUGH"}
        try:
            got = self.find(context, event)
            if got is None:
                if STATE["hover"] is not None:
                    STATE["hover"] = None
                    _redraw(context)
                if et == "LEFTMOUSE" and ev == "RELEASE" and STATE["pressed"] is not None:
                    STATE["pressed"] = None             # pressed a button, let go somewhere else
                    _redraw(context)
                    return {"RUNNING_MODAL"}
                return {"PASS_THROUGH"}
            area, region, x, y = got
            it = key_at(layout(area, region, context), x, y)
            hov = (area.as_pointer(), it["id"]) if it is not None and it["enabled"] else None
            if hov != STATE["hover"]:
                STATE.update(hover=hov, x=x)
                area.tag_redraw()
            if et != "LEFTMOUSE":
                return {"PASS_THROUGH"}
            B.note_event(event)
            if ev in ("PRESS", "DOUBLE_CLICK"):         # (a quick second click arrives as DOUBLE_CLICK)
                STATE["pressed"] = it["id"] if hov else "plate"
                area.tag_redraw()
                return {"RUNNING_MODAL"}
            if ev == "RELEASE":
                pressed, STATE["pressed"] = STATE["pressed"], None
                if pressed is None:
                    return {"PASS_THROUGH"}             # a drag that started in the view ends here
                if hov and it["id"] == pressed:
                    with context.temp_override(window=context.window, area=area, region=region):
                        run(bpy.context, pressed)
                _redraw(context)
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}                    # CLICK, CLICK_DRAG... on the deck
        except Exception:
            B.note_error("panel: mouse handling")
            STATE["pressed"] = None
            return {"PASS_THROUGH"}


def _ensure_timer():
    try:
        ctx = bpy.context
        if not shown(ctx):
            return None
        for w in ctx.window_manager.windows:
            if w.as_pointer() in KEEP:
                continue
            for a in w.screen.areas:
                if a.type != "VIEW_3D":
                    continue
                r = next((q for q in a.regions if q.type == "WINDOW"), None)
                if r is None:
                    continue
                with ctx.temp_override(window=w, area=a, region=r):
                    bpy.ops.simplemesh.deck("INVOKE_DEFAULT")
                B.crumb("deck: keeper started")
                break
    except Exception:
        B.note_error("panel: starting the keeper")
    return None


def ensure():
    """Make sure a keeper is watching every window that shows a 3D view. Safe while drawing."""
    try:
        if not bpy.app.timers.is_registered(_ensure_timer):
            bpy.app.timers.register(_ensure_timer, first_interval=0.1, persistent=True)
    except Exception:
        pass


def forget_keepers():
    """After a file is loaded Blender has dropped every running operator."""
    KEEP.clear()
    STATE.update(hover=None, pressed=None)


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

def _poly(pts, col):
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    tris = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        tris += [(cx, cy, 0), (a[0], a[1], 0), (b[0], b[1], 0)]
    I._batch("TRIS", tris, col)


def _rect(x, y, w, h, col):
    I._batch("TRIS", [(x, y, 0), (x + w, y, 0), (x + w, y + h, 0), (x, y, 0), (x + w, y + h, 0), (x, y + h, 0)], col)


def _rrect(x, y, w, h, r, col, seg=5):
    r = max(0.0, min(r, w / 2.0, h / 2.0))
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90.0 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    _poly(pts, col)


def _circle(cx, cy, r, col, n=20):
    _poly([(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)], col)


def _clip_x(poly, x0, x1):
    """Cut a polygon to the band x0 <= x <= x1."""
    for bound, keep_right in ((x0, True), (x1, False)):
        out = []
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            ina = a[0] >= bound if keep_right else a[0] <= bound
            inb = b[0] >= bound if keep_right else b[0] <= bound
            if ina:
                out.append(a)
            if ina != inb and b[0] != a[0]:
                t = (bound - a[0]) / (b[0] - a[0])
                out.append((bound, a[1] + t * (b[1] - a[1])))
        poly = out
        if len(poly) < 3:
            return []
    return poly


def _tape(x, y, w, h, u):
    """Yellow and black caution tape filling a rectangle."""
    _rrect(x, y, w, h, 7 * u, (1.0, 0.80, 0.0, 1.0))
    step = 16 * u
    k = -h
    while k < w:
        poly = _clip_x([(x + k, y), (x + k + step / 2.0, y), (x + k + step / 2.0 + h, y + h), (x + k + h, y + h)], x, x + w)
        if poly:
            _poly(poly, (0.06, 0.06, 0.06, 1.0))
        k += step


def _label(cx, cy, s, size, col, u):
    """Text centred on (cx, cy); the size is shrunk to the deck's scale."""
    f = u / I.ui_scale()
    I.text(cx, cy - size * 0.36 * u, s, size * f, col, centre=True, box=False)


def theme(context):
    lum = context.scene.simplemesh.look == "LUMINOUS"
    if lum:
        return dict(plate=(0.085, 0.095, 0.115, 0.97), hi=(0.13, 0.145, 0.17, 0.97), lo=(0.05, 0.055, 0.07, 0.97),
                    engrave=(0.42, 0.52, 0.60), key=(0.17, 0.19, 0.225, 1.0), key_hot=(0.25, 0.29, 0.34, 1.0),
                    key_edge=(0.02, 0.025, 0.03, 1.0), text=(0.86, 0.94, 1.0), dim=(0.40, 0.44, 0.50),
                    led=(0.0, 0.92, 1.0, 1.0), led_off=(0.06, 0.09, 0.11, 1.0), screw=(0.30, 0.33, 0.38, 1.0))
    return dict(plate=(0.70, 0.72, 0.745, 0.98), hi=(0.80, 0.82, 0.84, 0.98), lo=(0.57, 0.59, 0.62, 0.98),
                engrave=(0.30, 0.32, 0.35), key=(0.91, 0.92, 0.93, 1.0), key_hot=(1.0, 1.0, 1.0, 1.0),
                key_edge=(0.33, 0.35, 0.38, 1.0), text=(0.10, 0.11, 0.13), dim=(0.55, 0.57, 0.60),
                led=(0.15, 0.85, 0.25, 1.0), led_off=(0.45, 0.47, 0.50, 1.0), screw=(0.45, 0.47, 0.50, 1.0))


def _draw_item(it, T, u, hot, down):
    x, y, w, h = it["rect"]
    kind = it["kind"]
    if kind == "red":
        _tape(x, y, w, h, u)
        m = 7 * u
        col = (0.93, 0.13, 0.11, 1.0) if hot else (0.80, 0.07, 0.07, 1.0)
        if down:
            col = (0.60, 0.04, 0.04, 1.0)
        _rrect(x + m, y + m, w - 2 * m, h - 2 * m, 6 * u, (0.35, 0.0, 0.0, 1.0))
        _rrect(x + m + 2 * u, y + m + 2 * u, w - 2 * m - 4 * u, h - 2 * m - 4 * u, 5 * u, col)
        _rect(x + m + 8 * u, y + h - m - 9 * u, w - 2 * m - 16 * u, 3 * u, (1.0, 1.0, 1.0, 0.18))       # gloss
        size = 15 if len(it["label"]) <= 18 else 12.5
        _label(x + w / 2.0, y + h / 2.0 + 6 * u, it["label"], size, (1.0, 1.0, 1.0), u)
        _label(x + w / 2.0, y + h / 2.0 - 11 * u, it["sub"], 9.5, (1.0, 0.82, 0.80), u)
    elif kind == "badge":
        _rrect(x, y, w, h, 8 * u, (0.10, 0.25, 0.02, 1.0))
        _rrect(x + 2 * u, y + 2 * u, w - 4 * u, h - 4 * u, 7 * u, (0.55, 1.0, 0.08, 1.0))
        _rect(x + 9 * u, y + h - 10 * u, w - 18 * u, 3 * u, (1.0, 1.0, 1.0, 0.35))
        size = 13 if len(it["label"]) <= 16 else 10.5
        _label(x + w / 2.0, y + h / 2.0 + 5 * u, it["label"], size, (0.03, 0.10, 0.0), u)
        _label(x + w / 2.0, y + h / 2.0 - 11 * u, it["sub"], 9.5, (0.08, 0.30, 0.0), u)
    elif kind == "find":
        ring = ((1.0, 0.30, 0.25), (1.0, 0.80, 0.0), (0.25, 0.85, 0.35), (0.25, 0.55, 1.0))
        _rrect(x, y, w, h, 8 * u, (1.0, 0.85, 0.2, 1.0) if hot else (0.45, 0.35, 0.9, 1.0))
        _rrect(x + 2 * u, y + 2 * u, w - 4 * u, h - 4 * u, 7 * u, (0.05, 0.06, 0.10, 1.0) if not down else (0.0, 0.0, 0.0, 1.0))
        cx, cy, r = x + 26 * u, y + h / 2.0, 13 * u
        for i, c in enumerate(ring):
            a0 = math.radians(90 * i + 8)
            a1 = math.radians(90 * i + 82)
            pts = [(cx + r * math.cos(a0 + (a1 - a0) * j / 6.0), cy + r * math.sin(a0 + (a1 - a0) * j / 6.0)) for j in range(7)]
            I._batch("LINE_STRIP", [(p[0], p[1], 0) for p in pts], c + (1.0,), 3.0)
        I._batch("LINES", [(cx - r - 4 * u, cy, 0), (cx + r + 4 * u, cy, 0), (cx, cy - r - 4 * u, 0), (cx, cy + r + 4 * u, 0)],
                 (1.0, 1.0, 1.0, 0.9), 1.5)
        _circle(cx, cy, 3 * u, (1.0, 1.0, 1.0, 1.0))
        _label(x + w / 2.0 + 18 * u, cy + 7 * u, it["label"], 13, (1.0, 1.0, 1.0), u)
        _label(x + w / 2.0 + 18 * u, cy - 9 * u, it["sub"], 10.5, (0.75, 0.85, 1.0), u)
    else:
        en = it["enabled"]
        face = T["key_hot"] if (hot and en) else T["key"]
        if down and en:
            face = T["led"][:3] + (0.55,)
        _rrect(x, y, w, h, 4 * u, T["key_edge"])
        _rrect(x + 1.5 * u, y + 1.5 * u, w - 3 * u, h - 3 * u, 3 * u, face)
        led = T["led"] if it["on"] else T["led_off"]
        if it["on"]:
            _circle(x + 9 * u, y + h / 2.0, 5.5 * u, led[:3] + (0.30,))        # glow
        _circle(x + 9 * u, y + h / 2.0, 3.2 * u, led)
        _label(x + w / 2.0 + 5 * u, y + h / 2.0, it["label"], 11, T["text"] if en else T["dim"], u)


def draw():
    """POST_PIXEL draw handler of every 3D view."""
    try:
        context = bpy.context
        if not shown(context):
            return
        area, region = context.area, context.region
        if area is None or region is None or region.type != "WINDOW" or area.type != "VIEW_3D":
            return
        if context.window is not None and context.window.as_pointer() not in KEEP:
            ensure()
        u = I.ui_scale() * fit(region)
        T = theme(context)
        px, py, pw, ph = plate(area, region)
        _rect(px, py - 3 * u, pw, 3 * u, (0.0, 0.0, 0.0, 0.35))                 # shadow under the plate
        _rect(px, py, pw, ph, T["plate"])
        _rect(px, py + ph - 5 * u, pw, 5 * u, T["hi"])
        _rect(px, py, pw, 3 * u, T["lo"])
        for i in range(1, 6):                                                    # a hint of brushed grain
            _rect(px, py + ph * i / 6.0, pw, 1.0, T["hi"][:3] + (0.25,))
        for sx, sy in ((px + 7 * u, py + 7 * u), (px + 7 * u, py + ph - 7 * u), (px + pw - 7 * u, py + 7 * u),
                       (px + pw - 7 * u, py + ph - 7 * u)):
            _circle(sx, sy, 3.2 * u, T["screw"], 10)
            I._batch("LINES", [(sx - 2.2 * u, sy - 1.2 * u, 0), (sx + 2.2 * u, sy + 1.2 * u, 0)], T["lo"][:3] + (1.0,), 1.0)
        items = layout(area, region, context)
        hov = STATE["hover"]
        aptr = area.as_pointer()
        tip = ""
        for it in items:
            hot = hov is not None and hov[0] == aptr and hov[1] == it["id"]
            _draw_item(it, T, u, hot, hot and STATE["pressed"] == it["id"])
            if "module" in it:
                f = u / I.ui_scale()
                I.text(it["mx"] + 2 * u, py + ph - 14.5 * u, it["module"], 8.5 * f, T["engrave"], box=False)
            if hot:
                tip = it["tip"]
        s = I.ui_scale()
        tx = max(px + 16 * s, min(STATE["x"] - 40 * s, px + pw - 520 * s))       # under the button, kept on the plate
        keep, I.BOX[0] = I.BOX[0], 0.97            # a solid box: it lies over the size read-out for a moment
        if STATE["msg"] and time.time() - STATE["msg_t"] < 4.0:
            I.text(tx, py - 30 * s, STATE["msg"], 15, I.AMBER)
        elif tip:
            I.text(tx, py - 30 * s, tip[:110], 14, I.WHITE)
        I.BOX[0] = keep
    except Exception:
        B.note_error("drawing the panel")


CLASSES = (SM_MT_look, SM_MT_more, SIMPLEMESH_OT_deck)
_handles = []


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    I.DECK.update(height=height, over=over_from_tool)
    forget_keepers()
    if not bpy.app.background:
        _handles.append(bpy.types.SpaceView3D.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL"))


def unregister():
    I.DECK.update(height=None, over=None)
    forget_keepers()                      # the keepers end by themselves on their next event
    for h in _handles:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
        except Exception:
            pass
    _handles.clear()
    try:
        if bpy.app.timers.is_registered(_ensure_timer):
            bpy.app.timers.unregister(_ensure_timer)
    except Exception:
        pass
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)

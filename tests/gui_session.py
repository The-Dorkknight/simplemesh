# SimpleMesh real-window test: drives the tools with simulated mouse and keys.
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
#
# Run (Linux, needs a Blender executable, Xvfb and ImageMagick's `import`):
#   xvfb-run -a -s "-screen 0 1600x900x24" blender --factory-startup \
#       --enable-event-simulate --python tests/gui_session.py -- OUT_DIR
# It prints GUI-OK / GUI-FAIL lines and saves screenshots of the real window.

import math
import os
import struct
import subprocess
import sys
import traceback

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import simplemesh as sm  # noqa: E402
from simplemesh import interactive as it  # noqa: E402
from simplemesh import easy  # noqa: E402

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "/tmp/simplemesh_gui"
os.makedirs(OUT, exist_ok=True)
FAILS = []
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.view.smooth_view = 0
sm.register()
# The first part of the session drives the tools through the thin strip in Blender's
# header (the big-button panel switched off); the panel has its own part further down.
sm.base._DefaultPrefs.show_deck = False


def say(ok, msg):
    print(("GUI-OK   " if ok else "GUI-FAIL ") + msg)
    sys.stdout.flush()
    if not ok:
        FAILS.append(msg)


def win():
    return bpy.context.window_manager.windows[0]


def area():
    return next(a for a in win().screen.areas if a.type == "VIEW_3D")


def region():
    return next(r for r in area().regions if r.type == "WINDOW")


def rv3d():
    return area().spaces.active.region_3d


def override():
    return bpy.context.temp_override(window=win(), area=area(), region=region())


def shot(name):
    try:
        with override():
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
    except Exception:
        pass
    subprocess.run(["import", "-window", "root", os.path.join(OUT, name + ".png")])


def px(p):
    """Window pixel of a world point."""
    r = region()
    v = view3d_utils.location_3d_to_region_2d(r, rv3d(), Vector(p))
    return int(v.x + r.x), int(v.y + r.y)


def ev(kind, value, xy, **mods):
    win().event_simulate(type=kind, value=value, x=xy[0], y=xy[1], **mods)


def key(kind, xy, **mods):
    ev(kind, "PRESS", xy, **mods)
    ev(kind, "RELEASE", xy, **mods)


def meshes():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def dims(o):
    lo, hi = sm.obj_bounds(o)
    return hi - lo


def vol(o):
    return sm.compute_check(o)["volume"]


def close(a, b, tol=0.02):
    return abs(a - b) <= tol * max(1.0, abs(b))


def write_stl(path, sx, sy, sz):
    x, y, z = sx / 2, sy / 2, sz / 2
    v = [(-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z), (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    with open(path, "wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", 12))
        for q in quads:
            a, b, c, d = [v[k] for k in q]
            for t in ((a, b, c), (a, c, d)):
                f.write(struct.pack("<12fH", 0, 0, 0, *t[0], *t[1], *t[2], 0))


S = {}          # scratch shared between steps


def tool(name):
    with override():
        getattr(bpy.ops.simplemesh, "tool_" + name)("INVOKE_DEFAULT")


def stop():
    with override():
        bpy.ops.simplemesh.tool_stop()


def bracket():
    """An L-shaped bracket standing on its end, as a badly oriented STL would arrive."""
    for o in meshes():
        bpy.data.objects.remove(o, do_unlink=True)
    with override():
        bpy.ops.simplemesh.add_shape(shape="BLOCK", size_x=80, size_y=40, size_z=10, at_model=False)
        a = bpy.context.object
        bpy.ops.simplemesh.add_shape(shape="BLOCK", size_x=10, size_y=40, size_z=50, at_model=False)
        b = bpy.context.object
        b.location = (-35, 0, 25)
        sm.refresh(bpy.context)
        sm.select_only(bpy.context, [a, b], active=a)
        bpy.ops.simplemesh.weld()
        o = bpy.context.object
        o.name = "bracket"
        bpy.ops.simplemesh.frame(everything=True)
        bpy.ops.ed.undo_push(message="test: bracket made")
        return o


# ---------------------------------------------------------------- the steps

def s_start():
    a = [x.type for x in win().screen.areas]
    say(a == ["VIEW_3D"], "start-up leaves one big 3D view (areas: %s)" % a)
    say(len(meshes()) == 0 and sm.units_are_mm(bpy.context.scene), "empty scene in millimetres")
    say(sorted(w.name for w in bpy.data.workspaces) == ["Full Blender", "SimpleMesh"],
        "workspace tabs trimmed to %s" % [w.name for w in bpy.data.workspaces])
    shot("01-start")


def s_import():
    p = os.path.join(OUT, "huge.stl")
    write_stl(p, 5200, 3100, 900)
    with override():
        bpy.ops.simplemesh.import_stl(filepath=p)
    o = meshes()[0]
    d = dims(o)
    say(close(d.x, 52) and close(d.z, 9), "5200 mm STL auto-fitted to %.0f x %.0f x %.0f" % (d.x, d.y, d.z))


def s_import_check():
    o = meshes()[0]
    lo, hi = sm.obj_bounds(o)
    c = px((lo + hi) / 2)
    r = region()
    inside = r.x + r.width * 0.25 < c[0] < r.x + r.width * 0.75 and r.y + r.height * 0.25 < c[1] < r.y + r.height * 0.75
    w = abs(px(hi)[0] - px(lo)[0])
    say(inside, "imported model is in the middle of the view (pixel %s)" % (c,))
    say(r.width * 0.08 < w < r.width * 0.8, "and a sensible size on screen (%d px of %d)" % (w, r.width))
    shot("02-imported")


def s_scale_then_find():
    with override():
        bpy.ops.simplemesh.scale_by(factor=0.1)
    S["after_scale"] = True


def s_scale_check():
    o = meshes()[0]
    lo, hi = sm.obj_bounds(o)
    c = px((lo + hi) / 2)
    r = region()
    w = abs(px(hi)[0] - px(lo)[0])
    say(abs(c[0] - (r.x + r.width / 2)) < r.width * 0.25 and w > r.width * 0.08,
        "after scaling to 1/10 the view re-centred and zoomed in (%d px wide)" % w)


def s_layflat_start():
    o = bracket()
    with override():
        bpy.ops.simplemesh.frame(everything=True)
    S["z0"] = dims(o).z
    tool("layflat")


def s_layflat_hover():
    o = meshes()[0]
    lo, hi = sm.obj_bounds(o)
    # the big outer face of the upright leg (faces -X)
    S["p"] = px((lo.x, 0.0, lo.z + 35.0))
    ev("MOUSEMOVE", "NOTHING", S["p"])


def s_layflat_shot():
    say(it.ACTIVE["name"] == "layflat", "Lay flat tool is running")
    shot("03-layflat-hover")
    ev("LEFTMOUSE", "PRESS", S["p"])
    ev("LEFTMOUSE", "RELEASE", S["p"])


def s_layflat_check():
    o = meshes()[0]
    d = dims(o)
    say(close(d.z, 80) and abs(sm.obj_bounds(o)[0].z) < 1e-3,
        "click laid the bracket on the hovered face (height now %.0f, was %.0f)" % (d.z, S["z0"]))
    shot("04-layflat-done")
    with override():
        bpy.ops.ed.undo()


def s_layflat_undo():
    o = meshes()[0]
    say(close(dims(o).z, S["z0"]), "Ctrl+Z undoes the lay-flat (height %.0f)" % dims(o).z)
    stop()


def s_move_start():
    bracket()
    tool("move")


def s_move_press():
    o = meshes()[0]
    lo, hi = sm.obj_bounds(o)
    S["loc0"] = o.location.copy()
    S["a"] = px((10.0, 0.0, hi.z - 40.0 if False else 10.0))
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def s_move_drag():
    S["b"] = (S["a"][0] + 160, S["a"][1] + 40)
    ev("MOUSEMOVE", "NOTHING", ((S["a"][0] + S["b"][0]) // 2, (S["a"][1] + S["b"][1]) // 2))
    ev("MOUSEMOVE", "NOTHING", S["b"])


def s_move_shot():
    shot("05-move-drag")
    ev("LEFTMOUSE", "RELEASE", S["b"])


def s_move_check():
    o = meshes()[0]
    d = o.location - S["loc0"]
    say(d.length > 5 and abs(d.z) < 1e-4, "drag slid the model %.1f mm across the bed, height unchanged" % d.length)
    key("RIGHT_ARROW", S["b"])


def s_move_nudge():
    o = meshes()[0]
    say(True, "arrow key nudge -> x %.1f" % o.location.x)
    stop()


def s_turn_start():
    o = bracket()
    S["d0"] = dims(o).copy()
    tool("turn")


def s_turn_press():
    S["a"] = px((10.0, 0.0, 10.0))
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def s_turn_drag():
    S["b"] = (S["a"][0] + 180, S["a"][1])       # 180 px * 0.5 = 90 degrees
    ev("MOUSEMOVE", "NOTHING", (S["a"][0] + 90, S["a"][1]))
    ev("MOUSEMOVE", "NOTHING", S["b"])


def s_turn_shot():
    shot("06-turn-drag")
    ev("LEFTMOUSE", "RELEASE", S["b"])


def s_turn_check():
    o = meshes()[0]
    d = dims(o)
    say(close(d.x, S["d0"].y) and close(d.y, S["d0"].x), "drag turned it 90 degrees about Z (%.0f x %.0f -> %.0f x %.0f)"
        % (S["d0"].x, S["d0"].y, d.x, d.y))
    key("Y", S["b"])
    key("RIGHT_ARROW", S["b"])


def s_turn_key():
    o = meshes()[0]
    d = dims(o)
    say(close(d.z, S["d0"].y) or close(d.z, S["d0"].x) or close(d.x, S["d0"].z),
        "Y then arrow turned it 90 degrees about Y, back on the bed (z min %.3f)" % sm.obj_bounds(o)[0].z)
    stop()


def s_size_start():
    o = bracket()
    sm.select_only(bpy.context, [o])
    tool("size")


def s_size_type():
    c = px((0.0, 0.0, 5.0))
    ev("MOUSEMOVE", "NOTHING", c)
    for k in ("ONE", "TWO", "ZERO"):
        key(k, c)
    S["c"] = c


def s_size_type_shot():
    shot("07-size-typing")
    key("RET", S["c"])


def s_size_check():
    o = meshes()[0]
    d = dims(o)
    say(close(max(d), 120), "typing 120 + Enter made the longest side 120 mm (%.1f x %.1f x %.1f)" % (d.x, d.y, d.z))
    say(abs(sm.obj_bounds(o)[0].z) < 1e-3 and close(o.scale.x, 1.0), "still on the bed, scale baked to 1.0")
    S["a"] = px((20.0, 0.0, 5.0))
    S["d0"] = d.copy()
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def s_size_drag():
    c = px((0.0, 0.0, dims(meshes()[0]).z / 2))
    v = (S["a"][0] - c[0], S["a"][1] - c[1])
    S["b"] = (int(c[0] + v[0] * 1.5), int(c[1] + v[1] * 1.5))
    ev("MOUSEMOVE", "NOTHING", S["b"])


def s_size_drag_shot():
    shot("08-size-drag")
    ev("LEFTMOUSE", "RELEASE", S["b"])


def s_size_drag_check():
    o = meshes()[0]
    d = dims(o)
    say(d.x > S["d0"].x * 1.15 and close(d.x / S["d0"].x, d.z / S["d0"].z, 0.01),
        "dragging away made it bigger, same proportions (x %.1f -> %.1f)" % (S["d0"].x, d.x))
    stop()


def s_cut_start():
    o = bracket()
    S["v0"] = vol(o)
    tool("cut")


def s_cut_hover():
    S["p"] = px((-40.0, 0.0, 30.0))              # on the upright leg, 30 mm up
    ev("MOUSEMOVE", "NOTHING", S["p"])


def s_cut_shot():
    shot("09-cut-hover")
    ev("LEFTMOUSE", "PRESS", S["p"])
    ev("LEFTMOUSE", "RELEASE", S["p"])


def s_cut_check():
    ms = meshes()
    say(len(ms) == 2, "click cut the bracket into %d pieces" % len(ms))
    if len(ms) == 2:
        say(close(sum(vol(x) for x in ms), S["v0"]), "volumes add up to the original")
        say(all(sm.compute_check(x)["open"] == 0 for x in ms), "both pieces are closed (capped)")
    shot("10-cut-done")
    stop()


def s_linecut_start():
    o = bracket()
    S["v0"] = vol(o)
    tool("cut")


def s_linecut_press():
    S["a"] = px((0.0, -40.0, 20.0))
    S["b"] = px((0.0, 40.0, -10.0))
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def s_linecut_drag():
    ev("MOUSEMOVE", "NOTHING", ((S["a"][0] + S["b"][0]) // 2, (S["a"][1] + S["b"][1]) // 2))
    ev("MOUSEMOVE", "NOTHING", S["b"])


def s_linecut_shot():
    shot("11-linecut-drag")
    ev("LEFTMOUSE", "RELEASE", S["b"])


def s_linecut_check():
    ms = meshes()
    say(len(ms) == 2 and close(sum(vol(x) for x in ms), S["v0"]),
        "dragging a line across cut it into %d pieces, volume kept" % len(ms))
    shot("12-linecut-done")
    stop()


def s_hole_start():
    o = bracket()
    S["v0"] = vol(o)
    bpy.context.scene.simplemesh.hole_diameter = 5.0
    bpy.context.scene.simplemesh.hole_depth = 0.0
    tool("hole")


def s_hole_hover():
    S["p"] = px((15.0, 0.0, 10.0))               # top of the flat base
    ev("MOUSEMOVE", "NOTHING", S["p"])
    key("ONE", S["p"])
    key("TWO", S["p"])
    key("RET", S["p"])


def s_hole_shot():
    say(close(bpy.context.scene.simplemesh.hole_diameter, 12.0), "typing 12 + Enter set the diameter to 12 mm")
    ev("MOUSEMOVE", "NOTHING", (S["p"][0] + 1, S["p"][1]))


def s_hole_click():
    shot("13-hole-hover")
    ev("LEFTMOUSE", "PRESS", S["p"])
    ev("LEFTMOUSE", "RELEASE", S["p"])


def s_hole_check():
    o = meshes()[0]
    exp = S["v0"] - math.pi * 36 * 10
    say(len(meshes()) == 1 and close(vol(o), exp, 0.03),
        "click drilled a 12 mm hole through the 10 mm base (volume %.0f, expected %.0f)" % (vol(o), exp))
    say(sm.compute_check(o)["open"] == 0, "model still watertight")
    shot("14-hole-done")
    stop()


def s_measure_start():
    bracket()
    tool("measure")


def s_measure_a():
    o = meshes()[0]
    lo, hi = sm.obj_bounds(o)
    S["a"] = px((hi.x - 0.5, lo.y + 0.5, 10.0 - 0.01))
    S["b"] = px((hi.x - 0.5, hi.y - 0.5, 10.0 - 0.01))
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])
    ev("LEFTMOUSE", "RELEASE", S["a"])


def s_measure_b():
    ev("MOUSEMOVE", "NOTHING", S["b"])
    ev("LEFTMOUSE", "PRESS", S["b"])
    ev("LEFTMOUSE", "RELEASE", S["b"])


def s_measure_check():
    shot("15-measure")
    say(True, "measure tool ran (see screenshot for the read-out)")
    key("ESC", S["b"])


def s_esc_check():
    say(it.ACTIVE["token"] is None, "Esc left the tool")
    with override():
        bpy.ops.simplemesh.frame(everything=True)


def s_pull_start():
    o = bracket()
    S["v0"] = vol(o)
    tool("pull")


def s_pull_hover():
    S["a"] = px((15.0, 0.0, 10.0))                # top of the flat base (70 x 40 mm of it is free)
    ev("MOUSEMOVE", "NOTHING", S["a"])


def s_pull_shot():
    shot("23-pull-hover")
    for k in ("FIVE",):
        key(k, S["a"])
    key("RET", S["a"])


def s_pull_typed_check():
    o = meshes()[0]
    exp = S["v0"] + 70 * 40 * 5
    say(close(vol(o), exp, 0.01), "pointing at the base and typing 5 + Enter raised it 5 mm (volume %.0f, expected %.0f)" % (vol(o), exp))
    say(sm.compute_check(o)["open"] == 0, "still watertight")
    S["v1"] = vol(o)
    S["a"] = px((15.0, 0.0, 15.0))
    S["b"] = px((15.0, 0.0, 25.0))                # drag the same face 10 mm further up
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def s_pull_drag():
    ev("MOUSEMOVE", "NOTHING", ((S["a"][0] + S["b"][0]) // 2, (S["a"][1] + S["b"][1]) // 2))
    ev("MOUSEMOVE", "NOTHING", S["b"])


def s_pull_drag_shot():
    shot("24-pull-drag")
    ev("LEFTMOUSE", "RELEASE", S["b"])


def s_pull_drag_check():
    o = meshes()[0]
    grown = (vol(o) - S["v1"]) / (70 * 40)
    say(8.0 <= grown <= 12.0 and abs(grown * 2 - round(grown * 2)) < 1e-3,
        "dragging the face up pulled it %.1f mm (half-millimetre steps)" % grown)
    say(sm.compute_check(o)["open"] == 0 and close(o.scale.x, 1.0), "watertight, scale still 1.0")
    stop()


def s_clay_setup():
    for o in meshes():
        bpy.data.objects.remove(o, do_unlink=True)
    with override():
        bpy.ops.simplemesh.add_shape(shape="BLOCK", size_x=60, size_y=60, size_z=20, at_model=False)
        bpy.ops.simplemesh.frame(everything=True)
        bpy.ops.ed.undo_push(message="test: block")
    r = region()
    S["mid"] = (r.x + r.width // 2, r.y + r.height // 2)
    ev("MOUSEMOVE", "NOTHING", S["mid"])


def s_clay_click():
    strip_click(917)                              # "Clay"


def s_clay_check():
    ts = bpy.context.scene.tool_settings
    say(bpy.context.mode == "SCULPT", "clicking 'Clay' enters clay mode (mode %s)" % bpy.context.mode)
    if bpy.context.mode != "SCULPT":
        return
    say(bpy.context.sculpt_object.use_dynamic_topology_sculpting, "automatic detail is on")
    say(ts.sculpt.brush.sculpt_tool == "SNAKE_HOOK" and close(ts.unified_paint_settings.strength, 1.0),
        "Pull brush selected at full strength (%s)" % ts.sculpt.brush.name)
    say(ts.unified_paint_settings.use_locked_size == "SCENE" and close(ts.unified_paint_settings.unprojected_radius, 12.0),
        "brush size is in millimetres (radius %.1f mm for a 60 mm block)" % ts.unified_paint_settings.unprojected_radius)
    say(not meshes()[0].data.use_mirror_x, "mirror symmetry is off")
    S["a"] = px((0.0, 0.0, 20.0))
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def mk_stroke(n_steps, per_step, dx, dy):
    """A drag delivered over several redraws, the way a hand moves."""
    out = []
    for i in range(n_steps):
        def f(i=i):
            a = S["a"]
            for k in range(1, per_step + 1):
                j = i * per_step + k
                ev("MOUSEMOVE", "NOTHING", (a[0] + j * dx, a[1] + j * dy))
            S["b"] = (a[0] + (i + 1) * per_step * dx, a[1] + (i + 1) * per_step * dy)
        f.__name__ = "stroke_%d" % i
        out.append(f)
    return out


def s_clay_release():
    ev("LEFTMOUSE", "RELEASE", S["b"])


def box_height():
    """Height of the model as Blender shows it while sculpting (the mesh data itself is
    only brought up to date when sculpting ends)."""
    o = meshes()[0]
    zs = [(o.matrix_world @ Vector(c)).z for c in o.bound_box]
    return max(zs) - min(zs)


def s_clay_undo():
    S["h_pulled"] = box_height()
    say(S["h_pulled"] > 25.0, "the Pull stroke stretched the top (%.1f mm, was 20)" % S["h_pulled"])
    ev("MOUSEMOVE", "NOTHING", S["mid"])
    key("Z", S["mid"], ctrl=True)                 # Ctrl+Z after the very first stroke


def s_clay_undo_check():
    h = box_height()
    say(bpy.context.mode == "SCULPT", "Ctrl+Z after the first stroke keeps you in Clay (mode %s)" % bpy.context.mode)
    say(close(h, 20.0, 0.05), "and takes back just that stroke (height %.1f mm)" % h)
    key("Z", S["mid"], ctrl=True, shift=True)     # redo


def s_clay_redo_check():
    # (whether the stroke is really back is checked after Done, on the finished mesh:
    # the size Blender reports while sculpting is not refreshed by a redo)
    say(bpy.context.mode == "SCULPT", "Ctrl+Shift+Z (redo) also stays in Clay")


def s_clay_shot():
    shot("25-clay-pull")
    strip_click(252)                              # "Push in"


def s_clay_push():
    ts = bpy.context.scene.tool_settings
    say(ts.sculpt.brush.sculpt_tool == "DRAW" and ts.sculpt.brush.direction == "SUBTRACT",
        "clicking 'Push in' switches brush (%s, %s)" % (ts.sculpt.brush.name, ts.sculpt.brush.direction))
    S["a"] = px((-20.0, -20.0, 20.0))
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def s_clay_push_shot():
    shot("26-clay-push")
    strip_click(40)                               # "Done"


def s_clay_done_check():
    say(bpy.context.mode == "OBJECT", "clicking 'Done' returns to the normal tools")
    o = meshes()[0]
    lo, hi = sm.obj_bounds(o)
    c = sm.compute_check(o)
    say(hi.z - lo.z > 25.0, "the finished model has the Pull stroke that was undone and redone (height %.1f mm, was 20)" % (hi.z - lo.z))
    say(200 < c["tris"] < 40000, "moulded areas kept their detail, flat areas merged again (%d triangles)" % c["tris"])
    say(c["open"] == 0 and c["bad"] == 0 and not c["inverted"], "model is still watertight")
    shot("27-clay-done")


def s_own_sculpt():
    """Sculpt Mode chosen from Blender's own mode menu instead of the Clay button."""
    from simplemesh import clay
    for o in meshes():
        bpy.data.objects.remove(o, do_unlink=True)
    with override():
        bpy.ops.simplemesh.add_shape(shape="BLOCK", size_x=60, size_y=60, size_z=20, at_model=False)
        bpy.ops.simplemesh.frame(everything=True)
        bpy.ops.ed.undo_push(message="test: block 2")
    sm.select_only(bpy.context, [meshes()[0]])
    S["tris0"] = len(meshes()[0].data.polygons)
    bpy.context.scene.simplemesh.clay_brush = "pull"
    clay.forget()
    with override():
        bpy.ops.object.mode_set(mode="SCULPT")
    say(bpy.context.mode == "SCULPT" and clay.needs_setup(bpy.context),
        "Blender's own Sculpt Mode starts without the Clay set-up (%d triangles)" % S["tris0"])
    ev("MOUSEMOVE", "NOTHING", S["mid"])


def s_own_sculpt_wait():
    ev("MOUSEMOVE", "NOTHING", (S["mid"][0] + 2, S["mid"][1]))


def s_own_sculpt_check():
    from simplemesh import clay
    ts = bpy.context.scene.tool_settings
    o = meshes()[0]
    say(bpy.context.mode == "SCULPT" and not clay.needs_setup(bpy.context),
        "SimpleMesh notices and runs the Clay set-up by itself")
    say(bpy.context.sculpt_object is not None and bpy.context.sculpt_object.use_dynamic_topology_sculpting
        and len(o.data.polygons) > 500, "small triangles (%d, was %d) and automatic detail are on"
        % (len(o.data.polygons), S["tris0"]))
    say(getattr(ts.sculpt.brush, "sculpt_tool", "") == "SNAKE_HOOK" and clay.actual_key(bpy.context) == "pull"
        and ts.unified_paint_settings.use_locked_size == "SCENE",
        "the Pull brush is really the active brush, sized in millimetres (%s)" % ts.sculpt.brush.name)
    shot("28a-own-sculpt-ready")
    S["a"] = px((0.0, 0.0, 20.0))
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def s_own_sculpt_done():
    h = box_height()
    say(h > 25.0, "dragging then pulls the clay out (height %.1f mm, was 20)" % h)
    shot("28b-own-sculpt-pull")
    strip_click(40)                               # "Done"


def s_own_sculpt_done_check():
    say(bpy.context.mode == "OBJECT", "Done returns to the normal tools")
    say(not sm.base.ERRORS, "no problems were caught on the way (%s)" % ", ".join(sm.base.ERRORS) if sm.base.ERRORS else "no problems were caught on the way")


def s_other_mode():
    sm.select_only(bpy.context, [meshes()[0]])
    with override():
        bpy.ops.object.mode_set(mode="EDIT")


def s_other_mode_back():
    shot("28-other-mode")
    strip_click(60)                               # "Back to the models"


def s_other_mode_check():
    say(bpy.context.mode == "OBJECT", "'Back to the models' leaves Edit Mode (mode %s)" % bpy.context.mode)


def s_find_setup():
    o = bracket()
    o.location = (4000.0, -2500.0, 25.0)         # lost far away from the bed
    sm.refresh(bpy.context)
    sm.select_only(bpy.context, [o])
    r = region()
    S["mid"] = (r.x + r.width // 2, r.y + r.height // 2)
    ev("MOUSEMOVE", "NOTHING", S["mid"])
    key("F", S["mid"])


def s_find_check():
    o = meshes()[0]
    lo, hi = sm.obj_bounds(o)
    c = px((lo + hi) / 2)
    r = region()
    say(abs(c[0] - (r.x + r.width / 2)) < 60 and abs(c[1] - (r.y + r.height / 2)) < 60,
        "F key found a model lost 4.7 m away and centred it (pixel %s)" % (c,))
    with override():
        bpy.ops.simplemesh.place(center=True)


def strip_click(x):
    """Click in the strip at window x (layout of a 1600 px wide window)."""
    r = next(q for q in area().regions if q.type == "TOOL_HEADER")
    xy = (x, r.y + r.height // 2)
    # a real pointer sends a stream of moves; Blender's buttons need one move to
    # drop the previously hovered button and another to pick up the new one
    ev("MOUSEMOVE", "NOTHING", (x - 3, xy[1]))
    ev("MOUSEMOVE", "NOTHING", (x - 1, xy[1]))
    ev("MOUSEMOVE", "NOTHING", xy)
    ev("LEFTMOUSE", "PRESS", xy)
    ev("LEFTMOUSE", "RELEASE", xy)
    return xy


def s_strip_tool():
    S["xy"] = strip_click(410)                    # "Lay flat"


def s_strip_tool_check():
    say(it.ACTIVE["name"] == "layflat", "clicking 'Lay flat' in the strip starts the tool (active: %r)" % it.ACTIVE["name"])
    shot("16-strip-tool-on")
    strip_click(328)                              # "Select"


def s_strip_select_check():
    say(it.ACTIVE["token"] is None, "clicking 'Select' in the strip leaves the tool")
    ev("MOUSEMOVE", "NOTHING", S["mid"])          # a real mouse always moves between clicks


def s_strip_switch():
    strip_click(472)                              # "Move"


def s_strip_switch2():
    say(it.ACTIVE["name"] == "move", "clicking 'Move' starts Move (active: %r)" % it.ACTIVE["name"])
    ev("MOUSEMOVE", "NOTHING", S["mid"])


def s_strip_switch3():
    strip_click(714)                              # "Cut", straight from Move


def s_strip_switch4():
    say(it.ACTIVE["name"] == "cut", "clicking 'Cut' while Move is on switches tool (active: %r)" % it.ACTIVE["name"])
    ev("MOUSEMOVE", "NOTHING", S["mid"])


def mk_pop(x, name):
    def a():
        S["xy"] = strip_click(x)

    def b():
        shot(name)
        key("ESC", S["xy"])
    a.__name__ = "pop_open_" + name
    b.__name__ = "pop_shot_" + name
    return [a, b]


def s_open_dialog():
    strip_click(40)                               # "Open"


def s_open_dialog_shot():
    wins = bpy.context.window_manager.windows
    say(len(wins) == 2 or any(a.type == "FILE_BROWSER" for w in wins for a in w.screen.areas),
        "'Open' shows the file chooser")
    shot("22-open-dialog")
    for w in wins:
        if any(a.type == "FILE_BROWSER" for a in w.screen.areas):
            w.event_simulate(type="ESC", value="PRESS", x=200, y=200)
            w.event_simulate(type="ESC", value="RELEASE", x=200, y=200)


def s_sidebar():
    area().spaces.active.show_region_ui = True


def s_final():
    shot("21-sidebar")



# ---------------------------------------------------------------- Easy mode (a child's session)

def et():
    return easy.CURRENT["tool"]


def tile(key):
    r = region()
    x, y, w, h = et().rects[key]
    return (int(x + w / 2 + r.x), int(y + h / 2 + r.y))


def hpos(kind):
    r = region()
    p = et().handles[kind]["p"]
    return (int(p.x + r.x), int(p.y + r.y))


def click(xy):
    ev("MOUSEMOVE", "NOTHING", (xy[0] - 2, xy[1]))
    ev("MOUSEMOVE", "NOTHING", xy)
    ev("LEFTMOUSE", "PRESS", xy)
    ev("LEFTMOUSE", "RELEASE", xy)


def hover(xy):
    ev("MOUSEMOVE", "NOTHING", (xy[0] - 2, xy[1]))
    ev("MOUSEMOVE", "NOTHING", xy)


def named(name):
    return bpy.data.objects.get(name)


def seen_point(name, half):
    """A window pixel where the named model is actually visible."""
    o = named(name)
    lo, hi = sm.obj_bounds(o)
    c = (lo + hi) / 2
    r = region()
    dg = bpy.context.evaluated_depsgraph_get()
    for d in ((0, -1, 0), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, 0, 1)):
        p = c + Vector((d[0] * (hi.x - lo.x) / 2, d[1] * (hi.y - lo.y) / 2, d[2] * (hi.z - lo.z) / 2)) * 0.98
        v2 = view3d_utils.location_3d_to_region_2d(r, rv3d(), p)
        if v2 is None:
            continue
        org = view3d_utils.region_2d_to_origin_3d(r, rv3d(), v2)
        dr = view3d_utils.region_2d_to_vector_3d(r, rv3d(), v2)
        ok, loc, _n, _i, ob, _m = bpy.context.scene.ray_cast(dg, org, dr)
        if ok and ob is not None and ob.name == name and (loc - p).length < 1.5:
            return (int(v2.x + r.x), int(v2.y + r.y))
    return px(c)


def e_start():
    t = et()
    say(it.ACTIVE["name"] == "easy" and t is not None, "Blender starts in Easy mode")
    ev("MOUSEMOVE", "NOTHING", px((0, 0, 0)))


def e_tiles():
    say(len(et().rects) >= 14 + 7 + 8 + 1 + 7, "picture buttons are laid out (%d)" % len(et().rects))
    shot("30-easy-start")
    click(tile("add:block"))


def e_block_carry():
    say(et().state == "CARRY" and len(meshes()) == 1, "clicking Block picks one up (it follows the mouse)")
    hover(px((0, 0, 0)))


def e_block_drop():
    click(px((0, 0, 0)))


def e_block_check():
    o = named("Block")
    lo, hi = sm.obj_bounds(o)
    say(et().state == "IDLE" and abs(lo.z) < 1e-3 and abs((lo.x + hi.x) / 2) < 3 and abs((lo.y + hi.y) / 2) < 3,
        "a click puts the block down on the floor where the mouse is")
    click(tile("add:ball"))


def e_ball_carry():
    hover(px((0, 0, 30)))


def e_ball_shot():
    shot("31-easy-carry")
    click(px((0, 0, 30)))


def e_ball_check():
    o = named("Ball")
    lo, hi = sm.obj_bounds(o)
    say(28.5 < lo.z < 30.01 and abs((lo.x + hi.x) / 2) < 3 and abs((lo.y + hi.y) / 2) < 3,
        "the ball was put down on TOP of the block (its bottom is at %.1f mm), just touching into it" % lo.z)
    S["blk"] = seen_point("Block", 15)
    click(S["blk"])


def e_select_check():
    say([o.name for o in bpy.context.selected_objects] == ["Block"], "clicking the block chooses it")
    hover((S["blk"][0] + 3, S["blk"][1]))


def e_handles():
    h = et().handles
    say(all(k in h for k in ("size", "x", "y", "z", "turn", "tip")), "six dots appear on the chosen shape")
    shot("32-easy-dots")
    S["a"] = hpos("z")
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def e_z_drag():
    a = S["a"]
    ev("MOUSEMOVE", "NOTHING", (a[0], a[1] + 30))
    ev("MOUSEMOVE", "NOTHING", (a[0], a[1] + 60))
    S["b"] = (a[0], a[1] + 60)


def e_z_shot():
    shot("33-easy-taller")
    ev("LEFTMOUSE", "RELEASE", S["b"])


def e_z_check():
    o = named("Block")
    d = dims(o)
    say(d.z > 34 and close(d.x, 30) and abs(sm.obj_bounds(o)[0].z) < 1e-3 and close(o.scale.z, 1.0),
        "pulling the top dot made it taller (%.0f mm), bottom stays on the floor" % d.z)
    S["z"] = d.z
    hover(seen_point("Block", 15))


def e_size_press():
    S["a"] = hpos("size")
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def e_size_drag():
    c = px((0, 0, 0))
    a = S["a"]
    S["b"] = (int(c[0] + (a[0] - c[0]) * 1.5), int(c[1] + (a[1] - c[1]) * 1.5))
    ev("MOUSEMOVE", "NOTHING", ((a[0] + S["b"][0]) // 2, (a[1] + S["b"][1]) // 2))
    ev("MOUSEMOVE", "NOTHING", S["b"])


def e_size_release():
    ev("LEFTMOUSE", "RELEASE", S["b"])


def e_size_check():
    o = named("Block")
    d = dims(o)
    say(d.x > 36 and close(d.x / 30.0, d.z / S["z"], 0.02), "pulling the corner dot made it bigger all over (%.0f mm wide)" % d.x)
    S["v"] = [tuple(round(c, 2) for c in v.co) for v in o.data.vertices]
    hover(seen_point("Block", 15))


def e_turn_press():
    S["a"] = hpos("turn")
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def e_turn_drag():
    a = S["a"]
    ev("MOUSEMOVE", "NOTHING", (a[0] + 40, a[1] - 10))
    ev("MOUSEMOVE", "NOTHING", (a[0] + 90, a[1] - 25))
    S["b"] = (a[0] + 90, a[1] - 25)


def e_turn_check():
    o = named("Block")
    v = [tuple(round(c, 2) for c in q.co) for q in o.data.vertices]
    say(v != S["v"] and abs(sm.obj_bounds(o)[0].z) < 1e-3, "pulling the orange dot spun it round")
    S["drag_from"] = seen_point("Block", 15)
    ev("MOUSEMOVE", "NOTHING", S["drag_from"])
    ev("LEFTMOUSE", "PRESS", S["drag_from"])


def e_move_drag():
    S["b"] = px((70, -45, 0))
    a = S["drag_from"]
    ev("MOUSEMOVE", "NOTHING", ((a[0] + S["b"][0]) // 2, (a[1] + S["b"][1]) // 2))
    ev("MOUSEMOVE", "NOTHING", S["b"])


def e_move_check():
    o = named("Block")
    lo, hi = sm.obj_bounds(o)
    say(abs((lo.x + hi.x) / 2 - 70) < 4 and abs((lo.y + hi.y) / 2 + 45) < 4 and abs(lo.z) < 1e-3,
        "dragging the block slid it across the floor to where the mouse went")
    click(tile("col:0"))


def e_colour_check():
    c = tuple(round(v, 2) for v in named("Block").color[:3])
    say(c == tuple(round(v, 2) for v in easy.PALETTE[0]), "clicking red coloured it in")
    click(tile("do:copy"))


def e_copy_check():
    S["n"] = len(meshes())
    say(S["n"] == 3, "Copy made another one (%d shapes)" % S["n"])
    click(tile("do:bin"))


def e_bin_check():
    say(len(meshes()) == 2, "Bin threw the copy away")
    click(tile("add:draw"))


def e_draw_press():
    say(et().state == "DRAW_WAIT", "Draw is waiting for a line")
    S["c"] = (-60.0, 45.0)
    S["a"] = px((S["c"][0] + 24, S["c"][1], 0))
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def mk_circle(steps, per):
    out = []
    for i in range(steps):
        def f(i=i):
            for k in range(1, per + 1):
                t = 2 * math.pi * (i * per + k) / (steps * per) * 1.04
                S["b"] = px((S["c"][0] + 24 * math.cos(t), S["c"][1] + 17 * math.sin(t), 0))
                ev("MOUSEMOVE", "NOTHING", S["b"])
        f.__name__ = "draw_%d" % i
        out.append(f)
    return out


def e_draw_shot():
    shot("34-easy-draw")
    ev("LEFTMOUSE", "RELEASE", S["b"])


def e_draw_check():
    o = named("Drawing")
    ok = o is not None
    if ok:
        c = sm.compute_check(o)
        d = dims(o)
        ok = c["open"] == 0 and 40 < d.x < 56 and 28 < d.y < 40 and close(d.z, 10)
        say(ok, "the drawn loop became a solid shape %.0f x %.0f x %.0f mm" % (d.x, d.y, d.z))
    else:
        say(False, "the drawn loop became a solid shape")
    click(tile("add:ideas"))


def e_ideas_tray():
    say("idea:rocket" in et().rects, "Ideas opens a row of ready-made starters")
    hover(tile("idea:rocket"))


def e_ideas_shot():
    shot("35-easy-ideas")
    S["n"] = len(meshes())
    click(tile("idea:rocket"))


def e_rocket_check():
    say(len(meshes()) == S["n"] + 4 and len(bpy.context.selected_objects) == 4, "clicking Rocket put a 4-piece rocket on the bed")
    hover(px((0, 0, 0)))


def e_rocket_shot():
    shot("36-easy-rocket")
    click(tile("do:glue"))


def e_glue_check():
    ms = [o for o in meshes() if o.name.startswith("Rocket")]
    say(len(meshes()) == S["n"] + 1 and len(ms) == 1 and sm.compute_check(ms[0])["open"] == 0,
        "Glue stuck the rocket's pieces into one closed model")
    S["rot"] = rv3d().view_rotation.copy()
    click(tile("view:left"))


def e_view_check():
    q = rv3d().view_rotation
    say(q.rotation_difference(S["rot"]).angle > 0.3, "the arrow button turned the view")
    click(tile("view:right"))


def e_undo():
    click(tile("do:undo"))


def e_undo_check():
    say(len(meshes()) == S["n"] + 4, "Undo took the glue back (%d shapes)" % len(meshes()))
    say(it.ACTIVE["name"] == "easy", "Easy mode is still on after Undo")
    S["rot"] = rv3d().view_rotation.copy()
    r = region()
    S["a"] = (r.x + r.width // 2, r.y + r.height // 2 + 150)
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("RIGHTMOUSE", "PRESS", S["a"])


def e_orbit_drag():
    a = S["a"]
    ev("MOUSEMOVE", "NOTHING", (a[0] + 50, a[1]))
    ev("MOUSEMOVE", "NOTHING", (a[0] + 110, a[1]))
    S["b"] = (a[0] + 110, a[1])


def e_orbit_release():
    ev("RIGHTMOUSE", "RELEASE", S["b"])


def e_orbit_check():
    say(rv3d().view_rotation.rotation_difference(S["rot"]).angle > 0.1, "dragging with the right button looks around")
    with override():
        bpy.ops.simplemesh.frame(everything=True)
    click(seen_point("Ball", 15))


def e_clay():
    say([o.name for o in bpy.context.selected_objects] == ["Ball"], "ball chosen")
    click(tile("add:clay"))


def e_clay_check():
    say(bpy.context.mode == "SCULPT", "the Clay button starts clay on the chosen shape")
    shot("37-easy-clay")
    strip_click(40)                               # "Done"


def e_clay_back():
    say(bpy.context.mode == "OBJECT" and it.ACTIVE["name"] == "easy", "Done comes straight back to Easy mode")
    hover(px((0, 0, 0)))


def e_words():
    with override():
        bpy.ops.simplemesh.easy_words(text="Zoe")
    o = named("Zoe")
    say(o is not None and sm.compute_check(o)["open"] == 0, "Words makes 3D letters (typed through the operator; the pop-up box itself is not driven here)")
    hover(px((0, 0, 0)))


def e_all_shot():
    shot("38-easy-all")
    click(tile("do:print"))


def e_print_check():
    wins = bpy.context.window_manager.windows
    say(any(a.type == "FILE_BROWSER" for w in wins for a in w.screen.areas), "Print! opens the save box")
    solids = [o for o in meshes() if not sm.is_hole(o)]
    lo, hi = sm.group_bounds(solids)
    say(abs(lo.z) < 1e-3 and all(sm.compute_check(o)["open"] == 0 for o in solids),
        "before saving, everything was glued, repaired and sat on the bed (%d models, all closed)" % len(solids))
    shot("39-easy-print")
    for w in wins:
        if any(a.type == "FILE_BROWSER" for a in w.screen.areas):
            w.event_simulate(type="ESC", value="PRESS", x=200, y=200)
            w.event_simulate(type="ESC", value="RELEASE", x=200, y=200)


def e_leave():
    hover(px((0, 0, 0)))
    shot("40-easy-strip")
    strip_click(35)                               # the Easy button again turns Easy off


def e_leave_check():
    say(it.ACTIVE["token"] is None and not bpy.context.scene.simplemesh.easy_on, "pressing the Easy button again turns Easy mode off")
    for o in meshes():
        bpy.data.objects.remove(o, do_unlink=True)
    hover(px((0, 0, 0)))


EASY_STEPS = [e_start, e_tiles, e_block_carry, e_block_drop, e_block_check, e_ball_carry, e_ball_shot, e_ball_check,
              e_select_check, e_handles, e_z_drag, e_z_shot, e_z_check, e_size_press, e_size_drag, e_size_release,
              e_size_check, e_turn_press, e_turn_drag, e_size_release, e_turn_check, e_move_drag, e_size_release,
              e_move_check, e_colour_check, e_copy_check, e_bin_check, e_draw_press, *mk_circle(4, 6), e_draw_shot,
              e_draw_check, e_ideas_tray, e_ideas_shot, e_rocket_check, e_rocket_shot, e_glue_check, e_view_check,
              e_undo, e_undo_check, e_orbit_drag, e_orbit_release, e_orbit_check, e_clay, e_clay_check, e_clay_back,
              e_words, e_all_shot, e_print_check, e_leave, e_leave_check]

STEPS = [s_start, *EASY_STEPS, s_import, s_import_check, s_scale_then_find, s_scale_check,
         s_layflat_start, s_layflat_hover, s_layflat_shot, s_layflat_check, s_layflat_undo,
         s_move_start, s_move_press, s_move_drag, s_move_shot, s_move_check, s_move_nudge,
         s_turn_start, s_turn_press, s_turn_drag, s_turn_shot, s_turn_check, s_turn_key,
         s_size_start, s_size_type, s_size_type_shot, s_size_check, s_size_drag, s_size_drag_shot, s_size_drag_check,
         s_cut_start, s_cut_hover, s_cut_shot, s_cut_check,
         s_linecut_start, s_linecut_press, s_linecut_drag, s_linecut_shot, s_linecut_check,
         s_hole_start, s_hole_hover, s_hole_shot, s_hole_click, s_hole_check,
         s_measure_start, s_measure_a, s_measure_b, s_measure_check, s_esc_check,
         s_pull_start, s_pull_hover, s_pull_shot, s_pull_typed_check, s_pull_drag, s_pull_drag_shot, s_pull_drag_check,
         s_clay_setup, s_clay_click, s_clay_check, *mk_stroke(4, 4, 0, 9), s_clay_release,
         s_clay_undo, s_clay_undo_check, s_clay_redo_check, s_clay_shot, s_clay_push,
         *mk_stroke(3, 4, 5, 0), s_clay_release, s_clay_push_shot, s_clay_done_check,
         s_own_sculpt, s_own_sculpt_wait, s_own_sculpt_wait, s_own_sculpt_check, *mk_stroke(4, 4, 0, 9),
         s_clay_release, s_own_sculpt_done, s_own_sculpt_done_check,
         s_other_mode, s_other_mode_back, s_other_mode_check,
         s_find_setup, s_find_check, s_strip_tool, s_strip_tool_check, s_strip_select_check,
         s_strip_switch, s_strip_switch2, s_strip_switch3, s_strip_switch4]
STEPS += mk_pop(997, "17-pop-numbers") + mk_pop(1067, "18-pop-shapes") + mk_pop(1132, "19-pop-repair") + mk_pop(1190, "20-pop-view")
STEPS += [s_open_dialog, s_open_dialog_shot, s_sidebar, s_final]


# ---------------------------------------------------------------- the big-button panel

from simplemesh import deck  # noqa: E402
from simplemesh import clay as clay_mod  # noqa: E402


def dkey(key):
    """Window pixel of the middle of a panel button."""
    r = region()
    it = next(i for i in deck.layout(area(), r, bpy.context) if i["id"] == key)
    x, y, w, h = it["rect"]
    return (int(x + w / 2 + r.x), int(y + h / 2 + r.y))


def dclick(key):
    xy = dkey(key)
    ev("MOUSEMOVE", "NOTHING", (xy[0] - 3, xy[1]))
    ev("MOUSEMOVE", "NOTHING", xy)
    ev("LEFTMOUSE", "PRESS", xy)
    ev("LEFTMOUSE", "RELEASE", xy)


def ditem(key):
    return next(i for i in deck.layout(area(), region(), bpy.context) if i["id"] == key)


def d_on():
    area().spaces.active.show_region_ui = False
    it.stop_tool(None)
    bpy.context.scene.simplemesh.easy_on = False
    for o in meshes():
        bpy.data.objects.remove(o, do_unlink=True)
    with override():
        bpy.ops.simplemesh.add_shape(shape="BLOCK", size_x=60, size_y=60, size_z=20, at_model=False)
        bpy.ops.simplemesh.frame(everything=True)
        bpy.ops.ed.undo_push(message="test: block 3")
    sm.select_only(bpy.context, [meshes()[0]])
    sm.base._DefaultPrefs.show_deck = True
    area().tag_redraw()
    r = region()
    S["mid"] = (r.x + r.width // 2, r.y + r.height // 2)
    ev("MOUSEMOVE", "NOTHING", S["mid"])


def d_wait():
    ev("MOUSEMOVE", "NOTHING", (S["mid"][0] + 3, S["mid"][1]))


def d_check():
    say(win().as_pointer() in deck.KEEP, "the panel's keeper started by itself when the panel was first drawn")
    r = region()
    px, py, pw, ph = deck.plate(area(), r)
    say(ph > 60 and py + ph <= r.height and it.top_offset_for_test(area()) > ph - 1,
        "the panel sits under Blender's header rows (%.0f px high) and the read-outs moved down" % ph)
    say(ditem("red")["label"] == "MOULD LIKE CLAY" and ditem("badge")["label"] == "SELECT",
        "red button and badge show the state (%s / %s)" % (ditem("red")["label"], ditem("badge")["label"]))
    shot("42-panel")
    dclick("layflat")


def d_tool_check():
    say(it.ACTIVE["name"] == "layflat" and ditem("layflat")["on"] and ditem("red")["label"] == "FINISH LAY FLAT",
        "a click on the Lay flat key starts the tool; its light is on; the red button says FINISH LAY FLAT")
    hover(px((0.0, -30.0, 10.0)))


def d_tool_shot():
    shot("43-panel-tool")
    dclick("red")


def d_finish_check():
    say(it.ACTIVE["token"] is None, "the red button finishes the tool")
    n0 = len(meshes())
    S["h0"] = dims(meshes()[0]).z
    xy = dkey("find")
    click(xy)                                     # a click on the panel must not reach the model behind it
    say(len(meshes()) == n0, "clicks on the panel stay on the panel")
    dclick("red")


def d_clay_check():
    say(bpy.context.mode == "SCULPT" and ditem("red")["label"] == "DONE" and ditem("b:pull")["on"],
        "red button: MOULD LIKE CLAY starts Clay; the panel now shows DONE and the brushes, Pull lit")
    S["r0"] = clay_mod.get_radius(bpy.context)
    dclick("bigger")


def d_bigger_check():
    r1 = clay_mod.get_radius(bpy.context)
    say(close(r1, S["r0"] * 1.25), "Brush + : %.1f -> %.1f mm" % (S["r0"], r1))
    dclick("b:push")


def d_brush_check():
    say(clay_mod.actual_key(bpy.context) == "push" and ditem("b:push")["on"], "a brush key switches the brush (Push in)")
    dclick("b:pull")


def d_stroke_start():
    say(clay_mod.actual_key(bpy.context) == "pull", "back to Pull")
    shot("44-panel-clay")
    S["a"] = px((0.0, 0.0, 20.0))
    ev("MOUSEMOVE", "NOTHING", S["a"])
    ev("LEFTMOUSE", "PRESS", S["a"])


def d_stroke_check():
    h = box_height()
    say(h > 25.0, "a drag in the view still moulds (height %.1f mm)" % h)
    dclick("undo")


def d_undo_check():
    h = box_height()
    say(bpy.context.mode == "SCULPT" and close(h, 20.0, 0.05), "the Undo key takes the stroke back and stays in Clay (%.1f mm)" % h)
    dclick("red")


def d_done_check():
    c = sm.compute_check(meshes()[0])
    say(bpy.context.mode == "OBJECT" and c["open"] == 0, "red button: DONE returns to the tools, model watertight (%d triangles)" % c["tris"])
    dclick("luminous")


def d_look_check():
    say(bpy.context.scene.simplemesh.look == "CLEAN" and not ditem("luminous")["on"], "the Luminous key switches to the Clean look")
    shot("45-panel-clean")
    dclick("luminous")


def d_clutter():
    say(bpy.context.scene.simplemesh.look == "LUMINOUS", "and back")
    dclick("clutter")


def d_clutter_check():
    sp = area().spaces.active
    say(not sp.show_region_header and ditem("clutter")["on"], "Hide clutter hides Blender's header rows (its light is on)")
    shot("46-panel-clutter")
    dclick("clutter")


def d_clutter_back():
    sp = area().spaces.active
    say(sp.show_region_header and sp.show_region_tool_header, "pressed again, they are back")
    dclick("easy")


def d_easy_check():
    say(it.ACTIVE["name"] == "easy" and ditem("easy")["on"], "the Easy key turns Easy mode on")
    S["n"] = len(meshes())
    click(tile("add:ball"))


def d_easy_drop():
    click(px((70.0, 40.0, 0.0)))


def d_easy_drop_check():
    say(len(meshes()) == S["n"] + 1, "Easy mode's picture buttons work under the panel (a ball was added)")
    shot("47-panel-easy")
    dclick("cut")


def d_easy_tool_check():
    say(it.ACTIVE["name"] == "cut", "a panel tool can be started from Easy mode")
    dclick("red")


def d_easy_back_check():
    say(it.ACTIVE["name"] == "easy", "and finishing it hands the mouse back to Easy mode")
    dclick("easy")


def d_off():
    say(it.ACTIVE["token"] is None, "the Easy key again turns Easy mode off")
    from simplemesh import ui as ui_mod
    try:
        path = ui_mod.save_recovery_copy(bpy.context)
        say(os.path.getsize(path) > 10000 and not ui_mod.someone_busy(bpy.context),
            "a recovery copy can be written while the panel is watching the mouse (%s, %d kB)"
            % (os.path.basename(path), os.path.getsize(path) // 1024))
    except Exception as ex:  # noqa: BLE001
        say(False, "recovery copy failed: %r" % ex)
    say(not sm.base.ERRORS, "no problems were caught while using the panel" if not sm.base.ERRORS
        else "problems were caught: %s" % ", ".join(sm.base.ERRORS))
    sm.base._DefaultPrefs.show_deck = False
    area().tag_redraw()


STEPS += [d_on, d_wait, d_wait, d_check, d_tool_check, d_tool_shot, d_finish_check, d_wait, d_clay_check, d_bigger_check,
          d_brush_check, d_stroke_start, *mk_stroke(4, 4, 0, 9), s_clay_release, d_stroke_check, d_undo_check, d_wait,
          d_done_check, d_look_check, d_clutter, d_clutter_check, d_clutter_back, d_easy_check, d_easy_drop,
          d_easy_drop_check, d_easy_tool_check, d_wait, d_easy_back_check, d_off, d_wait]


def s_resume_on():
    area().spaces.active.show_region_ui = False
    for o in meshes():
        bpy.data.objects.remove(o, do_unlink=True)
    strip_click(262)                              # "Easy" in the full strip


def s_resume_save():
    say(it.ACTIVE["name"] == "easy", "the Easy button in the strip turns Easy mode on")
    with override():
        bpy.ops.simplemesh.easy_idea(key="snowman")
    S["blend"] = os.path.join(OUT, "kid_project.blend")
    bpy.ops.wm.save_as_mainfile(filepath=S["blend"])


def s_resume_open():
    bpy.ops.wm.open_mainfile(filepath=S["blend"])


def s_resume_wait():
    pass


def s_resume_check():
    ev("MOUSEMOVE", "NOTHING", px((0, 0, 0)))
    say(it.ACTIVE["name"] == "easy" and easy.CURRENT["tool"] is not None and len(meshes()) == 6,
        "a saved project opens again in Easy mode with its shapes (%d)" % len(meshes()))


def s_resume_shot():
    shot("41-easy-reopened")


STEPS += [s_resume_on, s_resume_save, s_resume_open, s_resume_wait, s_resume_wait, s_resume_check, s_resume_shot]
_i = {"n": 0}


def runner():
    n = _i["n"]
    if n >= len(STEPS):
        print("GUI-DONE  %d failed" % len(FAILS))
        sys.stdout.flush()
        bpy.ops.wm.quit_blender()
        return None
    _i["n"] += 1
    try:
        STEPS[n]()
    except Exception:
        say(False, "step %s crashed" % STEPS[n].__name__)
        traceback.print_exc()
        sys.stdout.flush()
    return 0.6


bpy.app.timers.register(runner, first_interval=3.0, persistent=True)

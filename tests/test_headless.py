# SimpleMesh headless tests (run with:  python tests/test_headless.py)
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
#
# Needs the `bpy` pip module (Blender as a Python module). It exercises every
# operator on generated STL files. It cannot test the on-screen panels or the
# viewport drawing (no window); the panel draw functions are run against a fake
# layout object only to catch coding errors.

import math
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import simplemesh as sm  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def close(a, b, tol=1e-2):
    return abs(a - b) <= tol * max(1.0, abs(b))


def write_stl(path, tris):
    with open(path, "wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(tris)))
        for t in tris:
            a, b, c = map(np.array, t)
            n = np.cross(b - a, c - a)
            ln = np.linalg.norm(n)
            n = n / ln if ln else n
            f.write(struct.pack("<12fH", *n, *a, *b, *c, 0))


def box_tris(sx, sy, sz, drop_face=None, flip=False):
    x, y, z = sx / 2, sy / 2, sz / 2
    v = [(-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z),
         (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    tris = []
    for i, q in enumerate(quads):
        if i == drop_face:
            continue
        a, b, c, d = [v[k] for k in q]
        t = [(a, b, c), (a, c, d)]
        if flip:
            t = [(a, c, b), (a, d, c)]
        tris += t
    return tris


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sm.register() if not hasattr(bpy.types.Scene, "simplemesh") else None


def objs():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def dims(o):
    lo, hi = sm.obj_bounds(o)
    return hi - lo


def vol(o):
    return sm.compute_check(o)["volume"]


def sel(*obs):
    sm.select_only(bpy.context, list(obs))


def imp(path, **kw):
    r = bpy.ops.simplemesh.import_stl(filepath=path, **kw)
    return r


class FakeLayout:
    """Duck-typed UILayout: records calls, returns itself for chaining."""
    def __getattr__(self, name):
        def f(*a, **k):
            return FakeLayout()
        return f

    def __setattr__(self, k, v):
        pass


def main():
    tmp = tempfile.mkdtemp()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sm.register()
    sc = bpy.context.scene

    print("registration / startup tidy")
    check(hasattr(bpy.ops.simplemesh, "import_stl"), "operators registered")
    bpy.ops.wm.read_factory_settings(use_empty=False)
    for nm in ("Cube", "Light", "Camera"):   # recreate the default startup scene
        ob = bpy.data.objects.new(nm, bpy.data.meshes.new(nm) if nm == "Cube" else None)
        bpy.context.scene.collection.objects.link(ob)
    check(len(bpy.context.scene.objects) == 3, "default Cube/Light/Camera present before tidy")
    sm.tidy_new_file(bpy.context)
    check(len(bpy.context.scene.objects) == 0, "default cube/camera/light removed")
    check(sm.units_are_mm(bpy.context.scene), "scene units = mm")
    sc = bpy.context.scene

    print("import: normal size")
    p = os.path.join(tmp, "box.stl")
    write_stl(p, box_tris(40, 30, 20))
    imp(p)
    o = objs()[0]
    d = dims(o)
    check(close(d.x, 40) and close(d.y, 30) and close(d.z, 20), "40x30x20 mm kept, got %s" % (tuple(round(v, 3) for v in d),))
    lo, hi = sm.obj_bounds(o)
    check(abs(lo.z) < 1e-4, "sits on the bed (z min 0)")
    check(abs((lo.x + hi.x) / 2) < 1e-4 and abs((lo.y + hi.y) / 2) < 1e-4, "centred on bed")
    r = sm.compute_check(o)
    check(r["open"] == 0 and r["bad"] == 0 and not r["inverted"], "imported box is watertight")
    check(close(r["volume"], 40 * 30 * 20), "volume correct (%.1f)" % r["volume"])
    check(o.matrix_basis.to_scale()[:] == (1.0, 1.0, 1.0) or close(o.scale.x, 1.0), "scale applied (1.0)")

    print("import: massive model auto-fit")
    reset()
    write_stl(os.path.join(tmp, "huge.stl"), box_tris(5200, 3100, 900))
    imp(os.path.join(tmp, "huge.stl"))
    o = objs()[0]
    d = dims(o)
    check(close(d.x, 52) and close(d.y, 31) and close(d.z, 9), "5200 mm model shrunk /100 -> %s" % (tuple(round(v, 2) for v in d),))
    lo, hi = sm.obj_bounds(o)
    check(abs(lo.z) < 1e-3 and abs((lo.x + hi.x) / 2) < 1e-3, "centred + on bed after auto-fit")

    print("import: metres opened as mm (tiny)")
    reset()
    write_stl(os.path.join(tmp, "tiny.stl"), box_tris(0.2, 0.1, 0.05))
    imp(os.path.join(tmp, "tiny.stl"))
    d = dims(objs()[0])
    check(close(d.x, 200), "0.2 -> x1000 = 200 mm (got %.3f)" % d.x)

    print("import: units + fit_size + auto off")
    reset()
    write_stl(os.path.join(tmp, "inch.stl"), box_tris(4, 2, 1))
    imp(os.path.join(tmp, "inch.stl"), units="IN")
    d = dims(objs()[0])
    check(close(d.x, 101.6), "4 inch = 101.6 mm (got %.3f)" % d.x)
    reset()
    imp(os.path.join(tmp, "huge.stl"), auto_fit=False)
    check(close(dims(objs()[0]).x, 5200), "auto-fit off keeps 5200")
    reset()
    imp(os.path.join(tmp, "huge.stl"), fit_size=150.0)
    check(close(max(dims(objs()[0])), 150), "fit_size 150 -> longest 150")

    print("import: several files side by side")
    reset()
    bpy.ops.simplemesh.import_stl(filepath=p, directory=tmp,
                                  files=[{"name": "box.stl"}, {"name": "inch.stl"}], units="MM")
    ob = objs()
    check(len(ob) == 2, "two models imported")
    if len(ob) == 2:
        a, b = sorted(ob, key=lambda o: o.location.x)
        la, ha = sm.obj_bounds(a)
        lb, hb = sm.obj_bounds(b)
        check(lb.x - ha.x >= sm.GAP_MM - 1e-3, "spaced %.1f mm apart" % (lb.x - ha.x))

    print("scale tools")
    reset()
    imp(p)
    o = objs()[0]
    sel(o)
    bpy.ops.simplemesh.scale_by(factor=0.5)
    d = dims(o)
    lo, hi = sm.obj_bounds(o)
    check(close(d.x, 20) and close(d.z, 10), "scale 0.5")
    check(abs(lo.z) < 1e-4 and abs((lo.x + hi.x) / 2) < 1e-4, "stays on bed, centred")
    bpy.ops.simplemesh.fit_longest(size=100.0)
    check(close(max(dims(o)), 100), "fit longest = 100")
    check(close(o.scale.x, 1.0) and close(o.scale.z, 1.0), "object scale stays 1.0 (baked)")

    print("rotate / mirror / place")
    reset()
    imp(p)
    o = objs()[0]
    sel(o)
    bpy.ops.simplemesh.rotate90(axis="Y", angle=90.0)
    d = dims(o)
    check(close(d.x, 20) and close(d.z, 40), "rotate Y 90: x20 z40")
    check(abs(sm.obj_bounds(o)[0].z) < 1e-4, "dropped to bed after turn")
    v0 = vol(o)
    bpy.ops.simplemesh.mirror(axis="X")
    r = sm.compute_check(o)
    check(not r["inverted"] and r["open"] == 0 and close(r["volume"], v0), "mirror keeps normals outward + volume")
    o.location.x += 500
    sm.refresh(bpy.context)
    bpy.ops.simplemesh.place(center=True)
    lo, hi = sm.obj_bounds(o)
    check(abs((lo.x + hi.x) / 2) < 1e-3, "centre on bed")

    print("lay flat (auto)")
    reset()
    write_stl(os.path.join(tmp, "slab.stl"), box_tris(100, 60, 10))
    imp(os.path.join(tmp, "slab.stl"))
    o = objs()[0]
    sel(o)
    o.rotation_euler = (math.radians(70), math.radians(25), math.radians(10))
    sm.refresh(bpy.context)
    bpy.ops.simplemesh.lay_flat()
    d = dims(o)
    check(close(d.z, 10, 0.02), "slab lies flat: height %.2f" % d.z)
    check(abs(sm.obj_bounds(o)[0].z) < 1e-3, "and on the bed")

    print("lay on a chosen face direction (what the Lay flat tool does on click)")
    reset()
    imp(os.path.join(tmp, "slab.stl"))
    o = objs()[0]
    sm.lay_on_normal(bpy.context, o, Vector((1.0, 0.0, 0.0)))      # the +X end face goes down
    d = dims(o)
    check(close(d.z, 100), "stood on its end face: height %.1f" % d.z)
    check(abs(sm.obj_bounds(o)[0].z) < 1e-3, "and on the bed")

    print("flat region under a face (hover highlight)")
    from simplemesh import interactive as it
    import bmesh as _bm
    reset()
    imp(os.path.join(tmp, "slab.stl"))
    o = objs()[0]
    bm = _bm.new(); bm.from_mesh(o.data); bm.faces.ensure_lookup_table(); bm.normal_update()
    top = next(f.index for f in bm.faces if f.normal.z > 0.9)
    faces, nrm, ctr = it.flat_region(bm, top)
    check(len(faces) == 2 and nrm.z > 0.99, "top of the slab = 2 triangles, normal up")
    check(abs(ctr.x) < 1e-3 and abs(ctr.y) < 1e-3, "face centre found (for Ctrl-centre holes)")
    check(len(it.region_tris(bm, faces, o.matrix_world, 0.01)) == 6, "highlight triangles built")
    bm.free()

    print("cut with any plane (what the Cut tool does), incl. cut faces down")
    reset()
    imp(p)
    o = objs()[0]
    v0 = vol(o)
    parts = sm.split_model(bpy.context, o, Vector((0, 0, 10)), Vector((1, 0, 1)).normalized(), "BOTH", True)
    check(len(parts) == 2 and close(sum(vol(x) for x in parts), v0, 0.02), "diagonal cut: two pieces, volume kept")
    for x in parts:
        c = sm.compute_check(x)
        check(c["open"] == 0 and not c["inverted"] and abs(sm.obj_bounds(x)[0].z) < 1e-3,
              "%s watertight and resting on the bed" % x.name)
        nf = sm.largest_flat_normal(x)
    check(sm.obj_bounds(parts[1])[0].x - sm.obj_bounds(parts[0])[1].x >= sm.GAP_MM - 1e-3, "pieces placed apart")
    check(sm.split_model(bpy.context, parts[0], Vector((0, 0, 9999)), Vector((0, 0, 1)), "BOTH") == [],
          "a plane that misses is refused and nothing is left behind (%d models)" % len(objs()))
    check(len(objs()) == 2, "no stray copy after a missed cut")

    print("drill a hole (what the Hole tool does)")
    reset()
    imp(p)                                       # 40 x 30 x 20 box on the bed
    o = objs()[0]
    v0 = vol(o)
    sm.drill_hole(bpy.context, o, Vector((0, 0, 20)), Vector((0, 0, -1)), 10.0, 0.0)
    exp = v0 - math.pi * 25 * 20
    check(close(vol(o), exp, 0.02), "through hole removes a 10 mm cylinder (%.0f vs %.0f)" % (vol(o), exp))
    check(sm.compute_check(o)["open"] == 0 and len(objs()) == 1, "watertight, drill bit removed")
    v1 = vol(o)
    sm.drill_hole(bpy.context, o, Vector((12, 0, 20)), Vector((0, 0, -1)), 6.0, 5.0)
    exp = v1 - math.pi * 9 * 5
    check(close(vol(o), exp, 0.02), "blind hole 6 mm x 5 deep (%.0f vs %.0f)" % (vol(o), exp))
    check(close(dims(o).x, 40) and close(dims(o).z, 20), "outer size unchanged")

    print("pull a face (what the Pull tool does)")
    reset()
    imp(p)                                       # 40 x 30 x 20 box
    o = objs()[0]
    fx = next(pl.index for pl in o.data.polygons if pl.normal.x > 0.9)
    n = sm.pull_face(o, fx, 5.0)
    d = dims(o)
    check(n == 2 and close(d.x, 45) and close(d.y, 30) and close(d.z, 20), "+X face pulled out 5 mm: %.1f x %.1f x %.1f" % (d.x, d.y, d.z))
    check(close(vol(o), 45 * 30 * 20) and sm.compute_check(o)["open"] == 0, "volume follows, still watertight")
    fz = next(pl.index for pl in o.data.polygons if pl.normal.z > 0.9)
    sm.pull_face(o, fz, -8.0)
    d = dims(o)
    check(close(d.z, 12) and close(o.scale.x, 1.0), "top pushed in 8 mm: height %.1f, scale stays 1.0" % d.z)

    print("refine for clay, then merge flat areas again")
    reset()
    imp(p)
    o = objs()[0]
    v0 = vol(o)
    n = sm.refine_mesh(o.data, 2.0, 100000)
    c = sm.compute_check(o)
    check(n > 1000 and c["open"] == 0 and close(c["volume"], v0, 1e-4), "refined 12 -> %d triangles, same volume, watertight" % n)
    longest = max((o.data.vertices[e.vertices[0]].co - o.data.vertices[e.vertices[1]].co).length for e in o.data.edges)
    check(longest <= 2.0 + 1e-4, "no edge longer than 2 mm (longest %.2f)" % longest)
    fz = next(pl.index for pl in o.data.polygons if pl.normal.z > 0.9)
    vi = o.data.polygons[fz].vertices[0]
    o.data.vertices[vi].co.z += 3.0              # a moulded bump
    o.data.update()
    b4, aft = sm.tidy_flat(bpy.context, o)
    c = sm.compute_check(o)
    check(aft < b4 / 4 and c["open"] == 0 and c["bad"] == 0, "flat areas merged: %d -> %d triangles, still watertight" % (b4, aft))
    check(dims(o).z > 22.5, "the bump survived the tidy-up (height %.1f)" % dims(o).z)

    print("clay mode set-up (no window: brushes cannot be stroked here)")
    from simplemesh import clay
    reset()
    imp(p)
    o = objs()[0]
    sel(o)
    r = bpy.ops.simplemesh.clay_start()
    ts = bpy.context.scene.tool_settings
    check("FINISHED" in r and bpy.context.mode == "SCULPT", "clay mode entered")
    if bpy.context.mode == "SCULPT":
        check(bpy.context.sculpt_object.use_dynamic_topology_sculpting, "automatic detail on")
        ups = clay.unified(bpy.context)
        nm, k = clay.size_prop(ups)
        check(len(o.data.polygons) > 500, "model was given small triangles (12 -> %d)" % len(o.data.polygons))
        check(nm is not None and close(getattr(ups, nm) / k, 8.0) and ups.use_locked_size == "SCENE",
              "brush radius 8 mm (a fifth of the model) in scene units via '%s'" % nm)
        check(close(ts.sculpt.constant_detail_resolution, 1.0 / bpy.context.scene.simplemesh.clay_detail),
              "detail %.2f mm" % bpy.context.scene.simplemesh.clay_detail)
        names = []
        for key in [b[0] for b in clay.BRUSHES]:
            ok = clay.activate_brush(bpy.context, key)
            names.append("%s=%s" % (key, ts.sculpt.brush.name if (ok and ts.sculpt.brush) else "FAILED"))
            if ok and clay.actual_key(bpy.context) != key:
                check(False, "%s: Blender is really using %s (%s)" % (key, ts.sculpt.brush.name, clay.brush_type(ts.sculpt.brush)))
        if any("FAILED" in x for x in names):
            print("  note " + ", ".join(names) + "  (brush switching needs a 3D view on this Blender)")
        else:
            check(True, "all seven brushes activate: " + ", ".join(names))
            bpy.ops.simplemesh.clay_brush(key="push")
            check(ts.sculpt.brush.direction == "SUBTRACT", "Push in = Draw brush, subtract")
        bpy.ops.simplemesh.clay_done()
        c = sm.compute_check(objs()[0])
        check(bpy.context.mode == "OBJECT" and c["open"] == 0 and c["tris"] == 12 and close(c["volume"], 24000),
              "Done returns to object mode; untouched model is back to %d triangles, same volume" % c["tris"])

    print("sculpt mode entered Blender's own way (mode menu, Ctrl+Tab, Sculpting workspace)")
    reset()
    imp(p)
    o = objs()[0]
    sel(o)
    clay.forget()
    bpy.ops.object.mode_set(mode="SCULPT")
    check(bpy.context.mode == "SCULPT" and clay.needs_setup(bpy.context) and len(o.data.polygons) == 12
          and not bpy.context.sculpt_object.use_dynamic_topology_sculpting,
          "Blender's own sculpt mode is noticed as not set up (12 big triangles, no automatic detail)")
    check(bpy.ops.simplemesh.clay_start.poll(), "the Clay set-up may be run from there")
    r = bpy.ops.simplemesh.clay_start()
    o = objs()[0]
    check("FINISHED" in r and bpy.context.mode == "SCULPT" and not clay.needs_setup(bpy.context)
          and bpy.context.sculpt_object.use_dynamic_topology_sculpting and len(o.data.polygons) > 500,
          "after the set-up: still sculpting, %d small triangles, automatic detail on" % len(o.data.polygons))
    ups = clay.unified(bpy.context)
    check(ups.use_locked_size == "SCENE", "brush size in millimetres, not screen pixels")
    bpy.ops.simplemesh.clay_done()
    check(bpy.context.mode == "OBJECT" and clay._ready["name"] is None, "Done: back in object mode, set-up forgotten")
    reset()
    imp(p)
    sel(objs()[0])
    r = bpy.ops.simplemesh.clay_start()
    r2 = bpy.ops.simplemesh.clay_start.poll()
    check("FINISHED" in r and not r2, "the Clay button is not offered again once the model is ready")
    bpy.ops.simplemesh.back()
    check(bpy.context.mode == "OBJECT", "Back to the models leaves sculpt mode")

    print("clay: limits that keep Blender answering")
    reset()
    imp(p)
    o = objs()[0]
    n = sm.refine_mesh(o.data, 0.2, 20000)
    check(15000 < n <= 20000, "the triangle budget is a real limit (asked for 0.2 mm edges within 20,000: got %d)" % n)
    check("clay_flood" not in dir(bpy.ops.simplemesh), "'Finer everywhere' is gone")
    reset()
    imp(p)
    sel(objs()[0])
    bpy.ops.simplemesh.clay_start()
    scn = bpy.context.scene.simplemesh
    r0 = clay.get_radius(bpy.context)
    check(close(r0, 8.0) and close(scn.clay_detail, 40.0 / 60.0, 0.02),
          "brush 8 mm, detail %.2f mm for a 40 mm box" % scn.clay_detail)
    scn.clay_detail = 0.05
    check(close(scn.clay_detail, r0 / 30.0), "Detail cannot go finer than a thirtieth of the brush (asked 0.05, got %.3f)" % scn.clay_detail)
    clay.resize(bpy.context, 4.0)
    check(close(clay.get_radius(bpy.context), 32.0) and close(scn.clay_detail, 32.0 / 30.0),
          "a bigger brush takes Detail with it (32 mm brush, detail %.2f)" % scn.clay_detail)
    check(clay.tri_count(bpy.context) > 500, "triangle count of the model being moulded: %d" % clay.tri_count(bpy.context))
    bpy.ops.simplemesh.clay_done()

    print("the big-button panel (laid out without a window)")
    from simplemesh import deck, interactive
    deck.TEST["on"] = True
    region = type("R", (), {"width": 1600, "height": 800, "x": 0, "y": 0, "type": "WINDOW"})()
    ctx = bpy.context
    reset()
    imp(p)
    sel(objs()[0])
    items = {it["id"]: it for it in deck.layout(None, region, ctx)}
    px, py, pw, ph = deck.plate(None, region)
    check(close(ph, 92.0) and close(py, 800 - 92.0) and pw < 1600, "the panel is 92 px high across the top, leaving room at the right")
    inside = all(px <= it["rect"][0] and it["rect"][0] + it["rect"][2] <= px + pw and py <= it["rect"][1]
                 and it["rect"][1] + it["rect"][3] <= py + ph for it in items.values())
    check(inside and len(items) == 19, "all %d buttons lie on the panel" % len(items))
    check(items["red"]["label"] == "MOULD LIKE CLAY" and items["badge"]["label"] == "SELECT",
          "object mode: red button '%s', badge '%s'" % (items["red"]["label"], items["badge"]["label"]))
    check(all(k in items for k in ("layflat", "move", "turn", "size", "pull", "cut", "hole", "measure", "open", "save",
                                   "undo", "redo", "find", "easy", "luminous", "clutter", "more")), "tools and system keys present")
    it = deck.key_at(list(items.values()), items["cut"]["rect"][0] + 3, items["cut"]["rect"][1] + 3)
    check(it is not None and it["id"] == "cut", "a point on the Cut key finds the Cut key")
    check(deck.over(None, region, 100, 800 - 10) and not deck.over(None, region, 100, 800 - 200)
          and not deck.over(None, region, 1590, 800 - 10), "the panel knows which points are on it")
    small = type("R", (), {"width": 1000, "height": 700, "x": 0, "y": 0, "type": "WINDOW"})()
    its = deck.layout(None, small, ctx)
    spx, spy, spw, sph = deck.plate(None, small)
    check(max(i["rect"][0] + i["rect"][2] for i in its) <= spx + spw + 0.5 and sph < 92,
          "a narrow view shrinks the buttons to fit (%.0f px high at 1000 px wide)" % sph)
    check(deck.run(ctx, "red") and ctx.mode == "SCULPT", "red button: MOULD LIKE CLAY starts Clay")
    items = {it["id"]: it for it in deck.layout(None, region, ctx)}
    check(items["red"]["label"] == "DONE" and items["badge"]["label"].startswith("CLAY") and "b:pull" in items
          and "bigger" in items and "layflat" not in items, "while moulding: DONE, a CLAY badge and the brush keys")
    r0 = clay.get_radius(ctx)
    deck.run(ctx, "bigger")
    check(close(clay.get_radius(ctx), r0 * 1.25), "Brush + makes the brush a quarter bigger (%.1f mm)" % clay.get_radius(ctx))
    deck.run(ctx, "mirror")
    check(ctx.scene.simplemesh.clay_mirror, "Mirror key")
    deck.run(ctx, "mirror")
    bpy.ops.object.mode_set(mode="EDIT")
    clay.forget()
    items = {it["id"]: it for it in deck.layout(None, region, ctx)}
    check(items["red"]["label"] == "BACK TO THE MODELS" and items["badge"]["label"] == "BLENDER: EDIT MESH"
          and not items["layflat"]["enabled"], "another Blender mode: BACK TO THE MODELS, tools greyed out")
    check(deck.run(ctx, "red") and ctx.mode == "OBJECT", "red button leaves that mode")
    bpy.ops.object.mode_set(mode="SCULPT")
    items = {it["id"]: it for it in deck.layout(None, region, ctx)}
    check(items["red"]["label"] == "GET READY TO MOULD" and not items["b:pull"]["enabled"],
          "Blender's own sculpt mode: GET READY TO MOULD, brushes greyed out until then")
    deck.run(ctx, "red")
    items = {it["id"]: it for it in deck.layout(None, region, ctx)}
    check(items["red"]["label"] == "DONE" and not clay.needs_setup(ctx), "red button runs the set-up")
    check(deck.run(ctx, "red") and ctx.mode == "OBJECT", "red button: DONE goes back to the tools")
    look0 = ctx.scene.simplemesh.look
    deck.run(ctx, "luminous")
    check(ctx.scene.simplemesh.look != look0 and ctx.scene.simplemesh.look in ("LUMINOUS", "CLEAN"), "Luminous key switches the look")
    deck.run(ctx, "luminous")
    for cls in (deck.SM_MT_more, deck.SM_MT_look):
        try:
            cls.draw(type("P", (), {"layout": FakeLayout()})(), ctx)
            check(True, cls.__name__ + " draw")
        except Exception as ex:  # noqa: BLE001
            check(False, "%s draw raised %r" % (cls.__name__, ex))
    ctx.scene.simplemesh.look_rainbow = True
    ctx.scene.simplemesh.show_edges = True
    ctx.scene.simplemesh.look_rainbow = False
    ctx.scene.simplemesh.show_edges = False
    check(True, "rainbow and show-the-triangles switch without errors")
    deck.TEST["on"] = False

    print("the log of what SimpleMesh was doing")
    with sm.base.busy(ctx, "test step"):
        pass
    sm.base.crumb("hello")
    try:
        txt = open(sm.base._LOG["path"], encoding="utf-8").read()
    except Exception as ex:  # noqa: BLE001
        txt = repr(ex)
    check("session start" in txt and "test step ..." in txt and "test step done after" in txt and "hello" in txt
          and "clay: ready" in txt, "log file has the steps, with start and end of long ones (%d lines)" % txt.count("\n"))

    print("recovery copies: knowing when a drag is going on")
    from simplemesh import ui as ui_mod
    E = lambda t, v: type("Ev", (), {"type": t, "value": v})()  # noqa: E731
    sm.base.note_input(E("LEFTMOUSE", "PRESS"))
    busy1 = ui_mod.someone_busy(bpy.context)
    sm.base.note_input(E("TIMER", "NOTHING"))
    busy2 = ui_mod.someone_busy(bpy.context)
    sm.base.note_input(E("MOUSEMOVE", "NOTHING"))
    busy3 = ui_mod.someone_busy(bpy.context)
    check(busy1 and busy2 and not busy3, "a button press with nothing seen after it counts as busy; the next mouse move clears it")
    check(ui_mod.recovery_path().endswith("%d_autosave.blend" % os.getpid()), "recovery copy uses Blender's own auto-save name")

    print("shading of an imported model, problem report")
    reset()
    imp(p)
    me = objs()[0].data
    flat_ok = all(pl.use_smooth for pl in me.polygons) and (
        getattr(me, "use_auto_smooth", False) or any(e.use_edge_sharp for e in me.edges))
    check(flat_ok, "a box is shaded with sharp corners (smooth faces + sharp edges), not as a pillow")
    try:
        raise ValueError("test problem")
    except ValueError:
        sm.base.note_error("test")
    rep = sm.base.problem_report(bpy.context)
    check("SimpleMesh " + sm.__version__ in rep and "Blender" in rep and "test problem" in rep and "Clay:" in rep
          and "This session's log" in rep and "clay: ready" in rep,
          "problem report lists versions, the Clay state and caught errors (%d lines)" % rep.count("\n"))
    sm.base.ERRORS.clear()

    print("Easy mode: shape library")
    from simplemesh import easy
    reset()
    for kind, nm, size in easy.SHAPES:
        ob = easy.new_shape(bpy.context, kind)
        d = dims(ob)
        c = sm.compute_check(ob)
        check(close(d.x, size[0]) and close(d.y, size[1]) and close(d.z, size[2]) and c["open"] == 0
              and c["bad"] == 0 and not c["inverted"] and c["volume"] > 0,
              "%s: %.0f x %.0f x %.0f mm, closed, volume %.0f" % (nm, d.x, d.y, d.z, c["volume"]))

    print("Easy mode: drawing a shape")
    ring = [(30 * math.cos(t), 20 * math.sin(t)) for t in (2 * math.pi * i / 60 for i in range(60))]
    o1 = easy.clean_outline(ring)
    check(o1 is not None and easy._simple(o1) and easy._area(o1) > 0.8 * math.pi * 30 * 20, "a clean loop is kept (%d points)" % len(o1))
    over = ring + ring[:6]                      # went round and a bit further
    o2 = easy.clean_outline(over)
    check(o2 is not None and easy._simple(o2) and easy._area(o2) > 0.7 * math.pi * 30 * 20, "overshooting the start still gives the loop")
    eight = [(20 * math.sin(2 * t), 30 * math.sin(t)) for t in (2 * math.pi * i / 80 for i in range(80))]
    o3 = easy.clean_outline(eight)
    check(o3 is not None and easy._simple(o3) and easy._area(o3) > 50, "a figure-of-eight becomes one usable shape (area %.0f)" % easy._area(o3))
    scribble = [(math.sin(i * 1.7) * 20 + i * 0.3, math.cos(i * 2.3) * 15) for i in range(60)]
    o4 = easy.clean_outline(scribble)
    check(o4 is not None and easy._simple(o4), "even a scribble gives a solid outline, never an error")
    check(easy.clean_outline([(0, 0), (1, 0), (1, 1), (0, 1)]) is None, "a tiny dot is ignored")
    reset()
    ob = easy.solid_from_outline(bpy.context, o1)
    c = sm.compute_check(ob)
    check(c["open"] == 0 and not c["inverted"] and close(dims(ob).z, 10) and abs(sm.obj_bounds(ob)[0].z) < 1e-4,
          "the drawing becomes a 10 mm thick closed solid on the bed (volume %.0f)" % c["volume"])

    print("Easy mode: words, ideas, glue, print")
    reset()
    t = easy.make_text(bpy.context, "Hi")
    c = sm.compute_check(t) if t else None
    check(t is not None and c["tris"] > 20 and c["open"] == 0 and close(dims(t).z, 5),
          "'Hi' becomes closed 3D letters, 5 mm thick (%d triangles)" % (c["tris"] if c else 0))
    check(easy.make_text(bpy.context, "   ") is None, "empty words are refused")
    for key in easy.IDEA_ORDER:
        reset()
        parts = easy.build_idea(bpy.context, key)
        lo, hi = sm.group_bounds(parts)
        ok = all(sm.compute_check(x)["open"] == 0 for x in parts) and abs(lo.z) < 0.6
        models, fits, tight = easy.make_printable(bpy.context)
        check(ok and len(models) == 1 and fits and tight and sm.compute_check(models[0])["tris"] > 20,
              "idea '%s': %d shapes -> Print! makes 1 watertight model that fits the bed" % (key, len(parts)))
    reset()
    a = easy.new_shape(bpy.context, "block")
    b2 = easy.new_shape(bpy.context, "ball")
    b2.location = (0, 0, 25)                     # ball half sunk into the top of the block
    c3 = easy.new_shape(bpy.context, "cone")
    c3.location = (200, 0, 15)                   # far away, touching nothing
    h = easy.new_shape(bpy.context, "tube", (10, 10, 80))
    sm.set_hole(h, True)
    sm.refresh(bpy.context)
    va = vol(a)
    left = easy.glue_everything(bpy.context)
    solids = [x for x in left if not sm.is_hole(x)]
    check(len(solids) == 2 and not any(sm.is_hole(x) for x in left), "glue: touching block+ball become one, the far cone stays, the hole is used up")
    big = max(solids, key=vol)
    check(vol(big) < va + 14137 and vol(big) > va * 0.9 and sm.compute_check(big)["open"] == 0, "glued model is one closed solid with the hole through it")
    sel(*solids)
    bpy.ops.simplemesh.easy_glue()
    check(len(objs()) == 1, "glue with two chosen shapes joins them even when they do not touch")

    print("hole shapes, weld, separate, copy, delete")
    reset()
    imp(p)
    blk = objs()[0]
    sel(blk)
    bpy.ops.simplemesh.add_shape(shape="CYLINDER", size_x=10, size_y=10, size_z=40, at_model=True)
    cyl = [x for x in objs() if x is not blk][0]
    sel(cyl)
    bpy.ops.simplemesh.mark_hole()
    check(sm.is_hole(cyl) and cyl.display_type == "WIRE", "cylinder marked as a hole (wire)")
    vb = vol(blk)
    r = bpy.ops.simplemesh.apply_holes()
    check("FINISHED" in r and len(objs()) == 1, "holes cut out, hole shape removed (no selection order needed)")
    check(close(vol(objs()[0]), vb - math.pi * 25 * 20, 0.03), "right amount removed")
    bpy.ops.simplemesh.add_shape(shape="BLOCK", size_x=10, size_y=10, size_z=10, at_model=False)
    extra = [x for x in objs() if x.name.startswith("Block")][0]
    extra.location.x = 18
    sm.refresh(bpy.context)
    sel(*objs())
    bpy.ops.simplemesh.weld()
    check(len(objs()) == 1 and sm.compute_check(objs()[0])["open"] == 0, "weld: one watertight model")
    reset()
    imp(p)
    a = objs()[0]
    bpy.ops.simplemesh.add_shape(shape="BLOCK", size_x=10, size_y=10, size_z=10, at_model=False)
    b2 = [x for x in objs() if x is not a][0]
    b2.location.x = 100
    sm.refresh(bpy.context)
    sel(b2, a)
    bpy.ops.simplemesh.combine(mode="JOIN")
    sel(objs()[0])
    bpy.ops.simplemesh.split_loose()
    check(len(objs()) == 2, "separate loose pieces -> 2 models")
    sel(objs()[0])
    bpy.ops.simplemesh.duplicate()
    check(len(objs()) == 3, "copy makes a third model")
    bpy.ops.simplemesh.delete()
    check(len(objs()) == 2, "delete removes the selected copy")

    print("cut")
    reset()
    imp(p)
    o = objs()[0]
    sel(o)
    v0 = vol(o)
    sc = bpy.context.scene
    sc.simplemesh.cut_axis, sc.simplemesh.cut_pos, sc.simplemesh.cut_keep = "Z", 25.0, "BOTH"
    r = bpy.ops.simplemesh.cut()
    check("FINISHED" in r, "cut ran")
    ob = objs()
    check(len(ob) == 2, "two halves")
    if len(ob) == 2:
        vs = sorted(vol(x) for x in ob)
        check(close(vs[0], v0 * 0.25) and close(vs[1], v0 * 0.75), "halves are 25/75 of volume: %s" % [round(v, 1) for v in vs])
        for x in ob:
            c = sm.compute_check(x)
            check(c["open"] == 0 and c["bad"] == 0 and not c["inverted"], "%s capped and watertight" % x.name)
            check(abs(sm.obj_bounds(x)[0].z) < 1e-3, "%s on the bed" % x.name)
    reset()
    imp(p)
    o = objs()[0]
    sel(o)
    sc = bpy.context.scene
    sc.simplemesh.cut_axis, sc.simplemesh.cut_pos, sc.simplemesh.cut_keep = "X", 50.0, "ABOVE"
    bpy.ops.simplemesh.cut()
    check(len(objs()) == 1 and close(dims(o).x, 20), "keep upper half only (x=20)")
    check(sm.compute_check(o)["open"] == 0, "single half capped")

    print("cut a sphere (curved, many loops)")
    reset()
    bpy.ops.simplemesh.add_shape(shape="SPHERE", size_x=60, size_y=60, size_z=60, at_model=False)
    o = objs()[0]
    sel(o)
    v0 = vol(o)
    sc = bpy.context.scene
    sc.simplemesh.cut_axis, sc.simplemesh.cut_pos, sc.simplemesh.cut_keep = "Z", 50.0, "BOTH"
    bpy.ops.simplemesh.cut()
    vs = [vol(x) for x in objs()]
    check(len(vs) == 2 and close(sum(vs), v0, 0.02), "sphere halves add up (%.0f vs %.0f)" % (sum(vs), v0))
    check(all(sm.compute_check(x)["open"] == 0 for x in objs()), "sphere halves watertight")

    print("shapes + combine")
    reset()
    imp(p)
    blk = objs()[0]
    sel(blk)
    bpy.ops.simplemesh.add_shape(shape="CYLINDER", size_x=10, size_y=10, size_z=40, at_model=True)
    cyl = [x for x in objs() if x is not blk][0]
    check(close(dims(cyl).x, 10) and close(dims(cyl).z, 40), "cylinder 10x10x40")
    vb, vc = vol(blk), vol(cyl)
    sel(cyl, blk)  # blk active
    r = bpy.ops.simplemesh.combine(mode="DIFFERENCE")
    check("FINISHED" in r and len(objs()) == 1, "subtract ran, cutter removed")
    b = objs()[0]
    expected = vb - math.pi * 5 * 5 * 20
    check(close(vol(b), expected, 0.03), "hole removed correct volume (%.0f vs %.0f)" % (vol(b), expected))
    check(sm.compute_check(b)["open"] == 0, "result watertight")
    reset()
    imp(p)
    a = objs()[0]
    bpy.ops.simplemesh.add_shape(shape="BLOCK", size_x=10, size_y=10, size_z=10, at_model=False)
    c2 = [x for x in objs() if x is not a][0]
    c2.location.x = 100
    sm.refresh(bpy.context)
    sel(c2, a)
    bpy.ops.simplemesh.combine(mode="JOIN")
    check(len(objs()) == 1 and len(objs()[0].data.polygons) > 12, "join merged two meshes")
    for shape in ("BLOCK", "SPHERE", "CONE"):
        reset()
        bpy.ops.simplemesh.add_shape(shape=shape, size_x=12, size_y=8, size_z=30, at_model=False)
        d = dims(objs()[0])
        check(close(d.x, 12) and close(d.y, 8) and close(d.z, 30) and sm.compute_check(objs()[0])["open"] == 0,
              "%s sized 12x8x30 and closed" % shape)

    print("repair")
    reset()
    write_stl(os.path.join(tmp, "holey.stl"), box_tris(30, 30, 30, drop_face=1))
    imp(os.path.join(tmp, "holey.stl"))
    o = objs()[0]
    sel(o)
    r0 = sm.compute_check(o)
    check(r0["open"] > 0, "test model has a hole (%d open edges)" % r0["open"])
    bpy.ops.simplemesh.repair()
    r1 = sm.compute_check(o)
    check(r1["open"] == 0 and close(r1["volume"], 27000, 0.02), "hole filled, volume %.0f" % r1["volume"])
    reset()
    write_stl(os.path.join(tmp, "inside.stl"), box_tris(30, 30, 30, flip=True))
    imp(os.path.join(tmp, "inside.stl"))
    o = objs()[0]
    sel(o)
    check(sm.compute_check(o)["inverted"], "inside-out model detected")
    bpy.ops.simplemesh.repair()
    check(not sm.compute_check(o)["inverted"], "normals fixed by repair")

    print("simplify")
    reset()
    bpy.ops.simplemesh.add_shape(shape="SPHERE", size_x=40, size_y=40, size_z=40, segments=96, at_model=False)
    o = objs()[0]
    sel(o)
    n0 = sm.compute_check(o)["tris"]
    bpy.ops.simplemesh.simplify(ratio=0.3)
    n1 = sm.compute_check(o)["tris"]
    check(n1 < n0 * 0.5, "triangles %d -> %d" % (n0, n1))

    print("export round-trip")
    reset()
    imp(p)
    o = objs()[0]
    sel(o)
    bpy.ops.simplemesh.scale_by(factor=2.0)
    out = os.path.join(tmp, "out.stl")
    bpy.ops.simplemesh.export_stl(filepath=out)
    check(os.path.exists(out) and os.path.getsize(out) > 84, "file written")
    reset()
    imp(out)
    d = dims(objs()[0])
    check(close(d.x, 80) and close(d.y, 60) and close(d.z, 40), "re-imported at 80x60x40 mm (got %s)" % (tuple(round(v, 2) for v in d),))

    print("views / look (via stored screens)")
    n_before = len(list(sm.each_view3d()))
    sm.declutter_viewports()
    sm.set_clip(bpy.context, 5000)
    sps = [s for _a, s in sm.each_view3d()]
    check(n_before > 0, "found %d 3D views in the stored screens" % n_before)
    if sps:
        sm.frame_bounds(bpy.context, Vector((-2500, -100, 0)), Vector((2500, 100, 50)))
        check(sps[0].region_3d.view_distance > 2500 and abs(sps[0].region_3d.view_location.z - 25) < 1, "view pointed at a 5 m model from far enough away")
        check(sps[0].clip_end >= 5000, "clip_end grown to %.0f for a big model" % sps[0].clip_end)
        check(sps[0].overlay.show_cursor is False and sps[0].show_region_toolbar is False, "3D cursor and Blender toolbar hidden")
        bpy.context.scene.simplemesh.look = "LUMINOUS"
        check(tuple(sps[0].shading.single_color)[2] > 0.5, "luminous look applied")
        bpy.context.scene.simplemesh.show_flipped = True
        check(sps[0].overlay.show_face_orientation, "flipped-face overlay on")

    print("strip, pop-ups and panels draw without errors (fake layout)")
    from simplemesh import ui
    ctx = bpy.context
    reset()
    imp(p)
    sel(objs()[0])
    bpy.ops.simplemesh.check()
    fake = type("P", (), {"layout": FakeLayout()})()
    for nm, fn in (("strip", lambda: ui.draw_strip(fake, ctx)), ("numbers", lambda: ui.draw_numbers(FakeLayout(), ctx)),
                   ("shapes", lambda: ui.draw_shapes(FakeLayout(), ctx)), ("repair", lambda: ui.draw_repair(FakeLayout(), ctx)),
                   ("view", lambda: ui.draw_view(FakeLayout(), ctx))):
        try:
            fn()
            check(True, nm + " draw")
        except Exception as ex:  # noqa: BLE001
            check(False, "%s draw raised %r" % (nm, ex))
    for cls in ui.PANELS:
        try:
            cls.draw(fake, ctx)
            check(True, cls.__name__ + " draw")
        except Exception as ex:  # noqa: BLE001
            check(False, "%s draw raised %r" % (cls.__name__, ex))

    print("unregister / re-register")
    sm.unregister()
    sm.register()
    check(True, "clean unregister + register")

    print()
    if FAILS:
        print("%d FAILED:" % len(FAILS))
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("ALL PASSED  (numpy: %s)" % ("yes" if sm.base.np is not None else "NO - fallback code")) 


if __name__ == "__main__":
    main()

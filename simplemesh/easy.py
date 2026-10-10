# SimpleMesh - Easy mode: build things from shapes with picture buttons
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 3. No warranty; see LICENSE.
#
# Written for a ten-year-old (see docs/DESIGN.md, "Easy mode"):
#   * pictures and plain words, no CAD vocabulary, nothing to type
#   * you start from ready-made shapes, a drawing, your name, a lump of clay or
#     a ready-made idea, never from a blank screen with forty buttons
#   * shapes sit on whatever is under the mouse, so things stack and stick
#   * the selected shape has dots on it: pull a dot to stretch, grow or turn it
#   * big buttons turn the view, because orbiting with a mouse is hard
#   * nothing can be broken: Undo is a big button, and "Print!" repairs, joins
#     and checks the model before saving it

import math
import os

import bmesh
import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper
from mathutils import Matrix, Vector
from mathutils.geometry import convex_hull_2d, intersect_line_line, intersect_line_plane

from . import base as B
from . import interactive as I

CURRENT = {"tool": None}          # the running Easy tool (tests read its button positions)

PALETTE = [(0.95, 0.26, 0.21), (1.0, 0.60, 0.0), (1.0, 0.85, 0.15), (0.30, 0.75, 0.30),
           (0.0, 0.80, 0.90), (0.20, 0.45, 0.95), (0.62, 0.32, 0.85), (0.93, 0.93, 0.93)]
_next_colour = {"i": 4}


def next_colour():
    c = PALETTE[_next_colour["i"] % len(PALETTE)]
    _next_colour["i"] += 1
    return c


# --------------------------------------------------------------------------
# Shape library
# --------------------------------------------------------------------------

SHAPES = (            # key, name on the button, size in mm (x, y, z)
    ("block", "Block", (30.0, 30.0, 30.0)),
    ("ball", "Ball", (30.0, 30.0, 30.0)),
    ("tube", "Tube", (30.0, 30.0, 30.0)),
    ("cone", "Cone", (30.0, 30.0, 30.0)),
    ("pyramid", "Pyramid", (30.0, 30.0, 30.0)),
    ("roof", "Roof", (30.0, 30.0, 18.0)),
    ("ring", "Ring", (40.0, 40.0, 12.0)),
    ("star", "Star", (40.0, 38.0, 8.0)),
    ("heart", "Heart", (40.0, 36.0, 8.0)),
)
SHAPE_SIZE = {k: s for k, _n, s in SHAPES}
SHAPE_NAME = {k: n for k, n, _s in SHAPES}


def outline_star(points=5, inner=0.45):
    out = []
    for i in range(points * 2):
        a = math.pi / 2 + math.pi * i / points
        r = 1.0 if i % 2 == 0 else inner
        out.append((r * math.cos(a), r * math.sin(a)))
    return out


def outline_heart(n=44):
    out = []
    for i in range(n):
        t = 2 * math.pi * i / n
        out.append((16 * math.sin(t) ** 3,
                    13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
    return out


def bm_prism(outline, height):
    """A flat outline (list of (x, y)) pushed up into a solid."""
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, 0.0)) for x, y in outline]
    face = bm.faces.new(vs)
    res = bmesh.ops.extrude_face_region(bm, geom=[face])
    for g in res["geom"]:
        if isinstance(g, bmesh.types.BMVert):
            g.co.z += height
    return bm


def bm_torus(big=1.0, small=0.3, nu=40, nv=16):
    bm = bmesh.new()
    rings = []
    for i in range(nu):
        a = 2 * math.pi * i / nu
        ring = []
        for j in range(nv):
            b = 2 * math.pi * j / nv
            d = big + small * math.cos(b)
            ring.append(bm.verts.new((d * math.cos(a), d * math.sin(a), small * math.sin(b))))
        rings.append(ring)
    for i in range(nu):
        for j in range(nv):
            bm.faces.new((rings[i][j], rings[(i + 1) % nu][j],
                          rings[(i + 1) % nu][(j + 1) % nv], rings[i][(j + 1) % nv]))
    return bm


def _cone(bm, segments, r2):
    try:
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                              radius1=0.5, radius2=r2, depth=1.0)
    except TypeError:
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                              diameter1=0.5, diameter2=r2, depth=1.0)


def bm_shape(kind):
    if kind == "star":
        return bm_prism(outline_star(), 1.0)
    if kind == "heart":
        return bm_prism(outline_heart(), 1.0)
    if kind == "ring":
        return bm_torus()
    bm = bmesh.new()
    if kind == "block":
        bmesh.ops.create_cube(bm, size=1.0)
    elif kind == "ball":
        try:
            bmesh.ops.create_uvsphere(bm, u_segments=40, v_segments=20, radius=0.5)
        except TypeError:
            bmesh.ops.create_uvsphere(bm, u_segments=40, v_segments=20, diameter=0.5)
    elif kind == "tube":
        _cone(bm, 48, 0.5)
    elif kind == "cone":
        _cone(bm, 48, 0.0)
    elif kind == "pyramid":
        _cone(bm, 4, 0.0)
        bmesh.ops.rotate(bm, verts=bm.verts[:], cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 4, 3, "Z"))
    elif kind == "roof":
        v = [bm.verts.new(p) for p in ((-0.5, -0.5, 0), (0.5, -0.5, 0), (0, -0.5, 0.5),
                                       (-0.5, 0.5, 0), (0.5, 0.5, 0), (0, 0.5, 0.5))]
        for f in ((0, 1, 2), (3, 5, 4), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)):
            bm.faces.new([v[i] for i in f])
    else:
        raise ValueError("unknown shape %r" % kind)
    return bm


def fit_bm(bm, size):
    """Stretch a bmesh so its bounding box is exactly size (x, y, z), centred on 0."""
    lo = [min(v.co[k] for v in bm.verts) for k in range(3)]
    hi = [max(v.co[k] for v in bm.verts) for k in range(3)]
    for v in bm.verts:
        v.co = Vector([((v.co[k] - (lo[k] + hi[k]) / 2.0) / ((hi[k] - lo[k]) or 1.0)) * size[k]
                       for k in range(3)])
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])


def new_shape(context, kind, size=None, colour=None, name=None):
    bm = bm_shape(kind)
    fit_bm(bm, size or SHAPE_SIZE[kind])
    ob = B.new_mesh_object(context, name or SHAPE_NAME[kind], bm)
    c = colour or next_colour()
    ob.color = (c[0], c[1], c[2], 1.0)
    return ob


# --------------------------------------------------------------------------
# Drawing a shape: turn a wobbly mouse line into a clean outline
# --------------------------------------------------------------------------

def _seg_x(a, b, c, d):
    """Where segment a-b properly crosses c-d, or None."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if 1e-9 < t < 1 - 1e-9 and 1e-9 < u < 1 - 1e-9:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def _area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                     for i in range(len(poly)))


def _simple(poly):
    n = len(poly)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _seg_x(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]) is not None:
                return False
    return True


def clean_outline(points, max_points=160):
    """Thin, close and untangle a hand-drawn loop. Always returns a usable
    counter-clockwise outline (falling back to the hull of the scribble), or
    None if there is hardly anything there."""
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 3:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    if span < 3.0:
        return None
    step = max(span / 80.0, 0.5)
    thin = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - thin[-1][0], p[1] - thin[-1][1]) >= step:
            thin.append(p)
    while len(thin) > max_points:
        thin = thin[::2]
    if len(thin) < 3:
        return None
    cands = []
    if _simple(thin):
        cands.append(thin)
    else:
        n = len(thin)
        for i in range(n - 1):                    # loops closed where the line crosses itself
            for j in range(i + 2, n - 1):
                x = _seg_x(thin[i], thin[i + 1], thin[j], thin[j + 1])
                if x is not None:
                    loop = [x] + thin[i + 1:j + 1]
                    if len(loop) >= 3:
                        cands.append(loop)
    best = None
    for c in sorted(cands, key=lambda q: -abs(_area(q))):
        if _simple(c):
            best = c
            break
    if best is None or abs(_area(best)) < 0.15 * span * span * 0.2:
        hull = convex_hull_2d([Vector(p) for p in thin])
        best = [thin[i] for i in hull]
    if len(best) < 3 or abs(_area(best)) < 4.0:
        return None
    n = len(best)                                  # one round of corner cutting: smoother curves
    smooth = []
    for i in range(n):
        a, b = best[i], best[(i + 1) % n]
        smooth.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
        smooth.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
    if not _simple(smooth):
        smooth = best
    if _area(smooth) < 0:
        smooth.reverse()
    return smooth


def solid_from_outline(context, outline, height=10.0, name="Drawing"):
    cx = sum(p[0] for p in outline) / len(outline)
    cy = sum(p[1] for p in outline) / len(outline)
    bm = bm_prism([(x - cx, y - cy) for x, y in outline], height)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    ob = B.new_mesh_object(context, name, bm)
    ob.location = Vector((cx, cy, 0.0))
    c = next_colour()
    ob.color = (c[0], c[1], c[2], 1.0)
    B.bake(ob)
    return ob


# --------------------------------------------------------------------------
# Words, glue, ideas, print
# --------------------------------------------------------------------------

def make_text(context, text, size=24.0, thick=5.0):
    """3D letters lying flat on the bed, readable from above."""
    text = (text or "").strip()
    if not text:
        return None
    cu = bpy.data.curves.new("SimpleMeshText", "FONT")
    cu.body = text
    cu.size = size
    cu.extrude = thick / 2.0
    B._set(cu, "align_x", "CENTER")
    tmp = bpy.data.objects.new("SimpleMeshText", cu)
    context.collection.objects.link(tmp)
    try:
        dg = context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg), depsgraph=dg)
    finally:
        bpy.data.objects.remove(tmp, do_unlink=True)
        bpy.data.curves.remove(cu)
    if len(me.polygons) == 0:
        bpy.data.meshes.remove(me)
        return None
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-4)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(text[:20], me)
    context.collection.objects.link(ob)
    c = next_colour()
    ob.color = (c[0], c[1], c[2], 1.0)
    B.bake(ob)
    lo, _hi = B.obj_bounds(ob)
    ob.location = ob.location + Vector((0.0, 0.0, -lo.z))
    return ob


def _join_plain(base, other):
    me2 = other.data.copy()
    me2.transform(base.matrix_basis.inverted() @ other.matrix_basis)
    bm = bmesh.new()
    bm.from_mesh(base.data)
    bm.from_mesh(me2)
    bm.to_mesh(base.data)
    bm.free()
    bpy.data.meshes.remove(me2)
    base.data.update()


def glue(context, objs):
    """Make several models one. Overlapping parts are properly merged; if Blender's
    merge gives a broken result the parts are simply kept together instead."""
    objs = [o for o in objs if not B.is_hole(o)]
    if not objs:
        return None
    base = objs[0]
    for o in objs:
        B.bake(o)
    B.refresh(context)
    for t in objs[1:]:
        before, tb = B.compute_check(base), B.compute_check(t)
        backup = base.data.copy()
        ok = True
        try:
            B._boolean(context, base, t, "UNION")
            B.bake(base)
            after = B.compute_check(base)
            ok = (after["tris"] > 0 and after["open"] <= before["open"] + tb["open"]
                  and after["volume"] >= max(before["volume"], tb["volume"]) * 0.98)
        except Exception:
            ok = False
        if ok:
            bpy.data.meshes.remove(backup)
        else:
            old = base.data
            name = old.name
            base.data = backup
            if old.users == 0:
                bpy.data.meshes.remove(old)
            backup.name = name
            B.bake(base)
            _join_plain(base, t)
        B._remove(t)
        B.bake(base)
        B.refresh(context)
    return base


def touching_groups(objs):
    parent = list(range(len(objs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(objs)):
        for j in range(i + 1, len(objs)):
            if B._overlap(objs[i], objs[j]):
                parent[find(i)] = find(j)
    groups = {}
    for i, o in enumerate(objs):
        groups.setdefault(find(i), []).append(o)
    return list(groups.values())


def glue_everything(context, only=None):
    """Cut out the holes, then glue every group of touching models.
    Returns the list of models left."""
    vis = [o for o in context.view_layer.objects if o.type == "MESH" and o.visible_get()]
    if any(B.is_hole(o) for o in vis):
        try:
            bpy.ops.simplemesh.apply_holes()
        except Exception:
            pass
        vis = [o for o in context.view_layer.objects if o.type == "MESH" and o.visible_get()]
    solids = [o for o in vis if not B.is_hole(o)]
    if only is not None:
        names = {o.name for o in only}
        chosen = [o for o in solids if o.name in names]
        if len(chosen) >= 2:
            glue(context, chosen)
    else:
        for o in solids:
            B.unparent(o)
        for grp in touching_groups(solids):
            if len(grp) > 1:
                glue(context, grp)
    return [o for o in context.view_layer.objects if o.type == "MESH" and o.visible_get()]


def make_printable(context):
    """Holes cut, touching parts glued, everything repaired and resting on the
    bed. Returns (models, fits_bed, all_watertight)."""
    models = glue_everything(context)
    for o in models:
        B.bake(o)
        B.repair_mesh(o.data)
        B.bake(o)
    if not models:
        return [], True, True
    lo, hi = B.group_bounds(models)
    for o in models:
        o.location = o.location + Vector((-(lo.x + hi.x) / 2.0, -(lo.y + hi.y) / 2.0, -lo.z))
    B.refresh(context)
    lo, hi = B.group_bounds(models)
    p = B.prefs(context)
    d = hi - lo
    fits = d.x <= p.bed_x + 1e-3 and d.y <= p.bed_y + 1e-3 and d.z <= p.bed_z + 1e-3
    tight = True
    for o in models:
        c = B.compute_check(o)
        if c["open"] or c["inverted"]:
            tight = False
    return models, fits, tight


# ready-made starters: (shape, size, centre, turn in degrees about x/y/z, colour number)
IDEAS = {
    "snowman": ("Snowman", [
        ("ball", (40, 40, 40), (0, 0, 20), (0, 0, 0), 7),
        ("ball", (30, 30, 30), (0, 0, 50), (0, 0, 0), 7),
        ("ball", (22, 22, 22), (0, 0, 72), (0, 0, 0), 7),
        ("cone", (6, 6, 14), (0, -15, 72), (90, 0, 0), 1),
        ("tube", (26, 26, 3), (0, 0, 82), (0, 0, 0), 5),
        ("tube", (16, 16, 14), (0, 0, 89), (0, 0, 0), 5)]),
    "house": ("House", [
        ("block", (50, 40, 30), (0, 0, 15), (0, 0, 0), 2),
        ("roof", (56, 46, 24), (0, 0, 41), (0, 0, 0), 0),
        ("block", (8, 8, 18), (16, 8, 44), (0, 0, 0), 7),
        ("block", (10, 4, 18), (-10, -20, 9), (0, 0, 0), 5)]),
    "rocket": ("Rocket", [
        ("cone", (40, 40, 22), (0, 0, 11), (0, 0, 0), 5),
        ("tube", (24, 24, 52), (0, 0, 36), (0, 0, 0), 7),
        ("cone", (24, 24, 24), (0, 0, 73), (0, 0, 0), 0),
        ("ball", (10, 10, 10), (0, -10, 48), (0, 0, 0), 4)]),
    "robot": ("Robot", [
        ("block", (12, 14, 24), (-9, 0, 12), (0, 0, 0), 5),
        ("block", (12, 14, 24), (9, 0, 12), (0, 0, 0), 5),
        ("block", (34, 22, 36), (0, 0, 41), (0, 0, 0), 4),
        ("block", (24, 20, 20), (0, 0, 68), (0, 0, 0), 7),
        ("tube", (8, 8, 28), (-21, 0, 44), (0, 0, 0), 1),
        ("tube", (8, 8, 28), (21, 0, 44), (0, 0, 0), 1),
        ("ball", (6, 6, 6), (-5, -10, 70), (0, 0, 0), 0),
        ("ball", (6, 6, 6), (5, -10, 70), (0, 0, 0), 0)]),
    "car": ("Car", [
        ("block", (70, 32, 16), (0, 0, 17), (0, 0, 0), 0),
        ("block", (34, 28, 14), (-4, 0, 31), (0, 0, 0), 4),
        ("tube", (18, 18, 8), (-22, -16, 9), (90, 0, 0), 7),
        ("tube", (18, 18, 8), (22, -16, 9), (90, 0, 0), 7),
        ("tube", (18, 18, 8), (-22, 16, 9), (90, 0, 0), 7),
        ("tube", (18, 18, 8), (22, 16, 9), (90, 0, 0), 7)]),
}
IDEA_ORDER = ("snowman", "house", "rocket", "robot", "car")


def build_idea(context, key):
    name, parts = IDEAS[key]
    out = []
    for kind, size, pos, rot, col in parts:
        ob = new_shape(context, kind, size, PALETTE[col], name + " " + SHAPE_NAME[kind].lower())
        m = Matrix.Translation(Vector(pos))
        for ax, deg in zip("XYZ", rot):
            if deg:
                m = m @ Matrix.Rotation(math.radians(deg), 4, ax)
        ob.matrix_basis = m
        B.bake(ob)
        out.append(ob)
    B.refresh(context)
    return out


def free_spot(context, width):
    """An x position beside whatever is already on the bed."""
    vis = [o for o in context.view_layer.objects if o.type == "MESH" and o.visible_get()]
    if not vis:
        return 0.0
    _lo, hi = I.quick_bounds(vis)
    return hi.x + 12.0 + width / 2.0


class SIMPLEMESH_OT_easy_words(Operator):
    """Type a word or your name and get it as 3D letters"""
    bl_idname = "simplemesh.easy_words"
    bl_label = "Type your words, then press OK"
    bl_options = {"REGISTER", "UNDO"}

    text: StringProperty(name="Words", default="Hello")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        ob = make_text(context, self.text)
        if ob is None:
            self.report({"WARNING"}, "Type some letters first")
            return {"CANCELLED"}
        lo, hi = B.obj_bounds(ob)
        others = [o for o in context.view_layer.objects if o.type == "MESH" and o.visible_get() and o is not ob]
        if others:
            _olo, ohi = I.quick_bounds(others)
            ob.location = ob.location + Vector((ohi.x + 12.0 - lo.x, 0.0, 0.0))
        B.refresh(context)
        B.select_only(context, [ob])
        B.frame_model(context, everything=True)
        return {"FINISHED"}


class SIMPLEMESH_OT_easy_glue(Operator):
    """Glue: stick the chosen shapes together into one (or, with nothing chosen,
    everything that touches). Red hole shapes are cut out first"""
    bl_idname = "simplemesh.easy_glue"
    bl_label = "Glue"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        B.ensure_object_mode(context)
        sel = [o for o in B.mesh_objects(context) if not B.is_hole(o)]
        left = glue_everything(context, only=sel if len(sel) >= 2 else None)
        solids = [o for o in left if not B.is_hole(o)]
        if solids:
            B.select_only(context, [solids[0]] if len(sel) >= 2 else solids)
        self.report({"INFO"}, "%d model(s) now" % len(solids))
        return {"FINISHED"}


class SIMPLEMESH_OT_easy_idea(Operator):
    """Put a ready-made idea on the bed to change and add to"""
    bl_idname = "simplemesh.easy_idea"
    bl_label = "Idea"
    bl_options = {"REGISTER", "UNDO"}

    key: StringProperty(default="snowman")

    def execute(self, context):
        if self.key not in IDEAS:
            return {"CANCELLED"}
        x = free_spot(context, 70.0)
        parts = build_idea(context, self.key)
        if x:
            for o in parts:
                o.location = o.location + Vector((x, 0.0, 0.0))
        B.refresh(context)
        B.select_only(context, parts)
        B.frame_model(context, everything=True)
        return {"FINISHED"}


class SIMPLEMESH_OT_easy_print(Operator, ExportHelper):
    """Print!: cuts out the holes, glues touching shapes, repairs everything, sits
    it on the bed and saves a file for your 3D printer"""
    bl_idname = "simplemesh.easy_print"
    bl_label = "Save for printing"

    filename_ext = ".stl"
    filter_glob: StringProperty(default="*.stl", options={"HIDDEN"})

    def invoke(self, context, event):
        B.ensure_object_mode(context)
        models, fits, tight = make_printable(context)
        if not models:
            self.report({"WARNING"}, "There is nothing to print yet. Add a shape first!")
            return {"CANCELLED"}
        try:
            bpy.ops.ed.undo_push(message="SimpleMesh: ready to print")
        except Exception:
            pass
        B.select_only(context, models)
        B.frame_model(context, everything=True)
        if not fits:
            self.report({"WARNING"}, "It is bigger than your printer's bed. Make it smaller, or save it anyway")
        elif not tight:
            self.report({"WARNING"}, "Some parts still have gaps; your printer program may fix them")
        d = context.scene.simplemesh.last_dir
        self.filepath = os.path.join(d, "my_model.stl") if d else "my_model.stl"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        objs = [o for o in context.view_layer.objects
                if o.type == "MESH" and o.visible_get() and not B.is_hole(o)]
        if not objs:
            return {"CANCELLED"}
        B.select_only(context, objs)
        B.raw_export_stl(self.filepath, True)
        self.report({"INFO"}, "Saved %s. Open it in your printer program!" % bpy.path.basename(self.filepath))
        return {"FINISHED"}


# --------------------------------------------------------------------------
# Picture buttons (drawn straight onto the 3D view)
# --------------------------------------------------------------------------

W = (1.0, 1.0, 1.0, 1.0)
W2 = (0.80, 0.86, 0.92, 1.0)
W3 = (0.62, 0.70, 0.78, 1.0)


def _fan(pts, col):
    if len(pts) < 3:
        return
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    tris = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        tris += [(cx, cy, 0), (a[0], a[1], 0), (b[0], b[1], 0)]
    I._batch("TRIS", tris, col)


def _rect(x, y, w, h, col):
    I._batch("TRIS", [(x, y, 0), (x + w, y, 0), (x + w, y + h, 0), (x, y, 0), (x + w, y + h, 0), (x, y + h, 0)], col)


def _circle(cx, cy, r, col, n=28, sy=1.0):
    _fan([(cx + r * math.cos(2 * math.pi * i / n), cy + r * sy * math.sin(2 * math.pi * i / n)) for i in range(n)], col)


def _line(pts, col, width=2.0, loop=False):
    I._batch("LINE_LOOP" if loop else "LINE_STRIP", [(p[0], p[1], 0) for p in pts], col, width)


def _arrow(x, y, dx, dy, col, s):
    ln = math.hypot(dx, dy) or 1.0
    ux, uy = dx / ln, dy / ln
    _line([(x, y), (x + dx, y + dy)], col, 2.5)
    hx, hy = x + dx, y + dy
    _fan([(hx + ux * 5 * s, hy + uy * 5 * s), (hx - uy * 4 * s, hy + ux * 4 * s), (hx + uy * 4 * s, hy - ux * 4 * s)], col)


def icon(name, cx, cy, r, s):
    """Draw the picture for a button, centred on (cx, cy) with half-size r."""
    if name == "block":
        _fan([(cx, cy + r), (cx + r, cy + r * 0.5), (cx, cy), (cx - r, cy + r * 0.5)], W)
        _fan([(cx - r, cy + r * 0.5), (cx, cy), (cx, cy - r), (cx - r, cy - r * 0.5)], W2)
        _fan([(cx + r, cy + r * 0.5), (cx, cy), (cx, cy - r), (cx + r, cy - r * 0.5)], W3)
    elif name == "ball":
        _circle(cx, cy, r, W2)
        _circle(cx - r * 0.3, cy + r * 0.3, r * 0.3, W)
    elif name == "tube":
        _rect(cx - r * 0.7, cy - r * 0.7, r * 1.4, r * 1.4, W2)
        _circle(cx, cy - r * 0.7, r * 0.7, W2, sy=0.35)
        _circle(cx, cy + r * 0.7, r * 0.7, W, sy=0.35)
    elif name == "cone":
        _fan([(cx, cy + r), (cx + r * 0.8, cy - r * 0.7), (cx - r * 0.8, cy - r * 0.7)], W2)
        _circle(cx, cy - r * 0.7, r * 0.8, W2, sy=0.3)
    elif name == "pyramid":
        _fan([(cx, cy + r), (cx - r, cy - r * 0.6), (cx + r * 0.2, cy - r)], W)
        _fan([(cx, cy + r), (cx + r * 0.2, cy - r), (cx + r, cy - r * 0.5)], W3)
    elif name == "roof":
        _fan([(cx - r, cy - r * 0.6), (cx - r * 0.2, cy - r * 0.6), (cx - r * 0.6, cy + r * 0.5)], W)
        _fan([(cx - r * 0.2, cy - r * 0.6), (cx + r, cy - r * 0.1), (cx + r * 0.6, cy + r), (cx - r * 0.6, cy + r * 0.5)], W3)
    elif name == "ring":
        n = 28
        tris = []
        for i in range(n):
            a, b = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
            p = [(cx + r * math.cos(a), cy + r * 0.7 * math.sin(a)), (cx + r * math.cos(b), cy + r * 0.7 * math.sin(b)),
                 (cx + r * 0.5 * math.cos(b), cy + r * 0.35 * math.sin(b)), (cx + r * 0.5 * math.cos(a), cy + r * 0.35 * math.sin(a))]
            tris += [(p[0][0], p[0][1], 0), (p[1][0], p[1][1], 0), (p[2][0], p[2][1], 0),
                     (p[0][0], p[0][1], 0), (p[2][0], p[2][1], 0), (p[3][0], p[3][1], 0)]
        I._batch("TRIS", tris, W2)
    elif name == "star":
        _fan([(cx + r * x, cy + r * y) for x, y in outline_star()], W)
    elif name == "heart":
        _fan([(cx + r * x / 17.0, cy + r * (y + 3) / 17.0) for x, y in outline_heart(30)], W)
    elif name == "draw":
        _line([(cx - r, cy - r * 0.3), (cx - r * 0.5, cy + r * 0.5), (cx, cy - r * 0.2), (cx + r * 0.4, cy + r * 0.4)], W2, 2.5)
        _fan([(cx + r * 0.2, cy - r * 0.9), (cx + r * 0.45, cy - r * 0.65), (cx + r, cy - r * 0.1 + r * 0.9), (cx + r * 0.75, cy + r * 0.55)], W)
    elif name == "words":
        I.text(cx, cy - r * 0.45, "Abc", 17, W, centre=True, box=False)
    elif name == "clay":
        _fan([(cx + r * (0.85 + 0.15 * math.sin(3 * t)) * math.cos(t), cy + r * 0.8 * (0.85 + 0.15 * math.cos(5 * t)) * math.sin(t))
              for t in (2 * math.pi * i / 30 for i in range(30))], W2)
        _circle(cx - r * 0.25, cy + r * 0.25, r * 0.22, W)
    elif name == "ideas":
        _circle(cx, cy + r * 0.25, r * 0.62, (1.0, 0.9, 0.3, 1.0))
        _rect(cx - r * 0.28, cy - r * 0.85, r * 0.56, r * 0.4, W3)
    elif name == "open":
        _rect(cx - r, cy - r * 0.7, r * 2, r * 1.2, W3)
        _fan([(cx - r, cy - r * 0.7), (cx + r * 0.7, cy - r * 0.7), (cx + r, cy + r * 0.2), (cx - r * 0.7, cy + r * 0.2)], W)
    elif name in ("undo", "redo"):
        d = 1 if name == "redo" else -1
        pts = [(cx + d * r * 0.8 * math.cos(t), cy - r * 0.2 + r * 0.8 * math.sin(t)) for t in (math.pi * i / 12 for i in range(1, 12))]
        _line(pts, W, 3.0)
        ex, ey = pts[0]
        _fan([(ex + d * r * 0.1, ey - r * 0.55), (ex - d * r * 0.4, ey + r * 0.15), (ex + d * r * 0.45, ey + r * 0.2)], W)
    elif name == "copy":
        _rect(cx - r * 0.8, cy - r * 0.2, r * 1.1, r * 1.1, W3)
        _rect(cx - r * 0.3, cy - r * 0.9, r * 1.1, r * 1.1, W)
    elif name == "bin":
        _fan([(cx - r * 0.6, cy + r * 0.5), (cx + r * 0.6, cy + r * 0.5), (cx + r * 0.45, cy - r), (cx - r * 0.45, cy - r)], W)
        _rect(cx - r * 0.8, cy + r * 0.6, r * 1.6, r * 0.22, W)
        _rect(cx - r * 0.25, cy + r * 0.8, r * 0.5, r * 0.2, W)
    elif name == "hole":
        _rect(cx - r, cy - r * 0.8, r * 2, r * 1.6, W2)
        _circle(cx, cy, r * 0.5, (0.95, 0.25, 0.2, 1.0))
    elif name == "glue":
        _rect(cx - r, cy - r * 0.6, r * 1.1, r * 1.1, W3)
        _circle(cx + r * 0.35, cy + r * 0.2, r * 0.6, W)
    elif name == "save":
        _rect(cx - r * 0.85, cy - r * 0.85, r * 1.7, r * 1.7, W)
        _rect(cx - r * 0.5, cy + r * 0.25, r * 1.0, r * 0.6, W3)
        _rect(cx - r * 0.55, cy - r * 0.85, r * 1.1, r * 0.7, W2)
    elif name == "print":
        _rect(cx - r, cy - r * 0.5, r * 2, r * 0.9, W)
        _rect(cx - r * 0.6, cy + r * 0.4, r * 1.2, r * 0.55, W2)
        _rect(cx - r * 0.6, cy - r, r * 1.2, r * 0.6, W2)
    elif name in ("left", "right", "up", "down"):
        d = {"left": (-1, 0), "right": (1, 0), "up": (0, 1), "down": (0, -1)}[name]
        _fan([(cx + d[0] * r * 0.8, cy + d[1] * r * 0.8),
              (cx - d[0] * r * 0.5 - d[1] * r * 0.7, cy - d[1] * r * 0.5 + d[0] * r * 0.7),
              (cx - d[0] * r * 0.5 + d[1] * r * 0.7, cy - d[1] * r * 0.5 - d[0] * r * 0.7)], W)
    elif name in ("plus", "minus"):
        _rect(cx - r * 0.8, cy - r * 0.18, r * 1.6, r * 0.36, W)
        if name == "plus":
            _rect(cx - r * 0.18, cy - r * 0.8, r * 0.36, r * 1.6, W)
    elif name == "home":
        _line([(cx + r * 0.8 * math.cos(t), cy + r * 0.8 * math.sin(t)) for t in (2 * math.pi * i / 20 for i in range(20))], W, 2.5, loop=True)
        _circle(cx, cy, r * 0.25, W)


ADD_TILES = [(k, n) for k, n, _s in SHAPES] + [("draw", "Draw"), ("words", "Words"), ("clay", "Clay"),
                                              ("ideas", "Ideas"), ("open", "Open")]
DO_TILES = [("undo", "Undo"), ("redo", "Redo"), ("copy", "Copy"), ("bin", "Bin"), ("hole", "Hole"), ("glue", "Glue"),
            ("save", "Save")]
VIEW_TILES = [("left", ""), ("right", ""), ("up", ""), ("down", ""), ("plus", ""), ("minus", ""), ("home", "")]
TIPS = {
    "block": "Block: click, then click where you want it", "ball": "Ball", "tube": "Tube", "cone": "Cone",
    "pyramid": "Pyramid", "roof": "Roof", "ring": "Ring", "star": "Star", "heart": "Heart",
    "draw": "Draw your own shape on the floor and it becomes solid",
    "words": "Type a word or your name: you get 3D letters",
    "clay": "Clay: squish and pull the chosen shape (or a new ball) like clay",
    "ideas": "Ideas: start from a snowman, a house, a rocket, a robot or a car",
    "open": "Open a model file (STL) from the computer",
    "undo": "Undo: go back one step", "redo": "Redo: go forward again",
    "copy": "Copy: make another one the same", "bin": "Bin: throw the chosen shape away",
    "hole": "Hole: turn the chosen shape into a hole (it goes red). Glue or Print cuts it out",
    "glue": "Glue: stick the shapes together into one",
    "save": "Save your work so you can carry on another day",
    "print": "Print!: fixes everything and saves a file for the 3D printer",
    "left": "Look from the left", "right": "Look from the right", "up": "Look from higher up",
    "down": "Look from lower down", "plus": "Closer", "minus": "Further away", "home": "Show everything",
}
HANDLE_TIP = {"size": "pull: bigger or smaller", "x": "pull: longer", "y": "pull: wider", "z": "pull: taller",
              "turn": "pull sideways: spin round", "tip": "pull up or down: tip over"}
HANDLE_COL = {"size": (1.0, 1.0, 1.0), "x": I.AXIS_COL["X"], "y": I.AXIS_COL["Y"], "z": I.AXIS_COL["Z"],
              "turn": (1.0, 0.72, 0.1), "tip": (0.62, 0.32, 0.85)}
KEYS = "right-drag or the arrow buttons = look around   |   wheel = zoom   |   Delete = bin   |   Ctrl+Z = undo"


class SIMPLEMESH_OT_tool_easy(I.ToolBase, Operator):
    """Easy mode: build with picture buttons. Click a shape, click where it goes; shapes sit on each other. Pull the dots to stretch, grow and turn"""
    bl_idname = "simplemesh.tool_easy"
    bl_label = "Easy"
    tool_name = "easy"
    title = "Easy"
    hint = "click a picture on the left to add a shape"
    keys = KEYS

    # ---- set-up ------------------------------------------------------------
    def setup(self, context):
        self.state = "IDLE"
        self.rects = {}
        self.hover = None
        self.tray = False
        self.drag = None
        self.handles = {}
        self.stroke = []
        self.stroke2d = []
        context.scene.simplemesh.easy_on = True
        for _a, sp in B.each_view3d(context):
            B._set(sp.shading, "color_type", "OBJECT")
        CURRENT["tool"] = self
        self.idle_hint(context)

    def finish(self, context):
        if CURRENT["tool"] is self:
            CURRENT["tool"] = None
        try:
            if not context.scene.simplemesh.easy_on:      # really leaving, not just lending the mouse to another tool
                B.apply_look(context)
        except Exception:
            pass
        I.ToolBase.finish(self, context)

    def idle_hint(self, context):
        sel = self.selection(context)
        if sel:
            self.say("drag it to move it  -  pull the dots to stretch, grow or turn it", KEYS)
        else:
            self.say("click a picture on the left to add a shape  -  shapes sit on each other", KEYS)

    def selection(self, context):
        return [o for o in context.selected_objects if o.type == "MESH"]

    # ---- where the buttons are ---------------------------------------------
    def place_buttons(self, context):
        s = I.ui_scale()
        rg = self.region
        top = rg.height - I.top_offset(context) - 96 * s
        gap = 6 * s
        bar = 58 * s
        rows = (len(ADD_TILES) + 1) // 2
        size = max(40 * s, min(64 * s, (top - (bar + 28 * s)) / rows - gap))
        rects = {}
        x0 = 12 * s
        for i, (key, _n) in enumerate(ADD_TILES):
            col, row = i % 2, i // 2
            rects["add:" + key] = (x0 + col * (size + gap), top - (row + 1) * (size + gap) + gap, size, size)
        if self.tray:
            tx = x0 + 2 * (size + gap) + 6 * s
            ty = rects["add:ideas"][1]
            for i, key in enumerate(IDEA_ORDER):
                rects["idea:" + key] = (tx + i * (size * 1.5 + gap), ty, size * 1.5, size)
        b = 50 * s
        sw = 30 * s
        total = len(DO_TILES) * (b + gap) + 14 * s + len(PALETTE) * (sw + 4 * s) + 14 * s + b * 1.7
        x = max((rg.width - total) / 2.0, x0 + 2 * (size + gap) + 10 * s)
        y = 12 * s
        for key, _n in DO_TILES:
            rects["do:" + key] = (x, y, b, b)
            x += b + gap
        x += 14 * s
        for i in range(len(PALETTE)):
            rects["col:%d" % i] = (x, y + (b - sw) / 2.0, sw, sw)
            x += sw + 4 * s
        x += 14 * s
        rects["do:print"] = (x, y, b * 1.7, b)
        v = 36 * s
        vx = rg.width - 12 * s - 3 * (v + 4 * s)
        vy = 12 * s
        pos = {"left": (0, 1), "home": (1, 1), "right": (2, 1), "up": (1, 2), "down": (1, 0), "minus": (0, 0), "plus": (2, 0)}
        for key, (cx, cy) in pos.items():
            rects["view:" + key] = (vx + cx * (v + 4 * s), vy + cy * (v + 4 * s), v, v)
        self.rects = rects

    def tile_at(self, x, y):
        for key, (rx, ry, rw, rh) in self.rects.items():
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return key
        return None

    def in_gizmo_corner(self, context, x, y):
        s = I.ui_scale()
        rg = self.region
        return x > rg.width - 150 * s and y > rg.height - I.top_offset(context) - 330 * s

    # ---- the dots on the chosen shape ----------------------------------------
    def compute_handles(self, context):
        self.handles = {}
        sel = self.selection(context)
        if len(sel) != 1 or self.state not in ("IDLE", "HANDLE"):
            return
        ob = sel[0]
        lo, hi = I.quick_bounds([ob])
        c = (lo + hi) / 2.0
        rg, rv = self.region, self.rv3d
        view = rv.view_rotation @ Vector((0.0, 0.0, -1.0))      # the way we are looking
        sx = -1.0 if view.x > 0 else 1.0
        sy = -1.0 if view.y > 0 else 1.0
        px = hi.x if sx > 0 else lo.x
        py = hi.y if sy > 0 else lo.y
        s = I.ui_scale()

        def p2(v):
            return I.to_2d(rg, rv, v)
        pts = {
            "x": Vector((px, c.y, lo.z)), "y": Vector((c.x, py, lo.z)), "z": Vector((c.x, c.y, hi.z)),
        }
        top = [Vector((x, y, hi.z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y)]
        bot = [Vector((x, y, lo.z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y)]
        t2 = [(p2(v), v) for v in top]
        b2 = [(p2(v), v) for v in bot]
        if any(q[0] is None for q in t2 + b2):
            return
        pts["size"] = max(t2, key=lambda q: q[0].x)[1]
        pts["tip"] = min(t2, key=lambda q: q[0].x)[1]
        pts["turn"] = min(b2, key=lambda q: q[0].x)[1]
        c2 = p2(c)
        for k, w in pts.items():
            q = p2(w)
            if q is None or c2 is None:
                continue
            d = q - c2
            if d.length > 1e-3:                    # sit a little outside the shape
                q = q + d.normalized() * 14 * s
            self.handles[k] = {"world": w, "p": q, "sx": sx, "sy": sy}
        self.handles["_"] = {"ob": ob.name, "lo": lo, "hi": hi}

    def handle_at(self, x, y):
        s = I.ui_scale()
        best, bd = None, 15 * s
        for k, h in self.handles.items():
            if k == "_":
                continue
            d = (h["p"] - Vector((x, y))).length
            if d < bd:
                best, bd = k, d
        return best

    # ---- finding the surface under the mouse ---------------------------------
    def surface_under(self, context, ignore):
        origin, direction = self.ray(context)
        try:
            dg = context.evaluated_depsgraph_get()
            o = origin.copy()
            for _i in range(24):
                ok, loc, nor, _idx, obj, _m = context.scene.ray_cast(dg, o, direction)
                if not ok or obj is None:
                    break
                obj = getattr(obj, "original", obj) or obj
                if obj.name in ignore or obj.type != "MESH":
                    o = loc + direction * 1e-3
                    continue
                return loc.copy(), nor.normalized(), obj
        except Exception:
            pass
        if abs(direction.z) > 1e-6:
            p = intersect_line_plane(origin, origin + direction, Vector((0, 0, 0)), Vector((0, 0, 1)))
            if p is not None and (p - origin).dot(direction) > 0:
                return p, Vector((0.0, 0.0, 1.0)), None
        return None

    def rest_on(self, half, surf):
        """Centre for a box of half-size `half` resting on the surface point."""
        p, n, obj = surf
        support = abs(n.x) * half.x + abs(n.y) * half.y + abs(n.z) * half.z
        if obj is None:
            return p + n * support                  # flat on the bed
        spread = abs(n.x) + abs(n.y) + abs(n.z)
        # on another shape: sink in slightly so that Glue has something to join
        return p + n * (support * (0.5 + 0.5 / spread) - min(0.6, support * 0.2))

    # ---- moving a group -------------------------------------------------------
    def begin_move(self, context, objs, carry=False):
        for o in objs:
            B.unparent(o)
        lo, hi = I.quick_bounds(objs)
        self.drag = {"names": [o.name for o in objs], "c0": (lo + hi) / 2.0, "half": (hi - lo) / 2.0,
                     "locs": {o.name: o.location.copy() for o in objs},
                     "start": (self.mx, self.my), "moving": carry, "carry": carry}
        self.state = "CARRY" if carry else "MOVE"

    def update_move(self, context):
        d = self.drag
        if not d["moving"]:
            if math.hypot(self.mx - d["start"][0], self.my - d["start"][1]) < 5:
                return
            d["moving"] = True
        surf = self.surface_under(context, set(d["names"]))
        if surf is None:
            return
        delta = self.rest_on(d["half"], surf) - d["c0"]
        for name, loc in d["locs"].items():
            ob = bpy.data.objects.get(name)
            if ob is not None:
                ob.location = loc + delta
        on = surf[2]
        self.label = ("on top of %s" % on.name) if on is not None else "on the floor"

    def end_move(self, context, keep=True):
        d = self.drag
        self.drag = None
        self.state = "IDLE"
        if d is None:
            return
        objs = [bpy.data.objects.get(n) for n in d["names"]]
        objs = [o for o in objs if o is not None]
        if not keep:
            if d["carry"]:
                for o in objs:
                    B._remove(o)
            else:
                for o in objs:
                    o.location = d["locs"][o.name]
        elif d["moving"]:
            B.refresh(context)
            self.commit(context, "add shape" if d["carry"] else "move")
        self.label = ""
        self.idle_hint(context)

    # ---- pulling a dot -----------------------------------------------------------
    def begin_handle(self, context, kind):
        info = self.handles["_"]
        ob = bpy.data.objects.get(info["ob"])
        if ob is None:
            return
        B.bake(ob)
        lo, hi = B.obj_bounds(ob)
        h = self.handles[kind]
        self.drag = {"kind": kind, "name": ob.name, "lo": lo, "hi": hi, "c": (lo + hi) / 2.0,
                     "loc": ob.location.copy(), "start": Vector((self.mx, self.my)),
                     "world": h["world"].copy(), "sx": h["sx"], "sy": h["sy"], "changed": False}
        c2 = I.to_2d(self.region, self.rv3d, Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)))
        self.drag["c2d"] = c2 or Vector((self.mx, self.my))
        self.drag["dist0"] = max((self.drag["start"] - self.drag["c2d"]).length, 25.0)
        if kind == "tip":
            right = self.rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
            self.drag["axis"] = "X" if abs(right.x) >= abs(right.y) else "Y"
            self.drag["sign"] = 1.0 if (right.x if self.drag["axis"] == "X" else right.y) >= 0 else -1.0
        self.state = "HANDLE"

    def _scaled(self, ob, fv, anchor):
        d = self.drag
        ob.scale = fv
        c = Vector([anchor[k] + (d["c"][k] - anchor[k]) * fv[k] for k in range(3)])
        ob.location = c                          # baked: the origin is the centre

    def update_handle(self, context, event):
        d = self.drag
        ob = bpy.data.objects.get(d["name"])
        if ob is None:
            return
        lo, hi, c = d["lo"], d["hi"], d["c"]
        size = hi - lo
        kind = d["kind"]
        m = Vector((self.mx, self.my))
        if kind == "size":
            f = max(min((m - d["c2d"]).length / d["dist0"], 20.0), 0.05)
            self._scaled(ob, Vector((f, f, f)), Vector((c.x, c.y, lo.z)))
            self.label = "%s x %s x %s mm" % (I.fmt(size.x * f), I.fmt(size.y * f), I.fmt(size.z * f))
        elif kind in ("x", "y", "z"):
            k = "xyz".index(kind)
            sgn = 1.0 if kind == "z" else (d["sx"] if kind == "x" else d["sy"])
            axis = Vector((0.0, 0.0, 0.0))
            axis[k] = sgn
            origin, direction = self.ray(context)
            pts = intersect_line_line(d["world"], d["world"] + axis, origin, origin + direction)
            if pts is None:
                return
            t = (pts[0] - d["world"]).dot(axis)
            new = max(size[k] + t, 1.0)
            if not event.shift:
                new = max(round(new), 1.0)
            fv = Vector((1.0, 1.0, 1.0))
            fv[k] = new / size[k] if size[k] > 0 else 1.0
            anchor = c.copy()
            anchor[k] = lo[k] if sgn > 0 else hi[k]
            self._scaled(ob, fv, anchor)
            self.label = "%s mm" % I.fmt(new)
        elif kind == "turn":
            origin, direction = self.ray(context)
            p = intersect_line_plane(origin, origin + direction, Vector((0, 0, d["world"].z)), Vector((0, 0, 1)))
            if p is None:
                return
            a0 = math.atan2(d["world"].y - c.y, d["world"].x - c.x)
            a1 = math.atan2(p.y - c.y, p.x - c.x)
            ang = math.degrees(a1 - a0)
            ang = (ang + 180.0) % 360.0 - 180.0
            if not event.shift:
                ang = round(ang / 15.0) * 15.0
            d["angle"] = ang
            ob.matrix_basis = Matrix.Translation(d["loc"]) @ Matrix.Rotation(math.radians(ang), 4, "Z")
            self.label = "turned %g" % ang
        elif kind == "tip":
            ang = (self.my - d["start"].y) * 0.6 * d["sign"]
            if not event.shift:
                ang = round(ang / 15.0) * 15.0
            d["angle"] = ang
            ob.matrix_basis = Matrix.Translation(d["loc"]) @ Matrix.Rotation(math.radians(-ang), 4, d["axis"])
            self.label = "tipped %g" % abs(ang)
        d["changed"] = True

    def end_handle(self, context, keep=True):
        d = self.drag
        self.drag = None
        self.state = "IDLE"
        if d is None:
            return
        ob = bpy.data.objects.get(d["name"])
        if ob is not None:
            if not keep:
                ob.matrix_basis = Matrix.Translation(d["loc"])
            elif d["changed"]:
                B.bake(ob)
                if d["kind"] == "tip":                 # keep it standing where it stood
                    lo, _hi = B.obj_bounds(ob)
                    ob.location = ob.location + Vector((0.0, 0.0, d["lo"].z - lo.z))
                B.refresh(context)
                self.commit(context, "change shape")
        self.label = ""
        self.idle_hint(context)

    # ---- buttons -----------------------------------------------------------------
    def act(self, context, key):
        group, _sep, name = key.partition(":")
        sel = self.selection(context)
        if group == "add":
            self.tray = False
            if name in SHAPE_SIZE:
                ob = new_shape(context, name)
                surf = self.surface_under(context, {ob.name})
                ob.location = Vector((0.0, 0.0, SHAPE_SIZE[name][2] / 2.0))
                B.refresh(context)
                B.select_only(context, [ob])
                self.begin_move(context, [ob], carry=True)
                self.say("move the mouse, then click to put the %s down" % SHAPE_NAME[name].lower(),
                         "it sits on whatever is under the mouse   |   Esc = never mind")
                if surf is not None:
                    self.update_move(context)
            elif name == "draw":
                self.state = "DRAW_WAIT"
                self.say("draw your shape on the floor: hold the mouse button and go all the way round",
                         "let go to make it solid   |   Esc = never mind")
            elif name == "words":
                try:
                    bpy.ops.simplemesh.easy_words("INVOKE_DEFAULT")
                except Exception:
                    pass
            elif name == "clay":
                if not sel:
                    x = free_spot(context, 40.0)
                    ob = new_shape(context, "ball", (40.0, 40.0, 40.0), name="Clay")
                    ob.location = Vector((x, 0.0, 20.0))
                    B.refresh(context)
                    B.select_only(context, [ob])
                    B.frame_model(context)
                else:
                    B.select_only(context, [sel[0]])
                try:
                    bpy.ops.simplemesh.clay_start()
                except Exception as ex:  # noqa: BLE001
                    self.report({"WARNING"}, "Could not start Clay: %s" % ex)
            elif name == "ideas":
                self.tray = not self.tray
            elif name == "open":
                try:
                    bpy.ops.simplemesh.import_stl("INVOKE_DEFAULT")
                except Exception:
                    pass
            return
        if group == "idea":
            self.tray = False
            try:
                bpy.ops.simplemesh.easy_idea(key=name)
                self.commit(context, "idea")
            except Exception as ex:  # noqa: BLE001
                self.report({"WARNING"}, str(ex))
            self.idle_hint(context)
            return
        if group == "col":
            c = PALETTE[int(name)]
            for o in sel:
                if not B.is_hole(o):
                    o.color = (c[0], c[1], c[2], 1.0)
            if sel:
                self.commit(context, "colour")
            else:
                self.report({"INFO"}, "Click a shape first, then a colour")
            return
        if group == "view":
            step = math.radians(30.0)
            if name in ("left", "right"):
                B.view_op(context, "view_orbit", type="ORBITLEFT" if name == "left" else "ORBITRIGHT", angle=step)
            elif name in ("up", "down"):
                B.view_op(context, "view_orbit", type="ORBITUP" if name == "up" else "ORBITDOWN", angle=step)
            elif name in ("plus", "minus"):
                B.view_op(context, "zoom", delta=1 if name == "plus" else -1)
            else:
                B.frame_model(context, everything=True)
            return
        try:
            if name == "undo":
                self.cache.clear()
                bpy.ops.ed.undo()
            elif name == "redo":
                self.cache.clear()
                bpy.ops.ed.redo()
            elif name == "print":
                bpy.ops.simplemesh.easy_print("INVOKE_DEFAULT")
            elif name == "save":
                if bpy.data.filepath:
                    bpy.ops.wm.save_mainfile()
                    self.report({"INFO"}, "Saved!")
                else:
                    bpy.ops.wm.save_mainfile("INVOKE_DEFAULT")
            elif name == "glue":
                bpy.ops.simplemesh.easy_glue()
                self.commit(context, "glue")
            elif not sel:
                self.report({"INFO"}, "Click a shape first")
            elif name == "copy":
                bpy.ops.simplemesh.duplicate()
                self.commit(context, "copy")
            elif name == "bin":
                bpy.ops.simplemesh.delete()
                self.commit(context, "bin")
            elif name == "hole":
                bpy.ops.simplemesh.mark_hole()
                self.commit(context, "hole")
        except Exception as ex:  # noqa: BLE001
            self.report({"WARNING"}, str(ex))
        self.idle_hint(context)

    # ---- drawing a shape ---------------------------------------------------------
    def stroke_add(self, context):
        origin, direction = self.ray(context)
        if abs(direction.z) < 1e-6:
            return
        p = intersect_line_plane(origin, origin + direction, Vector((0, 0, 0)), Vector((0, 0, 1)))
        if p is None:
            return
        self.stroke.append((p.x, p.y))
        self.stroke2d.append((self.mx, self.my))

    def stroke_finish(self, context):
        pts, self.stroke, self.stroke2d = self.stroke, [], []
        self.state = "IDLE"
        outline = clean_outline(pts)
        if outline is None:
            self.report({"INFO"}, "That was too small. Press Draw and go round in a bigger loop")
        else:
            ob = solid_from_outline(context, outline)
            B.refresh(context)
            B.select_only(context, [ob])
            self.commit(context, "draw shape")
        self.idle_hint(context)

    def never_mind(self, context):
        if self.state in ("MOVE", "CARRY"):
            self.end_move(context, keep=False)
        elif self.state == "HANDLE":
            self.end_handle(context, keep=False)
        self.stroke, self.stroke2d = [], []
        self.state = "IDLE"
        self.tray = False
        self.label = ""
        self.idle_hint(context)

    # ---- events ------------------------------------------------------------------
    def modal(self, context, event):
        if I.ACTIVE["token"] is not self.token:
            self.finish(context)
            return {"FINISHED", "PASS_THROUGH"}
        area = self._area(context)
        if area is None:
            self.finish(context)
            return {"FINISHED", "PASS_THROUGH"}
        B.note_input(event)
        if context.mode != "OBJECT":                 # asleep while Clay (or another mode) is on
            return {"PASS_THROUGH"}
        B.note_event(event)
        self.region = next((r for r in area.regions if r.type == "WINDOW"), None)
        self.rv3d = getattr(area.spaces.active, "region_3d", None)
        et, ev = event.type, event.value
        if self.region is None or self.rv3d is None or et.startswith("TIMER"):
            return {"PASS_THROUGH"}
        area.tag_redraw()
        self.place_buttons(context)
        busy = self.state in ("MOVE", "HANDLE", "DRAW")
        mx, my = event.mouse_x - self.region.x, event.mouse_y - self.region.y
        inside = 0 <= mx < self.region.width and 0 <= my < self.region.height
        if inside:
            for r in area.regions:
                if r.type != "WINDOW" and r.width > 1 and r.height > 1 and \
                        r.x <= event.mouse_x < r.x + r.width and r.y <= event.mouse_y < r.y + r.height:
                    inside = False
                    break
        if inside and not busy and I.over_deck(area, self.region, mx, my):
            inside = False                           # the big-button panel handles its own clicks
        if not inside and not busy:
            self.mx = self.my = -1
            self.hover = None
            if self.state == "IDLE":
                self.label = ""
            return {"PASS_THROUGH"}
        self.mx, self.my = mx, my
        if self.state == "IDLE" and self.tile_at(mx, my) is None and self.in_gizmo_corner(context, mx, my):
            self.hover = None
            self.label = ""
            return {"PASS_THROUGH"}                  # Blender's own view ball and hand
        if not busy:
            if et in I.NAV_EVENTS or et in I.NUMPAD_NAV or et.startswith("NDOF") or (event.alt and et == "LEFTMOUSE"):
                return {"PASS_THROUGH"}
            if et == "Z" and (event.ctrl or event.oskey):
                self.cache.clear()
                return {"PASS_THROUGH"}
        if et in ("MOUSEMOVE", "INBETWEEN_MOUSEMOVE"):
            self.on_move(context, event)
            return {"RUNNING_MODAL"}
        if et == "LEFTMOUSE":
            if ev in ("PRESS", "DOUBLE_CLICK"):      # Blender reports a quick second click as DOUBLE_CLICK
                self.on_move(context, event)
                self.on_press(context, event)
            elif ev == "RELEASE":
                self.on_release(context, event)
            return {"RUNNING_MODAL"}
        if et == "RIGHTMOUSE":
            if ev in ("PRESS", "DOUBLE_CLICK"):
                if self.state != "IDLE":
                    self.never_mind(context)
                else:
                    try:
                        bpy.ops.view3d.rotate("INVOKE_DEFAULT")     # look around
                    except Exception:
                        pass
            return {"RUNNING_MODAL"}
        if ev == "PRESS":
            if et == "ESC":
                self.never_mind(context)
                return {"RUNNING_MODAL"}
            if self.state == "IDLE":
                if et in ("DEL", "BACK_SPACE", "X"):
                    self.act(context, "do:bin")
                    return {"RUNNING_MODAL"}
                if et == "D" and (event.ctrl or event.shift):
                    self.act(context, "do:copy")
                    return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def on_move(self, context, event):
        st = self.state
        if st in ("MOVE", "CARRY"):
            self.update_move(context)
            return
        if st == "HANDLE":
            self.update_handle(context, event)
            return
        if st == "DRAW":
            self.stroke_add(context)
            return
        t = self.tile_at(self.mx, self.my)
        self.hover = t
        if t is not None:
            _g, _s, name = t.partition(":")
            if t.startswith("col:"):
                self.label = "colour in the chosen shape"
            elif t.startswith("idea:"):
                self.label = "start from a %s" % IDEAS[name][0].lower()
            else:
                self.label = TIPS.get(name, "")
            return
        if st == "DRAW_WAIT":
            self.label = "hold the button and draw"
            return
        self.compute_handles(context)
        h = self.handle_at(self.mx, self.my)
        if h is not None:
            self.hover = "handle:" + h
            self.label = HANDLE_TIP[h]
            return
        hit = self.hit(context)
        self.label = ("drag to move %s" % hit["obj"].name) if hit else ""

    def on_press(self, context, event):
        st = self.state
        if st == "CARRY":
            if self.tile_at(self.mx, self.my) is None:
                self.end_move(context, keep=True)
            return
        t = self.tile_at(self.mx, self.my)
        if t is not None:
            if st == "DRAW_WAIT":
                self.state = "IDLE"
            self.act(context, t)
            return
        if st == "DRAW_WAIT":
            self.state = "DRAW"
            self.stroke, self.stroke2d = [], []
            self.stroke_add(context)
            return
        self.tray = False
        self.compute_handles(context)
        h = self.handle_at(self.mx, self.my)
        if h is not None:
            self.begin_handle(context, h)
            return
        hit = self.hit(context)
        if hit is None:
            B.select_only(context, [])
            self.idle_hint(context)
            return
        ob = hit["obj"]
        sel = self.selection(context)
        if event.shift:
            ob.select_set(not ob.select_get())
            if ob.select_get():
                context.view_layer.objects.active = ob
            self.idle_hint(context)
            return
        if ob not in sel:
            B.select_only(context, [ob])
            sel = [ob]
        else:
            context.view_layer.objects.active = ob
        self.begin_move(context, sel)
        self.idle_hint(context)

    def on_release(self, context, event):
        st = self.state
        if st == "MOVE":
            self.end_move(context, keep=True)
        elif st == "HANDLE":
            self.end_handle(context, keep=True)
        elif st == "DRAW":
            self.stroke_finish(context)

    # ---- drawing -----------------------------------------------------------------
    def _safe3d(self):
        pass

    def _safe2d(self):
        try:
            if I.ACTIVE["token"] is not self.token:
                return
            ctx = bpy.context
            if ctx.area is None or ctx.area.as_pointer() != self.area_ptr or ctx.mode != "OBJECT":
                return
            if self.region is None or self.rv3d is None:
                return
            self.draw_all(ctx)
        except Exception:
            B.note_error("drawing the Easy mode pictures")

    def draw_tile(self, key, label, pic, base, s):
        x, y, w, h = self.rects[key]
        hot = self.hover == key
        col = tuple(min(1.0, c + (0.14 if hot else 0.0)) for c in base) + (0.94,)
        _rect(x - 1.5 * s, y - 1.5 * s, w + 3 * s, h + 3 * s, (0.0, 0.0, 0.0, 0.55))
        _rect(x, y, w, h, col)
        if label:
            icon(pic, x + w / 2.0, y + h * 0.60, min(w, h) * 0.26, s)
            I.text(x + w / 2.0, y + 5 * s, label, 11, W, centre=True, box=False)
        else:
            icon(pic, x + w / 2.0, y + h / 2.0, min(w, h) * 0.32, s)

    def draw_all(self, context):
        s = I.ui_scale()
        self.place_buttons(context)
        teal, purple, slate = (0.05, 0.42, 0.52), (0.42, 0.27, 0.66), (0.20, 0.24, 0.30)
        for key, label in ADD_TILES:
            base = teal if key in SHAPE_SIZE else purple
            if key == "draw" and self.state in ("DRAW_WAIT", "DRAW"):
                base = (0.85, 0.45, 0.0)
            self.draw_tile("add:" + key, label, key, base, s)
        for key in IDEA_ORDER:
            if "idea:" + key in self.rects:
                x, y, w, h = self.rects["idea:" + key]
                hot = self.hover == "idea:" + key
                _rect(x - 1.5 * s, y - 1.5 * s, w + 3 * s, h + 3 * s, (0.0, 0.0, 0.0, 0.55))
                _rect(x, y, w, h, (0.95, 0.70, 0.10, 0.96) if hot else (0.85, 0.58, 0.05, 0.94))
                I.text(x + w / 2.0, y + h / 2.0 - 6 * s, IDEAS[key][0], 14, W, centre=True, box=False)
        for key, label in DO_TILES:
            self.draw_tile("do:" + key, label, key, (0.55, 0.16, 0.14) if key == "bin" else slate, s)
        self.draw_tile("do:print", "Print!", "print", (0.10, 0.55, 0.25), s)
        for i, c in enumerate(PALETTE):
            x, y, w, h = self.rects["col:%d" % i]
            m = 2.5 * s if self.hover == "col:%d" % i else 1.5 * s
            _rect(x - m, y - m, w + 2 * m, h + 2 * m, (0.0, 0.0, 0.0, 0.7))
            _rect(x, y, w, h, c + (1.0,))
        for key, _l in VIEW_TILES:
            self.draw_tile("view:" + key, "", key, slate, s)

        if self.state in ("DRAW", "DRAW_WAIT") and len(self.stroke2d) > 1:
            _line(self.stroke2d, (1.0, 0.72, 0.1, 1.0), 4.0)
        if self.state in ("IDLE", "HANDLE"):
            if self.state == "IDLE":
                self.compute_handles(context)
            for k, h in self.handles.items():
                if k == "_":
                    continue
                p = h["p"]
                hot = self.hover == "handle:" + k or (self.state == "HANDLE" and self.drag and self.drag.get("kind") == k)
                r = (11 if hot else 9) * s
                _circle(p.x, p.y, r + 2 * s, (0.0, 0.0, 0.0, 0.85))
                _circle(p.x, p.y, r, HANDLE_COL[k] + (1.0,))
                _circle(p.x, p.y, r * 0.4, (0.0, 0.0, 0.0, 0.75))
        if self.state == "IDLE" and not any(o.type == "MESH" for o in context.view_layer.objects):
            cx = self.region.width / 2.0
            cy = self.region.height * 0.62
            I.text(cx, cy, "Click a picture on the left to start", 22, W, centre=True)
            I.text(cx, cy - 40 * s, "...or press Ideas for a snowman, a rocket, a robot", 15, W2, centre=True)
        if self.mx >= 0 and self.label:
            I.text(self.mx + 22 * s, self.my - 26 * s, self.label, 15, I.AMBER)


def start_easy(context=None):
    """Switch Easy mode on in the first 3D view of the open window (used at start-up
    and after another tool finishes)."""
    ctx = context or bpy.context
    try:
        if ctx.mode != "OBJECT" or I.ACTIVE["token"] is not None:
            return False
        for w in ctx.window_manager.windows:
            for a in w.screen.areas:
                if a.type != "VIEW_3D":
                    continue
                r = next((q for q in a.regions if q.type == "WINDOW"), None)
                if r is None:
                    continue
                if hasattr(ctx, "temp_override"):
                    with ctx.temp_override(window=w, area=a, region=r):
                        bpy.ops.simplemesh.tool_easy("INVOKE_DEFAULT")
                else:
                    bpy.ops.simplemesh.tool_easy({"window": w, "screen": w.screen, "area": a, "region": r},
                                                 "INVOKE_DEFAULT")
                return True
    except Exception:
        pass
    return False


def _restart_timer():
    try:
        sm = bpy.context.scene.simplemesh
        if sm.easy_on and I.ACTIVE["token"] is None and bpy.context.mode == "OBJECT":
            start_easy(bpy.context)
    except Exception:
        pass
    return None


def restart_soon():
    try:
        if not bpy.app.background and not bpy.app.timers.is_registered(_restart_timer):
            bpy.app.timers.register(_restart_timer, first_interval=0.15)
    except Exception:
        pass


CLASSES = (SIMPLEMESH_OT_easy_words, SIMPLEMESH_OT_easy_glue, SIMPLEMESH_OT_easy_idea,
           SIMPLEMESH_OT_easy_print, SIMPLEMESH_OT_tool_easy)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    CURRENT["tool"] = None
    try:
        if bpy.app.timers.is_registered(_restart_timer):
            bpy.app.timers.unregister(_restart_timer)
    except Exception:
        pass
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)

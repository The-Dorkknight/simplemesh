# Why the tools work the way they do

Version 0.1 put every tool in a sidebar tab as buttons and number boxes. In use that was awkward:
you had to find the tab, select things in the right order, enter Edit Mode to pick a face, and guess
a percentage for a cut without seeing where it would land. Version 0.2 was redesigned after looking
at what already exists.

## What already exists (looked at 2026-10-03)

**Blender add-ons for 3D printing.** None of them is a whole "simple STL workbench"; each covers one job.

| Add-on | What it does | How you use it | What we took from it |
|---|---|---|---|
| [Lay Flat](https://extensions.blender.org/add-ons/object-lay-flat/) | Puts a chosen face on the ground | Edit Mode, select a face, then a sidebar button | The job is right, the route is the awkward one 0.1 copied. We do it with hover and one click instead. |
| [3D Print Toolbox](https://extensions.blender.org/add-ons/print3d-toolbox/) | Volume/area, problem checks, make manifold, hollow, scale to bounds, align to bed, export | Sidebar panels | The check list (holes, inside-out faces, volume). |
| [Easy-Print](https://extensions.blender.org/add-ons/easy-print/) | Split a model and add connectors | **Draw a line across the model**, hover the part to keep | Drawing a line to cut. |
| [EasySlice Print](https://github.com/Onvistlex/easySlicePrint) | Plane / curve / freehand cuts with pins and sockets | Drag a line in the view; plan first, build later | Drag-a-line cutting; coloured preview before anything changes. |
| [PrintSplit](https://github.com/Max-Pare/printsplit) | Draw a line to split, rigid and articulated joints | Straight or freehand stroke, tweak afterwards | Same: the stroke is the tool. |
| [SnapSplit](https://github.com/Betakontext/snapsplit) | Split with snap-fit connectors, material tolerances | Sidebar offset with a permanent plane preview | A visible plane before cutting. |

All of these are GPL and need Blender 4.2 or newer; SimpleMesh shares none of their code. If you need
**connectors** (pins, dovetails, snap fits) use one of the four splitters above next to SimpleMesh: it does
not make connectors.

**Programs people find easy** (the real inspiration):

- **PrusaSlicer "Place on face"**: flat faces are highlighted, you click one, the model rotates so it is on the bed
  ([Prusa help](https://help.prusa3d.com/article/place-on-face-tool_1781)). → our **Lay flat**.
- **Bambu Studio / PrusaSlicer cut tool**: a visible plane you move, a millimetre box for exact height, choose which part to keep,
  "place on cut", and Shift-drag to draw a cut line ([Bambu wiki](https://wiki.bambulab.com/en/software/bambu-studio/cut-tool)). → our **Cut**.
- **Tinkercad** (as far as we know it; not re-checked in detail): sizes shown on the model, any shape can be turned into a "hole"
  and holes are cut out of whatever they touch, a key drops a shape onto the workplane. → the always-on size
  read-out, **Shapes ▸ Make it a hole / Cut the holes out**, and *D = drop to bed*.

## Moulding like clay (added in 0.3, looked at 2026-10-03)

"Pull the surface, stretch it, push it in" covers two different jobs, and the programs that do them well are different too.

**Moving a flat face of a mechanical part.** SketchUp's Push/Pull is the reference: click a face, move the mouse, the face
follows along its own direction, and you can type the exact distance
([SketchUp help](https://help.sketchup.com/en/sketchup/pushing-and-pulling-shapes-3d)); Fusion's Press Pull is the same idea.
→ our **Pull** tool: the face lights up on hover, drag it, or type millimetres.

**Free-form moulding.** Sculpting programs all share a small core of brushes: move/grab, clay/draw, inflate, smooth, flatten
([brush overview](https://www.mixos.io/learn/sculpting-brushes-explained)). Blender already has these, and its *Snake Hook*
"pulls vertices along with the movement of the brush to create long, snake-like forms"
([Blender manual](https://docs.blender.org/manual/en/4.0/sculpt_paint/sculpting/tools/snake_hook.html)), which is exactly
"pull the clay". Its *Dynamic Topology* "will subdivide the mesh during the stroke"
([Blender manual](https://docs.blender.org/manual/en/4.0/sculpt_paint/sculpting/tool_settings/dyntopo.html)), which is what an
STL needs because its flat faces are two big triangles with nothing to mould.

So there was no point writing a new sculpting engine. What makes Blender's hard to use for STL work is the set-up, and
**Clay mode is that set-up done for you**:

| Stock Blender sculpting | Clay mode |
|---|---|
| About thirty brushes in a toolbar | Seven, named for what they do: Pull, Build up, Push in, Shift, Inflate, Smooth, Flatten |
| Brush size in screen pixels (changes with zoom) | Size in millimetres |
| Nothing happens on a flat STL face until you find and enable Dyntopo and choose a detail size | Small triangles are added to the whole model first (shape unchanged), Dyntopo is on with a detail size chosen from the model's size |
| Dragging brushes let go of the clay at default settings | Pull and Shift run at full strength and carry all sides along |
| Mirror symmetry may be on | Off |
| The file stays huge afterwards | Done merges the untouched flat areas back into big triangles (kept only if the model is still watertight) |

Things we found by running it in a real window: with "front faces only" on, Snake Hook drops the clay after a few millimetres
(the sides of the lump face away from you), and on an un-subdivided flat face the first stroke has nothing to grab. Both are
handled in the set-up above.

## Easy mode: for a ten-year-old (added in 0.4, looked at 2026-10-03)

What goes wrong for children on a blank CAD screen is well described: too many buttons ("forty-seven buttons on the left
panel"), camera control ("spinning an object smoothly in 3D space takes coordination that many kids under ten are still
building"), vocabulary ("extrusion", "Boolean union") and no visible goal
([guided tools vs blank CAD screen](https://www.aoseed.com/blogs/aoseed-sale/3d-modeling-for-kids-beginners)). What works:
dragging pre-made shapes, building by combining them, a drawing tool, and the design-print-hold loop
([Tinkercad for kids](https://www.selfcad.com/blog/tinkercad-for-kids)). Programs made for primary schools add scaffolding and
pictures over text ([Makers Empire](https://www.makersempire.com/7-ways-makers-empire-is-different-from-other-3d-design-programs-for-primary-elementary-students/)).

| Problem | What Easy mode does |
|---|---|
| Too many buttons | Fourteen picture buttons to add things, seven to act on them, colours, one Print! button. The strip shrinks to the handful of extra tools. |
| Blank screen, no goal | The empty bed says what to do first; **Ideas** drops in a snowman, house, rocket, robot or car to take apart and change. |
| CAD words | Block, Ball, Tube, Glue, Hole, Bin, "bigger", "taller", "spin", "tip over". No millimetres need typing. |
| Positioning in 3D | A shape rests on whatever is under the mouse, so stacking needs no height control. |
| Mode switching (move / rotate / scale) | Six coloured dots on the chosen shape, as on Tinkercad's handles. |
| Orbiting the camera | Arrow buttons turn the view in steps; right-drag also works. |
| Fear of breaking it | Undo is a big button; Esc and right-click cancel; there is no way out of Easy mode by accident. |
| "Is it printable?" | Print! cuts holes, glues touching parts, repairs, sits it on the bed and checks the size before saving. |
| Drawing your own shape | Draw: a mouse loop on the floor becomes a solid; crossed or scribbled lines are untangled instead of refused. |

What we could not check: all of this was run by a script, not by a child. The first real session will show which words
and which dots are wrong.

## The rules that came out of it

1. **Work on the model, not in a panel.** Tools are a strip along the top of the 3D view; you pick one and then act in the view.
2. **Hover shows what a click will do.** The face lights up, the plane or circle follows the mouse, a label gives the millimetres. Nothing changes until you click.
3. **No Edit Mode, no selection order.** A tool acts on whatever model is under the mouse. Holes are a property of a shape, not "select the cutter then the base".
4. **Millimetres always visible.** The selected model's X × Y × Z and whether it fits the bed are written in the view all the time.
5. **Type a number when you need to be exact.** In Size, Turn, Cut and Hole you can just type and press Enter.
6. **Navigation never stops.** Orbit, pan, zoom and **F** (find my model) work while a tool is on. Esc or right-click leaves the tool.
7. **Undo is one step per action.** Ctrl+Z.

## What the strip replaces

| Stock Blender | SimpleMesh |
|---|---|
| G / R / S with view-plane movement, or three overlapping gizmos | **Move** (slides on the bed), **Turn** (15° steps, model re-seated on the bed), **Size** (stays on the bed, scale baked to 1.0) |
| Edit Mode ▸ select face ▸ align script/add-on | **Lay flat**: hover, click |
| Bisect in Edit Mode, fill, separate | **Cut**: click or drag a line; pieces are capped and laid out |
| Add cylinder, position, Boolean modifier, apply, delete cutter | **Hole**: click on the surface |
| MeasureIt / ruler tool | **Measure**: two clicks |
| Edit Mode ▸ select faces ▸ move along normal | **Pull**: drag the face, or type mm |
| Sculpt Mode ▸ enable Dyntopo ▸ pick brush ▸ set radius | **Clay**: one button, seven brushes, size in mm |

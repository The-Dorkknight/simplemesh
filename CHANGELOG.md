# Changelog

## 0.5.0-wip (2026-10-04)
- New **panel of big buttons** across the top of the 3D view, in every mode (the idea of SimpleCAD's deck): a big red button in caution tape that does the next obvious thing (MOULD LIKE CLAY / FINISH the tool / DONE / BACK TO THE MODELS / GET READY TO MOULD), a green badge saying what is active, FIND MODEL, the tools as keys with lights (the clay brushes, Brush +, Brush - and Mirror while moulding), and system keys Easy, Luminous, Hide clutter, More tools. With the panel on, Blender's header row keeps only the pop-ups with number fields. Switch it off in More tools and the tools return to the thin strip.
- New **look controls**: the Luminous key switches Luminous / Clean; **Hide clutter** hides Blender's own header rows and status bar; More tools ▸ Look adds **Rainbow** (a colour for each model) and **Show the triangles**. Imported models take the look's colour in Easy mode instead of plain white.
- Fixed a freeze: **"Finer everywhere" is removed.** Used after a few strokes it took an 82,000-triangle model to 530,000 triangles, Blender's memory from 0.8 to 4 GB, and Blender then stopped answering for minutes (measured here; the mouse pointer still moves, which is how it was reported). Automatic detail under the brush does that job.
- Clay limits that keep Blender answering: the triangle budget of the first "small triangles" step is now a real limit with a time limit (it could overshoot several times over); **Detail cannot be set finer than a thirtieth of the brush**, and making the brush bigger takes Detail with it; Detail starts at a sixtieth of the model (was a hundredth), so a few pulls make far fewer triangles; models above 700,000 triangles are moulded without automatic detail; the read-out shows the triangle count and warns when it passes 400,000.
- Fixed: **a quick second click was ignored** by every SimpleMesh tool and by Easy mode's picture buttons (Blender reports it as a "double click", not a press).
- Fixed: **Blender's timed recovery save never ran** while Easy mode (or now the panel) was on, because Blender skips it whenever an add-on tool is watching the mouse (measured: none in 150 s at a 1-minute setting). SimpleMesh now writes that copy itself, under Blender's own name and settings, when no drag is in progress. *File ▸ Recover ▸ Auto Save* finds it.
- The busy pointer is shown while Clay gets a model ready and while Done tidies up.
- A **log** of what SimpleMesh was doing (`simplemesh-log.txt` in Blender's settings folder, the session before as `.prev.txt`) is written line by line and included in *Report a problem*, so a freeze can be traced afterwards.
- Removed the untested line that hid Blender's brush shelf in Clay.
- Tests: the scripted window session grew from 90 to 114 checks (the panel driven by simulated clicks, the recovery copy); the windowless tests from 146 to 175.

## 0.4.3-wip (2026-10-03)
- Fixed: **Sculpt Mode chosen from Blender's own mode menu** (or Ctrl+Tab, or the Sculpting workspace) showed the Clay strip, with "Pull" lit, but none of the Clay set-up had been done: the STL still had its few big triangles, the brush was Blender's Draw brush sized in screen pixels, and dragging barely changed anything. SimpleMesh now notices that and runs the same set-up as the Clay button by itself (a "Get this model ready to mould" button is shown if it cannot).
- The strip now lights the brush Blender is **really** using, and the view says so when it is one of Blender's own brushes.
- Fixed: **Ctrl+Z after the first Clay stroke** left Clay altogether when Clay had been started from the Easy picture button. Strokes are now taken back one at a time; one more Ctrl+Z after the last one leaves Clay.
- Fixed: pressing Undo all the way back brought Blender's untouched start-up scene back (metres, the default cube). The millimetre scene now repairs itself.
- Imported STLs are shaded with **sharp corners and smooth curves** (30° rule). Before, a model with joined points was shaded fully smooth, so a bracket looked like a pillow. Only the shading changes, not the shape.
- Clay: the brush starts at a fifth of the model's size (was an eighth) and is no longer capped at 30 mm, nor Detail at 3 mm, on big models.
- In Blender's other modes (Edit Mode, Vertex Paint...) the view now says that the SimpleMesh tools are not there and how to get back.
- New **Report a problem** (View pop-up; a red button also appears in the strip when SimpleMesh has caught an error): copies the Blender version, graphics card, mode, Clay state, the names of the last mouse and key events and any caught errors to the clipboard and saves them as `simplemesh-report.txt` in the home folder. Nothing is sent anywhere; typed letters are recorded only as "KEY".
- Clay hides Blender's own brush shelf (Blender 4.1+). Not seen in a window yet.
- Tests: the real-window session grew from 79 to 90 checks (Clay undo and redo, Sculpt Mode entered Blender's own way); the windowless tests cover the same route, the shading and the report.

## 0.4.2-wip (2026-10-03)
- Fixed: running `install.py` showed no window (it was the terminal-only tool; the window was a separate file). `python3 install.py`, a double-click on it, and the launchers now all open the installer window.
- If Python has no window toolkit, the Blender chooser is shown with desktop dialog boxes (zenity on Linux) instead of failing silently; with no desktop it asks in the terminal with a numbered list; started by a double-click with nowhere to show anything, it opens a terminal or leaves `install_log.txt`.
- New `--cli` (terminal, asks which Blender) and `--all` (no questions).
- New test `tests/test_install_launch.py`: starts `install.py` as its own program and checks a window really appears.

## 0.4.1-wip (2026-10-03)
- New **installer window** (`install_gui.py`, with double-click launchers for Linux, Mac and Windows): lists every Blender found with its version and whether SimpleMesh is in it, tick the ones to use, add another by hand, choose Easy mode and start-up picture options, Install / Update / Remove / Open Blender, with a log.
- `install.py` gained `--list`, `--no-easy`, `--keep-splash`, `--version`; finds Steam and more download locations.
- Fixed: `install.py` could mistake a Python that has the `bpy` pip module for Blender itself.

## 0.4.0-wip (2026-10-03)
- New **Easy mode**, on by default: picture buttons drawn on the 3D view for building from shapes without CAD knowledge.
  - Nine shapes plus Draw (a mouse loop becomes a solid), Words (3D letters), Clay, Ideas (snowman, house, rocket, robot, car) and Open.
  - A new shape follows the mouse and rests on whatever is under it (the floor or another shape).
  - Six dots on the chosen shape: bigger, longer, wider, taller, spin, tip over. Drag to move.
  - Undo, Redo, Copy, Bin, Hole, Glue, Save, eight colours, and **Print!** (cuts holes, glues, repairs, sits on the bed, checks size, saves).
  - Arrow buttons and right-drag to look around. A saved project reopens in Easy mode.
- The strip shrinks to the extra tools while Easy mode is on. The drill tool is now labelled **Drill** (it was "Hole").
- Clay has a **Mirror** switch.

## 0.3.0-wip (2026-10-03)
- New **Pull** tool: point at a flat face and drag it out or in (or type mm) to make a part longer, shorter, thicker.
- New **Clay** mode: Blender's sculpting set up for STL work with seven plainly named brushes (Pull, Build up, Push in, Shift, Inflate, Smooth, Flatten), brush size in millimetres, automatic detail, no mirror symmetry. Done merges untouched flat areas back into big triangles.
- Strip shows a "Back to the models" button if you end up in another Blender mode.
- Works with both brush systems (tools up to Blender 4.2, brush assets from 4.3); only 4.0.2 was stroke-tested in a window.

## 0.2.0-wip (2026-10-03)
Redesign after the 0.1 tools proved awkward in use (see docs/DESIGN.md).
- **Tool strip** along the top of the 3D view replaces the sidebar as the main interface.
- New click-in-the-view tools with live preview: **Lay flat** (hover + click, no Edit Mode), **Move**, **Turn**, **Size** (drag or type), **Cut** (click a plane or drag a line), **Hole**, **Measure**.
- Size of the selection and "fits the bed" always written in the view; size labels on the model.
- Hole shapes ("Make it a hole" / "Cut the holes out"), weld, separate loose pieces, copy, delete; no selection order.
- Start-up now leaves one big 3D view (timeline, outliner, properties closed) with a "Full Blender" tab as the way back.
- Framing sets the view directly, with room around the model and the bed in sight.
- Fixed: installer reported success but did not actually switch the add-on on.
- Fixed: add-on needed numpy, which some Linux distro Blender packages do not ship.
- Removed: Edit-Mode "pick a face" route, always-on move/rotate gizmos.
- Tested in a real Blender 4.0.2 window with simulated input (tests/gui_session.py).

## 0.1.0-wip (2026-10-03)
- First public work-in-progress release.
- Millimetre scene, auto-scaled STL import (units, auto-fit, set longest side), placed on the bed, centred, framed.
- Find-my-model (F) with automatic clip-range fitting.
- Size quick fixes, auto lay flat, pick-a-face lay flat, turn, mirror, drop/centre on bed.
- Cut with capped faces (split or keep one side), add shapes, subtract/union/intersect/join.
- Check, repair, simplify; export STL in mm.
- Tidy startup, Luminous/Clean looks, flipped-face overlay, bed outline, laptop navigation helper.
- One-step `install.py`; add-on zip and extension zip builder.

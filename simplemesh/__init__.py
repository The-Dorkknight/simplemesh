# SimpleMesh - a decluttered, print-minded STL workspace for Blender
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 3. No warranty; see LICENSE.
#
# WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN
#
# Goal: open a STL, see it at its real size in millimetres, centred and framed,
# and do the things people actually do to STL files (lay flat, move, turn, resize,
# pull faces, cut, drill, mould like clay, measure, repair, export) by clicking on the model itself, with no
# scenery, cameras, lights, materials or game-asset tooling in the way.
#
#   base.py         units, framing, mesh operations, button operators, settings
#   interactive.py  the click-in-the-view tools and the on-screen read-outs
#   easy.py         Easy mode: picture buttons, shapes that stack, dots to pull
#   clay.py         Clay mode (Blender's sculpting, set up in mm with seven brushes)
#   deck.py         the panel of big buttons across the top of the 3D view
#   ui.py           tool strip, pop-up panels, sidebar tab, start-up tidying

bl_info = {
    "name": "SimpleMesh",
    "author": "Matthew Armstrong",
    "version": (0, 5, 0),
    "blender": (3, 0, 0),
    "location": "3D Viewport: the strip of tools along the top",
    "description": "STL-first workspace: millimetres, auto-scaled import, click-on-the-model tools",
    "warning": "Work in progress",
    "doc_url": "https://github.com/The-Dorkknight/simplemesh",
    "tracker_url": "https://github.com/The-Dorkknight/simplemesh/issues",
    "category": "3D View",
}

if "bpy" in locals():            # Blender "Reload Scripts"
    import importlib
    for _m in (version, base, interactive, clay, easy, deck, ui):   # noqa: F821
        importlib.reload(_m)

import bpy  # noqa: E402

from . import version, base, interactive, clay, easy, deck, ui  # noqa: E402
from .version import __version__, __build_date__  # noqa: E402,F401
from .base import *  # noqa: E402,F401,F403  (helpers are re-exported for scripts and tests)
from .base import prefs, _DefaultPrefs  # noqa: E402,F401
from .ui import tidy_new_file  # noqa: E402,F401


def register():
    base.log_open()
    base.register()
    interactive.register()
    clay.register()
    easy.register()
    deck.register()
    ui.register()


def unregister():
    ui.unregister()
    deck.unregister()
    easy.unregister()
    clay.unregister()
    interactive.unregister()
    base.unregister()
    base.log_close()


if __name__ == "__main__":
    register()

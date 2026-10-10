# Contributing

Bug reports and ideas are welcome through the issue forms. By contributing code you agree it is released under the same licence as the project (GPL-3.0-only).

Before sending changes:

```bash
pip install -r requirements-dev.txt     # the bpy module (Blender as a Python module)
python tests/test_headless.py           # must print ALL PASSED
python tools/build_zip.py               # builds dist/*.zip
# real-window test (Linux: a Blender executable, Xvfb, ImageMagick):
xvfb-run -a -s "-screen 0 1600x900x24" blender --factory-startup --enable-event-simulate \
    --python tests/gui_session.py -- /tmp/shots      # must end with "GUI-DONE  0 failed"
# installer window (use a throw-away HOME: it really installs and removes):
HOME=$(mktemp -d) xvfb-run -a -s "-screen 0 1100x760x24" python3 tests/test_installer_gui.py
HOME=$(mktemp -d) xvfb-run -a -s "-screen 0 1100x760x24" python3 tests/test_install_launch.py
```

Keep the add-on dependency-free (numpy is optional), keep working on Blender 3.0+ where you can (no `match`, no `X | Y` annotations), wrap viewport settings with `_set()` so a renamed property can't break startup, and don't claim in the docs anything you haven't run.

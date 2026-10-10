# SimpleMesh installer window test (needs a display, tkinter and a Blender on PATH).
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
#
#   HOME=$(mktemp -d) xvfb-run -a -s "-screen 0 1100x760x24" python3 tests/test_installer_gui.py [SHOT_DIR]
#
# Use a throw-away HOME: the test really installs into and removes from that
# HOME's Blender settings. It presses the window's own buttons and clicks its rows.
import os
import subprocess
import sys
import time
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import install as core  # noqa: E402
import install_gui as gui  # noqa: E402

SHOTS = sys.argv[1] if len(sys.argv) > 1 else None
FAILS = []


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    sys.stdout.flush()
    if not ok:
        FAILS.append(msg)


def wait(root, app, cond, limit=240):
    t0 = time.time()
    while time.time() - t0 < limit:
        root.update()
        if not app.busy and cond():
            return True
        time.sleep(0.05)
    return False


def shot(root, name):
    if SHOTS:
        root.update()
        time.sleep(0.3)
        root.update()
        subprocess.run(["import", "-window", "root", os.path.join(SHOTS, name + ".png")])


def click_row(root, app, r):
    x, y, w, h = app.tree.bbox(r["iid"], "pick")
    app.tree.event_generate("<Button-1>", x=x + w // 2, y=y + h // 2)
    root.update()


def log_text(app):
    return app.log.get("1.0", "end")


def pref_easy(cmd):
    r = subprocess.run(cmd + ["-b", "--python-expr",
                              "import bpy;a=bpy.context.preferences;print('PREF|%d|%d' % (a.addons['simplemesh'].preferences.easy_start, a.view.show_splash))"],
                       capture_output=True, text=True)
    for ln in r.stdout.splitlines():
        if ln.startswith("PREF|"):
            return ln.split("|")[1:]
    return None


def main():
    home = os.path.expanduser("~")
    # a second "downloaded" Blender so the list has something to choose between
    wrap = os.path.join(home, "blender-9.9-wrapper")
    real = core.candidates()
    check(len(real) >= 1, "a Blender is installed on this machine (%s)" % (real[0][0] if real else "none"))
    if not real:
        return 1
    os.makedirs(wrap, exist_ok=True)
    with open(os.path.join(wrap, "blender"), "w") as f:
        f.write('#!/bin/sh\nexec "%s" "$@"\n' % real[0][0])
    os.chmod(os.path.join(wrap, "blender"), 0o755)

    root = tk.Tk()
    root.geometry("1000x700+20+20")
    app = gui.App(root)
    check(root.title().startswith("SimpleMesh Installer") and "Built" in root.title(), "title shows version and build date: %s" % root.title())
    check(wait(root, app, lambda: len(app.rows) >= 2 and all(r["info"] for r in app.rows)), "the window found and questioned the Blenders")
    check(len(app.rows) == 2 and all(r["info"]["ok"] for r in app.rows), "two usable Blenders listed")
    vals = [app.tree.item(r["iid"], "values") for r in app.rows]
    check(all(v[0] == gui.TICK and v[1].startswith("Blender 4") or v[1].startswith("Blender ") for v in vals)
          and all("not installed" in v[3] for v in vals), "rows show version, source and 'not installed': %s" % (vals[0][1:4],))
    shot(root, "installer-1-found")

    second = app.rows[1]
    click_row(root, app, second)
    check(not second["ticked"] and app.tree.item(second["iid"], "values")[0] == gui.NOTICK, "clicking a row unticks it")
    check([r["cmd"] for r in app.chosen()] == [app.rows[0]["cmd"]], "only the ticked Blender is chosen")

    app.add_path("/bin/true")
    wait(root, app, lambda: "not a Blender" in log_text(app))
    check("not a Blender" in log_text(app) and len(app.rows) == 2, "a program that is not Blender is refused with an explanation")

    app.b_go.invoke()
    check(app.busy, "buttons lock while it works")
    check(wait(root, app, lambda: "Installed into" in log_text(app)), "Install finished")
    first = app.rows[0]
    check(first["info"]["installed"] == gui.VERSION and first["info"]["enabled"], "the list now shows SimpleMesh %s installed and on" % gui.VERSION)
    check(os.path.isfile(os.path.join(first["info"]["addons"], "easy.py")), "the add-on's files are in Blender's add-ons folder")
    check(pref_easy(first["cmd"]) == ["1", "0"], "Blender will start in Easy mode with its start-up picture hidden")
    check(app.rows[1]["info"]["installed"] == gui.VERSION,
          "the other Blender 4.0 shares the same settings folder, and the list shows that too")
    shot(root, "installer-2-installed")
    app.b_run.invoke()
    root.update()
    time.sleep(4)
    running = subprocess.run(["pgrep", "-f", "blender"], capture_output=True, text=True).stdout.split()
    check("Starting Blender" in log_text(app) and len(running) > 0, "'Open Blender' starts the ticked Blender")
    subprocess.run(["pkill", "-x", "blender"])

    app.v_easy.set(False)
    app.v_splash.set(False)
    app.b_go.invoke()
    wait(root, app, lambda: log_text(app).count("Installed into") >= 2)
    check(pref_easy(first["cmd"]) == ["0", "1"], "unticking the two options is respected on reinstall")

    app.b_rm.invoke()
    check(wait(root, app, lambda: "Removed from" in log_text(app)), "Remove finished")
    check(first["info"]["installed"] == "" and not first["info"]["enabled"], "the list shows it gone again")
    check(not os.path.isdir(first["info"]["addons"]), "the add-on folder was deleted")

    for r in app.rows:
        r["ticked"] = False
        app.refresh_row(r)
    app.b_go.invoke()
    root.update()
    check("Tick at least one Blender" in log_text(app) and not app.busy, "with nothing ticked it asks you to tick one")
    shot(root, "installer-3-removed")
    root.destroy()
    print()
    if FAILS:
        print("%d FAILED" % len(FAILS))
        return 1
    print("INSTALLER GUI: ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

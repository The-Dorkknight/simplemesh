#!/usr/bin/env python3
# SimpleMesh installer. Run it with no options and it opens the window (install_gui.py).
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
# No warranty; see LICENSE.
"""Install SimpleMesh into Blender, switch it on and save your preferences.

    python3 install.py                 # opens the window with the Blender chooser

Without the window:
    python3 install.py --cli           # in the terminal; asks which Blender if there are several
    python3 install.py --cli --all     # every Blender it can find, no questions
    python3 install.py --list          # just show the Blenders it can find
    python3 install.py --blender /path/to/blender
    python3 install.py --remove        # switch off and delete again
    python3 install.py --no-easy       # do not start Blender in Easy mode
    python3 install.py --keep-splash   # leave Blender's start-up picture on

It works by starting Blender in the background (no window) and asking *it* to
copy the add-on into its own add-ons folder and enable it, so the right folder is
used for whatever Blender version/packaging you have. Nothing else is touched.
"""
import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "simplemesh")
MODULE = "simplemesh"


def package_version():
    """(version, build date) of the SimpleMesh in this folder."""
    try:
        txt = open(os.path.join(SRC, "version.py"), encoding="utf-8").read()
        return (re.search(r'__version__ = "([^"]+)"', txt).group(1),
                re.search(r'__build_date__ = "([^"]+)"', txt).group(1))
    except Exception:
        return "?", "?"


def inside_blender():
    # Blender has already loaded its own "bpy" module before it runs this file.
    # (Merely being able to import bpy is not enough: it can also be pip-installed.)
    return "bpy" in sys.modules


# --------------------------------------------------------------------------
# The part that runs inside Blender
# --------------------------------------------------------------------------

def payload(remove, easy=True, hide_splash=True):
    import bpy
    dest_root = bpy.utils.user_resource("SCRIPTS", path="addons", create=True)
    dest = os.path.join(dest_root, MODULE)
    if remove:
        try:
            bpy.ops.preferences.addon_disable(module=MODULE)
        except Exception:
            pass
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        try:
            bpy.context.preferences.view.show_splash = True
        except Exception:
            pass
        bpy.ops.wm.save_userpref()
        print("SIMPLEMESH: removed from", dest)
        return 0
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(SRC, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # A just-created add-ons folder is not on Blender's search path yet.
    import addon_utils
    if dest_root not in sys.path:
        sys.path.append(dest_root)
    addon_utils.modules_refresh()
    addon_utils.enable(MODULE, default_set=True, persistent=True)
    if MODULE not in bpy.context.preferences.addons:
        print("SIMPLEMESH-FAILED: copied to", dest, "but Blender would not switch it on "
              "(see the error above). Tick it by hand in Edit > Preferences > Add-ons.")
        return 4
    try:
        bpy.context.preferences.addons[MODULE].preferences.easy_start = bool(easy)
    except Exception:
        pass
    # Blender's start-up picture offers "2D Animation", "VFX", "Video Editing"...:
    # exactly the clutter this add-on removes (--remove puts it back).
    try:
        bpy.context.preferences.view.show_splash = not hide_splash
    except Exception:
        pass
    bpy.ops.wm.save_userpref()
    print("SIMPLEMESH: installed to", dest, "and enabled (Blender %s)" % bpy.app.version_string)
    return 0


# --------------------------------------------------------------------------
# Finding Blender
# --------------------------------------------------------------------------

def _steam_dirs():
    return [os.path.expanduser(p) for p in (
        "~/.steam/steam/steamapps/common/Blender", "~/.local/share/Steam/steamapps/common/Blender",
        "~/Library/Application Support/Steam/steamapps/common/Blender")] + [
        r"C:\Program Files (x86)\Steam\steamapps\common\Blender"]


def candidates():
    """Every Blender we can find, as command lists (usually one path each)."""
    found = []
    exe = shutil.which("blender")
    if exe:
        found.append([exe])
    for p in ("/snap/bin/blender", "/usr/bin/blender", "/usr/local/bin/blender"):
        if os.path.exists(p):
            found.append([p])
    home = os.path.expanduser("~")
    pats = [os.path.join(home, "blender*", "blender"), os.path.join(home, "Downloads", "blender*", "blender"),
            os.path.join(home, "Applications", "blender*", "blender"), os.path.join(home, "apps", "blender*", "blender"),
            os.path.join(home, ".local", "share", "blender*", "blender"), "/opt/blender*/blender",
            "/Applications/Blender*.app/Contents/MacOS/Blender",
            os.path.join(home, "Applications", "Blender*.app", "Contents", "MacOS", "Blender"),
            r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
            r"C:\Program Files (x86)\Blender Foundation\Blender*\blender.exe"]
    for d in _steam_dirs():
        pats += [os.path.join(d, "blender"), os.path.join(d, "blender.exe"),
                 os.path.join(d, "Blender.app", "Contents", "MacOS", "Blender")]
    for pat in pats:
        for p in sorted(glob.glob(pat)):
            if os.path.isfile(p):
                found.append([p])
    if shutil.which("flatpak"):
        try:
            r = subprocess.run(["flatpak", "info", "org.blender.Blender"], capture_output=True, timeout=20)
            if r.returncode == 0:
                found.append(["flatpak", "run", "--filesystem=%s:ro" % HERE, "org.blender.Blender"])
        except Exception:
            pass
    seen, out = set(), []
    for c in found:
        real = os.path.realpath(c[0]) if len(c) == 1 else " ".join(c)
        if real not in seen:
            seen.add(real)
            out.append(c)
    return out


def label(cmd):
    """A short human name for where this Blender came from."""
    if cmd[0] == "flatpak":
        return "Flatpak"
    p = os.path.realpath(cmd[0])
    low = p.lower()
    if "/snap/" in low:
        return "Snap"
    if "steamapps" in low:
        return "Steam"
    if low.endswith(".app/contents/macos/blender"):
        return "Mac app"
    if low.startswith(("/usr/bin", "/usr/local/bin")):
        return "System package"
    if low.endswith(".exe"):
        return "Windows program"
    return "Download"


def shown_path(cmd):
    return "flatpak: org.blender.Blender" if cmd[0] == "flatpak" else cmd[0]


_QUERY = r'''
import bpy, os, re
d = os.path.join(bpy.utils.user_resource("SCRIPTS", path="addons"), "simplemesh")
v = ""
for f in ("version.py", "__init__.py"):
    try:
        v = re.search(r'__version__ = "([^"]+)"', open(os.path.join(d, f), encoding="utf-8").read()).group(1)
        break
    except Exception:
        pass
if not v and os.path.isdir(d):
    v = "?"
print("SIMPLEMESH-INFO|%s|%s|%s|%d" % (bpy.app.version_string, d, v, int("simplemesh" in bpy.context.preferences.addons)))
'''


def query(cmd, timeout=90):
    """Ask one Blender about itself: dict(ok, version, addons, installed, enabled, error)."""
    info = {"ok": False, "version": "", "addons": "", "installed": "", "enabled": False, "error": ""}
    try:
        r = subprocess.run(cmd + ["-b", "--python-expr", _QUERY], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        info["error"] = "not found"
        return info
    except subprocess.TimeoutExpired:
        info["error"] = "did not answer"
        return info
    except Exception as ex:  # noqa: BLE001
        info["error"] = str(ex)
        return info
    for line in (r.stdout + r.stderr).splitlines():
        if line.startswith("SIMPLEMESH-INFO|"):
            _tag, ver, addons, inst, en = line.split("|")
            info.update(ok=True, version=ver, addons=addons, installed=inst, enabled=en == "1")
            return info
    info["error"] = "this does not look like Blender" if r.returncode else "no answer from Blender"
    return info


def run_in(cmd, remove=False, easy=True, hide_splash=True, timeout=300):
    """Install into (or remove from) one Blender. Returns (ok, [message lines])."""
    args = (["--remove"] if remove else []) + ([] if easy else ["--no-easy"]) + ([] if hide_splash else ["--keep-splash"])
    full = cmd + ["-b", "--python", os.path.abspath(__file__), "--"] + args
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    except Exception as ex:  # noqa: BLE001
        return False, ["Could not run Blender: %s" % ex]
    lines = [ln for ln in (r.stdout + r.stderr).splitlines()
             if "SIMPLEMESH" in ln or "Error" in ln or "Traceback" in ln]
    if not lines:
        lines = ["(no output; Blender exit code %d)" % r.returncode]
    return any(ln.startswith("SIMPLEMESH:") for ln in lines), lines


def launch(cmd):
    """Start Blender normally, detached from this program."""
    kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008          # DETACHED_PROCESS
    else:
        kw["start_new_session"] = True
    cmd = [c for c in cmd if not c.startswith("--filesystem=")]
    return subprocess.Popen(cmd, **kw)


# --------------------------------------------------------------------------
# Starting point
# --------------------------------------------------------------------------

CLI_FLAGS = ("--cli", "--list", "--blender", "--remove", "--no-easy", "--keep-splash", "--all", "--help", "-h")


def choose_in_terminal(cmds):
    """A numbered list to pick from, for when there is no window."""
    infos = [(c, query(c)) for c in cmds]
    good = [(c, q) for c, q in infos if q["ok"]]
    if len(good) <= 1:
        return [c for c, _q in good] or cmds
    print("Which Blender?")
    for n, (c, q) in enumerate(good, 1):
        state = ("has SimpleMesh " + q["installed"]) if q["installed"] else "no SimpleMesh yet"
        print("  %d  Blender %-9s %-15s %s   (%s)" % (n, q["version"], label(c), shown_path(c), state))
    try:
        ans = input("Type the number(s), or just press Enter for all of them: ").replace(",", " ").split()
    except EOFError:
        ans = []
    picked = [good[int(a) - 1][0] for a in ans if a.isdigit() and 1 <= int(a) <= len(good)]
    return picked or [c for c, _q in good]


def main(argv):
    remove = "--remove" in argv
    easy = "--no-easy" not in argv
    hide_splash = "--keep-splash" not in argv
    if inside_blender():
        return payload(remove, easy, hide_splash)
    ver, built = package_version()
    if "--version" in argv:
        print("SimpleMesh installer %s (Built %s)" % (ver, built))
        return 0
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    if not any(a in CLI_FLAGS for a in argv):
        # plain "install.py" (or a double-click): open the window with the Blender chooser
        try:
            import install_gui
            return install_gui.main(argv)
        except Exception as ex:  # noqa: BLE001
            print("Could not open the installer window (%s); using the terminal instead.\n" % ex)
    code = cli(argv, remove, easy, hide_splash, ver)
    if "--pause" in argv:
        try:
            input("\nPress Enter to close this window.")
        except EOFError:
            pass
    return code


def cli(argv, remove, easy, hide_splash, ver):
    if not os.path.isdir(SRC):
        print("Run this from the unzipped SimpleMesh folder (the 'simplemesh' folder must be next to install.py).")
        return 1
    if "--blender" in argv:
        cmds = [[argv[argv.index("--blender") + 1]]]
    else:
        cmds = candidates()
    if "--list" in argv:
        for c in cmds:
            q = query(c)
            state = ("SimpleMesh %s%s" % (q["installed"], "" if q["enabled"] else " (switched off)")) if q["installed"] \
                else "SimpleMesh not installed"
            print("%-16s Blender %-10s %s   [%s]" % (label(c), q["version"] or "?", shown_path(c),
                                                     state if q["ok"] else q["error"]))
        if not cmds:
            print("No Blender found.")
        return 0
    if not cmds:
        print("Could not find Blender.\n"
              "Run this again with:  --blender /path/to/blender")
        return 2
    print("SimpleMesh %s" % ver)
    if "--blender" not in argv and "--all" not in argv and sys.stdin is not None and sys.stdin.isatty():
        cmds = choose_in_terminal(cmds)
    oks = []
    for c in cmds:
        print("\n>>", shown_path(c))
        ok, lines = run_in(c, remove, easy, hide_splash)
        print("\n".join(lines))
        oks.append(ok)
    if any(oks):
        print("\nDone." if remove else
              "\nDone. Start Blender: it opens with the SimpleMesh picture buttons and tool strip.")
        return 0
    print("\nBlender was found but the install did not report success. Install the zip by hand (see README).")
    return 3


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    sys.exit(main(args))

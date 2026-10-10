#!/usr/bin/env python3
# Build the installable add-on zips into dist/.
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
"""  python tools/build_zip.py

Writes three zips (same code, different layout):
  dist/simplemesh-<ver>-installer.zip  the installer window + launchers + add-on: unzip, double-click, done
  dist/simplemesh-<ver>.zip            folder layout: Blender 3.0+ (Edit > Preferences > Add-ons > Install)
  dist/simplemesh-<ver>-extension.zip  root layout with blender_manifest.toml: Blender 4.2+ extension install
"""
import os
import re
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "simplemesh")


def version():
    txt = open(os.path.join(SRC, "version.py"), encoding="utf-8").read()
    return re.search(r'__version__ = "([^"]+)"', txt).group(1)


def files():
    for dp, dn, fn in os.walk(SRC):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if not f.endswith(".pyc"):
                yield os.path.join(dp, f)


def main():
    v = version()
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    legacy = os.path.join(ROOT, "dist", "simplemesh-%s.zip" % v)
    ext = os.path.join(ROOT, "dist", "simplemesh-%s-extension.zip" % v)
    with zipfile.ZipFile(legacy, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files():
            z.write(f, os.path.join("simplemesh", os.path.relpath(f, SRC)))
        z.write(os.path.join(ROOT, "LICENSE"), "simplemesh/LICENSE")
    with zipfile.ZipFile(ext, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files():
            z.write(f, os.path.relpath(f, SRC))
        z.write(os.path.join(ROOT, "LICENSE"), "LICENSE")
    inst = os.path.join(ROOT, "dist", "simplemesh-%s-installer.zip" % v)
    top = "SimpleMesh-%s" % v
    extras = ["install_gui.py", "install.py", "Install SimpleMesh (Linux).sh", "Install SimpleMesh (Mac).command",
              "Install SimpleMesh (Windows).bat", "LICENSE", os.path.join("icons", "simplemesh-512.png")]
    with zipfile.ZipFile(inst, "w", zipfile.ZIP_DEFLATED) as z:
        def add(src, arc, exe=False):
            zi = zipfile.ZipInfo.from_file(src, arc)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = (0o100755 if exe else 0o100644) << 16      # keep "run me" permission
            with open(src, "rb") as fh:
                z.writestr(zi, fh.read())
        for f in files():
            add(f, os.path.join(top, "simplemesh", os.path.relpath(f, SRC)))
        for e in extras:
            add(os.path.join(ROOT, e), os.path.join(top, e), exe=e.endswith((".sh", ".command", ".py")))
        z.writestr(os.path.join(top, "READ ME FIRST.txt"),
                   "SimpleMesh %s\n\n1. Unzip this whole folder.\n2. Double-click the 'Install SimpleMesh' file for your "
                   "computer (Linux, Mac or Windows).\n   Or type:  python3 install.py\n3. Tick your Blender, press "
                   "'Install or update', then 'Open Blender'.\n\nWORK IN PROGRESS: many features may be broken.\n"
                   "Free software, GPL-3.0-only. No warranty. https://github.com/The-Dorkknight/simplemesh\n" % v)
    print(legacy)
    print(ext)
    print(inst)


if __name__ == "__main__":
    sys.exit(main())

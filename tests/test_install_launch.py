# SimpleMesh - checks that plain "python3 install.py" really opens the installer window
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
#
# Needs a display (use xvfb-run on a machine without a screen):
#   xvfb-run -a python3 tests/test_install_launch.py
#
# Regression test for 0.4.1, where install.py was the terminal-only tool and running it
# showed no window at all.
import os
import subprocess
import sys
import time
import tkinter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
FAILS = []


def check(ok, what):
    print("  %s %s" % ("ok  " if ok else "FAIL", what))
    if not ok:
        FAILS.append(what)
    return ok


def tk_apps(probe):
    """Names of the Tk programs that have a window open on this display."""
    try:
        return set(probe.tk.call("winfo", "interps"))
    except tkinter.TclError:
        return set()


def main():
    import install
    import install_gui

    # 1. which way does install.py go for each kind of command line?
    seen = []
    real_gui, real_cli = install_gui.main, install.cli
    install_gui.main = lambda argv: seen.append(("window", list(argv))) or 0
    install.cli = lambda argv, *rest: seen.append(("terminal", list(argv))) or 0
    try:
        install.main([])
        check(seen[-1][0] == "window", "no options -> the window")
        install.main(["--pause-is-not-a-cli-flag"])
        check(seen[-1][0] == "window", "an unknown option still -> the window")
        for flags in (["--cli"], ["--list"], ["--remove"], ["--all"], ["--blender", "x"], ["--no-easy"]):
            install.main(flags)
            check(seen[-1][0] == "terminal", "%s -> the terminal installer" % " ".join(flags))

        def boom(argv):
            raise RuntimeError("no window today")
        install_gui.main = boom
        install.main([])
        check(seen[-1][0] == "terminal", "if the window cannot open it falls back to the terminal installer")
    finally:
        install_gui.main, install.cli = real_gui, real_cli

    # 2. the real thing: start install.py as its own program and look for its window
    probe = tkinter.Tk()
    probe.withdraw()
    before = tk_apps(probe)
    env = dict(os.environ)
    env.pop("SIMPLEMESH_NO_TK", None)
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "install.py")], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    new = set()
    end = time.time() + 40
    while time.time() < end and proc.poll() is None:
        probe.update()
        new = tk_apps(probe) - before
        if new:
            break
        time.sleep(0.25)
    check(bool(new), "python3 install.py opened a window (%s)" % (", ".join(sorted(new)) or "none seen"))
    check(proc.poll() is None, "and it stays open, waiting for you")
    proc.terminate()
    try:
        out = proc.communicate(timeout=15)[0].decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        proc.kill()
        out = proc.communicate()[0].decode("utf-8", "replace")
    if not new:
        print(out)
    probe.destroy()

    # 3. --version and --help answer straight away without opening anything
    for flag, want in (("--version", "SimpleMesh installer"), ("--help", "--cli")):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "install.py"), flag],
                           capture_output=True, text=True, timeout=60)
        check(r.returncode == 0 and want in r.stdout, "install.py %s prints and exits" % flag)

    print()
    if FAILS:
        print("%d FAILED" % len(FAILS))
        return 1
    print("INSTALL LAUNCH: ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

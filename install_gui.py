#!/usr/bin/env python3
# SimpleMesh installer window: choose which Blender(s) to install into.
# Copyright (C) 2026 Matthew Armstrong (https://github.com/The-Dorkknight)
# SPDX-License-Identifier: GPL-3.0-only
# No warranty; see LICENSE.
#
# WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN
"""SimpleMesh installer with a window.

    python3 install.py            (or double-click "Install SimpleMesh" for your system)

It lists every Blender it can find, with its version and whether SimpleMesh is
already in it. Tick the ones you want, or add another Blender by hand, then press
Install. The work is done by install.py; this file is only the window.
If this computer's Python has no window toolkit (tkinter) the same chooser is
shown with the desktop's own dialog boxes (zenity, on Linux), or in a terminal.
"""
import os
import queue
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import install as core  # noqa: E402

VERSION, BUILT = core.package_version()
TITLE = "SimpleMesh Installer %s (Built %s)" % (VERSION, BUILT)

BG = "#161b22"
PANEL = "#1f2630"
INK = "#e8eaed"
MUTED = "#9aa3ad"
CYAN = "#35d6f5"
AMBER = "#ffb81a"
GREEN = "#4ade80"
RED = "#ff6b5e"
TICK, NOTICK = "☑", "☐"          # ticked / empty box


def state_text(info):
    if not info:
        return "checking..."
    if not info["ok"]:
        return "cannot use: " + (info["error"] or "no answer")
    if not info["installed"]:
        return "SimpleMesh not installed"
    if info["installed"] == VERSION:
        return "SimpleMesh %s installed" % VERSION + ("" if info["enabled"] else " (switched off)")
    return "SimpleMesh %s installed: update to %s" % (info["installed"], VERSION)


class App:
    def __init__(self, root, scan=True):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.root = root
        self.rows = []                  # dict(cmd, ticked, info, iid)
        self.busy = False
        self.q = queue.Queue()
        root.title(TITLE)
        root.configure(bg=BG)
        root.minsize(760, 560)
        try:
            self.icon = tk.PhotoImage(file=os.path.join(HERE, "icons", "simplemesh-512.png"))
            root.iconphoto(True, self.icon)
            self.logo = self.icon.subsample(8, 8)
        except Exception:
            self.icon = self.logo = None

        st = ttk.Style(root)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background=BG, foreground=INK, fieldbackground=PANEL, font=("TkDefaultFont", 10))
        st.configure("TFrame", background=BG)
        st.configure("TLabel", background=BG, foreground=INK)
        st.configure("Muted.TLabel", foreground=MUTED)
        st.configure("Head.TLabel", font=("TkDefaultFont", 16, "bold"))
        st.configure("Wip.TLabel", background=AMBER, foreground="#1c1f24", font=("TkDefaultFont", 9, "bold"))
        st.configure("TCheckbutton", background=BG, foreground=INK)
        st.map("TCheckbutton", background=[("active", BG)], foreground=[("active", INK)])
        st.configure("TButton", background=PANEL, foreground=INK, padding=(12, 7), borderwidth=1)
        st.map("TButton", background=[("active", "#2b3542"), ("disabled", BG)], foreground=[("disabled", "#5b646e")])
        st.configure("Go.TButton", background="#0f7a36", foreground="#ffffff", font=("TkDefaultFont", 11, "bold"),
                     padding=(18, 10))
        st.map("Go.TButton", background=[("active", "#149947"), ("disabled", BG)])
        st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=INK, rowheight=30,
                     borderwidth=0)
        st.configure("Treeview.Heading", background="#2b3542", foreground=INK, font=("TkDefaultFont", 9, "bold"))
        st.map("Treeview", background=[("selected", "#2b3542")], foreground=[("selected", INK)])

        ttk.Label(root, text="  WORK IN PROGRESS: many features may be broken  ", style="Wip.TLabel",
                  anchor="center").pack(fill="x")
        head = ttk.Frame(root, padding=(16, 12, 16, 4))
        head.pack(fill="x")
        if self.logo is not None:
            tk.Label(head, image=self.logo, bg=BG).pack(side="left", padx=(0, 12))
        col = ttk.Frame(head)
        col.pack(side="left", fill="x", expand=True)
        ttk.Label(col, text="Install SimpleMesh into Blender", style="Head.TLabel").pack(anchor="w")
        ttk.Label(col, text="Tick the Blender you want. Click a row to tick or untick it.",
                  style="Muted.TLabel").pack(anchor="w")

        mid = ttk.Frame(root, padding=(16, 6, 16, 0))
        mid.pack(fill="both", expand=True)
        cols = ("pick", "blender", "kind", "state", "path")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=5, selectmode="none")
        for c, text, w, stretch in (("pick", "Use", 44, False), ("blender", "Blender", 120, False),
                                    ("kind", "From", 120, False), ("state", "SimpleMesh in it", 270, True),
                                    ("path", "Where it is", 260, True)):
            self.tree.heading(c, text=text, anchor="w")
            self.tree.column(c, width=w, minwidth=w if not stretch else 120, stretch=stretch, anchor="w")
        self.tree.column("pick", anchor="center")
        self.tree.tag_configure("bad", foreground=MUTED)
        self.tree.tag_configure("old", foreground=AMBER)
        self.tree.tag_configure("good", foreground=GREEN)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Button-1>", self.on_click)
        self.empty = ttk.Label(mid, text="", style="Muted.TLabel")
        self.empty.pack(anchor="w", pady=(4, 0))

        row = ttk.Frame(root, padding=(16, 8, 16, 0))
        row.pack(fill="x")
        self.b_scan = ttk.Button(row, text="Find Blender again", command=self.scan)
        self.b_scan.pack(side="left")
        self.b_add = ttk.Button(row, text="Add another Blender...", command=self.add_dialog)
        self.b_add.pack(side="left", padx=8)

        opts = ttk.Frame(root, padding=(16, 10, 16, 0))
        opts.pack(fill="x")
        self.v_easy = tk.BooleanVar(value=True)
        self.v_splash = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Start Blender in Easy mode (big picture buttons, good for children)",
                        variable=self.v_easy).pack(anchor="w")
        ttk.Checkbutton(opts, text="Hide Blender's start-up picture (the one offering 2D Animation, VFX...)",
                        variable=self.v_splash).pack(anchor="w")

        act = ttk.Frame(root, padding=(16, 12, 16, 0))
        act.pack(fill="x")
        self.b_go = ttk.Button(act, text="Install or update", style="Go.TButton", command=self.install)
        self.b_go.pack(side="left")
        self.b_rm = ttk.Button(act, text="Remove", command=self.remove)
        self.b_rm.pack(side="left", padx=8)
        self.b_run = ttk.Button(act, text="Open Blender", command=self.open_blender)
        self.b_run.pack(side="left")
        self.b_quit = ttk.Button(act, text="Close", command=root.destroy)
        self.b_quit.pack(side="right")

        logf = ttk.Frame(root, padding=(16, 10, 16, 6))
        logf.pack(fill="both", expand=True)
        self.log = tk.Text(logf, height=7, bg="#0e131a", fg=INK, insertbackground=INK, relief="flat",
                           wrap="word", padx=8, pady=6, font=("TkFixedFont", 9))
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("ok", foreground=GREEN)
        self.log.tag_configure("bad", foreground=RED)
        self.log.tag_configure("dim", foreground=MUTED)
        self.log.configure(state="disabled")

        self.status = ttk.Label(root, text="v%s • %s" % (VERSION, BUILT), style="Muted.TLabel",
                                padding=(16, 0, 16, 8))
        self.status.pack(fill="x")

        self.say("SimpleMesh %s, from %s" % (VERSION, core.SRC), "dim")
        if not os.path.isdir(core.SRC):
            self.say("The 'simplemesh' folder is missing next to this installer. Unzip the whole download first.", "bad")
        root.after(100, self.poll)
        if scan:
            root.after(150, self.scan)

    # ---- small helpers -----------------------------------------------------
    def say(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", (tag,) if tag else ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_busy(self, busy, what=""):
        self.busy = busy
        for b in (self.b_scan, self.b_add, self.b_go, self.b_rm, self.b_run):
            b.configure(state="disabled" if busy else "normal")
        self.status.configure(text=(what + "   ") if busy else "v%s • %s" % (VERSION, BUILT))

    def refresh_row(self, r):
        info = r["info"]
        ok = bool(info and info["ok"])
        if info and not ok:
            r["ticked"] = False
        tag = "bad"
        if ok:
            tag = "good" if info["installed"] == VERSION and info["enabled"] else ("old" if info["installed"] else "")
        vals = (TICK if r["ticked"] else NOTICK, ("Blender " + info["version"]) if ok else "Blender",
                core.label(r["cmd"]), state_text(info), core.shown_path(r["cmd"]))
        self.tree.item(r["iid"], values=vals, tags=(tag,) if tag else ())

    def add_row(self, cmd, ticked=True):
        for r in self.rows:
            if r["cmd"] == cmd:
                return r
        r = {"cmd": cmd, "ticked": ticked, "info": None, "iid": self.tree.insert("", "end", values=("",) * 5)}
        self.rows.append(r)
        self.refresh_row(r)
        return r

    def chosen(self):
        return [r for r in self.rows if r["ticked"] and r["info"] and r["info"]["ok"]]

    def on_click(self, event):
        if self.busy:
            return
        iid = self.tree.identify_row(event.y)
        for r in self.rows:
            if r["iid"] == iid and r["info"] and r["info"]["ok"]:
                r["ticked"] = not r["ticked"]
                self.refresh_row(r)

    # ---- background work -----------------------------------------------------
    def work(self, fn, what):
        self.set_busy(True, what)

        def run():
            try:
                fn()
            except Exception as ex:  # noqa: BLE001
                self.q.put(("say", "Something went wrong: %s" % ex, "bad"))
            self.q.put(("done",))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "say":
                    self.say(m[1], m[2] if len(m) > 2 else None)
                elif m[0] == "found":
                    self.add_row(m[1])
                elif m[0] == "info":
                    for r in self.rows:
                        if r["cmd"] == m[1]:
                            r["info"] = m[2]
                            self.refresh_row(r)
                elif m[0] == "status":
                    self.status.configure(text=m[1] + "   ")
                elif m[0] == "done":
                    self.set_busy(False)
                    self.empty.configure(text="" if self.rows else
                                         "No Blender found. Press 'Add another Blender...' and choose the Blender program.")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def scan(self):
        if self.busy:
            return
        for r in self.rows:
            self.tree.delete(r["iid"])
        self.rows = []
        self.empty.configure(text="")

        def job():
            cmds = core.candidates()
            for c in cmds:
                self.q.put(("found", c))
            if not cmds:
                self.q.put(("say", "No Blender found in the usual places.", "bad"))
            for c in cmds:
                self.q.put(("status", "Asking %s about itself..." % core.shown_path(c)))
                info = core.query(c)
                self.q.put(("info", c, info))
                if info["ok"]:
                    self.q.put(("say", "Found Blender %s (%s): %s" % (info["version"], core.label(c), state_text(info))))
                else:
                    self.q.put(("say", "%s: %s" % (core.shown_path(c), info["error"]), "bad"))
        self.work(job, "Looking for Blender...")

    def add_path(self, path):
        """Add a Blender chosen by hand (also used by the tests)."""
        if not path:
            return
        if os.path.isdir(path) and path.rstrip("/").lower().endswith(".app"):
            path = os.path.join(path, "Contents", "MacOS", "Blender")
        cmd = [path]

        def job():
            self.q.put(("status", "Checking %s..." % path))
            info = core.query(cmd)
            if info["ok"]:
                self.q.put(("found", cmd))
                self.q.put(("info", cmd, info))
                self.q.put(("say", "Added Blender %s: %s" % (info["version"], path), "ok"))
            else:
                self.q.put(("say", "%s is not a Blender this installer can use (%s). Choose the program called "
                                   "'blender' (Linux), 'Blender' inside Blender.app (Mac) or 'blender.exe' (Windows)."
                            % (path, info["error"]), "bad"))
        self.work(job, "Checking...")

    def add_dialog(self):
        from tkinter import filedialog
        start = "/Applications" if sys.platform == "darwin" else os.path.expanduser("~")
        path = filedialog.askopenfilename(title="Choose the Blender program", initialdir=start)
        self.add_path(path)

    def _apply(self, remove):
        rows = self.chosen()
        if not rows:
            self.say("Tick at least one Blender first.", "bad")
            return
        easy, splash = bool(self.v_easy.get()), bool(self.v_splash.get())

        def job():
            good = 0
            for r in rows:
                name = "Blender %s (%s)" % (r["info"]["version"], core.label(r["cmd"]))
                self.q.put(("status", ("Removing from " if remove else "Installing into ") + name + "..."))
                ok, lines = core.run_in(r["cmd"], remove, easy, splash)
                for ln in lines:
                    self.q.put(("say", "  " + ln, "dim"))
                if ok:
                    good += 1
                    self.q.put(("say", ("Removed from " if remove else "Installed into ") + name, "ok"))
                else:
                    self.q.put(("say", "FAILED for " + name, "bad"))
            # Blenders of the same version share one settings folder, so ask them all again
            for r in [x for x in self.rows if x["info"] and x["info"]["ok"]]:
                self.q.put(("info", r["cmd"], core.query(r["cmd"])))
            if good and not remove:
                self.q.put(("say", "Done. Press 'Open Blender': it starts with the SimpleMesh buttons.", "ok"))
            elif good:
                self.q.put(("say", "Done.", "ok"))
        self.work(job, "Working...")

    def install(self):
        self._apply(False)

    def remove(self):
        self._apply(True)

    def open_blender(self):
        rows = self.chosen()
        if not rows:
            self.say("Tick the Blender you want to open.", "bad")
            return
        try:
            core.launch(rows[0]["cmd"])
            self.say("Starting Blender %s..." % rows[0]["info"]["version"], "ok")
        except Exception as ex:  # noqa: BLE001
            self.say("Could not start Blender: %s" % ex, "bad")


# --------------------------------------------------------------------------
# When the proper window cannot open (no tkinter): still show *something*
# --------------------------------------------------------------------------

def _zenity(*args):
    r = subprocess.run(["zenity"] + list(args), capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


class _Busy:
    """A small 'please wait' box while Blender is being asked or changed."""
    def __init__(self, text):
        try:
            self.p = subprocess.Popen(["zenity", "--progress", "--pulsate", "--no-cancel", "--auto-close",
                                       "--title", TITLE, "--text", text, "--width", "420"],
                                      stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            self.p = None

    def close(self):
        if self.p is not None:
            try:
                self.p.stdin.write(b"100\n")
                self.p.stdin.close()
                self.p.wait(timeout=5)
            except Exception:
                try:
                    self.p.kill()
                except Exception:
                    pass


def zenity_flow(reason):
    """The same chooser, built from the desktop's own dialog boxes (Linux)."""
    extra = []
    hint = "For the full installer window:  sudo apt install python3-tk"
    while True:
        busy = _Busy("Looking for Blender...")
        cmds = core.candidates() + [c for c in extra]
        infos = [(c, core.query(c)) for c in cmds]
        busy.close()
        good = [(c, q) for c, q in infos if q["ok"]]
        if not good:
            rc, _o = _zenity("--question", "--title", TITLE, "--width", "460",
                             "--text", "No Blender was found on this computer.\n\nChoose the Blender program yourself?")
            if rc != 0:
                return 2
            rc, path = _zenity("--file-selection", "--title", "Choose the Blender program")
            if rc == 0 and path:
                extra.append([path])
            continue
        rows = []
        for c, q in good:
            rows += ["TRUE", "Blender " + q["version"], core.label(c), state_text(q), core.shown_path(c)]
        rc, out = _zenity("--list", "--checklist", "--title", TITLE, "--width", "960", "--height", "420",
                          "--text", "Tick the Blender to put SimpleMesh %s into.\n%s" % (VERSION, hint),
                          "--column", "Use", "--column", "Blender", "--column", "From",
                          "--column", "SimpleMesh in it", "--column", "Where it is",
                          "--print-column", "5", "--separator", "\n",
                          "--ok-label", "Install or update", "--cancel-label", "Close",
                          "--extra-button", "Remove SimpleMesh", "--extra-button", "Add another Blender...", *rows)
        if out == "Add another Blender...":
            rc, path = _zenity("--file-selection", "--title", "Choose the Blender program")
            if rc == 0 and path:
                busy = _Busy("Checking...")
                q = core.query([path])
                busy.close()
                if q["ok"]:
                    extra.append([path])
                else:
                    _zenity("--error", "--title", TITLE, "--width", "460",
                            "--text", "That is not a Blender this installer can use.\nChoose the program called 'blender'.")
            continue
        remove = out == "Remove SimpleMesh"
        if remove:
            chosen = [c for c, q in good if q["installed"]]
            if not chosen:
                _zenity("--info", "--title", TITLE, "--text", "SimpleMesh is not installed in any of these.")
                continue
            rc, _o = _zenity("--question", "--title", TITLE, "--width", "460",
                             "--text", "Remove SimpleMesh from:\n\n" + "\n".join(core.shown_path(c) for c in chosen))
            if rc != 0:
                continue
        else:
            if rc != 0:
                return 0                                   # Close
            picked = set(out.splitlines())
            chosen = [c for c, q in good if core.shown_path(c) in picked]
            if not chosen:
                _zenity("--warning", "--title", TITLE, "--text", "Tick at least one Blender first.")
                continue
        easy = True
        if not remove:
            rc, _o = _zenity("--question", "--title", TITLE, "--width", "460",
                             "--text", "Start Blender in Easy mode?\n\nEasy mode has big picture buttons and is good for children.",
                             "--ok-label", "Yes, Easy mode", "--cancel-label", "No, grown-up tools")
            easy = rc == 0
        busy = _Busy("Removing..." if remove else "Installing...")
        report, any_ok = [], False
        for c in chosen:
            ok, lines = core.run_in(c, remove, easy, True)
            any_ok = any_ok or ok
            report.append(("%s  %s" % ("OK" if ok else "FAILED", core.shown_path(c))) + ("" if ok else "\n   " + "\n   ".join(lines[-3:])))
        busy.close()
        if remove or not any_ok:
            _zenity("--info" if any_ok else "--error", "--title", TITLE, "--width", "560", "--text", "\n".join(report))
            continue
        rc, _o = _zenity("--question", "--title", TITLE, "--width", "560",
                         "--text", "SimpleMesh %s is installed.\n\n%s\n\nOpen Blender now?" % (VERSION, "\n".join(report)),
                         "--ok-label", "Open Blender", "--cancel-label", "Close")
        if rc == 0:
            try:
                core.launch(chosen[0])
            except Exception as ex:  # noqa: BLE001
                _zenity("--error", "--title", TITLE, "--text", "Could not start Blender: %s" % ex)
        return 0


def no_window(reason, argv):
    """tkinter is missing or there is no display: fall back, visibly."""
    import shutil
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if sys.platform.startswith("linux") and has_display and shutil.which("zenity"):
        return zenity_flow(reason)
    msg = "The installer window cannot open on this computer (%s)." % reason
    if sys.stdin is not None and sys.stdin.isatty():
        print(msg)
        if sys.platform.startswith("linux"):
            print("To get the window:   sudo apt install python3-tk     (then run this again)")
        print("Carrying on in the terminal instead.\n")
        return core.main(["--cli"] + list(argv))
    # started by a double-click with nowhere to print: open a terminal for the text version
    here = os.path.join(HERE, "install.py")
    for term in (["x-terminal-emulator", "-e"], ["gnome-terminal", "--"], ["xfce4-terminal", "-x"],
                 ["konsole", "-e"], ["xterm", "-e"]):
        if shutil.which(term[0]):
            try:
                subprocess.Popen(term + [sys.executable, here, "--cli", "--pause"])
                return 0
            except Exception:
                continue
    try:
        with open(os.path.join(HERE, "install_log.txt"), "w", encoding="utf-8") as f:
            f.write(msg + "\nOpen a terminal in this folder and type:  python3 install.py --cli\n")
    except Exception:
        pass
    return 5


def main(argv):
    if "--version" in argv:
        print(TITLE)
        return 0
    try:
        if os.environ.get("SIMPLEMESH_NO_TK"):
            raise ImportError("tkinter switched off for testing")
        import tkinter as tk
        root = tk.Tk()
    except Exception as ex:  # noqa: BLE001
        return no_window(ex, argv)
    try:
        App(root)
        root.mainloop()
    except Exception as ex:  # noqa: BLE001
        try:
            from tkinter import messagebox
            messagebox.showerror(TITLE, "The installer hit a problem:\n\n%s\n\nTry:  python3 install.py --cli" % ex)
        except Exception:
            print("The installer hit a problem: %s" % ex)
        return 6
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

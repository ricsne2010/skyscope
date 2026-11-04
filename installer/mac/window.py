"""SkyScope's Mac installer and uninstaller window, made like the M.O.S.S. RPi SD Card Creator's: one window, a page
at a time (Back, Next, Cancel), the Project Moon Pi patch in the corner, and the work shown step by step on a bar.

    window.py               install or update (run by "Install SkyScope.app", from the program's files inside it)
    window.py --uninstall   remove it (run by "Uninstall SkyScope.app", from SkyScope's own folder)
    window.py --dry-run     every page, with pretend work: nothing is installed or removed (for testing;
                            with --auto it also clicks Next / Install / Uninstall by itself)

The work itself is install.sh / uninstall.sh beside this file; they print "@@ <percent> <text>" for each step and
"@! <note>" for the last page, and everything else goes to the log. SkyScope is started as the installer's very last
step, and the radar opens only when you click Finish (with "Open the radar now" ticked).
Needs Python 3.10 or newer with Tk (python.org's has it). Designed and Created by Project Moon Pi.
"""
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:                                 # Apple's own python3 can lack Tk
    sys.exit("This needs Python with Tk: install Python from python.org, then try again.")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))       # the program's files: in the installer app, or SkyScope's folder
UNINSTALL = "--uninstall" in sys.argv
DRY = "--dry-run" in sys.argv
AUTO = DRY and "--auto" in sys.argv
APP = "SkyScope"
TITLE = f"Uninstall {APP}" if UNINSTALL else f"Install {APP}"
CREDIT = "Designed and Created by Project Moon Pi"
APPDIR = os.path.expanduser("~/Library/Application Support/SkyScope")
LOG = os.path.expanduser(f"~/Library/Logs/{TITLE}.log")
WIDTH, WRAP = 580, 520                              # the window (points), the text's width
INSTALL_STEPS = [3, 8, 20, 45, 68, 74, 80, 84, 92, 95, 100]   # install.sh's steps (the bar creeps to the next)
UNINSTALL_STEPS = [10, 40, 75, 95, 100]


def version_of(folder):
    try:
        return re.search(r'VERSION = "([^"]+)"', open(os.path.join(folder, "version.py")).read()).group(1)
    except (OSError, AttributeError):
        return None


VERSION = version_of(ROOT) or ""
INSTALLED = version_of(APPDIR)


def image(*names):
    """The first of these program files that's there (they're in a different place in the installer and in SkyScope's
    folder), or None."""
    return next((os.path.join(ROOT, n) for n in names if os.path.exists(os.path.join(ROOT, n))), None)


LOGO = image("docs/images/moon-pi-logo-128.png")
ICON = image("tools/launcher/skyscope-1024.png", "tools/launcher/skyscope-uninstall-1024.png")


# ---- the welcome page's checks: (state, text), state ok / warn / fail
def check_mac():
    v = subprocess.run(["sw_vers", "-productVersion"], capture_output=True, text=True).stdout.strip()
    major = int(v.split(".")[0] or 0)
    return ("ok", f"macOS {v}") if major >= 11 else ("fail", f"macOS {v}: SkyScope needs macOS 11 (Big Sur) or newer")


def check_python():
    v = ".".join(map(str, sys.version_info[:3]))
    where = "python.org" if sys.executable.startswith("/Library/Frameworks/Python.framework") else sys.executable
    return ("ok", f"Python {v} ({where})") if sys.version_info >= (3, 10) else ("fail", f"Python {v}: 3.10 or newer is needed")


def check_internet():
    for url in ("https://pypi.org/simple/pygame-ce/", "https://www.python.org/"):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "SkyScope installer"})
            urllib.request.urlopen(req, timeout=10).close()
            return "ok", "connected (it downloads pygame-ce and the menu bar icon's parts)"
        except Exception:
            continue
    return "fail", "no connection: installing downloads pygame-ce from the internet. Connect, then Check again."


def check_space():
    free = shutil.disk_usage(os.path.expanduser("~")).free / 1e9
    return ("ok", f"{free:.0f} GB free") if free >= 0.5 else ("fail", f"only {free * 1000:.0f} MB free: it needs about 200 MB")


def check_installed():
    if not INSTALLED:
        return "ok", "not yet: this installs it"
    if INSTALLED == VERSION:
        return "ok", f"SkyScope {INSTALLED} is installed: this installs it again (your settings are kept)"
    return "ok", f"SkyScope {INSTALLED} is installed: this updates it to {VERSION} (your settings are kept)"


CHECKS = [("This Mac", check_mac), ("Python", check_python), ("Internet", check_internet), ("Disk space", check_space),
          ("SkyScope", check_installed)]


class MoonBar(tk.Canvas):
    """The work's progress, 0 to 100 %: a blue bar with the Project Moon Pi patch riding its leading edge and a little
    plane flying back and forth over the part already done (as the card creator's skid steer drives over its bar).
    It glides towards its target, and creeps on while a long step runs."""
    H, BAR_H, PATCH = 64, 12, 32
    SPEED, TICK = 1.6, 30

    def __init__(self, master, width):
        bg = ttk.Style().lookup("TFrame", "background") or "systemWindowBackgroundColor"
        super().__init__(master, width=width, height=self.H, bg=bg, highlightthickness=0)
        self.w, self.f, self.target, self.creep_to, self.since = width, 0.0, 0.0, 0.0, time.monotonic()
        self.x, self.dir = 0.0, 1
        self.bar_y = self.H - self.PATCH / 2 - 2
        y0, y1 = self.bar_y - self.BAR_H / 2, self.bar_y + self.BAR_H / 2
        self.create_rectangle(0, y0, width, y1, fill="#8e8e93", outline="", stipple="gray50")   # the track
        self.fill = self.create_rectangle(0, y0, 0, y1, fill="#0a84ff", outline="")
        # the plane: drawn (not the ✈ character) so it can turn round and face the way it flies
        self.plane = self.create_polygon(self.plane_points(0, 1), fill="#0a84ff", outline="")
        try:
            self.patch = tk.PhotoImage(file=LOGO).subsample(4) if LOGO else None
        except tk.TclError:
            self.patch = None
        self.pt = self.create_image(self.PATCH / 2, self.bar_y, image=self.patch) if self.patch else None
        self.after(self.TICK, self.tick)

    # an airliner seen from above, nose to the right, 24 px long, centred on (0, 0): the top half (the bottom mirrors it)
    PLANE = [(12, 0), (10.5, -1.6), (2.5, -1.6), (-3, -10), (-6, -10), (-2, -1.6), (-8, -1.6),
             (-10.5, -5.5), (-12.5, -5.5), (-11, -1.2), (-12, 0)]

    def plane_points(self, left, facing):
        """The plane's outline with its left end at `left`, facing right (1) or left (-1)."""
        cx, cy = left + 12, self.bar_y - self.BAR_H / 2 - 13
        half = self.PLANE + [(x, -y) for x, y in reversed(self.PLANE[1:-1])]
        return [v for x, y in half for v in (cx + facing * x, cy + y)]

    def set(self, fraction, creep_to=None):
        """Head for `fraction`; until the next set(), creep slowly towards `creep_to` (never quite reaching it)."""
        self.target = max(self.target, min(1.0, fraction))
        self.creep_to = max(self.target, creep_to or self.target)
        self.since = time.monotonic()

    def tick(self):
        if not self.winfo_exists():
            return
        t = time.monotonic() - self.since
        goal = self.target + (self.creep_to - self.target) * (1 - pow(2.718, -t / 25)) * 0.9
        self.f += max(0.0, goal - self.f) * 0.12
        edge = self.f * self.w
        self.coords(self.fill, 0, self.bar_y - self.BAR_H / 2, edge, self.bar_y + self.BAR_H / 2)
        if self.pt:
            self.coords(self.pt, min(max(edge, self.PATCH / 2), self.w - self.PATCH / 2), self.bar_y)
        room = edge - self.PATCH / 2 - 26
        if room <= 0:
            self.x, self.dir = 0.0, 1
        else:
            self.x += self.dir * self.SPEED
            if self.x >= room:
                self.x, self.dir = room, -1
            elif self.x <= 0:
                self.x, self.dir = 0.0, 1
        self.coords(self.plane, *self.plane_points(self.x, self.dir))
        self.itemconfig(self.plane, state="normal" if room > 0 else "hidden")
        if self.pt:
            self.tag_raise(self.pt)
        self.after(self.TICK, self.tick)


class Installer:
    def __init__(self, root):
        self.root = root
        root.withdraw()                                 # hidden until it's built and centred: no jump on opening
        root.title(f"{TITLE}  {VERSION}".strip() + ("  (dry run: nothing is changed)" if DRY else ""))
        root.geometry(f"{WIDTH}x420")
        self.events = queue.Queue()                     # from the worker threads, handled on the window's own thread
        self.working = False
        self.notes = []
        self.phones, self.autostart, self.desktop = (tk.BooleanVar(value=v) for v in self.answers())
        self.open_radar = tk.BooleanVar(value=True)

        style = ttk.Style()
        style.configure("Head.TLabel", font=("Helvetica", 18, "bold"))
        try:                                            # the Mac in dark mode? (the notes' grey must read on both)
            dark = bool(int(root.tk.call("tk::unsupported::MacWindowStyle", "isdark", root)))
        except (tk.TclError, ValueError):
            dark = False
        style.configure("Note.TLabel", foreground="#c8c8cd" if dark else "#3c3c43")
        style.configure("Err.TLabel", foreground="#ff453a", font=("Helvetica", 13, "bold"))
        top = ttk.Frame(root)                           # the heading, with the Project Moon Pi patch on the right
        top.pack(fill="x", padx=24, pady=(16, 6))
        self.head = ttk.Label(top, style="Head.TLabel")
        self.head.pack(side="left", anchor="s")
        try:
            if LOGO:
                self.logo = tk.PhotoImage(file=LOGO).subsample(2)
                ttk.Label(top, image=self.logo).pack(side="right")
            if ICON:
                root.iconphoto(True, tk.PhotoImage(file=ICON).subsample(4))   # the Dock
        except tk.TclError:                             # no picture: the window works without it
            pass
        self.body = ttk.Frame(root)
        self.body.pack(fill="both", expand=True, padx=24)
        self.msg = ttk.Label(root, style="Err.TLabel", wraplength=WRAP)
        self.msg.pack(anchor="w", padx=24, pady=(0, 6))
        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=24, pady=(0, 18))
        self.cancel_b = ttk.Button(bar, text="Cancel", command=self.cancel)
        self.cancel_b.pack(side="left")
        self.next_b = ttk.Button(bar, text="Next", default="active")
        self.next_b.pack(side="right")
        self.back_b = ttk.Button(bar, text="Back")
        self.back_b.pack(side="right", padx=6)
        root.bind("<Return>", lambda e: self.next_b.instate(["!disabled"]) and self.next_b.invoke())
        root.protocol("WM_DELETE_WINDOW", self.cancel)

        (self.p_confirm if UNINSTALL else self.p_welcome)()
        root.update_idletasks()                         # centred on the screen (a little above the middle)
        h = max(420, root.winfo_reqheight())
        x = (root.winfo_screenwidth() - WIDTH) // 2
        y = max(30, (root.winfo_screenheight() - h) // 3)
        root.geometry(f"{WIDTH}x{h}+{x}+{y}")
        root.deiconify()
        root.after(100, self.poll)
        root.lift(); root.attributes("-topmost", True)  # in front, as it opens
        root.after(400, lambda: root.attributes("-topmost", False))
        root.focus_force()

    @staticmethod
    def answers():
        """The tick boxes as the last install left them (settings.sh), else phones yes, at login no, Desktop yes."""
        got = {}
        try:
            got = dict(re.findall(r"^(\w+)=\"?([^\"\n]*)\"?$", open(os.path.join(APPDIR, "settings.sh")).read(), re.M))
        except OSError:
            pass
        return (got.get("PHONES", "yes") == "yes", got.get("AUTOSTART", "no") == "yes", got.get("DESKTOP", "yes") == "yes")

    # ---- plumbing
    def page(self, head, back=None, next_text="Next", next_cmd=None):
        self.head.config(text=head)
        for w in self.body.winfo_children():
            w.destroy()
        self.msg.config(text="")
        if not self.next_b.winfo_ismapped():            # (hidden while working)
            self.next_b.pack(side="right")
        self.back_b.config(state="normal" if back else "disabled", command=back or (lambda: None))
        self.next_b.config(text=next_text, state="normal", command=next_cmd or (lambda: None))
        if AUTO and next_cmd and next_text not in ("Finish", "Close"):
            here = head
            def go():
                if self.head.cget("text") != here:
                    return
                if self.next_b.instate(["!disabled"]):
                    self.next_b.invoke()
                else:
                    self.root.after(500, go)
            self.root.after(2500, go)

    def text(self, s, style=None, pady=(0, 10)):
        ttk.Label(self.body, text=s, wraplength=WRAP, justify="left", **({"style": style} if style else {})).pack(
            anchor="w", pady=pady)

    def fit(self):
        """Tall enough for this page: grows when a page needs more room, never shrinks (the buttons stay put)."""
        self.root.update_idletasks()
        need, have = self.root.winfo_reqheight(), self.root.winfo_height()
        if need > have:
            self.root.geometry(f"{WIDTH}x{need}")

    def poll(self):
        """Run what the worker threads sent (a window can only be changed from its own thread)."""
        try:
            while True:
                self.events.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def later(self, fn):
        self.events.put(fn)

    def cancel(self):
        if not self.working:                            # (while it's working, it finishes first)
            self.root.destroy()

    # ---- installing
    def p_welcome(self):
        self.page(TITLE, next_cmd=self.p_choices)
        self.text(f"SkyScope {VERSION}: a live aircraft radar in your web browser, styled after an ATC display. It "
                  "runs quietly in the background, with a radar icon in the menu bar, and phones, tablets and SkyScope "
                  "Satellite displays on your Wi-Fi can open it too.")
        ttk.Label(self.body, text="This Mac", font=("Helvetica", 14, "bold")).pack(anchor="w", pady=(6, 2))
        self.check_box = ttk.Frame(self.body)
        self.check_box.pack(anchor="w", fill="x")
        self.recheck_b = ttk.Button(self.body, text="Check again", command=self.run_checks)
        self.recheck_b.pack(anchor="w", pady=(6, 0))
        self.text(CREDIT, "Note.TLabel", pady=(14, 0))
        self.run_checks()

    def run_checks(self):
        """Each check on its own thread (one goes over the network), its row filled in as it finishes. Next stays
        off until nothing has failed."""
        self.next_b.config(state="disabled")
        self.recheck_b.config(state="disabled")
        self.msg.config(text="")
        for w in self.check_box.winfo_children():
            w.destroy()
        self.results, self.rows = {}, {}
        for name, fn in CHECKS:
            r = ttk.Frame(self.check_box)
            r.pack(anchor="w", fill="x", pady=1)
            mark = ttk.Label(r, text="…", width=2, font=("Helvetica", 14, "bold"))
            mark.pack(side="left", anchor="n")
            ttk.Label(r, text=name, width=11, font=("Helvetica", 12, "bold")).pack(side="left", anchor="n")
            info = ttk.Label(r, text="checking...", style="Note.TLabel", wraplength=WRAP - 140, justify="left")
            info.pack(side="left", anchor="n")
            self.rows[name] = (mark, info)
            threading.Thread(target=lambda n=name, f=fn: self.later(lambda res=self.safe(f): self.show_check(n, res)),
                             daemon=True).start()
        self.fit()

    @staticmethod
    def safe(fn):
        try:
            return fn()
        except Exception as e:                          # a check that breaks says so; it doesn't stop the window
            return "fail", f"couldn't check: {e}"

    def show_check(self, name, result):
        if name not in self.rows or not self.rows[name][0].winfo_exists():
            return
        state, text = result
        mark, info = self.rows[name]
        mark.config(text={"ok": "✓", "warn": "!", "fail": "✗"}[state],
                    foreground={"ok": "#30d158", "warn": "#ff9f0a", "fail": "#ff453a"}[state])
        info.config(text=text, style="Note.TLabel" if state == "ok" else "TLabel")
        self.results[name] = state
        if len(self.results) == len(CHECKS):
            self.recheck_b.config(state="normal")
            if "fail" in self.results.values():
                self.msg.config(text="Fix the ✗ above, then Check again.")
            else:
                self.next_b.config(state="normal")
        self.fit()

    def p_choices(self):
        self.page("Your choices", back=self.p_welcome, next_text="Install", next_cmd=self.install)
        for var, label, note in (
                (self.phones, "Phones, tablets and SkyScope Satellite displays on my Wi-Fi can open it",
                 "Otherwise only this Mac can. The settings page's About tab shows the address to use."),
                (self.autostart, "Start SkyScope by itself when I log in",
                 "Otherwise use Start SkyScope when you want it."),
                (self.desktop, "Put Start and Stop SkyScope on my Desktop",
                 "They're in Applications › SkyScope either way, with Uninstall SkyScope.")):
            ttk.Checkbutton(self.body, text="  " + label, variable=var).pack(anchor="w", pady=(8, 0))
            ttk.Label(self.body, text=note, style="Note.TLabel", wraplength=WRAP - 30).pack(anchor="w", padx=(28, 0))
        self.text("Installing takes about a minute. SkyScope starts when it's done.", pady=(16, 0))
        self.fit()

    def install(self):
        env = dict(os.environ, SS_PY=sys.executable, SS_PHONES="yes" if self.phones.get() else "no",
                   SS_AUTOSTART="yes" if self.autostart.get() else "no", SS_DESKTOP="yes" if self.desktop.get() else "no")
        self.work(f"Installing SkyScope {VERSION}", os.path.join(HERE, "install.sh"), env, INSTALL_STEPS, self.p_installed)

    def p_installed(self, ok, tail):
        if not ok:
            return self.p_failed("SkyScope wasn't installed", tail)
        was = f"updated from {INSTALLED} to {VERSION}" if INSTALLED and INSTALLED != VERSION else "installed"
        self.page(f"SkyScope is {was.split(' ')[0]}", next_text="Finish", next_cmd=self.finish)
        self.back_b.pack_forget()
        self.cancel_b.pack_forget()
        self.text(f"SkyScope {VERSION} is {was}, and running.")
        self.text("While it runs, its radar icon is in the menu bar at the top of the screen: click it for the radar, "
                  "the settings or Stop SkyScope. Start, Stop and Uninstall SkyScope are in Applications › SkyScope"
                  + (", and Start and Stop on your Desktop." if self.desktop.get() else "."))
        for n in self.notes:
            self.text(n, "TLabel")
        self.text("You can delete the downloaded installer now.", "Note.TLabel")
        ttk.Checkbutton(self.body, text="  Open the radar now", variable=self.open_radar).pack(anchor="w", pady=(8, 0))
        self.text(CREDIT, "Note.TLabel", pady=(16, 0))
        self.fit()

    def finish(self):
        if not UNINSTALL and self.open_radar.get():
            subprocess.run(["open", f"http://127.0.0.1:{self.port()}/radar"])
        self.root.destroy()

    def port(self):
        try:
            return int(re.search(r"^PORT=(\d+)", open(os.path.join(APPDIR, "settings.sh")).read(), re.M).group(1))
        except (OSError, AttributeError):
            return 7700

    # ---- uninstalling
    def p_confirm(self):
        self.page(TITLE, next_text="Uninstall", next_cmd=self.uninstall)
        self.text("Remove SkyScope from this Mac?")
        self.text("It stops SkyScope and removes the program, its settings (location, filters, FlightAware key), "
                  "Start, Stop and Uninstall SkyScope, and their Desktop icons. Python stays, for anything else that "
                  "uses it.")
        self.text("The first time, macOS may ask whether Uninstall SkyScope may access your Desktop folder: click Allow, "
                  "so it can remove the icons there.", "Note.TLabel")
        self.text(CREDIT, "Note.TLabel", pady=(14, 0))
        self.fit()

    def uninstall(self):
        env = dict(os.environ, SS_WINDOW="1")
        self.work("Removing SkyScope", os.path.join(HERE, "uninstall.sh"), env, UNINSTALL_STEPS, self.p_removed)

    def p_removed(self, ok, tail):
        if not ok:
            return self.p_failed("SkyScope wasn't fully removed", tail)
        self.page("SkyScope is removed", next_text="Close", next_cmd=self.root.destroy)
        self.back_b.pack_forget()
        self.cancel_b.pack_forget()
        self.text("SkyScope has been removed from this Mac. Python is still installed.")
        for n in self.notes:
            self.text(n, "TLabel")
        self.text(CREDIT, "Note.TLabel", pady=(16, 0))
        self.fit()

    # ---- the work, either way
    def work(self, head, script, env, steps, then):
        self.page(head)
        self.working = True
        self.cancel_b.config(state="disabled")          # from here on, nothing to click until it's done
        self.back_b.pack_forget()
        self.next_b.pack_forget()
        self.status = ttk.Label(self.body, text="Getting ready...", wraplength=WRAP)
        self.status.pack(anchor="w", pady=(4, 8))
        self.bar = MoonBar(self.body, WRAP)
        self.bar.pack(anchor="w", pady=4)
        self.bar.set(0.0, steps[0] / 100)
        self.details_b = ttk.Button(self.body, text="Show details", command=self.toggle_details)
        self.details_b.pack(anchor="w", pady=(10, 0))
        self.details = ttk.Frame(self.body)
        self.log = tk.Text(self.details, height=10, width=76, font=("Menlo", 9), relief="flat", bg="#1e1e1e",
                           fg="#9a9a9a", padx=8, pady=6, highlightthickness=0)   # a quiet console: small, grey
        sb = ttk.Scrollbar(self.details, command=self.log.yview)
        self.log.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        ttk.Label(self.body, text=f"Everything is also kept in the log: {LOG.replace(os.path.expanduser('~'), '~')}",
                  style="Note.TLabel", wraplength=WRAP).pack(anchor="w", side="bottom", pady=(6, 0))
        self.fit()
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')}  {TITLE} {VERSION} =====\n")
        threading.Thread(target=self.run, args=(script, env, steps, then), daemon=True).start()

    def toggle_details(self):
        if self.details.winfo_ismapped():
            self.details.pack_forget()
            self.details_b.config(text="Show details")
        else:
            self.details.pack(anchor="w", fill="both", pady=(6, 0), after=self.details_b)
            self.details_b.config(text="Hide details")
        self.fit()

    def run(self, script, env, steps, then):
        tail = []
        try:
            if DRY:                                     # pretend: each step, a moment apiece
                env = dict(env, SS_STEPS=" ".join(map(str, steps)))
                script = "-c"
                cmd = ["/bin/bash", "-c", 'for s in $SS_STEPS; do echo "@@ $s Pretending (dry run): step $s%..."; '
                       'echo "nothing is changed"; sleep 1.2; done']
            else:
                cmd = ["/bin/bash", script]
            p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, text=True, bufsize=1, cwd=os.path.expanduser("~"))
            with open(LOG, "a") as log:
                for line in p.stdout:
                    line = line.rstrip("\n")
                    log.write(line + "\n"); log.flush()
                    m = re.match(r"@@ (\d+) (.*)", line)
                    if m:
                        pct, what = int(m.group(1)), m.group(2)
                        nxt = next((s for s in steps if s > pct), 100)
                        self.later(lambda w=what, a=pct, b=nxt: (self.status.config(text=w), self.bar.set(a / 100, b / 100)))
                    elif line.startswith("@! "):
                        self.notes.append(line[3:])
                    else:
                        tail = (tail + [line])[-12:]
                        self.later(lambda t=line: (self.log.insert("end", t + "\n"), self.log.see("end")))
            ok = p.wait() == 0
        except Exception as e:
            tail, ok = tail + [str(e)], False
        self.later(lambda: self.done(ok, tail, then))

    def done(self, ok, tail, then):
        self.working = False
        self.cancel_b.config(state="normal")
        then(ok, tail)

    def p_failed(self, head, tail):
        self.page(head, next_text="Close", next_cmd=self.root.destroy)
        self.back_b.pack_forget()
        self.text("Something went wrong:" if tail else "Something went wrong.")
        if tail:
            box = tk.Text(self.body, height=8, width=76, font=("Menlo", 9), relief="flat", bg="#1e1e1e", fg="#d0d0d0",
                          padx=8, pady=6, highlightthickness=0)
            box.insert("end", "\n".join(tail))
            box.config(state="disabled")
            box.pack(anchor="w", fill="x", pady=(0, 10))
        self.text(f"The whole story is in {LOG.replace(os.path.expanduser('~'), '~')}. "
                  + ("Check the internet connection, then run the installer again." if not UNINSTALL else
                     "You can run Uninstall SkyScope again."))
        ttk.Button(self.body, text="Show the log", command=lambda: subprocess.run(["open", "-R", LOG])).pack(anchor="w")
        self.fit()


def main():
    root = tk.Tk()
    Installer(root)
    root.mainloop()


if __name__ == "__main__":
    main()

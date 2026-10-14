"""Alien theme: colors, fonts, ttk styles and a few custom widgets.
Pure Tkinter, no extra installs."""

from __future__ import annotations

import math
import random
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ---- palette -------------------------------------------------------------
BG = "#070b0c"          # deep space
SURFACE = "#0e1517"     # cards
SURFACE_2 = "#142023"   # inputs, table rows
BORDER = "#1f3237"
TEXT = "#eef3ea"
MUTED = "#8a9a92"
# Brand colors sampled from the AHE logos
ACCENT = "#52be29"      # alien green (head, beam)
ACCENT_HOVER = "#6ad83f"
ACCENT_DIM = "#3a8a1d"
ACCENT_TEXT = "#0a0d08"  # black, like the logo outlines
PURPLE = "#8f32c7"      # AHE lettering
PURPLE_HOVER = "#a54ddc"
SAUCER = "#7a3aa0"
BLUE = "#50ade5"        # saucer dome
VIOLET = BLUE           # one-shots use the dome blue
AMBER = "#ffcf5c"       # review
RED = "#ff6b7a"         # problems
CORAL = "#f0a0aa"       # name vs detection differ (soft: usually the detector)
ROW_ALT = "#0b1214"
SELECT = "#3a1f52"      # purple-tinted selection


def pick_fonts(root: tk.Misc) -> dict:
    fams = set(tkfont.families(root))

    def first(*names, default="TkDefaultFont"):
        for n in names:
            if n in fams:
                return n
        return default

    ui = first("Segoe UI", "Helvetica Neue", "DejaVu Sans", "Arial")
    ui_bold = first("Segoe UI Semibold", "Segoe UI", "DejaVu Sans", "Arial")
    mono = first("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New")
    title = first("Bahnschrift", "Impact", "Segoe UI Black", "DejaVu Sans", "Arial")
    return {
        "body": (ui, 10),
        "small": (ui, 9),
        "bold": (ui_bold, 10, "bold"),
        "button": (ui_bold, 10, "bold"),
        "big": (ui_bold, 20, "bold"),
        "title": (title, 26, "bold"),
        "tag": (ui_bold, 9, "bold"),
        "mono": (mono, 9),
    }


def apply(root: tk.Tk) -> dict:
    """Configure ttk styles. Returns the font table."""
    f = pick_fonts(root)
    root.configure(bg=BG)
    st = ttk.Style(root)
    st.theme_use("clam")

    st.configure(".", background=BG, foreground=TEXT, font=f["body"],
                 bordercolor=BORDER, lightcolor=BG, darkcolor=BG,
                 troughcolor=SURFACE_2, focuscolor=ACCENT,
                 selectbackground=SELECT, selectforeground=TEXT,
                 fieldbackground=SURFACE_2, insertcolor=ACCENT)
    st.configure("TFrame", background=BG)
    st.configure("Card.TFrame", background=SURFACE, relief="flat")
    st.configure("TLabel", background=BG, foreground=TEXT)
    st.configure("Card.TLabel", background=SURFACE)
    st.configure("Muted.TLabel", foreground=MUTED, font=f["small"])
    st.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED, font=f["small"])
    st.configure("Section.TLabel", background=SURFACE, foreground=PURPLE_HOVER, font=f["bold"])
    st.configure("Status.TLabel", foreground=MUTED, font=f["small"])

    # Buttons
    st.configure("TButton", background=SURFACE_2, foreground=TEXT, font=f["button"],
                 borderwidth=1, relief="flat", padding=(14, 8), bordercolor=BORDER,
                 lightcolor=SURFACE_2, darkcolor=SURFACE_2)
    st.map("TButton",
           background=[("disabled", SURFACE), ("pressed", BORDER), ("active", "#1b2c30")],
           foreground=[("disabled", "#4a5c57")],
           bordercolor=[("active", ACCENT_DIM)])
    st.configure("Accent.TButton", background=ACCENT, foreground=ACCENT_TEXT,
                 bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT, padding=(20, 10))
    st.map("Accent.TButton",
           background=[("disabled", "#1e3a22"), ("pressed", ACCENT_DIM), ("active", ACCENT_HOVER)],
           foreground=[("disabled", "#4f7a52")],
           bordercolor=[("disabled", "#1e3a22")],
           lightcolor=[("disabled", "#1e3a22")], darkcolor=[("disabled", "#1e3a22")])
    st.configure("Purple.TButton", background=PURPLE, foreground="#ffffff",
                 bordercolor=PURPLE, lightcolor=PURPLE, darkcolor=PURPLE, padding=(20, 10))
    st.map("Purple.TButton",
           background=[("disabled", "#2a1a36"), ("pressed", SAUCER), ("active", PURPLE_HOVER)],
           foreground=[("disabled", "#6c5880")],
           bordercolor=[("disabled", "#2a1a36")],
           lightcolor=[("disabled", "#2a1a36")], darkcolor=[("disabled", "#2a1a36")])
    st.configure("Ghost.TButton", background=BG, foreground=MUTED, bordercolor=BG,
                 lightcolor=BG, darkcolor=BG, padding=(10, 6))
    st.map("Ghost.TButton", background=[("active", SURFACE)], foreground=[("active", ACCENT)])
    st.configure("Card.TButton", background=SURFACE_2, padding=(12, 6))
    st.configure("Tab.TButton", background=BG, foreground=MUTED, bordercolor=BG,
                 lightcolor=BG, darkcolor=BG, padding=(16, 9))
    st.map("Tab.TButton", background=[("active", SURFACE)], foreground=[("active", TEXT)])
    st.configure("TabOn.TButton", background=SURFACE, foreground=ACCENT, bordercolor=SURFACE,
                 lightcolor=SURFACE, darkcolor=SURFACE, padding=(16, 9))
    st.map("TabOn.TButton", background=[("active", SURFACE)])
    # Two-way toggle (e.g. WAV / MP3) inside a card
    st.configure("Seg.TButton", background=SURFACE_2, foreground=MUTED, bordercolor=BORDER,
                 lightcolor=SURFACE_2, darkcolor=SURFACE_2, padding=(18, 6))
    st.map("Seg.TButton", background=[("active", BORDER)], foreground=[("active", TEXT)])
    st.configure("SegOn.TButton", background=ACCENT, foreground=ACCENT_TEXT, bordercolor=ACCENT,
                 lightcolor=ACCENT, darkcolor=ACCENT, padding=(18, 6))
    st.map("SegOn.TButton", background=[("active", ACCENT_HOVER)])

    # Inputs
    st.configure("TEntry", fieldbackground=SURFACE_2, foreground=TEXT, bordercolor=BORDER,
                 lightcolor=SURFACE_2, darkcolor=SURFACE_2, padding=(8, 6))
    st.map("TEntry", bordercolor=[("focus", ACCENT_DIM)], lightcolor=[("focus", ACCENT_DIM)])
    st.configure("TCombobox", fieldbackground=SURFACE_2, background=SURFACE_2, foreground=TEXT,
                 arrowcolor=ACCENT, bordercolor=BORDER, lightcolor=SURFACE_2,
                 darkcolor=SURFACE_2, padding=(8, 5))
    st.map("TCombobox", fieldbackground=[("readonly", SURFACE_2)],
           foreground=[("readonly", TEXT)], selectbackground=[("readonly", SURFACE_2)],
           selectforeground=[("readonly", TEXT)])
    root.option_add("*TCombobox*Listbox.background", SURFACE_2)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT)
    root.option_add("*TCombobox*Listbox.font", f["body"])
    st.configure("TCheckbutton", background=SURFACE, foreground=TEXT, focuscolor=SURFACE,
                 indicatorbackground=SURFACE_2, indicatorforeground=ACCENT_TEXT,
                 upperbordercolor=BORDER, lowerbordercolor=BORDER, indicatormargin=(0, 0, 8, 0))
    st.map("TCheckbutton",
           indicatorbackground=[("selected", ACCENT), ("active", BORDER)],
           indicatorforeground=[("selected", ACCENT_TEXT)],
           background=[("active", SURFACE)], foreground=[("active", ACCENT)])

    # Scrollbar
    st.configure("Vertical.TScrollbar", background=SURFACE_2, troughcolor=BG,
                 bordercolor=BG, arrowcolor=MUTED, lightcolor=SURFACE_2, darkcolor=SURFACE_2)
    st.map("Vertical.TScrollbar", background=[("active", BORDER)])

    # Table
    st.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
                 rowheight=28, bordercolor=SURFACE, lightcolor=SURFACE, darkcolor=SURFACE,
                 font=f["body"])
    st.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", TEXT)])
    st.configure("Treeview.Heading", background=BG, foreground=MUTED, font=f["small"],
                 relief="flat", bordercolor=BG, lightcolor=BG, darkcolor=BG, padding=(8, 6))
    st.map("Treeview.Heading", background=[("active", SURFACE)], foreground=[("active", PURPLE_HOVER)])
    st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # no border
    return f


ASSETS = Path(__file__).parent / "assets"


def load_image(name: str):
    """PNG from the assets folder, or None if it can't be loaded."""
    try:
        return tk.PhotoImage(file=str(ASSETS / name))
    except Exception:
        return None


class Header(tk.Canvas):
    """Starfield + the AHE spaceship. While busy, the ship bobs faster and
    its tractor beam glows and pulses with notes floating up."""

    # Beam position inside assets/ship.png (123x112): top edge, bottom edge
    BEAM_TOP = (55, 70, 44)
    BEAM_BOTTOM = (37, 84)

    def __init__(self, master, fonts: dict, height: int = 136):
        super().__init__(master, height=height, bg=BG, highlightthickness=0, bd=0)
        self.fonts = fonts
        self.h = height
        self.busy = False
        self.t = 0.0
        self.ship = load_image("ship.png")
        self._stars = [(random.random(), random.random(), random.choice((1, 1, 1, 2)),
                        random.random() * 6.28) for _ in range(80)]
        self.bind("<Configure>", lambda e: self._draw())
        self._tick()

    def set_busy(self, busy: bool):
        self.busy = busy

    def _tick(self):
        # Full animation only while working. Idle: stars twinkle about once
        # a second and the ship holds still, so an open, idle window uses
        # next to no CPU. Nothing is drawn while the window is minimized.
        if self.busy:
            self.t += 0.08
            self._draw()
            self.after(50, self._tick)
            return
        self.t += 0.9
        try:
            visible = self.winfo_viewable()
        except tk.TclError:
            return
        if visible:
            self._draw()
        self.after(1000, self._tick)

    def _draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 200), self.h
        for x, y, s, ph in self._stars:
            tw = 0.5 + 0.5 * math.sin(self.t + ph)
            c = _mix(BG, "#d8e8ff", 0.2 + 0.5 * tw)
            px, py = x * w, y * h
            if 150 < px < 700 and 20 < py < 125:  # keep the title area clean
                continue
            self.create_oval(px, py, px + s, py + s, fill=c, outline="")

        bob = math.sin(self.t * 1.6) * 4 if self.busy else 0.0
        sx, sy = 22, 14 + bob
        if self.busy:  # pulsing glow around the beam, notes rising
            pulse = 0.5 + 0.5 * math.sin(self.t * 3.2)
            l, r, ty = self.BEAM_TOP
            bl, br = self.BEAM_BOTTOM
            for grow, amt in ((16, 0.10 + 0.08 * pulse), (8, 0.18 + 0.12 * pulse)):
                self.create_polygon(sx + l - grow / 3, sy + ty, sx + r + grow / 3, sy + ty,
                                    sx + br + grow, h, sx + bl - grow, h,
                                    fill=_mix(BG, ACCENT, amt), outline="")
        if self.ship:
            self.create_image(sx, sy, image=self.ship, anchor="nw")
        else:  # fallback if the image is missing: simple saucer
            self.create_oval(sx + 10, sy + 30, sx + 110, sy + 52, fill=SAUCER, outline=PURPLE)
            self.create_oval(sx + 40, sy + 14, sx + 80, sy + 40, fill=BLUE, outline="")
        if self.busy:
            for i in range(3):
                ny = h - ((self.t * 22 + i * 24) % (h - 50))
                self.create_text(sx + (52, 68, 60)[i], ny, text="♪", fill="#0a0d08",
                                 font=(self.fonts["bold"][0], 11, "bold"))

        # Title: blocky white letters with a purple 3D shadow, like the AHE logo
        tx, ty = 162, 50
        title = "BEAT SORTER"
        for d in range(4, 0, -1):
            self.create_text(tx + d, ty + d, text=title, anchor="w",
                             fill=PURPLE if d > 1 else SAUCER, font=self.fonts["title"])
        self.create_text(tx, ty, text=title, anchor="w", fill="#ffffff", font=self.fonts["title"])

        # Slogan in alternating green/purple, like the spaceship logo
        x = tx + 2
        f = tkfont.Font(font=self.fonts["tag"])
        for i, word in enumerate(("TAKING", "OVER", "THE", "WORLD")):
            self.create_text(x, ty + 34, text=word, anchor="w", font=f,
                             fill=ACCENT if i % 2 == 0 else PURPLE_HOVER)
            x += f.measure(word + "  ")
        self.create_text(tx + 2, ty + 54, anchor="w", fill=MUTED, font=self.fonts["small"],
                         text="Sorts your beats into BPM + key folders. Originals never leave Earth.")


class Stat(tk.Frame):
    """Big number + label card."""

    def __init__(self, master, label: str, color: str, fonts: dict):
        super().__init__(master, bg=SURFACE, padx=14, pady=6,
                         highlightthickness=1, highlightbackground=BORDER)
        self.var = tk.StringVar(value="–")
        tk.Label(self, textvariable=self.var, bg=SURFACE, fg=color,
                 font=(fonts["big"][0], 15, "bold")).pack(side="left")
        tk.Label(self, text=label.upper(), bg=SURFACE, fg=MUTED,
                 font=fonts["small"]).pack(side="left", padx=(10, 0), pady=(3, 0))

    def set(self, value):
        self.var.set(str(value))


class Progress(tk.Canvas):
    """Thin neon progress line."""

    def __init__(self, master, height: int = 4):
        super().__init__(master, height=height, bg=SURFACE, highlightthickness=0, bd=0)
        self.frac = 0.0
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, done: float, total: float):
        self.frac = (done / total) if total else 0.0
        self._draw()

    def reset(self):
        self.set(0, 0)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), int(self["height"])
        if self.frac > 0:
            self.create_rectangle(0, 0, w * min(self.frac, 1.0), h, fill=ACCENT, outline="")


def card(master, padding=14) -> tk.Frame:
    return tk.Frame(master, bg=SURFACE, padx=padding, pady=padding,
                    highlightthickness=1, highlightbackground=BORDER)


def _mix(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return "#%02x%02x%02x" % (round(ar + (br - ar) * t), round(ag + (bg - ag) * t),
                              round(ab + (bb - ab) * t))


def tooltip(widget, text: str) -> None:
    """Small hover tooltip."""
    tip = {"w": None}

    def show(_e):
        if tip["w"] is not None:
            return
        w = tk.Toplevel(widget)
        w.wm_overrideredirect(True)
        w.configure(bg=BORDER)
        tk.Label(w, text=text, bg=SURFACE_2, fg=TEXT, padx=6, pady=2,
                 font=("TkDefaultFont", 8)).pack(padx=1, pady=1)
        w.geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 2}")
        tip["w"] = w

    def hide(_e):
        if tip["w"] is not None:
            tip["w"].destroy()
            tip["w"] = None

    widget.bind("<Enter>", show, add="+")
    widget.bind("<Leave>", hide, add="+")


class ScrollFrame(tk.Frame):
    """A frame whose contents scroll vertically (mouse wheel + a slim
    scrollbar that only appears when the contents don't fit).
    Put child widgets in .inner."""

    def __init__(self, master, bg: str = SURFACE, **kw):
        super().__init__(master, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda e: self._update())
        self.canvas.bind("<Configure>", lambda e: (
            self.canvas.itemconfigure(self._win, width=e.width), self._update()))
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", lambda e: self._bind_wheel(True))
            w.bind("<Leave>", lambda e: self._bind_wheel(False))

    def _update(self):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        fits = self.inner.winfo_reqheight() <= self.canvas.winfo_height()
        if fits:
            self.bar.pack_forget()
            self.canvas.yview_moveto(0)
        elif not self.bar.winfo_ismapped():
            self.bar.pack(side="right", fill="y", before=self.canvas)

    def _on_scroll(self, first, last):
        self.bar.set(first, last)

    def _bind_wheel(self, on: bool):
        if on:
            self.bind_all("<MouseWheel>", self._wheel)  # Windows / macOS
            self.bind_all("<Button-4>", lambda e: self._scroll(-1))  # Linux
            self.bind_all("<Button-5>", lambda e: self._scroll(1))
        else:
            self.unbind_all("<MouseWheel>")
            self.unbind_all("<Button-4>")
            self.unbind_all("<Button-5>")

    def _wheel(self, e):
        self._scroll(-1 if e.delta > 0 else 1)

    def _scroll(self, step: int):
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(step * 2, "units")

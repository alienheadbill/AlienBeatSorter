"""Small vector icon buttons, drawn on a canvas so they look crisp and
stay the same size (text glyphs like ▶ / ❚❚ render unevenly and make the
button jump when they change). Used for the transport controls."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from . import theme as T

DISABLED_FG = "#4a5c57"


class IconButton(tk.Canvas):
    def __init__(self, master, icon: str, command: Callable[[], None], size: int = 34,
                 primary: bool = False, tip: str = ""):
        super().__init__(master, width=size, height=size, bg=T.SURFACE,
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=0)
        self.icon = icon
        self.command = command
        self.size = size
        self.primary = primary
        self._enabled = True
        self._hover = False
        self._pressed = False
        self.bind("<Enter>", lambda e: self._set("_hover", True))
        self.bind("<Leave>", lambda e: self._set("_hover", False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self._draw()
        if tip:
            T.tooltip(self, tip)

    def set_icon(self, icon: str) -> None:
        if icon != self.icon:
            self.icon = icon
            self._draw()

    def set_enabled(self, on: bool) -> None:
        on = bool(on)
        if on != self._enabled:
            self._enabled = on
            self.configure(cursor="hand2" if on else "arrow")
            self._draw()

    def _set(self, attr: str, val: bool) -> None:
        setattr(self, attr, val)
        self._draw()

    def _press(self, e):
        if self._enabled:
            self._pressed = True
            self._draw()

    def _release(self, e):
        was = self._pressed
        self._pressed = False
        self._draw()
        if was and self._enabled and self.command and 0 <= e.x <= self.size and 0 <= e.y <= self.size:
            self.command()

    # ---- drawing ----
    def _round_rect(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.create_polygon(pts, smooth=True, **kw)

    def _draw(self):
        self.delete("all")
        s = self.size
        cx = cy = s / 2
        if self.primary:
            if not self._enabled:
                bg = "#1e3a22"
            elif self._pressed:
                bg = T.ACCENT_DIM
            elif self._hover:
                bg = T.ACCENT_HOVER
            else:
                bg = T.ACCENT
            r = s / 2 - 2
            self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=bg, outline="")
            fg = T.ACCENT_TEXT if self._enabled else "#4f7a52"
        else:
            if self._enabled and (self._hover or self._pressed):
                self._round_rect(2, 2, s - 2, s - 2, 9,
                                 fill=T.BORDER if self._pressed else T.SURFACE_2, outline="")
            fg = DISABLED_FG if not self._enabled else (T.ACCENT if self._hover else T.TEXT)
        self._shape(self.icon, cx, cy, s, fg)

    def _shape(self, icon: str, cx: float, cy: float, s: float, fg: str):
        def tri(pts):
            self.create_polygon(pts, fill=fg, outline=fg, joinstyle="round")

        if icon == "play":
            tri([cx - 0.16 * s, cy - 0.21 * s, cx - 0.16 * s, cy + 0.21 * s, cx + 0.22 * s, cy])
        elif icon == "pause":
            bw = 0.1 * s
            self.create_rectangle(cx - 0.16 * s, cy - 0.2 * s, cx - 0.16 * s + bw, cy + 0.2 * s,
                                  fill=fg, outline=fg)
            self.create_rectangle(cx + 0.06 * s, cy - 0.2 * s, cx + 0.06 * s + bw, cy + 0.2 * s,
                                  fill=fg, outline=fg)
        elif icon == "stop":
            self.create_rectangle(cx - 0.17 * s, cy - 0.17 * s, cx + 0.17 * s, cy + 0.17 * s,
                                  fill=fg, outline=fg)
        elif icon == "prev":
            tri([cx + 0.20 * s, cy - 0.16 * s, cx + 0.20 * s, cy + 0.16 * s, cx + 0.02 * s, cy])
            tri([cx + 0.02 * s, cy - 0.16 * s, cx + 0.02 * s, cy + 0.16 * s, cx - 0.16 * s, cy])
        elif icon == "next":
            tri([cx - 0.20 * s, cy - 0.16 * s, cx - 0.20 * s, cy + 0.16 * s, cx - 0.02 * s, cy])
            tri([cx - 0.02 * s, cy - 0.16 * s, cx - 0.02 * s, cy + 0.16 * s, cx + 0.16 * s, cy])

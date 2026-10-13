"""The player bar at the bottom of the window (same on every tab).

◀◀  ▶/❚❚  ■  ▶▶   beat name · BPM · key    [seek bar]  0:42 / 2:58   Loop  Autoplay  volume

* Play/Pause keeps your place; Stop unloads the beat.
* Click or drag the seek bar to jump.
* ◀◀ / ▶▶ play the previous / next beat in the list you're looking at.
* Loop repeats the beat; Autoplay moves on to the next beat when one ends.
* Keys: Space play/pause (in the beat lists), Esc stop,
  Ctrl+Left/Right jump 10 s, Ctrl+Up/Down next/previous beat.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as T


def mmss(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


class SeekBar(tk.Canvas):
    """A thin clickable/draggable progress bar."""

    def __init__(self, master, on_seek, height=14):
        super().__init__(master, height=height, bg=T.SURFACE, highlightthickness=0,
                         cursor="hand2")
        self.on_seek = on_seek
        self.frac = 0.0
        self.dragging = False
        self.enabled = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)

    def _frac_at(self, x: int) -> float:
        w = max(1, self.winfo_width() - 8)
        return max(0.0, min(1.0, (x - 4) / w))

    def _press(self, e):
        if self.enabled:
            self.dragging = True
            self.set(self._frac_at(e.x), force=True)

    def _drag(self, e):
        if self.dragging:
            self.set(self._frac_at(e.x), force=True)

    def _release(self, e):
        if self.dragging:
            self.dragging = False
            self.on_seek(self._frac_at(e.x))

    def set(self, frac: float, force: bool = False):
        if self.dragging and not force:
            return
        self.frac = max(0.0, min(1.0, frac))
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        y = h // 2
        self.create_line(4, y, w - 4, y, fill=T.BORDER, width=4, capstyle="round")
        if self.enabled:
            x = 4 + (w - 8) * self.frac
            self.create_line(4, y, x, y, fill=T.ACCENT, width=4, capstyle="round")
            self.create_oval(x - 5, y - 5, x + 5, y + 5, fill=T.ACCENT, outline="")


class TransportBar(tk.Frame):
    def __init__(self, app, master):
        super().__init__(master, bg=T.SURFACE, highlightthickness=1,
                         highlightbackground=T.BORDER, padx=10, pady=6)
        self.app = app
        p = app.player
        f = app.f

        btns = tk.Frame(self, bg=T.SURFACE)
        btns.pack(side="left")
        self.prev_btn = ttk.Button(btns, text="◀◀", width=4, style="Card.TButton",
                                   command=lambda: app._play_neighbor(-1))
        self.play_btn = ttk.Button(btns, text="▶", width=4, style="Accent.TButton",
                                   command=app._transport_play)
        self.stop_btn = ttk.Button(btns, text="■", width=4, style="Card.TButton",
                                   command=app._stop_play)
        self.next_btn = ttk.Button(btns, text="▶▶", width=4, style="Card.TButton",
                                   command=lambda: app._play_neighbor(1))
        for b in (self.prev_btn, self.play_btn, self.stop_btn, self.next_btn):
            b.pack(side="left", padx=(0, 4))
        T.tooltip(self.prev_btn, "Previous beat in the list (Ctrl+Up)")
        T.tooltip(self.play_btn, "Play / pause (Space in the list)")
        T.tooltip(self.stop_btn, "Stop (Esc)")
        T.tooltip(self.next_btn, "Next beat in the list (Ctrl+Down)")

        right = tk.Frame(self, bg=T.SURFACE)
        right.pack(side="right")
        self.loop_var = tk.BooleanVar(value=app.s.player_loop)
        self.auto_var = tk.BooleanVar(value=app.s.player_autoplay)
        ttk.Checkbutton(right, text="Loop", variable=self.loop_var,
                        command=self._set_loop).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(right, text="Autoplay", variable=self.auto_var,
                        command=self._set_auto).pack(side="left", padx=(0, 12))
        tk.Label(right, text="Vol", bg=T.SURFACE, fg=T.MUTED, font=f["small"]).pack(side="left")
        self.vol = SeekBar(right, self._set_volume)
        self.vol.configure(width=90)
        self.vol.enabled = True
        self.vol.on_seek = lambda frac: (self._set_volume(frac), self.app.s.save())
        self.vol.bind("<B1-Motion>", lambda e: (SeekBar._drag(self.vol, e),
                                                 self._set_volume(self.vol.frac)), add="")
        self.vol.pack(side="left", padx=(6, 0))
        self.vol.set(app.s.player_volume)
        p.set_volume(app.s.player_volume)
        p.loop = app.s.player_loop

        mid = tk.Frame(self, bg=T.SURFACE)
        mid.pack(side="left", fill="x", expand=True, padx=12)
        top = tk.Frame(mid, bg=T.SURFACE)
        top.pack(fill="x")
        self.title = tk.Label(top, text="Nothing playing", bg=T.SURFACE, fg=T.MUTED,
                              font=f["bold"], anchor="w")
        self.title.pack(side="left")
        self.time = tk.Label(top, text="", bg=T.SURFACE, fg=T.MUTED, font=f["small"])
        self.time.pack(side="right")
        self.seek = SeekBar(mid, self._seek)
        self.seek.pack(fill="x", pady=(2, 0))
        self._state = None
        self.update_state()

    # ---- controls ----
    def _seek(self, frac: float):
        p = self.app.player
        if p.duration:
            p.seek(frac * p.duration)
            self.update_state()

    def _set_volume(self, frac: float):
        self.app.player.set_volume(frac)
        self.app.s.player_volume = round(frac, 2)

    def _set_loop(self):
        self.app.player.loop = self.loop_var.get()
        self.app.s.player_loop = self.loop_var.get()
        self.app.s.save()

    def _set_auto(self):
        self.app.s.player_autoplay = self.auto_var.get()
        self.app.s.save()

    # ---- display ----
    def update_state(self) -> tuple:
        """Refresh the bar. Returns a small state tuple (path, playing,
        paused) so the app can tell when row markers need redrawing."""
        p = self.app.player
        loaded = p.path is not None
        if not loaded:
            self.title.configure(text="Nothing playing  ·  double-click a beat to play it",
                                 fg=T.MUTED)
            self.time.configure(text="")
            self.seek.enabled = False
            self.seek.set(0)
        else:
            info = self.app._now_playing_label(p.path)
            if p.loading():
                self.title.configure(text=f"Loading  {info}" + ("  (paused)" if p.paused else ""),
                                     fg=T.MUTED)
            else:
                state = "Paused  " if p.paused else ("Finished  " if p.ended else "")
                self.title.configure(text=f"{state}{info}",
                                     fg=T.AMBER if (p.paused or p.ended) else T.ACCENT)
            self.seek.enabled = not p.loading()
            pos, dur = p.position(), p.duration
            self.seek.set(pos / dur if dur else 0)
            self.time.configure(text=f"{mmss(pos)} / {mmss(dur)}" if dur else "")
        self.play_btn.configure(text="❚❚" if p.active() else "▶")
        for b in (self.stop_btn,):
            b.configure(state="normal" if loaded else "disabled")
        return (str(p.path) if loaded else None, p.is_playing(), p.paused)

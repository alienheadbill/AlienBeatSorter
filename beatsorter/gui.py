"""Beat Sorter window (Tkinter, ships with Python on Windows).

Layout and styling live here and in theme.py; all sorting logic lives in
the other modules and is unchanged by the look of the window.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from . import downloader, intake
from . import theme as T
from . import player as player_mod
from .builder import (NeedsCopy, PlanItem, UnsafePath, add_items, build, check_folders,
                      link_stem, plan, remove_tag_links, sync, tag_folder)
from .classifier import Decision, classify
from .config import Settings
from .folders import FolderStore
from .pipeline import Record, analyze_library, load_cached
from .report import accuracy, learn_bpm_range, suggest_bpm_range, write_csv
from .tags import TagStore
from .keys import PC_NAMES, Key, camelot, compatible
from . import updater
from .version import __version__


def _mmss(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"

COLUMNS = [
    ("play", "", 30, "center"),
    ("file", "FILE", 260, "w"),
    ("bpm", "BPM", 52, "e"),
    ("key", "KEY", 112, "w"),
    ("tags", "TAGS", 140, "w"),
    ("folder", "GOES TO", 170, "w"),
    ("flags", "NOTES", 180, "w"),
]
FILTERS = ["All files", "Sorted", "Needs review", "One-shots",
           "Name vs. detection differ", "Errors / not analyzed"]


class App(tk.Frame):
    def __init__(self, root: tk.Tk, fonts: dict):
        super().__init__(root, bg=T.BG)
        self.root = root
        self.f = fonts
        self.s = Settings.load()
        self.records: List[Record] = []
        self.decisions: List[Decision] = []
        self.q: "queue.Queue" = queue.Queue()
        self.cancel_evt = threading.Event()
        self.busy = False
        self.sort_col, self.sort_rev = "folder", False
        self._reclass_job = None
        self._settings_win: Optional[tk.Toplevel] = None
        # tags + preview player
        self.tags = TagStore()
        self.tag_map = self.tags.all()
        self.overrides = self.tags.overrides()  # your BPM/key fixes
        self.folders = FolderStore()  # My Folders
        self.current_tab = "library"
        self._sync_job = None
        self._sync_running = False
        self._sync_again = False
        self.player = player_mod.Player()
        # downloads
        self.dl_jobs: "queue.Queue" = queue.Queue()
        self.dl_cancel = threading.Event()
        self.dl_active = 0
        self._dl_thread: Optional[threading.Thread] = None

        # setting variables (edited in the Settings window)
        self.src_var = tk.StringVar(value=self.s.source)
        self.out_var = tk.StringVar(value=self.s.output)
        self.lo_var = tk.StringVar(value=f"{self.s.bpm_min:g}")
        self.hi_var = tk.StringVar(value=f"{self.s.bpm_max:g}")
        self.os_var = tk.StringVar(value=f"{self.s.oneshot_seconds:g}")
        self.bc_var = tk.StringVar(value=f"{self.s.bpm_conf_min:g}")
        self.kc_var = tk.StringVar(value=f"{self.s.key_conf_min:g}")
        self.detkey_var = tk.BooleanVar(value=self.s.use_detected_key)
        self.tagname_var = tk.BooleanVar(value=self.s.add_tags_to_names)
        self.bpmauto_var = tk.BooleanVar(value=self.s.bpm_auto)
        for v in (self.lo_var, self.hi_var, self.os_var, self.bc_var, self.kc_var, self.detkey_var):
            v.trace_add("write", lambda *a: self._schedule_reclassify())

        root.title("Beat Sorter")
        root.minsize(1000, 680)
        self.pack(fill="both", expand=True)
        self._build_ui()
        self.after(100, self._poll)
        self.after(200, self._tick_player)
        self.after(400, self._show_update_result)
        if "--smoke-test" not in sys.argv:
            self.after(2500, lambda: self._check_updates(quiet=True))
        self.after(300, self._startup_load)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(1000, self._mark_started)

    # ================= layout =================
    def _build_ui(self):
        self.header = T.Header(self, self.f)
        self.header.pack(fill="x")
        corner = tk.Frame(self, bg=T.BG)
        corner.place(relx=1.0, x=-20, y=20, anchor="ne")
        ttk.Button(corner, text="Report a problem", style="Ghost.TButton",
                   command=lambda: self._report()).pack(side="left", padx=(0, 6))
        ttk.Button(corner, text="⚙  Settings", style="Ghost.TButton",
                   command=self._open_settings).pack(side="left")

        body = tk.Frame(self, bg=T.BG, padx=20, pady=4)
        body.pack(fill="both", expand=True)

        # --- update banner (hidden until an update is found) ---
        self.upd_bar = tk.Frame(body, bg="#2a1640", highlightthickness=1,
                                highlightbackground=T.PURPLE, padx=14, pady=8)
        self.upd_text = tk.Label(self.upd_bar, bg="#2a1640", fg=T.TEXT, font=self.f["bold"],
                                 anchor="w", justify="left")
        self.upd_text.pack(side="left")
        x = tk.Label(self.upd_bar, text="✕", bg="#2a1640", fg=T.MUTED, cursor="hand2",
                     font=self.f["body"])
        x.pack(side="right", padx=(10, 0))
        x.bind("<Button-1>", lambda e: self.upd_bar.pack_forget())
        ttk.Button(self.upd_bar, text="Install & restart", style="Accent.TButton",
                   command=self._install_update).pack(side="right")
        ttk.Button(self.upd_bar, text="What's new", style="Card.TButton",
                   command=self._show_update_notes).pack(side="right", padx=(0, 8))
        self._upd_info = None

        # --- folders card ---
        fc = T.card(body)
        self.folders_card = fc
        fc.pack(fill="x")
        fc.columnconfigure(1, weight=1)
        for row, (label, var, cmd) in enumerate((("YOUR BEATS", self.src_var, self._pick_src),
                                                  ("SORTED FOLDER", self.out_var, self._pick_out))):
            ttk.Label(fc, text=label, style="CardMuted.TLabel", width=16).grid(
                row=row, column=0, sticky="w", pady=4)
            ttk.Entry(fc, textvariable=var).grid(row=row, column=1, sticky="ew", padx=10, pady=4)
            ttk.Button(fc, text="Browse", style="Card.TButton", command=cmd).grid(
                row=row, column=2, pady=4)

        # --- tabs ---
        tabbar = tk.Frame(body, bg=T.BG)
        tabbar.pack(fill="x", pady=(14, 0))
        self.tab_btns = {}
        for key, label in (("library", "Library"), ("sorted", "Sorted"),
                           ("download", "Download from YouTube")):
            b = ttk.Button(tabbar, text=label, style="Tab.TButton",
                           command=lambda k=key: self._show_tab(k))
            b.pack(side="left", padx=(0, 6))
            self.tab_btns[key] = b
        tk.Frame(body, bg=T.BORDER, height=1).pack(fill="x")
        self.tab_frames = {}
        lib = tk.Frame(body, bg=T.BG)
        self.tab_frames["library"] = lib

        # --- actions ---
        act = tk.Frame(lib, bg=T.BG, pady=10)
        act.pack(fill="x")
        self.analyze_btn = ttk.Button(act, text="Scan beats", style="Accent.TButton",
                                      command=self._analyze)
        self.analyze_btn.pack(side="left")
        self.build_btn = ttk.Button(act, text="Build sorted folder", command=self._build,
                                    state="disabled")
        self.build_btn.pack(side="left", padx=10)
        self.cancel_btn = ttk.Button(act, text="Cancel", style="Ghost.TButton",
                                     command=self._cancel)
        self.more_btn = ttk.Button(act, text="More  ▾", style="Ghost.TButton",
                                   command=self._show_more)
        self.more_btn.pack(side="right")
        self.more_menu = tk.Menu(self, tearoff=0, bg=T.SURFACE, fg=T.TEXT, bd=0,
                                 activebackground=T.SELECT, activeforeground=T.ACCENT,
                                 font=self.f["body"])
        self.more_menu.add_command(label="Suggest BPM range from my tagged files",
                                   command=self._suggest_range)
        self.more_menu.add_command(label="Accuracy report", command=self._accuracy)
        self.more_menu.add_command(label="Export results to CSV", command=self._export)
        self.more_menu.add_command(label="Find duplicates…", command=self._find_duplicates)
        self.more_menu.add_separator()
        self.more_menu.add_command(label="Sync tags to FL Studio…", command=self._fl_sync_dialog)
        self.more_menu.add_command(label="Undo last FL sync", command=self._fl_undo)
        self.more_menu.add_separator()
        self.more_menu.add_command(label=f"Check for updates  (you have v{__version__})",
                                   command=lambda: self._check_updates(quiet=False))
        self.more_menu.add_command(label="Undo last update", command=self._rollback)
        self.more_menu.add_separator()
        self.more_menu.add_command(label="Report a problem or send an idea…",
                                   command=lambda: self._report())

        # --- progress + status ---
        self.pbar = T.Progress(lib)
        self.pbar.pack(fill="x")
        self.status = tk.StringVar(value="Pick your beats folder, then hit Scan.")
        ttk.Label(lib, textvariable=self.status, style="Status.TLabel").pack(anchor="w", pady=(4, 8))

        # --- stats ---
        stats = tk.Frame(lib, bg=T.BG)
        stats.pack(fill="x", pady=(0, 10))
        self.stats = {}
        for i, (key, label, color) in enumerate((
                ("files", "Files", T.TEXT), ("sorted", "Sorted", T.ACCENT),
                ("review", "Need review", T.AMBER), ("oneshots", "One-shots", T.VIOLET),
                ("differ", "Name ≠ detection", T.CORAL))):
            stats.columnconfigure(i, weight=1, uniform="stat")
            st = T.Stat(stats, label, color, self.f)
            st.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 10, 0))
            self.stats[key] = st

        ttk.Label(lib, style="Muted.TLabel",
                  text="Double-click or Space to play · drag beats into FL Studio · right-click to "
                       "tag · your originals are only read, never moved or renamed").pack(
            side="bottom", anchor="w", pady=(0, 10))

        main = tk.Frame(lib, bg=T.BG)
        main.pack(fill="both", expand=True)

        # --- sidebar: filters ---
        side_card = tk.Frame(main, bg=T.SURFACE, highlightthickness=1,
                             highlightbackground=T.BORDER, width=240)
        side_card.pack(side="left", fill="y", padx=(0, 12), pady=(0, 6))
        side_card.pack_propagate(False)
        scroller = T.ScrollFrame(side_card)
        scroller.pack(fill="both", expand=True, padx=(12, 2), pady=12)
        side = scroller.inner

        def section(text):
            ttk.Label(side, text=text, style="CardMuted.TLabel").pack(anchor="w", pady=(10, 4))

        top_row = tk.Frame(side, bg=T.SURFACE)
        top_row.pack(fill="x")
        ttk.Label(top_row, text="SEARCH", style="CardMuted.TLabel").pack(side="left")
        clr = tk.Label(top_row, text="Clear filters", bg=T.SURFACE, fg=T.PURPLE_HOVER,
                       font=self.f["small"], cursor="hand2")
        clr.pack(side="right")
        clr.bind("<Button-1>", lambda e: self._clear_filters())
        tk.Frame(side, bg=T.SURFACE, height=4).pack()
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._refresh_table())
        ttk.Entry(side, textvariable=self.search_var).pack(fill="x")

        section("SHOW")
        self.filter_var = tk.StringVar(value=FILTERS[0])
        cb = ttk.Combobox(side, textvariable=self.filter_var, values=FILTERS, state="readonly")
        cb.pack(fill="x")
        cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_table())

        section("BPM")
        bpm_row = tk.Frame(side, bg=T.SURFACE)
        bpm_row.pack(fill="x")
        self.f_lo_var, self.f_hi_var = tk.StringVar(), tk.StringVar()
        ttk.Entry(bpm_row, textvariable=self.f_lo_var, width=6).pack(side="left")
        ttk.Label(bpm_row, text="  to  ", style="CardMuted.TLabel").pack(side="left")
        ttk.Entry(bpm_row, textvariable=self.f_hi_var, width=6).pack(side="left")
        for v in (self.f_lo_var, self.f_hi_var):
            v.trace_add("write", lambda *a: self._refresh_table())

        section("KEY")
        self.key_chips_frame = tk.Frame(side, bg=T.SURFACE)
        self.key_chips_frame.pack(fill="x")
        section("ONE-SHOT TYPE")
        self.type_chips_frame = tk.Frame(side, bg=T.SURFACE)
        self.type_chips_frame.pack(fill="x")
        section("TAGS")
        self.tag_chips_frame = tk.Frame(side, bg=T.SURFACE)
        self.tag_chips_frame.pack(fill="x")

        self.key_filter: set = set()
        self.tag_filter: set = set()
        self.compat_on = False  # also show compatible keys (Camelot wheel)
        self.type_filter: set = set()  # one-shot types: Kicks, 808s, ...

        # --- right: toolbar, table, now playing ---
        right = tk.Frame(main, bg=T.BG)
        right.pack(side="left", fill="both", expand=True)

        tb = tk.Frame(right, bg=T.BG)
        tb.pack(fill="x", pady=(0, 8))
        self.play_btn = ttk.Button(tb, text="▶  Play", style="Card.TButton", command=self._toggle_play)
        self.play_btn.pack(side="left")
        self.tag_btn = ttk.Button(tb, text="+ Tag", style="Card.TButton",
                                  command=lambda: self._popup_tag_menu(self.tag_btn))
        self.tag_btn.pack(side="left", padx=(8, 0))
        self.untag_btn = ttk.Button(tb, text="− Untag", style="Card.TButton",
                                    command=lambda: self._popup_untag_menu(self.untag_btn))
        self.untag_btn.pack(side="left", padx=(8, 0))
        self.fix_btn = ttk.Button(tb, text="✎  Fix", style="Card.TButton",
                                  command=self._fix_dialog)
        self.fix_btn.pack(side="left", padx=(8, 0))
        self.count_lbl = ttk.Label(tb, text="", style="Muted.TLabel")
        self.count_lbl.pack(side="right")

        tf = tk.Frame(right, bg=T.SURFACE, highlightthickness=1, highlightbackground=T.BORDER)
        tf.pack(fill="both", expand=True, pady=(0, 6))
        self.table_frame = tf
        tf.columnconfigure(0, weight=1)
        tf.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(tf, columns=[c[0] for c in COLUMNS], show="headings",
                                 selectmode="extended")
        for key, title, width, anchor in COLUMNS:
            self.tree.heading(key, text=title, anchor=anchor, command=lambda k=key: self._sort_by(k))
            self.tree.column(key, width=width, anchor=anchor, minwidth=30,
                             stretch=key in ("file", "folder", "flags"))
        ys = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("alt", background=T.ROW_ALT)
        self.tree.tag_configure("review", foreground=T.AMBER)
        self.tree.tag_configure("flag", foreground=T.CORAL)
        self.tree.tag_configure("error", foreground="#ff8f9a")
        self.tree.tag_configure("oneshot", foreground=T.VIOLET)
        self.tree.tag_configure("playing", foreground=T.ACCENT)
        self.tree.bind("<Double-1>", lambda e: self._toggle_play(force_play=True))
        self.tree.bind("<space>", lambda e: (self._toggle_play(), "break")[1])
        self.tree.bind("<Return>", lambda e: self._toggle_play(force_play=True))
        self.tree.bind("<Button-3>", self._row_menu)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_toolbar())
        self._setup_drag()
        self._ghost = T.load_image("head_ghost.png")
        self.empty = tk.Label(tf, bg=T.SURFACE, fg=T.MUTED, font=self.f["body"], justify="center",
                              image=self._ghost, compound="top", pady=8,
                              text="No signals yet.\nChoose your beats folder and hit Scan.")
        self.empty.place(relx=0.5, rely=0.56, anchor="center")
        self._update_toolbar()

        srt = tk.Frame(body, bg=T.BG)
        self.tab_frames["sorted"] = srt
        from .gui_sorted import SortedTab
        self.sorted_tab = SortedTab(self, srt)

        dl = tk.Frame(body, bg=T.BG)
        self.tab_frames["download"] = dl
        self._build_download_tab(dl)

        from .gui_player import TransportBar
        self.transport = TransportBar(self, body)
        self.transport.pack(side="bottom", fill="x", pady=(4, 8))
        self._player_state = None
        root = self.root
        root.bind("<Escape>", lambda e: self._stop_play() if self.player.path else None)
        def keys(fn):  # player shortcuts, except while typing in a text box
            return lambda e: None if isinstance(e.widget, (tk.Entry, ttk.Entry)) else fn()
        root.bind("<Control-Left>", keys(lambda: self._seek_by(-10)))
        root.bind("<Control-Right>", keys(lambda: self._seek_by(10)))
        root.bind("<Control-Up>", keys(lambda: self._play_neighbor(-1)))
        root.bind("<Control-Down>", keys(lambda: self._play_neighbor(1)))
        self._show_tab("library")

    # ================= tabs =================
    def _show_tab(self, key: str):
        for k, fr in self.tab_frames.items():
            fr.pack_forget()
            self.tab_btns[k].configure(style="TabOn.TButton" if k == key else "Tab.TButton")
        self.tab_frames[key].pack(fill="both", expand=True)
        self.current_tab = key
        if key == "download":
            self._update_dl_hint()
        elif key == "sorted":
            self.sorted_tab.refresh()
        else:
            self._update_toolbar()

    # ================= download tab =================
    DL_COLUMNS = [
        ("title", "TITLE", 330, "w"),
        ("status", "STATUS", 170, "w"),
        ("bpm", "BPM", 60, "e"),
        ("key", "KEY", 100, "w"),
        ("src", "FROM", 120, "w"),
        ("sorted", "SORTED INTO", 230, "w"),
    ]

    def _build_download_tab(self, dl: tk.Frame):
        top = T.card(dl)
        top.pack(fill="x", pady=(14, 0))
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text="PASTE YOUTUBE LINKS  ·  one per line  ·  playlists welcome",
                  style="CardMuted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.url_box = tk.Text(top, height=4, bg=T.SURFACE_2, fg=T.TEXT, insertbackground=T.ACCENT,
                               relief="flat", font=self.f["body"], wrap="none", padx=10, pady=8,
                               highlightthickness=1, highlightbackground=T.BORDER,
                               highlightcolor=T.ACCENT_DIM, selectbackground=T.SELECT)
        self.url_box.grid(row=1, column=0, sticky="ew")
        btns = tk.Frame(top, bg=T.SURFACE)
        btns.grid(row=1, column=1, sticky="n", padx=(12, 0))
        self.dl_btn = ttk.Button(btns, text="Beam it down", style="Accent.TButton",
                                 command=self._start_downloads)
        self.dl_btn.pack(fill="x")
        self.dl_stop_btn = ttk.Button(btns, text="Stop", style="Card.TButton",
                                      command=self._stop_downloads, state="disabled")
        self.dl_stop_btn.pack(fill="x", pady=(8, 0))

        fmt_row = tk.Frame(top, bg=T.SURFACE)
        fmt_row.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(fmt_row, text="SAVE AS", style="CardMuted.TLabel").pack(side="left", padx=(0, 10))
        self.fmt_btns = {}
        for key, label in (("wav", "WAV"), ("mp3", "MP3")):
            b = ttk.Button(fmt_row, text=label, style="Seg.TButton",
                           command=lambda k=key: self._set_format(k))
            b.pack(side="left", padx=(0, 2))
            self.fmt_btns[key] = b
        self.fmt_note = ttk.Label(fmt_row, style="CardMuted.TLabel")
        self.fmt_note.pack(side="left", padx=(12, 0))
        self._set_format(self.s.download_format, save=False)

        info = tk.Frame(dl, bg=T.BG)
        info.pack(fill="x", pady=(10, 10))
        self.dl_hint = tk.StringVar()
        ttk.Label(info, textvariable=self.dl_hint, style="Status.TLabel").pack(side="left")
        ttk.Button(info, text="Update downloader", style="Ghost.TButton",
                   command=self._update_downloader).pack(side="right")
        self.src_var.trace_add("write", lambda *a: self._update_dl_hint())
        self.out_var.trace_add("write", lambda *a: self._update_dl_hint())

        ttk.Label(dl, style="Muted.TLabel",
                  text="For your own uploads, or beats whose producers allow downloads. "
                       "YouTube's terms generally don't allow downloading, and most \"free\" "
                       "type beats are free for non-profit use only.").pack(
            side="bottom", anchor="w", pady=(0, 10))

        tf = tk.Frame(dl, bg=T.SURFACE, highlightthickness=1, highlightbackground=T.BORDER)
        tf.pack(fill="both", expand=True, pady=(0, 6))
        tf.columnconfigure(0, weight=1)
        tf.rowconfigure(0, weight=1)
        self.dl_tree = ttk.Treeview(tf, columns=[c[0] for c in self.DL_COLUMNS], show="headings")
        for key, title, width, anchor in self.DL_COLUMNS:
            self.dl_tree.heading(key, text=title, anchor=anchor)
            self.dl_tree.column(key, width=width, anchor=anchor, stretch=key in ("title", "sorted"))
        ys = ttk.Scrollbar(tf, orient="vertical", command=self.dl_tree.yview)
        self.dl_tree.configure(yscrollcommand=ys.set)
        self.dl_tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        self.dl_tree.tag_configure("done", foreground=T.ACCENT)
        self.dl_tree.tag_configure("fail", foreground=T.CORAL)
        self.dl_tree.tag_configure("work", foreground=T.BLUE)
        self.dl_tree.tag_configure("muted", foreground=T.MUTED)
        self.dl_tree.bind("<Double-1>", self._open_download_location)
        self._dl_ghost = T.load_image("ship_ghost.png")
        self.dl_empty = tk.Label(tf, bg=T.SURFACE, fg=T.MUTED, font=self.f["body"], justify="center",
                                 image=self._dl_ghost, compound="top", pady=8,
                                 text="Paste a link above and hit Beam it down.\n"
                                      "Each beat is saved, read for BPM + key, and dropped "
                                      "straight into your Sorted folder.")
        self.dl_empty.place(relx=0.5, rely=0.55, anchor="center")

    FORMAT_NOTES = {
        "wav": "Full quality, works everywhere · about 30 MB per beat",
        "mp3": "320 kbps · about 6 MB per beat · smaller, slightly lossier",
    }

    def _set_format(self, fmt: str, save: bool = True):
        if fmt not in self.FORMAT_NOTES:
            fmt = "wav"
        self.s.download_format = fmt
        for k, b in self.fmt_btns.items():
            b.configure(style="SegOn.TButton" if k == fmt else "Seg.TButton")
        self.fmt_note.configure(text=self.FORMAT_NOTES[fmt])
        if save:
            self.s.save()
        if hasattr(self, "dl_hint"):  # not built yet during startup
            self._update_dl_hint()

    def _update_dl_hint(self):
        src = self.src_var.get().strip()
        if not src:
            self.dl_hint.set("Pick your beats folder above first. Downloads are saved inside it.")
            return
        then = ("then sorts them into your Sorted folder" if self.out_var.get().strip()
                else "pick a Sorted folder above to sort them automatically")
        fmt = self.s.download_format.upper()
        self.dl_hint.set(f"Saves {fmt} files to \"{intake.DOWNLOAD_FOLDER}\" in your beats folder, "
                         f"{then}  ·  downloader {downloader.downloader_version()}")

    def _dl_set(self, row: str, **vals):
        if not self.dl_tree.exists(row):
            return
        cur = dict(zip([c[0] for c in self.DL_COLUMNS], self.dl_tree.item(row, "values")))
        tag = vals.pop("tag", None)
        cur.update({k: v for k, v in vals.items()})
        self.dl_tree.item(row, values=[cur.get(c[0], "") for c in self.DL_COLUMNS])
        if tag is not None:
            self.dl_tree.item(row, tags=(tag,) if tag else ())

    def _dl_add_row(self, title: str, status: str, tag: str = "muted") -> str:
        self.dl_empty.place_forget()
        return self.dl_tree.insert("", "end", values=(title, status, "", "", "", ""), tags=(tag,))

    def _start_downloads(self):
        ok, why = downloader.available()
        if not ok:
            messagebox.showerror("Beat Sorter", why)
            return
        s = self._read_settings()
        if s is None or not s.source or not Path(s.source).is_dir():
            messagebox.showerror("Beat Sorter", "Pick your beats folder first. Downloads are saved inside it.")
            return
        s.save()
        urls = [u.strip() for u in self.url_box.get("1.0", "end").split() if u.strip()]
        urls = [u for u in urls if u.lower().startswith(("http://", "https://", "www.", "youtu"))]
        if not urls:
            messagebox.showinfo("Beat Sorter", "Paste one or more YouTube links first.")
            return
        self.url_box.delete("1.0", "end")
        for u in urls:
            if not u.lower().startswith("http"):
                u = "https://" + u
            row = self._dl_add_row(u, "Looking up…")
            threading.Thread(target=self._probe_worker, args=(row, u), daemon=True).start()

    def _probe_worker(self, row: str, url: str):
        try:
            self.q.put(("dl_probe", row, downloader.probe(url), None))
        except Exception as e:
            msg = downloader._friendly_error(str(e))
            self.q.put(("dl_probe", row, None, msg))

    def _on_probe(self, row: str, pr, err: Optional[str]):
        if err:
            self._dl_set(row, status="Failed", sorted=err, tag="fail")
            return
        if pr.is_playlist:
            n = len(pr.entries)
            if n == 0:
                self._dl_set(row, title=pr.title, status="Empty playlist", tag="fail")
                return
            ans = messagebox.askyesnocancel(
                "Playlist",
                f"\"{pr.title}\" is a playlist with {n} videos.\n\n"
                f"Yes: download all {n}\n"
                + ("No: download just the video in the link\n" if pr.has_single_video else "")
                + "Cancel: skip it")
            if ans is None or (ans is False and not pr.has_single_video):
                self._dl_set(row, title=pr.title, status="Skipped", tag="muted")
                return
            if ans:
                self.dl_tree.delete(row)
                for url, title in pr.entries:
                    r = self._dl_add_row(title, "Waiting")
                    self._enqueue(r, url, "")
                return
            self._dl_set(row, title="(video from playlist link)", status="Waiting")
            self._enqueue(row, pr.url, "")
            return
        self._dl_set(row, title=pr.title, status="Waiting")
        self._enqueue(row, pr.url, pr.video_id)

    def _enqueue(self, row: str, url: str, video_id: str):
        self.dl_active += 1
        self.dl_stop_btn.configure(state="normal")
        self.dl_jobs.put((row, url, video_id))
        if not self._dl_thread or not self._dl_thread.is_alive():
            self._dl_thread = threading.Thread(target=self._dl_worker, daemon=True)
            self._dl_thread.start()

    def _dl_worker(self):
        """Downloads one at a time, in order."""
        while True:
            try:
                row, url, vid = self.dl_jobs.get(timeout=1.0)
            except queue.Empty:
                return
            if self.dl_cancel.is_set():
                self.q.put(("dl_done", row, None, "Stopped"))
                continue
            s = self._read_settings_threadsafe()
            last = [0.0]

            def prog(stage, frac, row=row):
                import time
                now = time.monotonic()
                if stage == "Downloading" and now - last[0] < 0.25 and frac < 1:
                    return
                last[0] = now
                label = f"Downloading {frac:.0%}" if stage == "Downloading" else stage + "…"
                self.q.put(("dl_status", row, label))

            try:
                res = intake.process(url, s, progress=prog, cancel=self.dl_cancel, video_id=vid)
                self.q.put(("dl_done", row, res, None))
            except downloader.Cancelled:
                self.q.put(("dl_done", row, None, "Stopped"))
            except Exception as e:
                self.q.put(("dl_done", row, None, str(e)))

    def _read_settings_threadsafe(self) -> Settings:
        # Settings object is plain data; copy the current values.
        from dataclasses import replace
        return replace(self.s)

    def _on_dl_done(self, row: str, res, err: Optional[str]):
        self.dl_active = max(0, self.dl_active - 1)
        if self.dl_active == 0:
            self.dl_stop_btn.configure(state="disabled")
            self.dl_cancel.clear()
        if err:
            self._dl_set(row, status="Stopped" if err == "Stopped" else "Failed",
                         sorted="" if err == "Stopped" else err,
                         tag="muted" if err == "Stopped" else "fail")
            return
        d = res.decision
        if res.sorted_to is not None and self.s.output:
            where = str(res.sorted_to.parent.relative_to(Path(self.s.output))).replace("\\", "/")
            status, tag = "Sorted ✓", "done"
        else:
            where, status, tag = res.note, ("Already have it" if "Already" in res.note else "Saved"), "muted"
        self._dl_set(row, title=res.title, status=status, bpm=f"{d.bpm:g}" if d.bpm else "",
                     key=d.key_label, src=self._source_label(d), sorted=where, tag=tag)
        self._dl_paths = getattr(self, "_dl_paths", {})
        self._dl_paths[row] = res.record.path
        # Add to the library view if a scan has been done (a partial list
        # must never be used for a full rebuild).
        if self.records and not any(r.path == res.record.path for r in self.records):
            self.records.append(res.record)
            self._reclassify()

    def _stop_downloads(self):
        self.dl_cancel.set()
        while True:
            try:
                row, _, _ = self.dl_jobs.get_nowait()
                self.q.put(("dl_done", row, None, "Stopped"))
            except queue.Empty:
                break

    def _open_download_location(self, _event):
        sel = self.dl_tree.selection()
        p = getattr(self, "_dl_paths", {}).get(sel[0]) if sel else None
        if p and sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(p)])

    def _update_downloader(self):
        if not messagebox.askyesno("Update downloader",
                                   "Download the latest version of the YouTube downloader?\n\n"
                                   "Do this when downloads start failing; YouTube changes often."):
            return
        self.dl_hint.set("Updating downloader…")

        def work():
            ok, msg = downloader.update_downloader()
            self.q.put(("dl_updated", ok, msg))

        threading.Thread(target=work, daemon=True).start()

    # ================= self-update =================
    def _check_updates(self, quiet: bool):
        repo, _ = updater.config()
        if not repo:
            if not quiet:
                messagebox.showinfo("Beat Sorter", "Automatic updates aren't set up yet "
                                    "(no GitHub repository in update.json).")
            return

        def work():
            try:
                self.q.put(("upd_checked", updater.check(), None, quiet))
            except Exception as e:
                self.q.put(("upd_checked", None, str(e), quiet))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_checked(self, info, err, quiet):
        if err:
            if not quiet:
                messagebox.showerror("Beat Sorter", f"Couldn't check for updates:\n{err}")
            return
        if info is None:
            if not quiet:
                messagebox.showinfo("Beat Sorter", f"You're up to date (v{__version__}).")
            return
        self._upd_info = info
        first = next((ln.strip("-• ").strip() for ln in info.notes.splitlines() if ln.strip()), "")
        self.upd_text.configure(text=f"Update available: v{info.version}"
                                     + (f"  ·  {first}" if first else ""))
        self.upd_bar.pack(fill="x", pady=(0, 10), before=self.folders_card)
        if not quiet:
            self._show_update_notes()

    def _show_update_notes(self):
        info = self._upd_info
        if not info:
            return
        if messagebox.askyesno(f"What's new in v{info.version}",
                               (info.notes or "Improvements and fixes.")
                               + f"\n\nYou have v{__version__}. Install now? Beat Sorter will "
                                 "restart. Your beats, tags and settings aren't touched."):
            self._install_update(confirmed=True)

    def _install_update(self, confirmed: bool = False):
        info = self._upd_info
        if not info:
            return
        if (self.busy or self.dl_active) and not messagebox.askyesno(
                "Beat Sorter", "A scan or download is still running. Stop it and update now?"):
            return
        if not confirmed and not messagebox.askyesno(
                "Install update", f"Install v{info.version} and restart Beat Sorter?"):
            return
        self.upd_text.configure(text=f"Downloading v{info.version}…")
        self.cancel_evt.set()
        self.dl_cancel.set()

        def work():
            try:
                self.q.put(("upd_staged", updater.stage(info), None))
            except Exception as e:
                self.q.put(("upd_staged", None, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_staged(self, path, err):
        if err:
            self.upd_text.configure(text="Update failed to download.")
            messagebox.showerror("Beat Sorter", f"Couldn't download the update:\n{err}")
            return
        try:
            updater.install(path)
        except Exception as e:
            messagebox.showerror("Beat Sorter", f"Couldn't start the update:\n{e}")
            return
        self._quit_for_update()

    def _rollback(self):
        lb = updater.latest_backup()
        if not lb:
            messagebox.showinfo("Beat Sorter", "There's no previous version to go back to yet.")
            return
        if not messagebox.askyesno("Undo last update",
                                   f"Go back to v{lb[0]}? (You have v{__version__}.) "
                                   "Beat Sorter will restart."):
            return
        updater.rollback()
        self._quit_for_update()

    def _quit_for_update(self):
        self.cancel_evt.set()
        try:
            self.player.stop()
            from . import essentiakey
            essentiakey._stop()  # close the Essentia helper before files are replaced
        except Exception:
            pass
        self.root.destroy()
        os._exit(0)  # let the installer replace our files right away

    def _show_update_result(self):
        r = updater.last_result()
        if not r:
            return
        status, old, new, err = r
        # Only report what's actually true for the version running now (a
        # result from before a manual reinstall is no longer accurate).
        if status == "ok" and __version__ == new:
            self.status.set(f"Updated to v{new}.")
            messagebox.showinfo("Beat Sorter", f"Updated from v{old} to v{new}.")
        elif status == "failed" and __version__ == old:
            messagebox.showerror("Beat Sorter",
                                 f"The update to v{new} didn't work, so v{old} was put back. "
                                 f"Nothing else changed. You can try again later, or use "
                                 f"More > Report a problem.\n\n{err[:600]}")

    def _show_more(self):
        b = self.more_btn
        self.more_menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    # ================= settings window =================
    def _open_settings(self):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        w = tk.Toplevel(self.root, bg=T.BG)
        w.title("Settings")
        w.resizable(False, False)
        w.transient(self.root)
        self._settings_win = w
        c = T.card(w, padding=18)
        c.pack(fill="both", expand=True, padx=16, pady=16)

        def section(text, row):
            ttk.Label(c, text=text, style="Section.TLabel").grid(
                row=row, column=0, columnspan=3, sticky="w", pady=(12 if row else 0, 4))

        def field(label, var, row, hint):
            ttk.Label(c, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(c, textvariable=var, width=8).grid(row=row, column=1, sticky="w", padx=10)
            ttk.Label(c, text=hint, style="CardMuted.TLabel").grid(row=row, column=2, sticky="w")

        section("Tempo", 0)
        ttk.Label(c, text="Preferred BPM range", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        rng = tk.Frame(c, bg=T.SURFACE)
        rng.grid(row=1, column=1, columnspan=2, sticky="w", padx=10)
        ttk.Entry(rng, textvariable=self.lo_var, width=6).pack(side="left")
        ttk.Label(rng, text="  to  ", style="CardMuted.TLabel").pack(side="left")
        ttk.Entry(rng, textvariable=self.hi_var, width=6).pack(side="left")
        ttk.Button(rng, text="Suggest from my files", style="Card.TButton",
                   command=self._suggest_range).pack(side="left", padx=10)
        ttk.Label(c, style="CardMuted.TLabel",
                  text="Detected tempos are halved/doubled to land here (70 vs 140).").grid(
            row=2, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(c, variable=self.bpmauto_var,
                        text="Learn this range from my named beats after each scan").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

        section("Sorting", 4)
        field("One-shots under", self.os_var, 5, "seconds")
        field("Min BPM confidence", self.bc_var, 6, "below this → _Review")
        field("Min key confidence", self.kc_var, 7, "below this → _Review")
        ttk.Checkbutton(c, variable=self.detkey_var,
                        text="Use detected key when a file has no key in its name").grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(c, style="CardMuted.TLabel",
                  text="Off: those files go to a \"Key unknown\" folder instead of a guessed key.").grid(
            row=9, column=0, columnspan=3, sticky="w", padx=(24, 0))
        ttk.Checkbutton(c, variable=self.tagname_var,
                        text="Add BPM/key to file names inside Sorted").grid(
            row=10, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(c, style="CardMuted.TLabel",
                  text="Only the copies in Sorted are renamed. Originals keep their names.").grid(
            row=11, column=0, columnspan=3, sticky="w", padx=(24, 0))

        ttk.Label(c, text=f"Beat Sorter v{__version__}", style="CardMuted.TLabel").grid(
            row=12, column=0, columnspan=2, sticky="w", pady=(18, 0))
        ttk.Button(c, text="Done", style="Accent.TButton", command=self._close_settings).grid(
            row=12, column=2, sticky="e", pady=(18, 0))
        w.protocol("WM_DELETE_WINDOW", self._close_settings)
        w.update_idletasks()  # center over the main window
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - w.winfo_height()) // 3
        w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        _dark_title_bar(w)

    def _close_settings(self):
        s = self._read_settings()
        if s is None:
            messagebox.showerror("Beat Sorter", "Check the settings: numbers only, and the "
                                 "BPM range low must be below high.", parent=self._settings_win)
            return
        s.save()
        self._settings_win.destroy()
        self._settings_win = None

    # ================= settings logic =================
    def _read_settings(self) -> Optional[Settings]:
        s = self.s
        try:
            s.bpm_min = float(self.lo_var.get())
            s.bpm_max = float(self.hi_var.get())
            s.oneshot_seconds = float(self.os_var.get())
            s.bpm_conf_min = float(self.bc_var.get())
            s.key_conf_min = float(self.kc_var.get())
        except ValueError:
            return None
        if not (20 <= s.bpm_min < s.bpm_max <= 300):
            return None
        s.add_tags_to_names = self.tagname_var.get()
        s.bpm_auto = self.bpmauto_var.get()
        s.use_detected_key = self.detkey_var.get()
        s.source, s.output = self.src_var.get().strip(), self.out_var.get().strip()
        return s

    def _schedule_reclassify(self):
        if self._reclass_job:
            self.after_cancel(self._reclass_job)
        self._reclass_job = self.after(400, self._reclassify)

    def _reclassify(self):
        self._reclass_job = None
        if not self.records or self.busy:
            return
        s = self._read_settings()
        if s is None:
            self.status.set("Check the settings: numbers only, and the BPM range low < high.")
            return
        self._attach_overrides()
        self.decisions = [classify(r, s) for r in self.records]
        self._refresh_table()
        self._summarize()
        if hasattr(self, "sorted_tab"):
            self.sorted_tab.refresh()
        self._schedule_sync()

    # ================= folder pickers =================
    def _pick_src(self):
        d = filedialog.askdirectory(title="Choose your beats folder", initialdir=self.src_var.get() or None)
        if d:
            self.src_var.set(os.path.normpath(d))
            if not self.out_var.get():
                p = Path(d)
                self.out_var.set(os.path.normpath(str(p.parent / f"{p.name} Sorted")))

    def _pick_out(self):
        d = filedialog.askdirectory(title="Choose (or create) the Sorted folder",
                                    initialdir=self.out_var.get() or self.src_var.get() or None)
        if d:
            self.out_var.set(os.path.normpath(d))

    # ================= scan =================
    def _analyze(self):
        s = self._read_settings()
        if s is None:
            messagebox.showerror("Beat Sorter", "Check the settings (⚙): numbers only, BPM range low < high.")
            return
        src = Path(s.source)
        if not s.source or not src.is_dir():
            messagebox.showerror("Beat Sorter", "Pick your beats folder first.")
            return
        s.save()
        exclude = [Path(s.output)] if s.output else []
        self._set_busy(True)
        self.cancel_evt.clear()

        def progress(stage, done, total, rec):
            self.q.put(("progress", stage, done, total))

        def work():
            try:
                recs = analyze_library(s, src, exclude=exclude, progress=progress, cancel=self.cancel_evt)
                self.q.put(("analyzed", recs))
            except Exception as e:
                self.q.put(("error", f"Scan failed: {e}"))

        self._scan_thread = threading.Thread(target=work, daemon=True)
        self._scan_thread.start()

    def _cancel(self):
        self.cancel_evt.set()
        self.status.set("Cancelling… finishing the files already in progress.")

    # ================= build =================
    def _build(self, allow_copy: bool = False, confirmed: bool = False):
        s = self._read_settings()
        if s is None or not self.records:
            return
        src, out = Path(s.source), Path(s.output) if s.output else None
        if not out:
            messagebox.showerror("Beat Sorter", "Pick a Sorted folder first.")
            return
        try:
            check_folders(src, out)
        except UnsafePath as e:
            messagebox.showerror("Beat Sorter", str(e))
            return
        s.save()
        self._attach_overrides()
        decisions = [classify(r, s) for r in self.records]
        items = self._plan(decisions, out)
        if not confirmed:
            n_rev = sum(d.category == "Review" for d in decisions)
            msg = (f"Build the Sorted folder at:\n{out}\n\n"
                   f"{len(items)} files will be linked into BPM/key folders "
                   f"({n_rev} in _Review).\n\n"
                   "Your original files are not moved, renamed or changed. Anything "
                   "Beat Sorter put in this Sorted folder before is replaced.\n\nContinue?")
            if not messagebox.askyesno("Build Sorted Folder", msg):
                return
        self._set_busy(True)

        def work():
            try:
                res = build(items, src, out, allow_copy=allow_copy,
                            progress=lambda d, t: self.q.put(("progress", "Building", d, t)))
                self.q.put(("built", res, out))
            except NeedsCopy as e:
                self.q.put(("needs_copy", e))
            except UnsafePath as e:
                self.q.put(("error", str(e)))
            except Exception as e:
                self.q.put(("error", f"Build failed: {e}"))

        threading.Thread(target=work, daemon=True).start()

    # ================= live Sorted folder =================
    def _plan(self, decisions, out: Path):
        s = self.s
        return plan(self.records, decisions, out, s.add_tags_to_names, tags=self.tag_map,
                    names=s.folder_names, folders=self.folders.memberships(s.number_my_folders))

    def _organize_changed(self, msg: str):
        """Something was reorganized in the Sorted tab."""
        self.tag_map = self.tags.all()
        self.overrides = self.tags.overrides()
        self._reclassify()
        note = "  ·  updating your Sorted folder…" if self._sorted_ready() else \
            "  ·  build the Sorted folder (Library tab) to see this in FL Studio"
        self.status.set(msg + note)

    def _schedule_sync(self, delay: int = 700):
        """Update the Sorted folder to match (if it's been built). Debounced,
        runs in the background, changes only what differs."""
        if not self.records or self._sorted_ready() is None:
            return
        if self._sync_job:
            self.after_cancel(self._sync_job)
        self._sync_job = self.after(delay, self._run_sync)

    def _run_sync(self):
        self._sync_job = None
        out = self._sorted_ready()
        if out is None or not self.records:
            return
        if self.busy or self._sync_running:
            self._sync_again = True
            self._sync_job = self.after(1500, self._run_sync)
            return
        if any(d.category == "Not analyzed" for d in self.decisions):
            # a cancelled/partial scan: syncing now would drop those beats'
            # links from Sorted until the next scan, so wait for a full one
            self.status.set(self.status.get().replace("  ·  updating your Sorted folder…", "")
                            + "  ·  Sorted folder updates after the scan finishes")
            return
        try:
            items = self._plan(self.decisions, out)
        except Exception as e:
            self.status.set(f"Couldn't update the Sorted folder: {e}")
            return
        src = Path(self.s.source)
        self._sync_running = True

        def work():
            try:
                res = sync(items, src, out)
                self.q.put(("synced", res))
            except NeedsCopy as e:
                self.q.put(("sync_done_flag",))
                self.q.put(("needs_copy", e))
            except Exception as e:
                self.q.put(("sync_failed", str(e)))

        threading.Thread(target=work, daemon=True).start()

    # ================= closing =================
    def _on_close(self):
        """Close everything: nothing keeps running after the window is gone."""
        self.cancel_evt.set()  # scans
        self.dl_cancel.set()  # downloads
        try:
            self.player.stop()
        except Exception:
            pass
        from . import essentiakey, procs
        procs.stop_all()  # analysis workers end now, not after the whole scan
        essentiakey._stop()
        t = getattr(self, "_scan_thread", None)
        if t is not None and t.is_alive():
            t.join(timeout=3)  # lets it save the results it already has
        if self._sync_running:
            time.sleep(0.5)  # let a Sorted-folder update finish its current file
        self.root.destroy()

    # ================= feedback =================
    def _report(self, kind: str = "problem", error_text: str = ""):
        from .gui_feedback import open_report
        return open_report(self, kind, error_text)

    # ================= startup =================
    def _mark_started(self):
        """Tell the updater this version opened fine (see apply_update)."""
        try:
            from .config import app_dir
            (app_dir() / "started.txt").write_text(__version__, encoding="utf-8")
        except OSError:
            pass

    def _startup_load(self):
        """Show your library from last time right away, then analyze only
        what's new or changed."""
        src = self.s.source
        if not src or not Path(src).is_dir() or self.records or self.busy:
            return
        exclude = [Path(self.s.output)] if self.s.output else []
        self.status.set("Loading your beats…")

        def work():
            try:
                recs, new = load_cached(Path(src), exclude=exclude)
                self.q.put(("cached", recs, new))
            except Exception as e:
                self.q.put(("cached_failed", str(e)))

        threading.Thread(target=work, daemon=True).start()

    # ================= reports =================
    def _export(self):
        if not self.records:
            messagebox.showinfo("Beat Sorter", "Scan first.")
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                         initialfile="beat_sorter_results.csv")
        if p:
            write_csv(Path(p), self.records, self.decisions)
            self.status.set(f"CSV saved: {p}")

    def _accuracy(self):
        s = self._read_settings()
        if not self.records or s is None:
            messagebox.showinfo("Beat Sorter", "Scan first.")
            return
        acc = accuracy(self.records, s.bpm_min, s.bpm_max, s.oneshot_seconds)
        lo, hi, rate = suggest_bpm_range(self.records, s.oneshot_seconds)

        win = tk.Toplevel(self.root, bg=T.BG)
        win.title("Accuracy report")
        win.geometry("760x540")
        txt = tk.Text(win, wrap="word", font=self.f["mono"], bg=T.SURFACE, fg=T.TEXT,
                      insertbackground=T.ACCENT, relief="flat", padx=16, pady=14,
                      highlightthickness=1, highlightbackground=T.BORDER)
        txt.pack(fill="both", expand=True, padx=16, pady=16)
        lines = ["HOW DETECTION COMPARES WITH YOUR FILE NAMES", "",
                 "Files with tags are sorted by the name, so this only shows how far",
                 "to trust detection for your UNTAGGED files.", ""]
        if not acc.bpm_total and not acc.key_total:
            lines.append("No files with BPM/key in the name were found.")
        else:
            lines += acc.summary_lines()
            if rate > 0:
                lines += ["", f"Best one-octave BPM range for your library: {lo:g}-{hi:g} "
                              f"({rate:.0%} of tagged files match)."]
            lines += ["", f"Disagreements ({len(acc.disagreements)}):"]
            lines += [f"  {n}\n      {why}" for n, why in acc.disagreements[:500]]
        txt.insert("1.0", "\n".join(lines))
        txt.configure(state="disabled")

    def _learn_range(self) -> str:
        """After a scan: pick the BPM range that matches the named beats
        best (if that setting is on). Returns a status note or ""."""
        s = self._read_settings()
        if s is None or not s.bpm_auto or not self.records:
            return ""
        got = learn_bpm_range(self.records, s)
        if not got:
            return ""
        lo, hi, rate, n, cur_rate = got
        s.bpm_min, s.bpm_max = lo, hi
        self.lo_var.set(f"{lo:g}")
        self.hi_var.set(f"{hi:g}")
        if self._reclass_job:  # the caller reclassifies right away
            self.after_cancel(self._reclass_job)
            self._reclass_job = None
        s.save()
        return (f"BPM range set to {lo:g}-{hi:g} from your named beats "
                f"({rate:.0%} match, was {cur_rate:.0%})")

    def _suggest_range(self):
        s = self._read_settings()
        if not self.records or s is None:
            messagebox.showinfo("Beat Sorter", "Scan first, so there's data to learn from.")
            return
        lo, hi, rate = suggest_bpm_range(self.records, s.oneshot_seconds)
        if rate <= 0:
            messagebox.showinfo("Beat Sorter", "No files with a BPM in the name were found.")
            return
        cur = accuracy(self.records, s.bpm_min, s.bpm_max, s.oneshot_seconds)
        cur_rate = ((cur.bpm_counts["exact"] + cur.bpm_counts["close"]) / cur.bpm_total) if cur.bpm_total else 0
        if messagebox.askyesno(
                "Suggested BPM range",
                f"Based on {cur.bpm_total} files with a BPM in the name:\n\n"
                f"Current range {s.bpm_min:g}-{s.bpm_max:g}: {cur_rate:.0%} match\n"
                f"Suggested {lo:g}-{hi:g}: {rate:.0%} match\n\n"
                "This decides whether untagged beats come out as e.g. 70 or 140.\n"
                "Use the suggested range?"):
            self.lo_var.set(f"{lo:g}")
            self.hi_var.set(f"{hi:g}")
            s.bpm_min, s.bpm_max = lo, hi
            s.save()

    # ================= table / browser =================
    @staticmethod
    def _source_label(d: Decision) -> str:
        names = {"filename": "name", "detected": "detected", "you": "you"}
        order = ["you", "name", "detected"]
        srcs = {names.get(x, x) for x in (d.bpm_source, d.key_source) if x}
        return " + ".join(s for s in order if s in srcs)

    def _tags_of(self, r: Record) -> set:
        return self.tag_map.get(str(r.path), set())

    def _row(self, r: Record, d: Decision):
        return (
            self._play_marker(r.path),
            str(r.rel),
            f"{d.bpm:g}" if d.bpm else "",
            f"{d.key_label}  {camelot(d.key)}" if d.key else d.key_label,
            ", ".join(sorted(self._tags_of(r), key=str.lower)),
            "/".join(self.s.folder_names.get(p, p) for p in d.folder) if d.folder else d.category,
            "; ".join(d.flags),
        )

    def _matches(self, d: Decision) -> bool:
        f = self.filter_var.get()
        if f == "Sorted":
            return d.category == "Sorted"
        if f == "Needs review":
            return d.category == "Review"
        if f == "One-shots":
            return d.category == "One-Shots"
        if f == "Name vs. detection differ":
            return any("tag" in fl for fl in d.flags)
        if f == "Errors / not analyzed":
            return d.category in ("Error", "Not analyzed")
        return True

    def _bpm_bounds(self):
        def num(v):
            try:
                return float(v.get())
            except ValueError:
                return None
        return num(self.f_lo_var), num(self.f_hi_var)

    def _passes_filters(self, r: Record, d: Decision, term: str, lo, hi) -> bool:
        if not self._matches(d):
            return False
        if term and term not in str(r.rel).lower() and term not in "/".join(d.folder).lower() \
                and not any(term in t.lower() for t in self._tags_of(r)):
            return False
        if lo is not None or hi is not None:
            if not d.bpm or (lo is not None and d.bpm < lo) or (hi is not None and d.bpm > hi):
                return False
        if self.key_filter and (not d.key or d.key.short not in self._key_targets()):
            return False
        if self.type_filter and d.shot_type not in self.type_filter:
            return False
        if self.tag_filter and not self.tag_filter <= self._tags_of(r):
            return False
        return True

    def _refresh_table(self):
        sel_paths = {str(self.records[int(i)].path) for i in self.tree.selection()
                     if i.isdigit() and int(i) < len(self.records)}
        self.tree.delete(*self.tree.get_children())
        if not self.decisions:
            self.count_lbl.configure(text="")
            self.empty.place(relx=0.5, rely=0.56, anchor="center")
            for st in self.stats.values():
                st.set("–")
            self._rebuild_chips()
            return
        self.empty.place_forget()
        term = self.search_var.get().strip().lower()
        lo, hi = self._bpm_bounds()
        rows = []
        for i, (r, d) in enumerate(zip(self.records, self.decisions)):
            if not self._passes_filters(r, d, term, lo, hi):
                continue
            row = self._row(r, d)
            if row[0]:
                tag = "playing"
            elif d.category in ("Error", "Not analyzed"):
                tag = "error"
            elif any("tag" in f for f in d.flags):
                tag = "flag"
            elif d.category == "Review":
                tag = "review"
            elif d.category == "One-Shots":
                tag = "oneshot"
            else:
                tag = ""
            rows.append((i, row, tag))
        idx = [c[0] for c in COLUMNS].index(self.sort_col)

        def key(item):
            v = item[1][idx]
            try:
                return (0, float(v), "")
            except ValueError:
                return (1, 0.0, v.lower())

        rows.sort(key=key, reverse=self.sort_rev)
        reselect = []
        for n, (i, row, tag) in enumerate(rows):
            tags = tuple(t for t in (tag, "alt" if n % 2 else "") if t)
            self.tree.insert("", "end", iid=str(i), values=row, tags=tags)
            if str(self.records[i].path) in sel_paths:
                reselect.append(str(i))
        if reselect:
            self.tree.selection_set(reselect)
        self.count_lbl.configure(text=f"{len(rows)} of {len(self.records)} beats")
        self._rebuild_chips()
        self._update_toolbar()
        if getattr(self, "sorted_tab", None) is not None and self.current_tab == "sorted":
            self.sorted_tab.refresh_list()

    def _sort_by(self, col):
        if self.sort_col == col:
            self.sort_rev = not self.sort_rev
        else:
            self.sort_col, self.sort_rev = col, False
        self._refresh_table()

    def _selected(self) -> List[int]:
        """Selected beats in the tab you're looking at (Library or Sorted)."""
        if self.current_tab == "sorted" and hasattr(self, "sorted_tab"):
            return self.sorted_tab.selected()
        return [int(i) for i in self.tree.selection() if i.isdigit() and int(i) < len(self.records)]

    def _update_toolbar(self):
        n = len(self._selected()) if hasattr(self, "tree") else 0
        for b in (self.play_btn, self.tag_btn, self.untag_btn, self.fix_btn):
            b.configure(state="normal" if n else "disabled")
        if n == 0:
            self.play_btn.configure(state="normal" if self.player.path else "disabled")
        sel_loaded = n and self.records[self._selected()[0]].path == self.player.path
        if sel_loaded or not n:
            playing = self.player.active()
        else:
            playing = False
        self.play_btn.configure(text="❚❚  Pause" if playing and self.player.path else "▶  Play")

    # ---- filter chips ----
    def _rebuild_chips(self):
        for fr in (self.key_chips_frame, self.tag_chips_frame):
            for w in fr.winfo_children():
                w.destroy()
        keys = Counter(d.key.short for d in self.decisions if d.key)
        order = sorted(keys, key=lambda k: (0 if k.endswith("m") else 1, k))
        self.key_filter &= set(keys)
        self._chip_grid(self.key_chips_frame, [(k, k, keys[k]) for k in order], self.key_filter, cols=4)
        if keys:
            on = self.compat_on
            sw = tk.Label(self.key_chips_frame, cursor="hand2", padx=8, pady=3, font=self.f["small"],
                          text=("✓ " if on else "+ ") + "compatible keys",
                          bg=T.PURPLE if on else T.SURFACE, fg="#ffffff" if on else T.PURPLE_HOVER)
            sw.grid(row=(len(order) + 3) // 4, column=0, columnspan=4, sticky="w", pady=(2, 0))
            sw.bind("<Button-1>", lambda e: self._toggle_compat())
            extra = sorted(self._key_targets() - self.key_filter) if on and self.key_filter else []
            T.tooltip(sw, ("Also showing " + ", ".join(extra)) if extra else
                      "Also show keys that mix well (relative key + neighbors on the Camelot wheel)")
        tag_counts = Counter(t for r in self.records for t in self._tags_of(r))
        self.tag_filter &= set(tag_counts)
        for w in self.type_chips_frame.winfo_children():
            w.destroy()
        types = Counter(d.shot_type for d in self.decisions if d.shot_type)
        self.type_filter &= set(types)
        if types:
            from .oneshots import TYPES
            order = sorted(types, key=lambda t: TYPES.index(t) if t in TYPES else 99)
            self._chip_grid(self.type_chips_frame, [(t, t, types[t]) for t in order],
                            self.type_filter, cols=3)
        else:
            tk.Label(self.type_chips_frame, bg=T.SURFACE, fg=T.MUTED, font=self.f["small"],
                     text="No one-shots found.").pack(anchor="w")
        if tag_counts:
            items = [(t, t, c) for t, c in sorted(tag_counts.items(), key=lambda x: (-x[1], x[0].lower()))]
            self._chip_grid(self.tag_chips_frame, items, self.tag_filter, cols=2)
        else:
            tk.Label(self.tag_chips_frame, bg=T.SURFACE, fg=T.MUTED, font=self.f["small"],
                     justify="left", wraplength=200,
                     text="No tags yet. Select beats and click + Tag.").pack(anchor="w")
        if not keys:
            tk.Label(self.key_chips_frame, bg=T.SURFACE, fg=T.MUTED, font=self.f["small"],
                     text="Scan to see keys.").pack(anchor="w")

    def _chip_grid(self, frame, items, selected: set, cols: int):
        for n, (value, label, count) in enumerate(items):
            on = value in selected
            chip = tk.Label(frame, text=label, cursor="hand2", padx=8, pady=3,
                            bg=T.ACCENT if on else T.SURFACE_2,
                            fg=T.ACCENT_TEXT if on else T.TEXT, font=self.f["small"])
            chip.grid(row=n // cols, column=n % cols, sticky="ew", padx=(0, 4), pady=(0, 4))
            chip.bind("<Button-1>", lambda e, v=value, sset=selected: self._toggle_chip(sset, v))
            from .keys import parse_key_name
            k = parse_key_name(value)
            code = f" · {camelot(k)}" if k and frame is self.key_chips_frame else ""
            T.tooltip(chip, f"{count} beat{'s' if count != 1 else ''}{code}")

    def _key_targets(self) -> set:
        """Selected keys, plus their compatible keys when that's switched on."""
        if not self.compat_on:
            return set(self.key_filter)
        from .keys import parse_key_name
        out = set()
        for short in self.key_filter:
            k = parse_key_name(short)
            out |= {c.short for c in compatible(k)} if k else {short}
        return out

    def _toggle_compat(self):
        self.compat_on = not self.compat_on
        self._refresh_table()

    def _toggle_chip(self, sset: set, value: str):
        sset.symmetric_difference_update({value})
        self._refresh_table()

    def _clear_filters(self):
        self.key_filter.clear()
        self.tag_filter.clear()
        self.type_filter.clear()
        self.f_lo_var.set("")
        self.f_hi_var.set("")
        self.search_var.set("")
        self.filter_var.set(FILTERS[0])
        self._refresh_table()

    # ---- tagging ----
    def _menu(self) -> tk.Menu:
        return tk.Menu(self, tearoff=0, bg=T.SURFACE, fg=T.TEXT, bd=0,
                       activebackground=T.SELECT, activeforeground=T.ACCENT, font=self.f["body"])

    def _popup_tag_menu(self, widget, x=None, y=None):
        m = self._add_tag_menu()
        if x is None:
            x, y = widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height()
        m.tk_popup(x, y)

    def _add_tag_menu(self) -> tk.Menu:
        m = self._menu()
        for t in self.tags.names()[:15]:
            m.add_command(label=t, command=lambda t=t: self._apply_tag(t))
        if self.tags.names():
            m.add_separator()
        m.add_command(label="New tag…", command=self._new_tag_dialog)
        return m

    def _popup_untag_menu(self, widget, x=None, y=None):
        m = self._remove_tag_menu()
        if m is None:
            return
        if x is None:
            x, y = widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height()
        m.tk_popup(x, y)

    def _remove_tag_menu(self) -> Optional[tk.Menu]:
        present = sorted({t for i in self._selected() for t in self._tags_of(self.records[i])},
                         key=str.lower)
        if not present:
            return None
        m = self._menu()
        for t in present:
            m.add_command(label=t, command=lambda t=t: self._apply_untag(t))
        return m

    def _new_tag_dialog(self):
        w = tk.Toplevel(self.root, bg=T.BG)
        w.title("New tag")
        w.resizable(False, False)
        w.transient(self.root)
        c = T.card(w, padding=16)
        c.pack(padx=14, pady=14)
        ttk.Label(c, text="TAG NAME", style="CardMuted.TLabel").pack(anchor="w")
        var = tk.StringVar()
        e = ttk.Entry(c, textvariable=var, width=28)
        e.pack(pady=(4, 6))
        ttk.Label(c, text="e.g. dark, drill, favorite, sold, needs mix",
                  style="CardMuted.TLabel").pack(anchor="w")

        def ok(*_):
            t = var.get()
            w.destroy()
            if t.strip():
                self._apply_tag(t)

        ttk.Button(c, text="Add tag", style="Accent.TButton", command=ok).pack(anchor="e", pady=(12, 0))
        e.bind("<Return>", ok)
        e.bind("<Escape>", lambda *_: w.destroy())
        w.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - w.winfo_height()) // 3
        w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        _dark_title_bar(w)
        e.focus_set()

    def _sorted_ready(self) -> Optional[Path]:
        """The Sorted folder if it's been built (so tag folders can be kept
        in sync), else None."""
        out = self.out_var.get().strip()
        if not out:
            return None
        p = Path(out)
        from .builder import MARKER
        return p if (p / MARKER).exists() else None

    def _apply_tag(self, tag: str):
        idx = self._selected()
        if not idx:
            return
        recs = [self.records[i] for i in idx]
        tag = self.tags.add([str(r.path) for r in recs], tag)
        if not tag:
            return
        self.tag_map = self.tags.all()
        out = self._sorted_ready()
        note = ""
        if out:
            items = []
            for i in idx:
                r, d = self.records[i], self.decisions[i]
                if d.category in ("Error", "Not analyzed"):
                    continue
                dest = tag_folder(out, tag) / (link_stem(r, d, self.s.add_tags_to_names) + r.path.suffix)
                if not dest.exists():
                    items.append(PlanItem(r.path, dest))
            try:
                if items:
                    add_items(items, Path(self.s.source), out)
                note = f" · added to Sorted\\Tags\\{tag}"
            except Exception as e:
                note = f" · couldn't update Sorted ({e})"
        self.status.set(f"Tagged {len(recs)} beat{'s' if len(recs) != 1 else ''} \"{tag}\"{note}")
        self._refresh_table()

    def _apply_untag(self, tag: str):
        idx = self._selected()
        recs = [self.records[i] for i in idx]
        self.tags.remove([str(r.path) for r in recs], tag)
        self.tag_map = self.tags.all()
        out = self._sorted_ready()
        if out:
            for r in recs:
                try:
                    remove_tag_links(r.path, tag, Path(self.s.source), out)
                except Exception:
                    pass
        self.status.set(f"Removed \"{tag}\" from {len(recs)} beat{'s' if len(recs) != 1 else ''}")
        self._refresh_table()
        self._schedule_sync()  # also tidies any link the quick removal missed

    # ---- FL Studio Browser tags ----
    def _fl_sorted_paths(self) -> dict:
        """Original path -> its link in the Sorted BPM/key folder (what FL's
        Browser shows), if the Sorted folder has been built."""
        out = self._sorted_ready()
        if not out:
            return {}
        from .builder import TAGS_FOLDER
        self._attach_overrides()
        decisions = [classify(r, self.s) for r in self.records]
        res = {}
        for it in plan(self.records, decisions, out, self.s.add_tags_to_names, tags={},
                       names=self.s.folder_names):
            if TAGS_FOLDER not in it.dest.relative_to(out).parts[:1]:
                res.setdefault(str(it.src), str(it.dest))
        return res

    def _fl_desired(self) -> dict:
        from . import fltags
        s = self.s
        return fltags.desired_tags(self.records, self.decisions, self.tag_map, self._fl_sorted_paths(),
                                   include_bpm=s.fl_sync_bpm, include_key=s.fl_sync_key,
                                   include_types=s.fl_sync_types, include_mine=s.fl_sync_mine)

    def _fl_sync_dialog(self):
        from . import fltags
        if not self.records:
            messagebox.showinfo("Beat Sorter", "Scan first.")
            return
        w = tk.Toplevel(self.root, bg=T.BG)
        w.title("Sync tags to FL Studio")
        w.resizable(False, False)
        w.transient(self.root)
        c = T.card(w, padding=18)
        c.pack(padx=14, pady=14)
        ttk.Label(c, text="Send to FL Studio's Browser tags", style="Section.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w")
        tk.Label(c, bg=T.SURFACE, fg=T.MUTED, font=self.f["small"], justify="left", wraplength=520,
                 text="Your beats get tags in FL's own Browser, so you can filter by them there "
                      "(Browser → Tags). Tags you made in FL are kept; Beat Sorter only ever "
                      "removes tags it added itself. FL's tag file is backed up first.").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 12))

        ttk.Label(c, text="FL USER DATA FOLDER", style="CardMuted.TLabel").grid(row=2, column=0, sticky="w")
        folder_var = tk.StringVar(value=self.s.fl_user_data)
        found = tk.StringVar()

        def refresh_found(*_):
            bd = fltags.browser_dir(folder_var.get().strip() or None)
            found.set(f"Tag file: {bd / 'Tags'}" if bd else
                      "FL's settings weren't found. Click Browse and pick your \"Image-Line\" folder "
                      "(usually Documents\\Image-Line).")
            return bd

        ttk.Entry(c, textvariable=folder_var, width=46).grid(row=3, column=0, columnspan=2, sticky="w")

        def browse():
            d = filedialog.askdirectory(title="Pick FL's \"Image-Line\" folder", parent=w)
            if d:
                folder_var.set(os.path.normpath(d))
        ttk.Button(c, text="Browse", style="Card.TButton", command=browse).grid(row=3, column=2, padx=(8, 0))
        folder_var.trace_add("write", refresh_found)
        tk.Label(c, textvariable=found, bg=T.SURFACE, fg=T.MUTED, font=self.f["small"],
                 wraplength=520, justify="left").grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 10))

        ttk.Label(c, text="SEND", style="CardMuted.TLabel").grid(row=5, column=0, sticky="w")
        opts = [("fl_sync_bpm", "BPM ranges (140-149bpm)"), ("fl_sync_key", "Keys (Fm, C#m…)"),
                ("fl_sync_types", "One-shot types (Kicks, 808s…)"), ("fl_sync_mine", "Your Beat Sorter tags")]
        vars_ = {}
        for n, (attr, label) in enumerate(opts):
            v = tk.BooleanVar(value=getattr(self.s, attr))
            vars_[attr] = v
            ttk.Checkbutton(c, text=label, variable=v).grid(row=6 + n // 2, column=n % 2, sticky="w",
                                                            pady=2, padx=(0, 16))
        where = ("your Sorted folder links (what you added to FL's Browser)" if self._sorted_ready()
                 else "your original files (build the Sorted folder to tag those links instead)")
        tk.Label(c, bg=T.SURFACE, fg=T.MUTED, font=self.f["small"], wraplength=520, justify="left",
                 text=f"Tags go on {where}. FL Studio must be closed while syncing.").grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(10, 0))

        def go():
            bd = refresh_found()
            if not bd:
                messagebox.showerror("Beat Sorter", "Pick FL's \"Image-Line\" folder first.", parent=w)
                return
            self.s.fl_user_data = folder_var.get().strip()
            for attr, v in vars_.items():
                setattr(self.s, attr, v.get())
            self.s.save()
            desired = self._fl_desired()
            _, _, preview = fltags.plan_sync(bd / "Tags", desired)
            if not messagebox.askyesno(
                    "Sync tags to FL Studio",
                    f"{preview['files']} files will get tags in FL's Browser "
                    f"({preview['added']} tags added, {preview['removed']} old Beat Sorter tags removed). "
                    f"{preview['kept_user_tags']} tags you made in FL are kept.\n\n"
                    "FL's tag file is backed up first. Continue?", parent=w):
                return
            try:
                st = fltags.sync(bd / "Tags", desired)
            except Exception as e:
                messagebox.showerror("Beat Sorter", str(e), parent=w)
                return
            w.destroy()
            self.status.set(f"Synced tags for {st['files']} files to FL Studio. Open FL → Browser → Tags.")
            messagebox.showinfo("Beat Sorter", "Done. Open FL Studio, then in the Browser click "
                                "Tags to filter by BPM, key and your tags.\n\n"
                                "If anything looks wrong: More → Undo last FL sync.")

        btns = tk.Frame(c, bg=T.SURFACE)
        btns.grid(row=9, column=0, columnspan=3, sticky="e", pady=(16, 0))
        ttk.Button(btns, text="Cancel", style="Card.TButton", command=w.destroy).pack(side="right")
        ttk.Button(btns, text="Sync to FL", style="Accent.TButton", command=go).pack(side="right", padx=(0, 8))
        refresh_found()
        w.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - w.winfo_height()) // 3
        w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        _dark_title_bar(w)

    def _fl_undo(self):
        from . import fltags
        try:
            p = fltags.undo_last()
        except Exception as e:
            messagebox.showerror("Beat Sorter", str(e))
            return
        if p:
            messagebox.showinfo("Beat Sorter", f"FL's tag file was restored from the backup:\n{p}")
        else:
            messagebox.showinfo("Beat Sorter", "There's no FL sync to undo yet.")

    def _fl_resync_after_build(self):
        """Sorted links can move on a rebuild; keep FL's tags pointing at them."""
        from . import fltags
        from .config import app_dir
        if not (app_dir() / "fl_sync_state.json").exists():
            return  # never synced: nothing to keep up to date
        bd = fltags.browser_dir(self.s.fl_user_data or None)
        if not bd:
            return
        try:
            fltags.sync(bd / "Tags", self._fl_desired())
            self.status.set(self.status.get() + "  ·  FL Studio tags updated")
        except RuntimeError:
            self.status.set(self.status.get() + "  ·  close FL Studio, then More → Sync tags to FL")
        except Exception:
            pass

    # ---- duplicates ----
    def _find_duplicates(self):
        if not self.records:
            messagebox.showinfo("Beat Sorter", "Scan first.")
            return
        if self.busy:
            return
        self._set_busy(True)
        recs = list(self.records)

        def work():
            from .duplicates import find_duplicates
            try:
                groups = find_duplicates(
                    recs, progress=lambda st, d, t: self.q.put(("progress", st, d, t)),
                    cancel=self.cancel_evt.is_set)
                self.q.put(("dups_found", recs, groups))
            except Exception as e:
                self.q.put(("error", f"Duplicate search failed: {e}"))

        self.cancel_evt.clear()
        threading.Thread(target=work, daemon=True).start()

    def _show_duplicates(self, recs, groups):
        self._set_busy(False)
        if not groups:
            self.status.set("No duplicates found.")
            messagebox.showinfo("Beat Sorter", "No duplicates found. 👽")
            return
        extra = sum(len(g.members) - 1 for g in groups)
        self.status.set(f"Found {len(groups)} duplicate group{'s' if len(groups) != 1 else ''}"
                        f" ({extra} extra cop{'ies' if extra != 1 else 'y'})")
        w = tk.Toplevel(self.root, bg=T.BG)
        w.title("Duplicates")
        w.geometry("820x480")
        w.transient(self.root)
        top = tk.Frame(w, bg=T.BG, padx=16, pady=12)
        top.pack(fill="x")
        tk.Label(top, bg=T.BG, fg=T.TEXT, font=self.f["bold"], anchor="w", justify="left",
                 wraplength=780, text=f"{len(groups)} group{'s' if len(groups) != 1 else ''} of duplicates. "
                      "The first file in each group is the one to keep "
                      "(BPM/key in its name, then WAV before MP3, then the bigger file).").pack(anchor="w")
        tk.Label(top, bg=T.BG, fg=T.MUTED, font=self.f["small"], anchor="w",
                 text="Nothing is deleted. Tagging marks the extra copies so you can review "
                      "them with the \"duplicate\" tag filter.").pack(anchor="w", pady=(2, 0))
        tf = tk.Frame(w, bg=T.SURFACE, highlightthickness=1, highlightbackground=T.BORDER)
        tf.pack(fill="both", expand=True, padx=16)
        tree = ttk.Treeview(tf, columns=("file", "kind", "size"), show="tree headings")
        tree.heading("#0", text="")
        tree.column("#0", width=30, stretch=False)
        for col, title, width in (("file", "FILE", 520), ("kind", "MATCH", 110), ("size", "SIZE", 80)):
            tree.heading(col, text=title, anchor="w")
            tree.column(col, width=width, anchor="w", stretch=col == "file")
        tree.pack(fill="both", expand=True)
        tree.tag_configure("keep", foreground=T.ACCENT)
        tree.tag_configure("extra", foreground=T.CORAL)
        for n, g in enumerate(groups, 1):
            kind = "identical file" if g.kind == "identical" else "same audio"
            parent = tree.insert("", "end", open=True,
                                 values=(f"Group {n}", kind, ""))
            for k, i in enumerate(g.members):
                r = recs[i]
                tree.insert(parent, "end", values=(("✓ keep   " if k == 0 else "   extra   ") + str(r.rel),
                                                   "", f"{r.size / 1e6:.1f} MB"),
                            tags=("keep" if k == 0 else "extra",))
        btns = tk.Frame(w, bg=T.BG, padx=16, pady=12)
        btns.pack(fill="x")

        def tag_extras():
            paths = [str(recs[i].path) for g in groups for i in g.members[1:]]
            self.tags.add(paths, "duplicate")
            self.tag_map = self.tags.all()
            self._refresh_table()
            self.status.set(f"Tagged {len(paths)} extra cop{'ies' if len(paths) != 1 else 'y'} "
                            "\"duplicate\". Click that tag in the sidebar to review them.")
            w.destroy()

        ttk.Button(btns, text=f"Tag {extra} extra cop{'ies' if extra != 1 else 'y'} \"duplicate\"",
                   style="Accent.TButton", command=tag_extras).pack(side="right")
        ttk.Button(btns, text="Close", style="Card.TButton", command=w.destroy).pack(
            side="right", padx=(0, 8))
        w.update_idletasks()  # center over the main window
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - w.winfo_height()) // 3
        w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        _dark_title_bar(w)

    # ---- BPM / key fixes ----
    def _attach_overrides(self):
        for r in self.records:
            r.override = self.overrides.get(str(r.path), {})

    def _apply_fix(self, bpm=None, key=None, clear_bpm=False, clear_key=False):
        idx = self._selected()
        if not idx:
            return
        paths = [str(self.records[i].path) for i in idx]
        self.tags.set_override(paths, bpm=bpm, key=key, clear_bpm=clear_bpm, clear_key=clear_key)
        self.overrides = self.tags.overrides()
        self._reclassify()
        n = len(paths)
        what = "Reset" if clear_bpm and clear_key and bpm is None and key is None else "Fixed"
        hint = "  ·  Sorted folder updated" if self._sorted_ready() else ""
        self.status.set(f"{what} {n} beat{'s' if n != 1 else ''}{hint}")

    def _scale_bpm(self, factor: float):
        idx = self._selected()
        if not idx:
            return
        for i in idx:  # each beat scales from its own current BPM
            d = self.decisions[i]
            if d.bpm:
                self.tags.set_override([str(self.records[i].path)], bpm=round(d.bpm * factor, 1))
        self.overrides = self.tags.overrides()
        self._reclassify()
        self.status.set(f"BPM {'halved' if factor < 1 else 'doubled'} on {len(idx)} beat"
                        f"{'s' if len(idx) != 1 else ''}")

    def _use_detected_key(self):
        """One click: take the detected key for the selected beats (e.g. when
        the name is a half-step off). Saved as your fix; originals untouched."""
        n = 0
        for i in self._selected():
            d = self.decisions[i]
            if d.detected_key and d.detected_key != d.key:
                self.tags.set_override([str(self.records[i].path)], key=d.detected_key.name)
                n += 1
        if not n:
            return
        self.overrides = self.tags.overrides()
        self._reclassify()
        hint = "  ·  Sorted folder updated" if self._sorted_ready() else ""
        self.status.set(f"Using the detected key on {n} beat{'s' if n != 1 else ''}{hint}")

    def _fix_dialog(self):
        idx = self._selected()
        if not idx:
            return
        first = self.decisions[idx[0]]
        multi = len(idx) > 1
        w = tk.Toplevel(self.root, bg=T.BG)
        w.title("Fix BPM / key")
        w.resizable(False, False)
        w.transient(self.root)
        c = T.card(w, padding=16)
        c.pack(padx=14, pady=14)
        title = (f"{len(idx)} beats selected" if multi
                 else self.records[idx[0]].path.name)
        ttk.Label(c, text=title, style="Section.TLabel").grid(row=0, column=0, columnspan=6,
                                                             sticky="w", pady=(0, 10))

        ttk.Label(c, text="BPM", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w")
        bpm_var = tk.StringVar(value="" if multi or not first.bpm else f"{first.bpm:g}")
        bpm_row = tk.Frame(c, bg=T.SURFACE)  # own frame so the buttons stay compact
        bpm_row.grid(row=1, column=1, columnspan=5, sticky="w", padx=(8, 0))
        ttk.Entry(bpm_row, textvariable=bpm_var, width=8).pack(side="left", padx=(0, 8))

        def scale(f):
            try:
                bpm_var.set(f"{round(float(bpm_var.get()) * f, 1):g}")
            except ValueError:
                pass
        for label, f in (("½×", 0.5), ("2×", 2)):
            tk.Button(bpm_row, text=label, command=lambda f=f: scale(f), bg=T.SURFACE_2, fg=T.TEXT,
                      activebackground=T.BORDER, activeforeground=T.TEXT, relief="flat", bd=0,
                      padx=10, pady=3, cursor="hand2", font=self.f["small"]).pack(side="left", padx=(0, 4))
        if multi:
            ttk.Label(bpm_row, text="blank = keep each beat's BPM", style="CardMuted.TLabel").pack(
                side="left", padx=(8, 0))

        ttk.Label(c, text="KEY", style="CardMuted.TLabel").grid(row=2, column=0, sticky="nw", pady=(14, 0))
        sel = {"pc": None, "mode": "minor", "none": False}
        if not multi and first.key:
            sel["pc"], sel["mode"] = first.key.pc, first.key.mode
        if not multi and first.no_key and first.key_source == "you":
            sel["none"] = True
        notes = tk.Frame(c, bg=T.SURFACE)
        notes.grid(row=2, column=1, columnspan=5, sticky="w", padx=(8, 0), pady=(14, 0))
        chips = {}

        def paint():
            for pc, ch in chips.items():
                on = sel["pc"] == pc and not sel["none"]
                ch.configure(bg=T.ACCENT if on else T.SURFACE_2, fg=T.ACCENT_TEXT if on else T.TEXT)
            for m, b in mode_btns.items():
                b.configure(style="SegOn.TButton" if sel["mode"] == m and not sel["none"] else "Seg.TButton")
            none_chip.configure(bg=T.ACCENT if sel["none"] else T.SURFACE_2,
                                fg=T.ACCENT_TEXT if sel["none"] else T.TEXT)

        def pick(pc):
            sel["pc"], sel["none"] = pc, False
            paint()

        for pc, nm in enumerate(PC_NAMES):
            ch = tk.Label(notes, text=nm, width=3, cursor="hand2", pady=4, font=self.f["small"])
            ch.grid(row=pc // 6, column=pc % 6, padx=(0, 4), pady=(0, 4))
            ch.bind("<Button-1>", lambda e, pc=pc: pick(pc))
            chips[pc] = ch
        modes = tk.Frame(c, bg=T.SURFACE)
        modes.grid(row=3, column=1, columnspan=5, sticky="w", padx=(8, 0), pady=(4, 0))
        mode_btns = {}
        for m in ("minor", "major"):
            b = ttk.Button(modes, text=m, style="Seg.TButton",
                           command=lambda m=m: (sel.update(mode=m, none=False), paint()))
            b.pack(side="left", padx=(0, 2))
            mode_btns[m] = b
        none_chip = tk.Label(modes, text="No key", cursor="hand2", padx=10, pady=4,
                             font=self.f["small"])
        none_chip.pack(side="left", padx=(12, 0))
        none_chip.bind("<Button-1>", lambda e: (sel.update(none=True), paint()))
        paint()

        def save():
            bpm = None
            txt = bpm_var.get().strip()
            if txt:
                try:
                    bpm = float(txt)
                except ValueError:
                    messagebox.showerror("Beat Sorter", "BPM must be a number.", parent=w)
                    return
                if not 30 <= bpm <= 300:
                    messagebox.showerror("Beat Sorter", "BPM should be between 30 and 300.", parent=w)
                    return
            key = "none" if sel["none"] else (
                Key(sel["pc"], sel["mode"]).name if sel["pc"] is not None else None)
            w.destroy()
            if bpm is not None or key is not None:
                self._apply_fix(bpm=bpm, key=key)

        def reset():
            w.destroy()
            self._apply_fix(clear_bpm=True, clear_key=True)

        btns = tk.Frame(c, bg=T.SURFACE)
        btns.grid(row=4, column=0, columnspan=6, sticky="ew", pady=(18, 0))
        ttk.Button(btns, text="Save", style="Accent.TButton", command=save).pack(side="right")
        ttk.Button(btns, text="Reset to automatic", style="Card.TButton", command=reset).pack(
            side="right", padx=(0, 8))
        ttk.Label(btns, text="Your fixes win over file names and detection.",
                  style="CardMuted.TLabel").pack(side="left")
        w.bind("<Return>", lambda e: save())
        w.bind("<Escape>", lambda e: w.destroy())
        w.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - w.winfo_height()) // 3
        w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        _dark_title_bar(w)

    # ---- right-click menu ----
    def _row_menu(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if row not in self.tree.selection():
            self.tree.selection_set(row)
        m = self._menu()
        r = self.records[int(row)]
        loaded = self.player.path == r.path
        m.add_command(label="❚❚  Pause" if loaded and self.player.active() else "▶  Play",
                      command=self._toggle_play)
        if self.player.path is not None:
            m.add_command(label="■  Stop", command=self._stop_play)
        m.add_cascade(label="Add tag", menu=self._add_tag_menu())
        m.add_separator()
        m.add_command(label="✎  Fix BPM / key…", command=self._fix_dialog)
        m.add_command(label="BPM  ½×  (halve)", command=lambda: self._scale_bpm(0.5))
        m.add_command(label="BPM  2×  (double)", command=lambda: self._scale_bpm(2.0))
        d = self.decisions[int(row)] if int(row) < len(self.decisions) else None
        if d and d.detected_key and d.detected_key != d.key:
            m.add_command(label=f"Use detected key ({d.detected_key.short})",
                          command=self._use_detected_key)
        if any(str(self.records[i].path) in self.overrides for i in self._selected()):
            m.add_command(label="Reset to automatic BPM / key",
                          command=lambda: self._apply_fix(clear_bpm=True, clear_key=True))
        um = self._remove_tag_menu()
        if um is not None:
            m.add_cascade(label="Remove tag", menu=um)
        m.add_separator()
        m.add_command(label="Show in Explorer", command=lambda: self._reveal(r.path))
        m.tk_popup(event.x_root, event.y_root)

    def _reveal(self, p: Path):
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(p)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p)])

    # ---- playback ----
    def _toggle_play(self, force_play: bool = False):
        """Play button / Space: play the selected beat, or pause/resume it if
        it's the one loaded. force_play (double-click, Enter): start the
        selected beat from the beginning."""
        idx = self._selected()
        r = self.records[idx[0]] if idx else None
        if r is not None and (force_play or self.player.path != r.path):
            self._start_play(r)
        elif self.player.path is not None:
            self.player.toggle_pause()
        self._player_changed()

    def _transport_play(self):
        """The big play/pause button in the player bar."""
        if self.player.path is not None:
            self.player.toggle_pause()
            self._player_changed()
        else:
            self._toggle_play()

    def _start_play(self, r: Record):
        ok, why = player_mod.available()
        if not ok:
            messagebox.showerror("Beat Sorter", why)
            return
        self.player.play(r.path,
                         on_started=lambda dur: self.q.put(("play_started", r.path, dur)),
                         on_error=lambda msg: self.q.put(("play_error", msg)))
        self._player_changed()

    def _stop_play(self):
        self.player.stop()
        self._player_changed()

    def _seek_by(self, seconds: float):
        if self.player.duration:
            self.player.seek(self.player.position() + seconds)
            self._player_changed()

    def _visible_list(self):
        """(treeview, row ids in order) of the beat list you're looking at."""
        if self.current_tab == "sorted":
            tv = self.sorted_tab.list
        else:
            tv = self.tree
        return tv, [i for i in tv.get_children() if i.isdigit()]

    def _play_neighbor(self, step: int):
        """Previous/next beat in the visible list (from the one playing, or
        the selection)."""
        tv, rows = self._visible_list()
        if not rows:
            return
        cur = None
        if self.player.path is not None:
            cur = next((n for n, i in enumerate(rows)
                        if self.records[int(i)].path == self.player.path), None)
        if cur is None:
            sel = [i for i in tv.selection() if i in rows]
            cur = rows.index(sel[0]) if sel else (-1 if step > 0 else len(rows))
        nxt = cur + step
        if not 0 <= nxt < len(rows):
            return
        iid = rows[nxt]
        tv.selection_set(iid)
        tv.see(iid)
        self._start_play(self.records[int(iid)])

    def _now_playing_label(self, path: Path) -> str:
        for r, d in zip(self.records, self.decisions):
            if r.path == path:
                bits = [path.name]
                if d.bpm:
                    bits.append(f"{d.bpm:g} BPM")
                if d.key:
                    bits.append(d.key.short)
                return "  ·  ".join(bits)
        return path.name

    def _play_marker(self, path: Path) -> str:
        p = self.player
        if p.path is None or p.path != path:
            return ""
        return "❚❚" if p.paused else "▶"

    def _player_changed(self):
        state = self.transport.update_state()
        if state != self._player_state:
            self._player_state = state
            self._refresh_table()

    def _tick_player(self):
        p = self.player
        if p.path is not None and p.ended and not p.loop and self.s.player_autoplay:
            p.ended = False  # don't trigger twice
            self._play_neighbor(1)
        if hasattr(self, "transport") and (p.path is not None or self._player_state is None
                                           or self._player_state[0] is not None):
            self._player_changed()  # only while something is loaded (or just stopped)
        self.after(150 if p.path is not None else 500, self._tick_player)

    # ---- drag into FL Studio ----
    def _setup_drag(self):
        """Drag selected beats out of the list (into FL Studio's playlist,
        channel rack or Explorer). Needs tkinterdnd2; silently off without it."""
        try:
            from tkinterdnd2 import COPY, DND_FILES
            self.tree.drag_source_register(1, DND_FILES)
        except Exception:
            self._drag_ok = False
            return
        self._drag_ok = True

        def init(event):
            idx = self._selected()
            if not idx:
                row = self.tree.identify_row(event.y_root - self.tree.winfo_rooty())
                if row:
                    self.tree.selection_set(row)
                    idx = self._selected()
            paths = [str(self.records[i].path) for i in idx]
            if not paths:
                return None
            data = " ".join("{" + p + "}" for p in paths)  # Tcl list, spaces-safe
            return (COPY, DND_FILES, data)

        self.tree.dnd_bind("<<DragInitCmd>>", init)

    def _summarize(self):
        c = Counter(d.category for d in self.decisions)
        flagged = sum(1 for d in self.decisions if any("tag" in f for f in d.flags))
        tagged = sum(1 for r in self.records if not r.tags.empty)
        self.stats["files"].set(len(self.records))
        self.stats["sorted"].set(c["Sorted"])
        self.stats["review"].set(c["Review"])
        self.stats["oneshots"].set(c["One-Shots"])
        self.stats["differ"].set(flagged)
        bad = c["Error"] + c["Not analyzed"]
        msg = f"Scan complete · {tagged} files had BPM/key in the name"
        if bad:
            msg += f" · {bad} couldn't be read (filter: Errors)"
        self.status.set(msg)

    # ================= worker messages =================
    def _set_busy(self, busy: bool):
        self.busy = busy
        self.header.set_busy(busy)
        self.analyze_btn.configure(state="disabled" if busy else "normal")
        self.build_btn.configure(state="disabled" if busy or not self.records else "normal")
        self.build_btn.configure(style="TButton" if busy or not self.records else "Purple.TButton")
        self.empty.configure(text="Scanning… results appear here when it finishes.\n"
                                  "First scans take a while; later ones only check new files."
                             if busy else "No signals yet.\nChoose your beats folder and hit Scan.")
        if busy:
            self.cancel_btn.pack(side="left")
        else:
            self.cancel_btn.pack_forget()
            self.pbar.reset()

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, stage, done, total = msg
                    if total:
                        self.pbar.set(done, total)
                        word = "Scanning" if stage == "Analyzing" else stage
                        self.status.set(f"{word}… {done} of {total} files")
                    else:
                        self.status.set(stage)
                elif kind == "cached":
                    recs, new = msg[1], msg[2]
                    if not self.records and not self.busy:
                        self.records = recs
                        self._set_busy(False)
                        self._reclassify()
                        if recs:
                            self.status.set(f"Loaded {len(recs)} beats from last time.")
                    if new > 0 and not self.busy:
                        self.status.set(f"Checking {new} new or changed beat"
                                        f"{'s' if new != 1 else ''}…")
                        self._analyze()
                elif kind == "cached_failed":
                    self.status.set(f"Couldn't load last time's results ({msg[1]}). "
                                    "Click Scan beats.")
                elif kind == "synced":
                    res = msg[1]
                    self._sync_running = False
                    if res.linked or res.copied or res.removed_old:
                        cur = self.status.get().replace("  ·  updating your Sorted folder…", "")
                        self.status.set(cur + "  ·  Sorted folder updated")
                        self._fl_resync_after_build()  # links moved: keep FL's tags pointing at them
                    if res.errors:
                        self.status.set(f"Sorted folder updated, {len(res.errors)} problem(s): "
                                        f"{res.errors[0]}")
                elif kind == "sync_done_flag":
                    self._sync_running = False
                elif kind == "sync_failed":
                    self._sync_running = False
                    self.status.set(f"Couldn't update the Sorted folder: {msg[1]}")
                elif kind == "analyzed":
                    self.records = msg[1]
                    self._set_busy(False)
                    learned = self._learn_range()
                    self._reclassify()
                    if learned:
                        self.status.set(self.status.get() + " · " + learned)
                    if self.cancel_evt.is_set():
                        self.status.set("Cancelled. Finished files are saved; Scan again to "
                                        "continue where you left off.")
                elif kind == "built":
                    res, out = msg[1], msg[2]
                    self._set_busy(False)
                    note = f"\n\n{len(res.errors)} files had problems:\n" + "\n".join(res.errors[:10]) \
                        if res.errors else ""
                    self.status.set(f"Sorted folder built ({res.mode}): {res.linked + res.copied} files.")
                    self._fl_resync_after_build()  # after the status, so its note shows
                    if messagebox.askyesno(
                            "Done",
                            f"Built with {res.mode}: {res.linked + res.copied} files.{note}\n\n"
                            "In FL Studio, add this folder to the Browser (Options > File settings > "
                            "Browser extra search folders), or refresh the Browser if it's already there.\n\n"
                            "Open the Sorted folder now?"):
                        if sys.platform == "win32":
                            os.startfile(str(out))  # type: ignore[attr-defined]
                elif kind == "needs_copy":
                    e = msg[1]
                    self._set_busy(False)
                    gb = e.total_bytes / 1e9
                    if messagebox.askyesno(
                            "Copy instead of link?",
                            f"{e.reason}\n\nBeat Sorter can't use hard links here, so it would "
                            f"have to COPY the files, using about {gb:.1f} GB of space.\n\n"
                            "Tip: put the Sorted folder on the same drive as your beats to "
                            "avoid copying.\n\nCopy anyway?"):
                        self._build(allow_copy=True, confirmed=True)
                elif kind == "play_started":
                    self._player_changed()
                elif kind == "play_error":
                    self._player_changed()
                    self.status.set(msg[1])
                elif kind == "dl_probe":
                    self._on_probe(msg[1], msg[2], msg[3])
                elif kind == "dl_status":
                    self._dl_set(msg[1], status=msg[2], tag="work")
                elif kind == "dl_done":
                    self._on_dl_done(msg[1], msg[2], msg[3])
                elif kind == "dups_found":
                    self._show_duplicates(msg[1], msg[2])
                elif kind == "upd_checked":
                    self._on_update_checked(msg[1], msg[2], msg[3])
                elif kind == "upd_staged":
                    self._on_update_staged(msg[1], msg[2])
                elif kind == "dl_updated":
                    self._update_dl_hint()
                    (messagebox.showinfo if msg[1] else messagebox.showerror)("Beat Sorter", msg[2])
                elif kind == "error":
                    self._set_busy(False)
                    messagebox.showerror("Beat Sorter", msg[1])
        except queue.Empty:
            pass
        quiet = not (self.busy or self.dl_active or self._sync_running or self.player.path)
        self.after(300 if quiet else 100, self._poll)  # check less often while idle


def _log_error(text: str) -> Path:
    from .config import app_dir
    p = app_dir() / "error.log"
    with open(p, "a", encoding="utf-8") as f:
        f.write(text + "\n")
    return p


def _dark_title_bar(root: tk.Tk) -> None:
    """Ask Windows 10/11 for a dark title bar (ignored elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4) == 0:
                break
    except Exception:
        pass


def logging_flush():
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass


def run():
    """Start the app. With --smoke-test: open the real window, let it run a
    few seconds, then quit with exit code 0 (worked) or 1 (an error), no
    pop-ups. Used by the automatic tests before every release."""
    import traceback
    smoke = "--smoke-test" in sys.argv
    errors: list = []

    try:  # drag-and-drop into FL Studio needs a tkdnd-enabled window
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except Exception:
        root = tk.Tk()

    app_ref = []

    def report(exc, val, tb):
        text = "".join(traceback.format_exception(exc, val, tb))
        if smoke:
            errors.append(text)
            print(text, file=sys.stderr)
            return
        p = _log_error(text)
        if app_ref and messagebox.askyesno(
                "Beat Sorter", f"Something went wrong: {val}\n\nDetails saved to:\n{p}\n\n"
                               "Report this problem so it can be fixed?", icon="error"):
            app_ref[0]._report("problem", text[-3000:])

    root.report_callback_exception = report
    try:
        app_ref.append(_start(root))
    except Exception as e:  # make startup problems visible (pythonw has no console)
        if smoke:
            print(traceback.format_exc(), file=sys.stderr)
            print("SMOKE TEST FAILED")
            sys.exit(1)
        p = _log_error(traceback.format_exc())
        try:
            messagebox.showerror("Beat Sorter", f"Beat Sorter couldn't start: {e}\n\n"
                                 f"Details saved to:\n{p}")
        finally:
            root.destroy()
        return
    if smoke:
        def finish():
            app = app_ref[0]
            ok = not errors and app.winfo_exists()
            print(f"SMOKE TEST {'OK' if ok else 'FAILED'}: v{__version__}, "
                  f"{len(app.records)} beats loaded, tabs {list(app.tab_frames)}")
            root.destroy()
            sys.exit(0 if ok else 1)
        root.after(int(float(os.environ.get("BEATSORTER_SMOKE_SECONDS", "6")) * 1000), finish)
    root.mainloop()
    if not smoke:
        # Window closed (see App._on_close). Exit for real, so no leftover
        # thread (a download, an update check) keeps the process alive.
        logging_flush()
        os._exit(0)


def _start(root):
    fonts = T.apply(root)
    icons = [T.load_image(f"head_{n}.png") for n in (256, 64, 32, 16)]
    icons = [i for i in icons if i]
    if icons:
        root.iconphoto(True, *icons)  # window + taskbar icon
    app = App(root, fonts)
    root.geometry("1180x800")
    if sys.platform == "win32":
        try:
            root.state("zoomed")  # open maximized: more room for the beat list
        except tk.TclError:
            pass
    _dark_title_bar(root)
    return app

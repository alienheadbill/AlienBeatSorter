"""The Sorted tab: your library as a folder tree you can organize.

Left: folders. Auto folders follow the layout you pick (BPM → Key, Key →
BPM, Camelot → BPM...), plus My Folders (yours, nested, in your order) and
Tags. Right: the beats in the selected folder.

* Drag beats onto an auto folder to change their BPM/key (saved as your
  fix), onto one of My Folders to put them there, onto a tag to tag them.
* Right-click folders to rename them (auto folders too), add subfolders,
  move them up/down or delete them; drag My Folders onto each other to nest.
* Every change updates the real Sorted folder right away (if it's been
  built), so FL Studio's Browser matches. Originals are never touched.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List, Optional, Tuple

from . import organizer as org
from . import theme as T
from .keys import camelot

SEP = "\x1f"
REVIEW, ONESHOTS = "_Review", "One-Shots"

LIST_COLUMNS = [
    ("play", "", 28, "center"),
    ("file", "BEAT", 300, "w"),
    ("bpm", "BPM", 60, "e"),
    ("key", "KEY", 120, "w"),
    ("tags", "TAGS", 140, "w"),
    ("where", "IN", 220, "w"),
]


def _natural(s: str):
    """Sort "080-089 BPM" before "140-149 BPM", "02A" before "11B"."""
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def ask_text(app, title: str, label: str, initial: str = "", button: str = "OK",
             hint: str = "") -> Optional[str]:
    """Small themed text prompt. Returns the text, or None if cancelled."""
    from .gui import _dark_title_bar
    w = tk.Toplevel(app.root, bg=T.BG)
    w.title(title)
    w.resizable(False, False)
    w.transient(app.root)
    c = T.card(w, padding=16)
    c.pack(padx=14, pady=14)
    ttk.Label(c, text=label.upper(), style="CardMuted.TLabel").pack(anchor="w")
    var = tk.StringVar(value=initial)
    e = ttk.Entry(c, textvariable=var, width=34)
    e.pack(pady=(4, 6))
    if hint:
        ttk.Label(c, text=hint, style="CardMuted.TLabel", wraplength=300,
                  justify="left").pack(anchor="w")
    result: List[Optional[str]] = [None]

    def ok(*_):
        result[0] = var.get().strip()
        w.destroy()

    ttk.Button(c, text=button, style="Accent.TButton", command=ok).pack(anchor="e", pady=(12, 0))
    e.bind("<Return>", ok)
    e.bind("<Escape>", lambda *_: w.destroy())
    w.update_idletasks()
    x = app.root.winfo_rootx() + (app.root.winfo_width() - w.winfo_width()) // 2
    y = app.root.winfo_rooty() + (app.root.winfo_height() - w.winfo_height()) // 3
    w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    _dark_title_bar(w)
    e.focus_set()
    e.select_range(0, "end")
    w.grab_set()
    app.root.wait_window(w)
    return result[0] or None


class SortedTab:
    def __init__(self, app, parent: tk.Frame):
        self.app = app
        self.f = app.f
        self.node: str = "all"  # selected folder node
        self._drag_folder: Optional[str] = None
        self._drag_beats: Optional[List[int]] = None
        self._press_xy = (0, 0)
        self._build(parent)

    # ================= layout =================
    def _build(self, parent: tk.Frame):
        app = self.app
        tb = tk.Frame(parent, bg=T.BG, pady=10)
        tb.pack(fill="x")
        ttk.Label(tb, text="Layout", style="Muted.TLabel").pack(side="left")
        self.layout_var = tk.StringVar(value=org.LAYOUTS.get(app.s.layout, org.LAYOUTS["bpm_key"]))
        cb = ttk.Combobox(tb, textvariable=self.layout_var, values=list(org.LAYOUTS.values()),
                          state="readonly", width=18)
        cb.pack(side="left", padx=(8, 14))
        cb.bind("<<ComboboxSelected>>", lambda e: self._set_layout())
        ttk.Button(tb, text="+ New folder", style="Card.TButton",
                   command=lambda: self.new_folder(None)).pack(side="left")
        self.play_btn = ttk.Button(tb, text="▶  Play", style="Card.TButton",
                                   command=self.app._toggle_play)
        self.play_btn.pack(side="left", padx=(8, 0))
        ttk.Button(tb, text="✎  Fix", style="Card.TButton",
                   command=self.app._fix_dialog).pack(side="left", padx=(8, 0))
        self.num_var = tk.BooleanVar(value=app.s.number_my_folders)
        ck = ttk.Checkbutton(tb, variable=self.num_var, text="Keep My Folders order in FL",
                             command=self._set_numbering)
        ck.pack(side="left", padx=(14, 0))
        T.tooltip(ck, "Adds 01, 02… to My Folders names inside Sorted so FL Studio's "
                      "Browser lists them in your order.")
        ttk.Button(tb, text="Open Sorted folder", style="Ghost.TButton",
                   command=self._open_sorted).pack(side="right")

        pane = ttk.PanedWindow(parent, orient="horizontal")
        pane.pack(fill="both", expand=True, pady=(0, 6))

        # --- folder tree ---
        lf = tk.Frame(pane, bg=T.SURFACE, highlightthickness=1, highlightbackground=T.BORDER)
        lf.rowconfigure(0, weight=1)
        lf.columnconfigure(0, weight=1)
        self.ftree = ttk.Treeview(lf, show="tree", selectmode="browse")
        self.ftree.column("#0", width=280, stretch=True)
        ys = ttk.Scrollbar(lf, orient="vertical", command=self.ftree.yview)
        self.ftree.configure(yscrollcommand=ys.set)
        self.ftree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        self.ftree.tag_configure("root", foreground=T.ACCENT, font=self.f["bold"])
        self.ftree.tag_configure("review", foreground=T.AMBER)
        self.ftree.tag_configure("shots", foreground=T.VIOLET)
        self.ftree.tag_configure("mine", foreground=T.TEXT)
        self.ftree.tag_configure("drop", background=T.SELECT)
        self.ftree.bind("<<TreeviewSelect>>", self._on_folder_select)
        self.ftree.bind("<Button-3>", self._folder_menu)
        self.ftree.bind("<F2>", lambda e: self.rename_node(self.ftree.focus()))
        self.ftree.bind("<Delete>", lambda e: self._delete_selected_folder())
        self.ftree.bind("<Alt-Up>", lambda e: (self._shift(self.ftree.focus(), -1), "break")[1])
        self.ftree.bind("<Alt-Down>", lambda e: (self._shift(self.ftree.focus(), 1), "break")[1])
        self.ftree.bind("<ButtonPress-1>", self._folder_press, add="+")
        self.ftree.bind("<B1-Motion>", self._folder_motion, add="+")
        self.ftree.bind("<ButtonRelease-1>", self._folder_release, add="+")
        pane.add(lf, weight=1)

        # --- beat list ---
        rf = tk.Frame(pane, bg=T.SURFACE, highlightthickness=1, highlightbackground=T.BORDER)
        rf.rowconfigure(1, weight=1)
        rf.columnconfigure(0, weight=1)
        head = tk.Frame(rf, bg=T.SURFACE)
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.title = tk.Label(head, bg=T.SURFACE, fg=T.TEXT, font=self.f["bold"], anchor="w",
                              padx=12, pady=8)
        self.title.pack(side="left")
        self.search_var = tk.StringVar()
        se = ttk.Entry(head, textvariable=self.search_var, width=24)
        se.pack(side="right", padx=(0, 10))
        tk.Label(head, text="Search", bg=T.SURFACE, fg=T.MUTED, font=self.f["small"]).pack(
            side="right", padx=(0, 6))
        self.search_var.trace_add("write", lambda *a: self.refresh_list())
        self.list = ttk.Treeview(rf, columns=[c[0] for c in LIST_COLUMNS], show="headings",
                                 selectmode="extended")
        for key, title, width, anchor in LIST_COLUMNS:
            self.list.heading(key, text=title, anchor=anchor)
            self.list.column(key, width=width, anchor=anchor, minwidth=24,
                             stretch=key in ("file", "where"))
        ys2 = ttk.Scrollbar(rf, orient="vertical", command=self.list.yview)
        self.list.configure(yscrollcommand=ys2.set)
        self.list.grid(row=1, column=0, sticky="nsew")
        ys2.grid(row=1, column=1, sticky="ns")
        self.list.tag_configure("alt", background=T.ROW_ALT)
        self.list.tag_configure("playing", foreground=T.ACCENT)
        self.list.tag_configure("review", foreground=T.AMBER)
        self.list.bind("<Double-1>", lambda e: self.app._toggle_play(force_play=True))
        self.list.bind("<space>", lambda e: (self.app._toggle_play(), "break")[1])
        self.list.bind("<Return>", lambda e: self.app._toggle_play(force_play=True))
        self.list.bind("<Button-3>", self._beat_menu)
        self.list.bind("<Delete>", lambda e: self._remove_from_current())
        self.list.bind("<<TreeviewSelect>>", lambda e: self._update_buttons())
        self.empty = tk.Label(rf, bg=T.SURFACE, fg=T.MUTED, font=self.f["body"], justify="center",
                              text="Your sorted beats show up here.\n"
                                   "Pick your beats folder and hit Scan once; after that they "
                                   "load when the app opens.")
        pane.add(rf, weight=3)
        self._setup_dnd()
        ttk.Label(parent, textvariable=app.status, style="Status.TLabel").pack(anchor="w")
        ttk.Label(parent, style="Muted.TLabel",
                  text="Drag beats onto a folder to move them · right-click folders to rename, "
                       "add or reorder · changes update your Sorted folder for FL Studio").pack(
            anchor="w", pady=(2, 6))

    # ================= data =================
    @property
    def names(self) -> Dict[str, str]:
        return self.app.s.folder_names

    def _auto_parts(self, d) -> Tuple[str, ...]:
        return tuple(d.folder) if d.folder else ()

    def selected(self) -> List[int]:
        n = len(self.app.records)
        return [int(i) for i in self.list.selection() if i.isdigit() and int(i) < n]

    def _indices_in(self, node: str) -> List[int]:
        app = self.app
        if node == "all":
            return [i for i, d in enumerate(app.decisions) if d.category not in ("Error",)]
        if node.startswith("auto:"):
            parts = tuple(node[5:].split(SEP))
            return [i for i, d in enumerate(app.decisions)
                    if self._auto_parts(d)[:len(parts)] == parts]
        if node == "my":
            return []
        if node.startswith("my:"):
            idx = {str(r.path): i for i, r in enumerate(app.records)}
            return [idx[p] for p in app.folders.items(int(node[3:]), recursive=True) if p in idx]
        if node.startswith("tag:"):
            tag = node[4:]
            return [i for i, r in enumerate(app.records) if tag in app.tag_map.get(str(r.path), ())]
        return []

    # ================= folder tree =================
    def refresh(self):
        """Rebuild the folder tree (keeps the selection and open folders)."""
        app = self.app
        t = self.ftree
        opened = {i for i in self._all_nodes() if t.item(i, "open")}
        t.delete(*t.get_children())
        if not app.decisions:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.empty.place_forget()
        counts: Dict[Tuple[str, ...], int] = {}
        for d in app.decisions:
            parts = self._auto_parts(d)
            for n in range(1, len(parts) + 1):
                counts[parts[:n]] = counts.get(parts[:n], 0) + 1
        total = sum(1 for d in app.decisions if d.category != "Error")
        t.insert("", "end", iid="all", text=f"All beats  ({total})", tags=("root",))

        def top_order(p: Tuple[str, ...]):
            first = p[0]
            return (first == REVIEW, first == ONESHOTS, _natural(first))

        def add_level(parent_iid: str, prefix: Tuple[str, ...]):
            kids = sorted({p[:len(prefix) + 1] for p in counts if len(p) == len(prefix) + 1
                           and p[:len(prefix)] == prefix},
                          key=top_order if not prefix else (lambda p: _natural(p[-1])))
            for p in kids:
                iid = "auto:" + SEP.join(p)
                tag = "review" if p[0] == REVIEW else "shots" if p[0] == ONESHOTS else ""
                t.insert(parent_iid, "end", iid=iid, open=iid in opened,
                         text=f"{org.display(p[-1], self.names)}  ({counts[p]})",
                         tags=(tag,) if tag else ())
                add_level(iid, p)

        add_level("", ())
        t.insert("", "end", iid="my", text=f"{org.MY_FOLDERS}", open=True, tags=("root",))

        def add_mine(parent_iid: str, parent_id: Optional[int]):
            for fid, name in app.folders.children(parent_id):
                iid = f"my:{fid}"
                t.insert(parent_iid, "end", iid=iid, open=iid in opened or parent_id is None,
                         text=f"{name}  ({app.folders.count(fid)})", tags=("mine",))
                add_mine(iid, fid)

        add_mine("my", None)
        if not app.folders.children(None):
            t.insert("my", "end", iid="my-hint", text="(right-click to make a folder)",
                     tags=("hint",))
            t.tag_configure("hint", foreground=T.MUTED)
        tags = app.tags.names()
        t.insert("", "end", iid="tags", text="Tags", open="tags" in opened, tags=("root",))
        for tag in tags:
            n = sum(1 for s in app.tag_map.values() if tag in s)
            t.insert("tags", "end", iid=f"tag:{tag}", text=f"{tag}  ({n})")
        if not t.exists(self.node):
            self.node = "all"
        t.selection_set(self.node)
        t.see(self.node)
        self.refresh_list()

    def _all_nodes(self, parent: str = "") -> List[str]:
        out = []
        for i in self.ftree.get_children(parent):
            out.append(i)
            out += self._all_nodes(i)
        return out

    def _on_folder_select(self, _e=None):
        sel = self.ftree.selection()
        if sel and sel[0] != self.node and sel[0] != "my-hint":
            self.node = sel[0]
            self.refresh_list()

    def _node_title(self, node: str) -> str:
        if node == "all":
            return "All beats"
        if node.startswith("auto:"):
            return " / ".join(org.display(p, self.names) for p in node[5:].split(SEP))
        if node.startswith("my:"):
            return org.MY_FOLDERS + " / " + " / ".join(self.app.folders.path(int(node[3:])))
        if node.startswith("tag:"):
            return f"Tag: {node[4:]}"
        return self.ftree.item(node, "text") if self.ftree.exists(node) else ""

    # ================= beat list =================
    def refresh_list(self):
        app = self.app
        sel = set(self.list.selection())
        self.list.delete(*self.list.get_children())
        term = self.search_var.get().strip().lower()
        rows = []
        for i in self._indices_in(self.node):
            r, d = app.records[i], app.decisions[i]
            tags = ", ".join(sorted(app.tag_map.get(str(r.path), ()), key=str.lower))
            name = r.path.name
            if term:
                hay = " ".join((name, tags, d.key_label or "",
                                d.key.short if d.key else "", f"{d.bpm:g}" if d.bpm else "")).lower()
                if term not in hay:
                    continue
            playing = app.player.path is not None and app.player.path == r.path
            where = " / ".join(org.display(p, self.names) for p in d.folder) if d.folder else d.category
            rows.append((i, ("▶" if playing else "", name, f"{d.bpm:g}" if d.bpm else "",
                             f"{d.key_label}  {camelot(d.key)}" if d.key else d.key_label,
                             tags, where), playing, d.category == "Review"))
        if not self.node.startswith("my:"):  # My Folders keep the order you added them
            rows.sort(key=lambda x: (_natural(x[1][5]), x[1][1].lower()))
        for n, (i, vals, playing, review) in enumerate(rows):
            tags = tuple(t for t in ("playing" if playing else "", "review" if review else "",
                                     "alt" if n % 2 else "") if t)
            self.list.insert("", "end", iid=str(i), values=vals, tags=tags)
        keep = [s for s in sel if self.list.exists(s)]
        if keep:
            self.list.selection_set(keep)
        self.title.configure(text=f"{self._node_title(self.node)}    ·    {len(rows)} beat"
                                  f"{'s' if len(rows) != 1 else ''}")
        self._update_buttons()

    def _update_buttons(self):
        n = len(self.selected())
        self.play_btn.configure(text="■  Stop" if self.app.player.path and not n else "▶  Play")

    # ================= organizing actions =================
    def _changed(self, msg: str):
        self.app._organize_changed(msg)

    def _set_layout(self):
        label = self.layout_var.get()
        lid = next((k for k, v in org.LAYOUTS.items() if v == label), org.DEFAULT_LAYOUT)
        if lid == self.app.s.layout:
            return
        self.app.s.layout = lid
        self.app.s.save()
        self.node = "all"
        self._changed(f"Layout: {label}")

    def _set_numbering(self):
        self.app.s.number_my_folders = self.num_var.get()
        self.app.s.save()
        self._changed("My Folders " + ("numbered in your order" if self.num_var.get()
                                       else "no longer numbered") + " in Sorted")

    def new_folder(self, parent_id: Optional[int], beats: Optional[List[int]] = None):
        name = ask_text(self.app, "New folder", "Folder name", button="Create",
                        hint="e.g. Album ideas, Send to artists, Sold, Placements")
        if not name:
            return
        fid = self.app.folders.create(name, parent_id)
        if beats:
            self.app.folders.add_items(fid, [str(self.app.records[i].path) for i in beats])
        self.node = f"my:{fid}"
        self._changed(f"Made folder \"{self.app.folders.get(fid)[1]}\"")

    def rename_node(self, node: str):
        if not node:
            return
        if node.startswith("my:"):
            fid = int(node[3:])
            old = self.app.folders.get(fid)[1]
            new = ask_text(self.app, "Rename folder", "New name", old, "Rename")
            if new and new != old:
                got = self.app.folders.rename(fid, new)
                self._changed(f"Renamed \"{old}\" to \"{got}\"")
        elif node.startswith("auto:"):
            part = node[5:].split(SEP)[-1]
            old = org.display(part, self.names)
            new = ask_text(self.app, "Rename folder", "New name", old, "Rename",
                           hint=f"Renames every \"{part}\" folder in this layout. Leave the "
                                "name as it was to keep it. Beats dropped here still get "
                                f"{part}.")
            if new is None:
                return
            from .folders import clean_name
            new = clean_name(new)
            if not new or new == part:
                self.names.pop(part, None)
            else:
                self.names[part] = new
            self.app.s.save()
            self._changed(f"Folder \"{part}\" shows as \"{self.names.get(part, part)}\"")

    def reset_name(self, node: str):
        part = node[5:].split(SEP)[-1]
        self.names.pop(part, None)
        self.app.s.save()
        self._changed(f"Folder \"{part}\" back to its own name")

    def _shift(self, node: str, delta: int):
        if node and node.startswith("my:"):
            self.app.folders.shift(int(node[3:]), delta)
            self._changed("Folder moved " + ("up" if delta < 0 else "down"))

    def delete_folder(self, node: str):
        fid = int(node[3:])
        name = self.app.folders.get(fid)[1]
        n = self.app.folders.count(fid)
        if not messagebox.askyesno(
                "Delete folder",
                f"Delete \"{name}\" and its subfolders?\n\n"
                f"The {n} beat{'s' if n != 1 else ''} in it stay in your library and in "
                "their BPM/key folders. Only this folder's links in Sorted are removed. "
                "Your original files are not touched."):
            return
        self.app.folders.delete(fid)
        self.node = "my"
        self._changed(f"Deleted folder \"{name}\"")

    def _delete_selected_folder(self):
        node = self.ftree.focus()
        if node.startswith("my:"):
            self.delete_folder(node)

    def drop_beats(self, indices: List[int], target: str, from_node: Optional[str] = None):
        """Beats dropped on a folder node."""
        app = self.app
        if not indices or not target or target == "my-hint":
            return
        paths = [str(app.records[i].path) for i in indices]
        n = len(indices)
        plural = "s" if n != 1 else ""
        if target.startswith("my:"):
            fid = int(target[3:])
            added = app.folders.add_items(fid, paths)
            moved = ""
            if from_node and from_node.startswith("my:") and from_node != target:
                app.folders.remove_items(int(from_node[3:]), paths)
                moved = "Moved"
            name = app.folders.get(fid)[1]
            count = n if moved else added
            self._changed(f"{moved or 'Added'} {count} beat{'s' if count != 1 else ''} to \"{name}\""
                          + ("" if moved or added == n else f" ({n - added} already there)"))
        elif target == "my":
            self.new_folder(None, beats=indices)
        elif target.startswith("tag:"):
            tag = app.tags.add(paths, target[4:])
            app.tag_map = app.tags.all()
            self._changed(f"Tagged {n} beat{plural} \"{tag}\"")
        elif target == "tags":
            name = ask_text(app, "New tag", "Tag name", button="Add tag")
            if name:
                tag = app.tags.add(paths, name)
                app.tag_map = app.tags.all()
                self._changed(f"Tagged {n} beat{plural} \"{tag}\"")
        elif target.startswith("auto:"):
            parts = tuple(target[5:].split(SEP))
            if parts[0] == REVIEW:
                parts = parts[1:]
            if not org.is_drop_target(parts):
                return
            changed = 0
            for i in indices:
                d = app.decisions[i]
                fix = org.fix_for_drop(parts, d.bpm, d.key)
                bpm = fix.get("bpm")
                if "ask_bpm" in fix:
                    lo, hi = fix["ask_bpm"]
                    got = ask_text(app, "BPM", f"BPM for {app.records[i].path.name}",
                                   str(lo), "Set BPM",
                                   hint=f"This beat is {d.bpm:g} BPM, which doesn't halve or "
                                        f"double into {lo}-{hi}. Type its BPM:" if d.bpm else
                                        f"Type a BPM between {lo} and {hi}:")
                    try:
                        bpm = float(got) if got else None
                    except ValueError:
                        bpm = None
                    if bpm is None or not (20 <= bpm <= 300):
                        continue
                if bpm is None and "key" not in fix:
                    continue
                app.tags.set_override([str(app.records[i].path)], bpm=bpm, key=fix.get("key"))
                changed += 1
            if changed:
                app.overrides = app.tags.overrides()
                where = " / ".join(org.display(p, self.names) for p in parts)
                self._changed(f"Moved {changed} beat{'s' if changed != 1 else ''} to {where}"
                              " (saved as your fix)")

    def _remove_from_current(self):
        if not self.node.startswith("my:"):
            return
        idx = self.selected()
        if not idx:
            return
        fid = int(self.node[3:])
        # remove from this folder and its subfolders
        for f in self.app.folders.descendants(fid):
            self.app.folders.remove_items(f, [str(self.app.records[i].path) for i in idx])
        self._changed(f"Removed {len(idx)} beat{'s' if len(idx) != 1 else ''} from "
                      f"\"{self.app.folders.get(fid)[1]}\"")

    # ================= menus =================
    def _menu(self) -> tk.Menu:
        return self.app._menu()

    def _folders_menu(self, menu: tk.Menu, indices: List[int], parent: Optional[int] = None):
        for fid, name in self.app.folders.children(parent):
            kids = self.app.folders.children(fid)
            if kids:
                sub = self._menu()
                sub.add_command(label=f"{name} (this folder)",
                                command=lambda f=fid: self.drop_beats(indices, f"my:{f}"))
                sub.add_separator()
                self._folders_menu(sub, indices, fid)
                menu.add_cascade(label=name, menu=sub)
            else:
                menu.add_command(label=name, command=lambda f=fid: self.drop_beats(indices, f"my:{f}"))
        if parent is None:
            if self.app.folders.children(None):
                menu.add_separator()
            menu.add_command(label="New folder…", command=lambda: self.new_folder(None, indices))

    def _beat_menu(self, event):
        row = self.list.identify_row(event.y)
        if not row:
            return
        if row not in self.list.selection():
            self.list.selection_set(row)
        idx = self.selected()
        m = self._menu()
        playing = self.app.player.path == self.app.records[idx[0]].path
        m.add_command(label="■  Stop" if playing else "▶  Play", command=self.app._toggle_play)
        fm = self._menu()
        self._folders_menu(fm, idx)
        m.add_cascade(label="Add to folder", menu=fm)
        if self.node.startswith("my:"):
            m.add_command(label="Remove from this folder", command=self._remove_from_current)
        m.add_cascade(label="Add tag", menu=self.app._add_tag_menu())
        m.add_separator()
        m.add_command(label="✎  Fix BPM / key…", command=self.app._fix_dialog)
        d = self.app.decisions[idx[0]]
        if d.detected_key and d.detected_key != d.key:
            m.add_command(label=f"Use detected key ({d.detected_key.short})",
                          command=self.app._use_detected_key)
        if any(str(self.app.records[i].path) in self.app.overrides for i in idx):
            m.add_command(label="Reset to automatic BPM / key",
                          command=lambda: self.app._apply_fix(clear_bpm=True, clear_key=True))
        m.add_separator()
        r = self.app.records[idx[0]]
        m.add_command(label="Show original in Explorer", command=lambda: self.app._reveal(r.path))
        m.tk_popup(event.x_root, event.y_root)

    def _folder_menu(self, event):
        node = self.ftree.identify_row(event.y)
        if not node:
            return
        self.ftree.selection_set(node)
        self.ftree.focus(node)
        m = self._menu()
        if node == "my" or node == "my-hint":
            m.add_command(label="New folder…", command=lambda: self.new_folder(None))
        elif node.startswith("my:"):
            fid = int(node[3:])
            m.add_command(label="New folder inside…", command=lambda: self.new_folder(fid))
            m.add_command(label="Rename…   F2", command=lambda: self.rename_node(node))
            m.add_separator()
            m.add_command(label="Move up   Alt+↑", command=lambda: self._shift(node, -1))
            m.add_command(label="Move down   Alt+↓", command=lambda: self._shift(node, 1))
            info = self.app.folders.get(fid)
            if info and info[0] is not None:
                m.add_command(label="Move to top level",
                              command=lambda: (self.app.folders.move(fid, None),
                                               self._changed("Folder moved to top level")))
            m.add_separator()
            m.add_command(label="Delete folder…", command=lambda: self.delete_folder(node))
        elif node.startswith("auto:"):
            part = node[5:].split(SEP)[-1]
            m.add_command(label="Rename…   F2", command=lambda: self.rename_node(node))
            if part in self.names:
                m.add_command(label=f"Reset name ({part})", command=lambda: self.reset_name(node))
        else:
            return
        p = self._disk_path(node)
        if p is not None:
            m.add_separator()
            m.add_command(label="Open in Explorer", command=lambda: self._open(p))
        m.tk_popup(event.x_root, event.y_root)

    # ================= drag and drop =================
    def _setup_dnd(self):
        """Beats: drag out to FL Studio (files) or onto a folder here. With
        tkinterdnd2 both use real file drag-and-drop; without it, dragging
        onto a folder still works inside the app."""
        self._dnd = False
        try:
            from tkinterdnd2 import COPY, DND_FILES
            self.list.drag_source_register(1, DND_FILES)
            self.ftree.drop_target_register(DND_FILES)
        except Exception:
            self.list.bind("<ButtonPress-1>", self._beat_press, add="+")
            self.list.bind("<B1-Motion>", self._beat_motion, add="+")
            self.list.bind("<ButtonRelease-1>", self._beat_release, add="+")
            return
        self._dnd = True

        def init(event):
            idx = self.selected()
            if not idx:
                return None
            self._drag_beats = idx
            self._drag_from = self.node
            data = " ".join("{" + str(self.app.records[i].path) + "}" for i in idx)
            return (COPY, DND_FILES, data)

        def over(event):
            node = self.ftree.identify_row(event.y_root - self.ftree.winfo_rooty())
            self._highlight(node)
            return COPY

        def drop(event):
            node = self.ftree.identify_row(event.y_root - self.ftree.winfo_rooty())
            self._highlight(None)
            idx = self._indices_for_paths(self.ftree.tk.splitlist(event.data))
            if idx:
                self.drop_beats(idx, node, getattr(self, "_drag_from", None))
            return COPY

        self.list.dnd_bind("<<DragInitCmd>>", init)
        self.list.dnd_bind("<<DragEndCmd>>", lambda e: setattr(self, "_drag_beats", None))
        self.ftree.dnd_bind("<<DropPosition>>", over)
        self.ftree.dnd_bind("<<DropLeave>>", lambda e: self._highlight(None))
        self.ftree.dnd_bind("<<Drop>>", drop)

    def _indices_for_paths(self, paths) -> List[int]:
        idx = {os.path.normcase(os.path.normpath(str(r.path))): i
               for i, r in enumerate(self.app.records)}
        out = []
        for p in paths:
            i = idx.get(os.path.normcase(os.path.normpath(p)))
            if i is not None:
                out.append(i)
        return out

    def _highlight(self, node: Optional[str]):
        for n in self.ftree.tag_has("drop"):
            tags = [t for t in self.ftree.item(n, "tags") if t != "drop"]
            self.ftree.item(n, tags=tags)
        if node and self.ftree.exists(node):
            self.ftree.item(node, tags=list(self.ftree.item(node, "tags")) + ["drop"])

    # in-app beat dragging (when tkinterdnd2 isn't installed)
    def _beat_press(self, e):
        self._press_xy = (e.x_root, e.y_root)
        self._drag_beats = None

    def _beat_motion(self, e):
        if self._drag_beats is None and abs(e.x_root - self._press_xy[0]) + abs(e.y_root - self._press_xy[1]) > 12:
            self._drag_beats = self.selected()
            self.list.configure(cursor="hand2")
        if self._drag_beats:
            self._highlight(self._tree_node_at(e.x_root, e.y_root))

    def _beat_release(self, e):
        self.list.configure(cursor="")
        if self._drag_beats:
            node = self._tree_node_at(e.x_root, e.y_root)
            self._highlight(None)
            if node:
                self.drop_beats(self._drag_beats, node, self.node)
        self._drag_beats = None

    def _tree_node_at(self, x_root: int, y_root: int) -> Optional[str]:
        t = self.ftree
        x, y = x_root - t.winfo_rootx(), y_root - t.winfo_rooty()
        if 0 <= x < t.winfo_width() and 0 <= y < t.winfo_height():
            return t.identify_row(y) or None
        return None

    # dragging My Folders onto each other (nesting)
    def _folder_press(self, e):
        node = self.ftree.identify_row(e.y)
        self._drag_folder = node if node.startswith("my:") else None
        self._press_xy = (e.x_root, e.y_root)
        self._folder_dragging = False

    def _folder_motion(self, e):
        if not self._drag_folder:
            return
        if abs(e.y_root - self._press_xy[1]) > 8:
            self._folder_dragging = True
            self.ftree.configure(cursor="hand2")
            self._highlight(self.ftree.identify_row(e.y))

    def _folder_release(self, e):
        self.ftree.configure(cursor="")
        src, self._drag_folder = self._drag_folder, None
        if not src or not getattr(self, "_folder_dragging", False):
            return
        self._highlight(None)
        target = self.ftree.identify_row(e.y)
        fid = int(src[3:])
        if target == src or not target:
            return
        if target.startswith("my:"):
            if self.app.folders.move(fid, int(target[3:])):
                self._changed(f"Moved \"{self.app.folders.get(fid)[1]}\" into "
                              f"\"{self.app.folders.get(int(target[3:]))[1]}\"")
            else:
                self.app.status.set("A folder can't go inside itself.")
        elif target == "my":
            self.app.folders.move(fid, None)
            self._changed("Folder moved to top level")

    # ================= disk =================
    def _disk_path(self, node: str) -> Optional[Path]:
        out = self.app._sorted_ready()
        if out is None:
            return None
        from .builder import _clean
        if node.startswith("auto:"):
            return out.joinpath(*[_clean(org.display(p, self.names)) for p in node[5:].split(SEP)])
        if node.startswith("my:"):
            return out.joinpath(org.MY_FOLDERS, *[_clean(p) for p in self.app.folders.path(
                int(node[3:]), self.app.s.number_my_folders)])
        return None

    def _open(self, p: Path):
        if not p.exists():
            self.app.status.set("That folder isn't in Sorted yet (build or wait for the update).")
            return
        if sys.platform == "win32":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])

    def _open_sorted(self):
        out = self.app._sorted_ready()
        if out is None:
            messagebox.showinfo("Beat Sorter", "Build the Sorted folder first (Library tab).")
            return
        self._open(out)

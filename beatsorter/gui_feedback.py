"""The "Report a problem / send an idea" window.

The user writes what happened, sees exactly which technical details will
be included, then sends it as a GitHub issue (opens the browser) or an
email (opens their mail app). The full report is also copied to the
clipboard, so nothing is lost if a link gets cut short.
"""

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import feedback
from . import theme as T


def open_report(app, kind: str = "problem", error_text: str = "") -> tk.Toplevel:
    from .gui import _dark_title_bar
    w = tk.Toplevel(app.root, bg=T.BG)
    w.title("Report a problem or send an idea")
    w.transient(app.root)
    w.minsize(560, 520)
    c = T.card(w, padding=16)
    c.pack(fill="both", expand=True, padx=14, pady=14)
    c.columnconfigure(0, weight=1)

    kind_var = tk.StringVar(value=kind)
    top = tk.Frame(c, bg=T.SURFACE)
    top.grid(row=0, column=0, sticky="w")
    for val, label in (("problem", "Something's wrong"), ("idea", "Idea or comment")):
        ttk.Radiobutton(top, text=label, value=val, variable=kind_var).pack(side="left", padx=(0, 16))

    hint = tk.StringVar()
    ttk.Label(c, textvariable=hint, style="CardMuted.TLabel", wraplength=520,
              justify="left").grid(row=1, column=0, sticky="w", pady=(10, 4))
    msg = tk.Text(c, height=7, wrap="word", bg=T.BG, fg=T.TEXT, insertbackground=T.ACCENT,
                  relief="flat", font=app.f["body"], highlightthickness=1,
                  highlightbackground=T.BORDER, padx=8, pady=6)
    msg.grid(row=2, column=0, sticky="nsew")
    c.rowconfigure(2, weight=1)

    def set_hint(*_):
        hint.set("What happened, and what were you doing right before? (e.g. \"I clicked "
                 "Build and got an error\")" if kind_var.get() == "problem" else
                 "What would make Beat Sorter better for you?")

    kind_var.trace_add("write", set_hint)
    set_hint()

    inc_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(c, variable=inc_var, text="Include technical details (shown below)").grid(
        row=3, column=0, sticky="w", pady=(12, 4))
    details = feedback.diagnostics(len(app.records) if app.records else None, error_text)
    det = tk.Text(c, height=8, wrap="none", bg=T.BG, fg=T.MUTED, relief="flat",
                  font=app.f["mono"], highlightthickness=1, highlightbackground=T.BORDER,
                  padx=8, pady=6)
    det.insert("1.0", details)
    det.configure(state="disabled")
    det.grid(row=4, column=0, sticky="nsew")
    c.rowconfigure(4, weight=1)
    ttk.Label(c, style="CardMuted.TLabel", wraplength=520, justify="left",
              text="Version, Windows version and recent error messages. Your folder names "
                   "are hidden. Nothing is sent until you press Send in your browser or "
                   "email app.").grid(row=5, column=0, sticky="w", pady=(4, 0))

    def report():
        text = msg.get("1.0", "end").strip()
        if not text and kind_var.get() == "idea":
            messagebox.showinfo("Beat Sorter", "Write your idea first.", parent=w)
            return None
        title, body = feedback.compose(kind_var.get(), text, details if inc_var.get() else "")
        app.root.clipboard_clear()
        app.root.clipboard_append(f"{title}\n\n{body}")
        return title, body

    def via_github():
        r = report()
        if r and (url := feedback.github_url(*r)):
            webbrowser.open(url)
            done("GitHub opened in your browser. Sign in if asked, then click "
                 "\"Submit new issue\".")

    def via_email():
        r = report()
        if r and (url := feedback.email_url(*r)):
            webbrowser.open(url)
            done(f"Your email app should open with the report filled in. If it doesn't, "
                 f"the report is copied: paste it into an email to {feedback.support_email()}.")

    def copy_only():
        if report():
            done("Report copied. Paste it into an email or a GitHub issue.")

    def done(text):
        app.status.set("Thanks for the report!")
        messagebox.showinfo("Beat Sorter", text, parent=w)
        w.destroy()

    btns = tk.Frame(c, bg=T.SURFACE)
    btns.grid(row=6, column=0, sticky="ew", pady=(14, 0))
    if feedback.repo():
        b = ttk.Button(btns, text="Send on GitHub", style="Accent.TButton", command=via_github)
        b.pack(side="left")
        T.tooltip(b, "Opens a new issue on the project's GitHub page (free account needed).")
    if feedback.support_email():
        ttk.Button(btns, text="Send by email", style="Card.TButton", command=via_email).pack(
            side="left", padx=(8, 0))
    ttk.Button(btns, text="Copy report", style="Ghost.TButton", command=copy_only).pack(side="left", padx=(8, 0))
    ttk.Button(btns, text="Cancel", style="Ghost.TButton", command=w.destroy).pack(side="right")
    w.bind("<Escape>", lambda e: w.destroy())

    w.update_idletasks()
    x = app.root.winfo_rootx() + (app.root.winfo_width() - w.winfo_width()) // 2
    y = app.root.winfo_rooty() + (app.root.winfo_height() - w.winfo_height()) // 4
    w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    _dark_title_bar(w)
    msg.focus_set()
    return w

"""The mdedit GUI: a Markdown editor with a live rendered preview.

Tkinter only.  The app reads and writes local files the user picks and does
nothing else with the outside world.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from . import flavors, html_export, parser as P, samples
from .tkrender import DARK, LIGHT, THEMES, MarkdownRenderer, body_family, mono_family

PREFS_PATH = os.path.join(os.path.expanduser("~"), ".mdedit.json")
FILETYPES = [
    ("Markdown", "*.md *.markdown *.mdown *.mkd *.mdtxt *.text"),
    ("Text files", "*.txt"),
    ("All files", "*.*"),
]
LAYOUTS = ("split", "editor", "preview")
RENDER_DELAY_MS = 220

_HEADING_SRC_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_FENCE_SRC_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LIST_SRC_RE = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])([ \t]+)(\[[ xX]\][ \t]+)?(.*)$")


def enable_dpi_awareness():
    """Ask Windows for real pixels so the UI is not blurry or tiny on 4K.

    Must run before the root window exists.  Silently does nothing anywhere
    else -- ctypes is standard library, so this stays dependency free.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system aware
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# --------------------------------------------------------------------------
# Widgets
# --------------------------------------------------------------------------


class EditorText(tk.Text):
    """A Text widget that emits ``<<TextChanged>>`` for edits and scrolls."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self._orig = str(self) + "_orig"
        self.tk.call("rename", str(self), self._orig)
        self.tk.createcommand(str(self), self._proxy)

    def _proxy(self, *args):
        try:
            result = self.tk.call((self._orig,) + args)
        except tk.TclError as exc:
            if "text doesn't contain any characters tagged with" in str(exc):
                return ""
            if args[:1] in (("edit",),):  # nothing to undo / redo
                return ""
            raise
        if args and (
            args[0] in ("insert", "delete", "replace")
            or args[:3] == ("mark", "set", "insert")
            or args[:2] in (("yview", "moveto"), ("yview", "scroll"))
        ):
            self.event_generate("<<TextChanged>>", when="tail")
        return result


class LineNumbers(tk.Canvas):
    """A thin gutter that mirrors the editor's visible line numbers."""

    def __init__(self, master, editor: tk.Text, theme: dict, width: int = 48, **kw):
        super().__init__(master, width=width, highlightthickness=0,
                         borderwidth=0, **kw)
        self.editor = editor
        self.theme = theme
        self.font = tkfont.Font(family=mono_family(), size=9)
        self.apply_theme(theme)

    def apply_theme(self, theme: dict):
        self.theme = theme
        self.configure(background=theme["gutter_bg"])
        self.redraw()

    def redraw(self, *_):
        self.delete("all")
        try:
            index = self.editor.index("@0,0")
            cursor_line = self.editor.index("insert").split(".")[0]
        except tk.TclError:
            return
        width = self.winfo_width()
        while True:
            info = self.editor.dlineinfo(index)
            if info is None:
                break
            line = index.split(".")[0]
            self.create_text(
                width - max(4, width // 8), info[1], anchor="ne", text=line,
                font=self.font,
                fill=self.theme["cursor"] if line == cursor_line
                else self.theme["gutter_fg"],
            )
            index = self.editor.index(f"{index}+1line")
            if int(line) > 100000:
                break


class FindBar(ttk.Frame):
    """An inline find/replace strip docked under the editor."""

    def __init__(self, master, app: "MarkdownApp"):
        super().__init__(master, padding=(6, 4))
        self.app = app
        self.find_var = tk.StringVar()
        self.repl_var = tk.StringVar()
        self.case_var = tk.BooleanVar(value=False)
        self.regex_var = tk.BooleanVar(value=False)

        ttk.Label(self, text="Find").grid(row=0, column=0, padx=(0, 4))
        self.find_entry = ttk.Entry(self, textvariable=self.find_var, width=26)
        self.find_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(self, text="⬆", width=3,
                   command=lambda: self.search(-1)).grid(row=0, column=2, padx=2)
        ttk.Button(self, text="⬇", width=3,
                   command=lambda: self.search(1)).grid(row=0, column=3, padx=2)

        ttk.Label(self, text="Replace").grid(row=1, column=0, padx=(0, 4), pady=(4, 0))
        self.repl_entry = ttk.Entry(self, textvariable=self.repl_var, width=26)
        self.repl_entry.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        ttk.Button(self, text="Replace", command=self.replace_one).grid(
            row=1, column=2, columnspan=2, padx=2, pady=(4, 0), sticky="ew")
        ttk.Button(self, text="All", width=5, command=self.replace_all).grid(
            row=1, column=4, padx=2, pady=(4, 0))

        ttk.Checkbutton(self, text="Aa", variable=self.case_var,
                        command=self.highlight).grid(row=0, column=4, padx=2)
        ttk.Checkbutton(self, text=".*", variable=self.regex_var,
                        command=self.highlight).grid(row=0, column=5, padx=2)
        ttk.Button(self, text="✕", width=3, command=self.hide).grid(
            row=0, column=6, padx=(6, 0))
        self.status = ttk.Label(self, text="", width=14, anchor="e")
        self.status.grid(row=1, column=5, columnspan=2, sticky="e", pady=(4, 0))

        self.columnconfigure(1, weight=1)
        self.find_var.trace_add("write", lambda *a: self.highlight())
        for widget in (self.find_entry, self.repl_entry):
            widget.bind("<Return>", lambda e: (self.search(1), "break")[1])
            widget.bind("<Shift-Return>", lambda e: (self.search(-1), "break")[1])
            widget.bind("<Escape>", lambda e: (self.hide(), "break")[1])

    # -- behaviour ---------------------------------------------------------

    def show(self):
        self.grid()
        selection = self.app.selected_text()
        if selection and "\n" not in selection:
            self.find_var.set(selection)
        self.find_entry.focus_set()
        self.find_entry.selection_range(0, "end")
        self.highlight()

    def hide(self):
        self.app.editor.tag_remove("search", "1.0", "end")
        self.grid_remove()
        self.app.editor.focus_set()

    def _matches(self):
        needle = self.find_var.get()
        editor = self.app.editor
        editor.tag_remove("search", "1.0", "end")
        if not needle:
            return []
        found, start = [], "1.0"
        count = tk.IntVar()
        while True:
            try:
                pos = editor.search(
                    needle, start, stopindex="end", count=count,
                    nocase=not self.case_var.get(), regexp=self.regex_var.get(),
                )
            except tk.TclError:
                return []  # malformed regular expression
            if not pos or not count.get():
                break
            end = f"{pos}+{count.get()}c"
            found.append((pos, end))
            start = end
        return found

    def highlight(self):
        matches = self._matches()
        for start, end in matches:
            self.app.editor.tag_add("search", start, end)
        self.status.configure(text=f"{len(matches)} match"
                                   f"{'' if len(matches) == 1 else 'es'}")
        return matches

    def search(self, direction: int):
        matches = self.highlight()
        if not matches:
            return
        editor = self.app.editor
        here = editor.index("insert")
        if direction > 0:
            target = next((m for m in matches
                           if editor.compare(m[0], ">=", here)), matches[0])
        else:
            earlier = [m for m in matches if editor.compare(m[1], "<=", here)]
            target = earlier[-1] if earlier else matches[-1]
        editor.mark_set("insert", target[1] if direction > 0 else target[0])
        editor.tag_remove("sel", "1.0", "end")
        editor.tag_add("sel", target[0], target[1])
        editor.see(target[0])
        self.app.update_status()

    def replace_one(self):
        editor = self.app.editor
        if editor.tag_ranges("sel"):
            editor.delete("sel.first", "sel.last")
            editor.insert("insert", self.repl_var.get())
        self.search(1)

    def replace_all(self):
        matches = self._matches()
        if not matches:
            return
        editor = self.app.editor
        replacement = self.repl_var.get()
        for start, end in reversed(matches):
            editor.delete(start, end)
            editor.insert(start, replacement)
        self.status.configure(text=f"{len(matches)} replaced")
        self.app.on_edit()


class FeatureDialog(tk.Toplevel):
    """Tick boxes for what to render.  Changes apply straight away.

    A box that matches the current emulation mode is not remembered as a
    choice, so it keeps following the mode; a box you change is an override
    and survives switching modes until you reset it.
    """

    def __init__(self, app: "MarkdownApp"):
        super().__init__(app)
        self.app = app
        self.title("Rendering features")
        self.resizable(False, False)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda e: self.close())

        frame = ttk.Frame(self, padding=(16, 14))
        frame.pack(fill="both", expand=True)

        self.intro = ttk.Label(frame, justify="left",
                               wraplength=app.px(430), text="")
        self.intro.grid(row=0, column=0, columnspan=2, sticky="w",
                        pady=(0, app.px(12)))

        self.vars = {}
        self.notes = {}
        for k, feature in enumerate(P.FEATURES):
            row = 1 + k * 2
            var = tk.BooleanVar(value=True)
            self.vars[feature.key] = var
            ttk.Checkbutton(
                frame, text=feature.label, variable=var,
                command=lambda key=feature.key: self.on_toggle(key),
            ).grid(row=row, column=0, sticky="w")
            note = ttk.Label(frame, text="", style="Hint.TLabel", anchor="e")
            note.grid(row=row, column=1, sticky="e", padx=(app.px(24), 0))
            self.notes[feature.key] = note
            ttk.Label(frame, text=feature.hint, style="Hint.TLabel").grid(
                row=row + 1, column=0, columnspan=2, sticky="w",
                padx=(app.px(22), 0), pady=(0, app.px(7)))

        buttons = ttk.Frame(frame)
        buttons.grid(row=1 + len(P.FEATURES) * 2, column=0, columnspan=2,
                     sticky="ew", pady=(app.px(6), 0))
        buttons.columnconfigure(0, weight=1)
        self.reset_button = ttk.Button(buttons, text="Reset",
                                       command=self.app.reset_features)
        self.reset_button.grid(row=0, column=1, padx=(0, app.px(6)))
        ttk.Button(buttons, text="Close", command=self.close).grid(row=0, column=2)

        self.refresh()
        self.update_idletasks()
        self.geometry("+%d+%d" % (
            app.winfo_rootx() + max(0, (app.winfo_width() - self.winfo_width()) // 2),
            app.winfo_rooty() + app.px(80),
        ))

    def refresh(self):
        """Re-read the app's state; called on every change and mode switch."""
        app = self.app
        opts, base = app.opts(), app.flavor.opts
        changed = P.differences(opts, base)
        self.configure(background=app.theme["status_bg"])
        self.intro.configure(
            text=f"Emulating {app.flavor.name}. Untick a feature to leave its "
                 f"markup as plain text; the preview and any exported HTML "
                 f"follow immediately."
        )
        for feature in P.FEATURES:
            live = getattr(opts, feature.key)
            self.vars[feature.key].set(live)
            now = "on" if live else "off"
            if feature.key in changed:
                was = "on" if getattr(base, feature.key) else "off"
                note, style = f"{now}  ·  {app.flavor.name}: {was}", "Changed.TLabel"
            else:
                note, style = now, "Hint.TLabel"
            self.notes[feature.key].configure(text=note, style=style)
        self.reset_button.configure(
            text=f"Reset to {app.flavor.name}",
            state="normal" if changed else "disabled",
        )

    def on_toggle(self, key: str):
        self.app.set_feature(key, self.vars[key].get())
        self.refresh()

    def close(self):
        self.app.feature_dialog = None
        self.destroy()


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------


class MarkdownApp(tk.Tk):
    def __init__(self, path: str | None = None):
        enable_dpi_awareness()
        super().__init__()
        self.title("mdedit")
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self.tk.call("tk", "scaling", self.winfo_fpixels("1i") / 72.0)
        self.geometry(f"{self.px(1240)}x{self.px(820)}")
        self.minsize(self.px(560), self.px(360))

        self.prefs = self._load_prefs()
        self.theme = THEMES.get(self.prefs.get("theme", "light"), LIGHT)
        self.flavor = flavors.get(self.prefs.get("flavor", flavors.DEFAULT.key))
        self.flavor_var = tk.StringVar(value=self.flavor.key)
        self.feature_overrides = {
            k: bool(v) for k, v in (self.prefs.get("features") or {}).items()
            if k in P.FEATURE_KEYS
        }
        self.feature_dialog: FeatureDialog | None = None
        self.base_size = int(self.prefs.get("font_size", 11))
        self.layout = self.prefs.get("layout", "split")
        self.sync_scroll = tk.BooleanVar(value=self.prefs.get("sync_scroll", True))
        self.wrap_editor = tk.BooleanVar(value=self.prefs.get("wrap", True))
        self.show_gutter = tk.BooleanVar(value=self.prefs.get("gutter", True))
        self.show_outline = tk.BooleanVar(value=self.prefs.get("outline", False))
        self.recent = list(self.prefs.get("recent", []))

        self.path: str | None = None
        self.dirty = False
        self._after_jobs: set = set()
        self._render_job = None
        self._last_source = None
        self._syncing = False

        self._build_ui()
        self._build_menu()
        self._bind_keys()
        self.apply_theme(self.theme)

        if path:
            self.open_path(path)
        else:
            self.editor.insert("1.0", samples.WELCOME)
            self.editor.edit_reset()
            self.set_dirty(False)
        self.update_mode_status()
        self.render_now()
        self.editor.focus_set()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def px(self, value: float) -> int:
        """Scale a design pixel to this display's density."""
        return int(round(value * self.scale))

    # -- construction ------------------------------------------------------

    def _build_ui(self):
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.panes = ttk.PanedWindow(self, orient="horizontal")
        self.panes.pack(side="top", fill="both", expand=True)

        # Outline sidebar
        self.outline_frame = ttk.Frame(self.panes, width=self.px(190))
        self.outline_list = tk.Listbox(
            self.outline_frame, activestyle="none", highlightthickness=0,
            borderwidth=0, exportselection=False,
        )
        self.outline_list.pack(fill="both", expand=True)
        self.outline_list.bind("<<ListboxSelect>>", self.on_outline_pick)
        self._outline_lines: list[int] = []

        # Editor side
        self.left = ttk.Frame(self.panes)
        self.editor = EditorText(
            self.left, undo=True, maxundo=-1, autoseparators=True,
            wrap="word" if self.wrap_editor.get() else "none",
            padx=self.px(10), pady=self.px(10),
            borderwidth=0, highlightthickness=0,
            font=tkfont.Font(family=mono_family(), size=self.base_size),
            tabs=("1c",),
        )
        self.gutter = LineNumbers(self.left, self.editor, self.theme,
                                  width=self.px(48))
        self.escroll = ttk.Scrollbar(self.left, orient="vertical",
                                     command=self.editor.yview)
        self.editor.configure(yscrollcommand=self._on_editor_scroll)
        self.findbar = FindBar(self.left, self)

        self.gutter.grid(row=0, column=0, sticky="ns")
        self.editor.grid(row=0, column=1, sticky="nsew")
        self.escroll.grid(row=0, column=2, sticky="ns")
        self.findbar.grid(row=1, column=0, columnspan=3, sticky="ew")
        self.findbar.grid_remove()
        self.left.rowconfigure(0, weight=1)
        self.left.columnconfigure(1, weight=1)

        # Preview side
        self.right = ttk.Frame(self.panes)
        self.preview = tk.Text(self.right, borderwidth=0, highlightthickness=0,
                               state="disabled", cursor="")
        self.pscroll = ttk.Scrollbar(self.right, orient="vertical",
                                     command=self.preview.yview)
        self.preview.configure(yscrollcommand=self.pscroll.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        self.pscroll.grid(row=0, column=1, sticky="ns")
        self.right.rowconfigure(0, weight=1)
        self.right.columnconfigure(0, weight=1)

        self.renderer = MarkdownRenderer(
            self.preview, self.theme, self.base_size, on_link=self.on_link,
            flavor=self.flavor,
        )

        # Status bar
        self.status = ttk.Frame(self)
        self.status.pack(side="bottom", fill="x")
        self.status_file = ttk.Label(self.status, text="", anchor="w", padding=(8, 3))
        self.status_file.pack(side="left")
        self.status_info = ttk.Label(self.status, text="", anchor="e", padding=(8, 3))
        self.status_info.pack(side="right")
        self.status_mode = ttk.Label(self.status, text="", anchor="e",
                                     padding=(8, 3))
        self.status_mode.pack(side="right")
        self.status_msg = ttk.Label(self.status, text="", anchor="center",
                                    padding=(8, 3))
        self.status_msg.pack(side="right")

        self.apply_layout(self.layout)

        self.editor.bind("<<TextChanged>>", self.on_edit)
        self.editor.bind("<Configure>", lambda e: self.gutter.redraw())
        self.editor.bind("<MouseWheel>", lambda e: self.after(1, self.gutter.redraw))
        self.preview.bind("<Configure>", lambda e: self.renderer.resize_rules(e.width))
        for widget in (self.preview,):
            widget.bind("<MouseWheel>", self._preview_wheel)

    def _build_menu(self):
        menubar = tk.Menu(self)

        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="New", accelerator="Ctrl+N", command=self.new_file)
        filemenu.add_command(label="Open...", accelerator="Ctrl+O",
                             command=self.open_file)
        self.recent_menu = tk.Menu(filemenu, tearoff=0)
        filemenu.add_cascade(label="Open recent", menu=self.recent_menu)
        filemenu.add_separator()
        filemenu.add_command(label="Save", accelerator="Ctrl+S", command=self.save)
        filemenu.add_command(label="Save as...", accelerator="Ctrl+Shift+S",
                             command=self.save_as)
        filemenu.add_command(label="Export HTML...", command=self.export_html)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", accelerator="Ctrl+Q", command=self.on_close)
        menubar.add_cascade(label="File", menu=filemenu)
        self._refresh_recent_menu()

        editmenu = tk.Menu(menubar, tearoff=0)
        editmenu.add_command(label="Undo", accelerator="Ctrl+Z",
                             command=lambda: self._edit_op("undo"))
        editmenu.add_command(label="Redo", accelerator="Ctrl+Y",
                             command=lambda: self._edit_op("redo"))
        editmenu.add_separator()
        editmenu.add_command(label="Cut", accelerator="Ctrl+X",
                             command=lambda: self.editor.event_generate("<<Cut>>"))
        editmenu.add_command(label="Copy", accelerator="Ctrl+C",
                             command=lambda: self.editor.event_generate("<<Copy>>"))
        editmenu.add_command(label="Paste", accelerator="Ctrl+V",
                             command=lambda: self.editor.event_generate("<<Paste>>"))
        editmenu.add_separator()
        editmenu.add_command(label="Select all", accelerator="Ctrl+A",
                             command=self.select_all)
        editmenu.add_command(label="Find / replace", accelerator="Ctrl+F",
                             command=self.findbar.show)
        menubar.add_cascade(label="Edit", menu=editmenu)

        fmt = tk.Menu(menubar, tearoff=0)
        fmt.add_command(label="Bold", accelerator="Ctrl+B",
                        command=lambda: self.wrap_selection("**"))
        fmt.add_command(label="Italic", accelerator="Ctrl+I",
                        command=lambda: self.wrap_selection("*"))
        fmt.add_command(label="Strikethrough",
                        command=lambda: self.wrap_selection("~~"))
        fmt.add_command(label="Inline code", accelerator="Ctrl+`",
                        command=lambda: self.wrap_selection("`"))
        fmt.add_separator()
        for level in range(1, 7):
            fmt.add_command(
                label=f"Heading {level}", accelerator=f"Ctrl+{level}",
                command=lambda n=level: self.toggle_prefix("#" * n + " "),
            )
        fmt.add_separator()
        fmt.add_command(label="Bullet list", command=lambda: self.toggle_prefix("- "))
        fmt.add_command(label="Numbered list", command=self.number_lines)
        fmt.add_command(label="Task item", command=lambda: self.toggle_prefix("- [ ] "))
        fmt.add_command(label="Block quote", command=lambda: self.toggle_prefix("> "))
        menubar.add_cascade(label="Format", menu=fmt)

        ins = tk.Menu(menubar, tearoff=0)
        ins.add_command(label="Link", accelerator="Ctrl+K", command=self.insert_link)
        ins.add_command(label="Image", command=self.insert_image)
        ins.add_command(label="Code block", command=self.insert_code_block)
        ins.add_command(label="Table", command=self.insert_table)
        ins.add_command(label="Horizontal rule",
                        command=lambda: self.insert_block("\n---\n"))
        ins.add_command(label="Table of contents", command=self.insert_toc)
        menubar.add_cascade(label="Insert", menu=ins)

        view = tk.Menu(menubar, tearoff=0)
        view.add_command(label="Cycle layout", accelerator="Ctrl+P",
                         command=self.cycle_layout)
        for name, label in (("split", "Editor + preview"), ("editor", "Editor only"),
                            ("preview", "Preview only")):
            view.add_command(label=label, command=lambda n=name: self.apply_layout(n))
        view.add_separator()
        view.add_checkbutton(label="Document outline", variable=self.show_outline,
                             command=lambda: self.apply_layout(self.layout))
        view.add_checkbutton(label="Line numbers", variable=self.show_gutter,
                             command=self.toggle_gutter)
        view.add_checkbutton(label="Wrap editor lines", variable=self.wrap_editor,
                             command=self.toggle_wrap)
        view.add_checkbutton(label="Synchronised scrolling",
                             variable=self.sync_scroll)
        view.add_separator()
        view.add_command(label="Dark theme", accelerator="Ctrl+D",
                         command=self.toggle_theme)
        view.add_command(label="Bigger preview text", accelerator="Ctrl+=",
                         command=lambda: self.bump_font(1))
        view.add_command(label="Smaller preview text", accelerator="Ctrl+-",
                         command=lambda: self.bump_font(-1))
        menubar.add_cascade(label="View", menu=view)

        emulate = tk.Menu(menubar, tearoff=0)
        for key in flavors.ORDER:
            fl = flavors.FLAVORS[key]
            emulate.add_radiobutton(
                label=fl.name, value=key, variable=self.flavor_var,
                command=lambda k=key: self.set_flavor(k),
            )
        emulate.add_separator()
        emulate.add_command(label="Next mode", accelerator="Ctrl+E",
                            command=self.cycle_flavor)
        emulate.add_command(label="Rendering features...", accelerator="Ctrl+R",
                            command=self.show_features)
        emulate.add_command(label="What this mode changes...",
                            command=self.show_flavor_info)
        emulate.add_command(label="Emulation demo document",
                            command=self.show_emulation_demo)
        menubar.add_cascade(label="Emulate", menu=emulate)

        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(label="Markdown cheat sheet", accelerator="F1",
                             command=self.show_cheatsheet)
        helpmenu.add_command(label="Welcome document", command=self.show_welcome)
        helpmenu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=helpmenu)

        self.configure(menu=menubar)

    #: Shortcuts that stay live while a text entry (the find bar) has focus.
    ENTRY_SAFE = {
        "<Control-s>", "<Control-S>", "<Control-o>", "<Control-n>",
        "<Control-q>", "<Control-f>", "<Control-p>", "<Control-d>",
        "<Control-equal>", "<Control-plus>", "<Control-minus>", "<F1>",
        "<Control-e>", "<Control-r>",
    }

    def _dispatch(self, fn, key: str):
        """Run a shortcut, unless a plain entry field should get the key."""
        if key not in self.ENTRY_SAFE:
            try:
                focused = self.focus_get()
            except KeyError:
                focused = None
            if isinstance(focused, (tk.Entry, ttk.Entry)):
                return None
        fn()
        return "break"

    def _bind_keys(self):
        binds = {
            "<Control-n>": self.new_file,
            "<Control-o>": self.open_file,
            "<Control-s>": self.save,
            "<Control-S>": self.save_as,
            "<Control-q>": self.on_close,
            "<Control-f>": self.findbar.show,
            "<Control-a>": self.select_all,
            "<Control-b>": lambda: self.wrap_selection("**"),
            "<Control-i>": lambda: self.wrap_selection("*"),
            "<Control-grave>": lambda: self.wrap_selection("`"),
            "<Control-k>": self.insert_link,
            "<Control-p>": self.cycle_layout,
            "<Control-d>": self.toggle_theme,
            "<Control-e>": self.cycle_flavor,
            "<Control-r>": self.show_features,
            "<Control-y>": lambda: self._edit_op("redo"),
            "<Control-equal>": lambda: self.bump_font(1),
            "<Control-plus>": lambda: self.bump_font(1),
            "<Control-minus>": lambda: self.bump_font(-1),
            "<F1>": self.show_cheatsheet,
        }
        for level in range(1, 7):
            binds[f"<Control-Key-{level}>"] = (
                lambda n=level: self.toggle_prefix("#" * n + " "))

        # Bind on the editor as well as globally.  Widget bindings run before
        # the built-in Text class bindings, so "break" there is what stops Tk
        # from also doing its own Ctrl+D (delete char), Ctrl+K (kill line),
        # Ctrl+O (open line) and friends.
        for key, fn in binds.items():
            handler = lambda e, f=fn, k=key: self._dispatch(f, k)
            self.bind_all(key, handler)
            self.editor.bind(key, handler)
        self.editor.bind("<Return>", self.on_return)
        self.editor.bind("<Tab>", self.on_tab)
        self.editor.bind("<Shift-Tab>", self.on_shift_tab)
        self.editor.bind("<Escape>", lambda e: self.findbar.hide())

    # -- preferences -------------------------------------------------------

    def _load_prefs(self) -> dict:
        try:
            with open(PREFS_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_prefs(self):
        data = {
            "theme": self.theme["name"],
            "flavor": self.flavor.key,
            "features": dict(self.feature_overrides),
            "font_size": self.base_size,
            "layout": self.layout,
            "sync_scroll": self.sync_scroll.get(),
            "wrap": self.wrap_editor.get(),
            "gutter": self.show_gutter.get(),
            "outline": self.show_outline.get(),
            "recent": self.recent[:10],
        }
        try:
            with open(PREFS_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError:
            pass

    # -- scheduled callbacks ----------------------------------------------

    def _schedule(self, ms: int, fn):
        """``after`` that forgets itself, so nothing fires past destroy()."""
        job = {}

        def run():
            self._after_jobs.discard(job.get("id"))
            fn()

        job["id"] = self.after(ms, run)
        self._after_jobs.add(job["id"])
        return job["id"]

    def _cancel(self, job_id):
        if job_id is None:
            return
        self._after_jobs.discard(job_id)
        try:
            self.after_cancel(job_id)
        except (tk.TclError, ValueError):
            pass

    def destroy(self):
        for job_id in list(getattr(self, "_after_jobs", ())):
            self._cancel(job_id)
        self._render_job = None
        super().destroy()

    def _remember(self, path: str):
        path = os.path.abspath(path)
        self.recent = [path] + [p for p in self.recent if p != path]
        del self.recent[10:]
        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        menu = self.recent_menu
        menu.delete(0, "end")
        if not self.recent:
            menu.add_command(label="(nothing yet)", state="disabled")
            return
        for path in self.recent:
            menu.add_command(
                label=os.path.basename(path) + "   " + os.path.dirname(path),
                command=lambda p=path: self.open_path(p),
            )
        menu.add_separator()
        menu.add_command(label="Clear list", command=lambda: (
            self.recent.clear(), self._refresh_recent_menu()))

    # -- appearance --------------------------------------------------------

    def apply_theme(self, theme: dict):
        self.theme = theme
        editor_font = tkfont.Font(family=mono_family(), size=self.base_size)
        self.editor.configure(
            background=theme["editor_bg"], foreground=theme["editor_fg"],
            insertbackground=theme["cursor"], selectbackground=theme["select"],
            font=editor_font,
        )
        self.editor.tag_configure("search", background=theme["match"],
                                  foreground=theme["editor_fg"])
        self.outline_list.configure(
            background=theme["gutter_bg"], foreground=theme["fg"],
            selectbackground=theme["select"], selectforeground=theme["fg"],
            font=tkfont.Font(family=body_family(), size=max(8, self.base_size - 1)),
        )
        self.gutter.apply_theme(theme)
        self.renderer.set_theme(theme)
        self.style.configure("TFrame", background=theme["status_bg"])
        self.style.configure("TLabel", background=theme["status_bg"],
                             foreground=theme["fg"])
        self.style.configure("TCheckbutton", background=theme["status_bg"],
                             foreground=theme["fg"])
        self.style.configure("TPanedwindow", background=theme["status_bg"])
        self.style.configure("Hint.TLabel", background=theme["status_bg"],
                             foreground=theme["muted"])
        self.style.configure("Changed.TLabel", background=theme["status_bg"],
                             foreground=theme["link"])
        if self.feature_dialog is not None:
            self.feature_dialog.refresh()
        self.configure(background=theme["status_bg"])
        self.render_now()

    def opts(self) -> P.Options:
        """The features actually in force: the mode, plus any overrides."""
        return P.with_overrides(self.flavor.opts, self.feature_overrides)

    def set_flavor(self, key: str):
        """Switch emulation mode: dialect, palette and layout all change."""
        self.flavor = flavors.get(key)
        self.flavor_var.set(self.flavor.key)
        self.renderer.set_flavor(self.flavor)
        self.update_mode_status()
        self.render_now()
        if self.feature_dialog is not None:
            self.feature_dialog.refresh()
        self.flash(self.flavor.blurb, 4000)

    def cycle_flavor(self):
        self.set_flavor(flavors.next_key(self.flavor.key))

    def update_mode_status(self):
        changed = P.differences(self.opts(), self.flavor.opts)
        extra = f"  ·  {len(changed)} changed" if changed else ""
        self.status_mode.configure(text=f"Emulating: {self.flavor.name}{extra}")

    # -- feature switches --------------------------------------------------

    def set_feature(self, key: str, value: bool):
        """Turn one feature on or off, on top of the current mode."""
        if key not in P.FEATURE_KEYS:
            return
        if bool(value) == getattr(self.flavor.opts, key):
            self.feature_overrides.pop(key, None)  # back in step with the mode
        else:
            self.feature_overrides[key] = bool(value)
        self.update_mode_status()
        self.render_now()
        feature = P.FEATURES_BY_KEY[key]
        self.flash(f"{feature.label}: {'on' if value else 'off'}")

    def set_features(self, overrides: dict):
        for key, value in overrides.items():
            self.set_feature(key, value)
        if self.feature_dialog is not None:
            self.feature_dialog.refresh()

    def reset_features(self):
        self.feature_overrides.clear()
        self.update_mode_status()
        self.render_now()
        if self.feature_dialog is not None:
            self.feature_dialog.refresh()
        self.flash(f"Features reset to {self.flavor.name}")

    def show_features(self):
        if self.feature_dialog is not None:
            self.feature_dialog.refresh()
            self.feature_dialog.deiconify()
            self.feature_dialog.lift()
            return self.feature_dialog
        self.feature_dialog = FeatureDialog(self)
        return self.feature_dialog

    def show_flavor_info(self):
        fl, opts = self.flavor, self.opts()
        width = max(len(f.label) for f in P.FEATURES) + 4
        lines = []
        for feature in P.FEATURES:
            state = "on" if getattr(opts, feature.key) else "off"
            if getattr(opts, feature.key) != getattr(fl.opts, feature.key):
                state += "   (changed here)"
            lines.append(f"{feature.label.ljust(width)}{state}")
        messagebox.showinfo(
            f"{fl.name} emulation",
            f"{fl.blurb}\n\n" + "\n".join(lines) + "\n\n"
            "Styling, fonts and exported CSS follow the same mode.\n"
            "Emulate > Rendering features... changes any of these.",
            parent=self,
        )

    def toggle_theme(self):
        self.apply_theme(DARK if self.theme["name"] == "light" else LIGHT)
        self.flash(f"{self.theme['name'].title()} theme")

    def bump_font(self, delta: int):
        self.base_size = max(7, min(28, self.base_size + delta))
        self.renderer.set_base_size(self.base_size)
        self.editor.configure(
            font=tkfont.Font(family=mono_family(), size=self.base_size))
        self.render_now()
        self.gutter.redraw()
        self.flash(f"Text size {self.base_size}")

    def apply_layout(self, name: str):
        if name not in LAYOUTS:
            name = "split"
        self.layout = name
        for pane in self.panes.panes():
            self.panes.forget(pane)
        if self.show_outline.get():
            self.panes.add(self.outline_frame, weight=0)
        if name in ("split", "editor"):
            self.panes.add(self.left, weight=3)
        if name in ("split", "preview"):
            self.panes.add(self.right, weight=4)
        self.update_idletasks()
        if name == "split":
            width = self.panes.winfo_width()
            offset = self.px(190) if self.show_outline.get() else 0
            if width > self.px(400):
                self.panes.sashpos(1 if offset else 0,
                                   offset + (width - offset) // 2)
        self.refresh_outline()

    def cycle_layout(self):
        self.apply_layout(LAYOUTS[(LAYOUTS.index(self.layout) + 1) % len(LAYOUTS)])
        self.flash({"split": "Editor + preview", "editor": "Editor only",
                    "preview": "Preview only"}[self.layout])

    def toggle_gutter(self):
        if self.show_gutter.get():
            self.gutter.grid(row=0, column=0, sticky="ns")
            self.gutter.redraw()
        else:
            self.gutter.grid_remove()

    def toggle_wrap(self):
        self.editor.configure(wrap="word" if self.wrap_editor.get() else "none")

    # -- document state ----------------------------------------------------

    def source(self) -> str:
        return self.editor.get("1.0", "end-1c")

    def set_dirty(self, dirty: bool):
        self.dirty = dirty
        name = os.path.basename(self.path) if self.path else "Untitled"
        self.title(f"{'*' if dirty else ''}{name} - mdedit")
        self.status_file.configure(
            text=(self.path or "Not saved yet") + ("  • modified" if dirty else ""))

    def on_edit(self, _event=None):
        if not self.dirty and self.source() != (self._last_source or ""):
            self.set_dirty(True)
        self.gutter.redraw()
        self.update_status()
        self.schedule_render()

    def update_status(self):
        line, col = self.editor.index("insert").split(".")
        text = self.source()
        words = len(text.split())
        self.status_info.configure(
            text=f"Ln {line}, Col {int(col) + 1}   {words} words   "
                 f"{len(text)} chars"
        )

    def flash(self, message: str, ms: int = 2200):
        self.status_msg.configure(text=message)
        self._schedule(ms, lambda: self.status_msg.configure(text=""))

    # -- rendering ---------------------------------------------------------

    def schedule_render(self):
        self._cancel(self._render_job)
        self._render_job = self._schedule(RENDER_DELAY_MS, self.render_now)

    def render_now(self):
        self._render_job = None
        source = self.source()
        self._last_source = source
        try:
            top = self.preview.yview()[0]
        except tk.TclError:
            top = 0.0
        doc = P.parse(source, self.opts())
        base_dir = os.path.dirname(self.path) if self.path else os.getcwd()
        self.preview.configure(state="normal")
        try:
            self.renderer.render(doc, base_dir, self.opts())
        finally:
            self.preview.configure(state="disabled")
        if self.sync_scroll.get():
            self.sync_preview_to_editor()
        else:
            self.preview.yview_moveto(top)
        self.refresh_outline()

    def _on_editor_scroll(self, first, last):
        self.escroll.set(first, last)
        self.gutter.redraw()
        if self.sync_scroll.get() and not self._syncing:
            self._syncing = True
            try:
                self.preview.yview_moveto(float(first))
            except (tk.TclError, ValueError):
                pass
            self._syncing = False

    def sync_preview_to_editor(self):
        try:
            self.preview.yview_moveto(self.editor.yview()[0])
        except (tk.TclError, ValueError):
            pass

    def _preview_wheel(self, event):
        self.preview.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def on_link(self, href: str, action: str):
        if action == "enter":
            self.status_msg.configure(text=href)
            return
        if action == "leave":
            self.status_msg.configure(text="")
            return
        # click
        if "://" in href or href.startswith("mailto:"):
            self.flash("External links are not opened - this app stays offline")
            self.clipboard_clear()
            self.clipboard_append(href)
            self.flash(f"Copied to clipboard: {href}")
            return
        if href.startswith("#"):
            self.jump_to_anchor(href[1:])
            return
        base = os.path.dirname(self.path) if self.path else os.getcwd()
        target = href if os.path.isabs(href) else os.path.normpath(
            os.path.join(base, href))
        if os.path.isfile(target):
            self.open_path(target)
        else:
            self.flash(f"No such file: {target}")

    def jump_to_anchor(self, slug: str):
        for line, (level, title) in zip(self._outline_lines, self._outline_titles):
            if html_export._slug(title) == slug.lower():
                self.goto_line(line)
                return
        self.flash(f"No heading named '{slug}'")

    # -- outline -----------------------------------------------------------

    def refresh_outline(self):
        lines = self.source().split("\n")
        entries, in_fence = [], False
        for number, line in enumerate(lines, start=1):
            if _FENCE_SRC_RE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            m = _HEADING_SRC_RE.match(line)
            if m:
                entries.append((number, len(m.group(1)), m.group(2).strip()))
        self._outline_lines = [e[0] for e in entries]
        self._outline_titles = [(e[1], e[2]) for e in entries]
        if not self.show_outline.get():
            return
        self.outline_list.delete(0, "end")
        for _, level, title in entries:
            self.outline_list.insert("end", "   " * (level - 1) + title)

    def on_outline_pick(self, _event=None):
        selection = self.outline_list.curselection()
        if selection and selection[0] < len(self._outline_lines):
            self.goto_line(self._outline_lines[selection[0]])

    def goto_line(self, line: int):
        self.editor.mark_set("insert", f"{line}.0")
        self.editor.see(f"{line}.0")
        self.editor.focus_set()
        self.update_status()

    # -- file handling -----------------------------------------------------

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved changes",
            f"Save changes to {os.path.basename(self.path) if self.path else 'Untitled'}?",
            parent=self,
        )
        if answer is None:
            return False
        if answer:
            return self.save()
        return True

    def new_file(self):
        if not self.confirm_discard():
            return
        self.editor.delete("1.0", "end")
        self.editor.edit_reset()
        self.path = None
        self.set_dirty(False)
        self.render_now()

    def open_file(self):
        if not self.confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self, title="Open Markdown file", filetypes=FILETYPES)
        if path:
            self.open_path(path)

    def open_path(self, path: str):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            messagebox.showerror("Could not open", str(exc), parent=self)
            return
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self.editor.edit_reset()
        self.editor.mark_set("insert", "1.0")
        self.editor.see("1.0")
        self.path = os.path.abspath(path)
        self._last_source = self.source()
        self.set_dirty(False)
        self._remember(self.path)
        self.render_now()
        self.flash(f"Opened {os.path.basename(path)}")

    def save(self) -> bool:
        if not self.path:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        path = filedialog.asksaveasfilename(
            parent=self, title="Save Markdown file", defaultextension=".md",
            initialfile=os.path.basename(self.path) if self.path else "untitled.md",
            filetypes=FILETYPES,
        )
        if not path:
            return False
        return self._write(path)

    def _write(self, path: str) -> bool:
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(self.source())
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc), parent=self)
            return False
        self.path = os.path.abspath(path)
        self._last_source = self.source()
        self.set_dirty(False)
        self._remember(self.path)
        self.flash(f"Saved {os.path.basename(path)}")
        return True

    def export_html(self):
        default = os.path.splitext(os.path.basename(self.path or "untitled"))[0] + ".html"
        path = filedialog.asksaveasfilename(
            parent=self, title="Export HTML", defaultextension=".html",
            initialfile=default,
            initialdir=os.path.dirname(self.path) if self.path else None,
            filetypes=[("HTML", "*.html *.htm"), ("All files", "*.*")],
        )
        if not path:
            return
        doc = P.parse(self.source(), self.opts())
        title = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(html_export.to_html(doc, title=title,
                                             flavor=self.flavor,
                                             opts=self.opts()))
        except OSError as exc:
            messagebox.showerror("Could not export", str(exc), parent=self)
            return
        self.flash(f"Exported {os.path.basename(path)}")

    def on_close(self):
        if not self.confirm_discard():
            return
        self._save_prefs()
        self.destroy()

    # -- editing helpers ---------------------------------------------------

    def _edit_op(self, op: str):
        try:
            getattr(self.editor, f"edit_{op}")()
        except tk.TclError:
            pass
        self.on_edit()

    def select_all(self):
        self.editor.tag_add("sel", "1.0", "end-1c")
        self.editor.mark_set("insert", "1.0")

    def selected_text(self) -> str:
        if self.editor.tag_ranges("sel"):
            return self.editor.get("sel.first", "sel.last")
        return ""

    def wrap_selection(self, marker: str, end_marker: str | None = None):
        end_marker = end_marker or marker
        editor = self.editor
        if editor.tag_ranges("sel"):
            start, end = editor.index("sel.first"), editor.index("sel.last")
            body = editor.get(start, end)
            if body.startswith(marker) and body.endswith(end_marker) and \
                    len(body) >= len(marker) + len(end_marker):
                new = body[len(marker):-len(end_marker)]
            else:
                new = f"{marker}{body}{end_marker}"
            editor.delete(start, end)
            editor.insert(start, new)
            editor.tag_add("sel", start, f"{start}+{len(new)}c")
        else:
            editor.insert("insert", marker + end_marker)
            editor.mark_set("insert", f"insert-{len(end_marker)}c")
        editor.focus_set()
        self.on_edit()

    def _selected_lines(self):
        editor = self.editor
        if editor.tag_ranges("sel"):
            first = int(editor.index("sel.first").split(".")[0])
            last_index = editor.index("sel.last")
            last = int(last_index.split(".")[0])
            if last_index.endswith(".0") and last > first:
                last -= 1
        else:
            first = last = int(editor.index("insert").split(".")[0])
        return first, last

    def toggle_prefix(self, prefix: str):
        editor = self.editor
        first, last = self._selected_lines()
        heading = prefix.strip().startswith("#")
        for line in range(first, last + 1):
            start, end = f"{line}.0", f"{line}.end"
            text = editor.get(start, end)
            stripped = text.lstrip()
            pad = text[:len(text) - len(stripped)]
            if stripped.startswith(prefix):
                new = pad + stripped[len(prefix):]
            elif heading and stripped.startswith("#"):
                new = pad + prefix + stripped.lstrip("#").lstrip()
            else:
                new = pad + prefix + stripped
            editor.delete(start, end)
            editor.insert(start, new)
        editor.focus_set()
        self.on_edit()

    def number_lines(self):
        editor = self.editor
        first, last = self._selected_lines()
        counter = 1
        for line in range(first, last + 1):
            start, end = f"{line}.0", f"{line}.end"
            text = editor.get(start, end).lstrip()
            text = re.sub(r"^\d{1,9}[.)][ \t]+", "", text)
            editor.delete(start, end)
            editor.insert(start, f"{counter}. {text}")
            counter += 1
        self.on_edit()

    def insert_block(self, text: str):
        editor = self.editor
        if editor.index("insert") != editor.index("insert linestart"):
            text = "\n" + text
        editor.insert("insert", text)
        editor.focus_set()
        self.on_edit()

    def insert_link(self):
        selection = self.selected_text()
        if selection:
            self.wrap_selection("[", "](url)")
        else:
            self.editor.insert("insert", "[text](url)")
            self.editor.mark_set("insert", "insert-11c")
        self.editor.focus_set()
        self.on_edit()

    def insert_image(self):
        path = filedialog.askopenfilename(
            parent=self, title="Insert image",
            filetypes=[("Images", "*.png *.gif *.ppm *.pgm"), ("All files", "*.*")],
        )
        if not path:
            return
        if self.path:
            try:
                path = os.path.relpath(path, os.path.dirname(self.path))
            except ValueError:
                pass
        alt = os.path.splitext(os.path.basename(path))[0]
        self.editor.insert("insert", f"![{alt}]({path.replace(os.sep, '/')})")
        self.on_edit()

    def insert_code_block(self):
        body = self.selected_text()
        if body:
            self.editor.delete("sel.first", "sel.last")
        self.insert_block(f"```\n{body or ''}\n```\n")
        if not body:
            self.editor.mark_set("insert", "insert-5c")

    def insert_table(self):
        self.insert_block(
            "\n| Column A | Column B |\n"
            "|:---------|---------:|\n"
            "| value    |        1 |\n"
            "| value    |        2 |\n\n"
        )

    def insert_toc(self):
        self.refresh_outline()
        if not self._outline_titles:
            self.flash("No headings to list")
            return
        top = min((lvl for lvl, _ in self._outline_titles), default=1)
        lines = [
            "  " * (level - top) + f"- [{title}](#{html_export._slug(title)})"
            for level, title in self._outline_titles
        ]
        self.insert_block("\n".join(lines) + "\n")

    # -- key handlers ------------------------------------------------------

    def on_return(self, _event):
        """Continue lists, quotes and indentation on Enter."""
        editor = self.editor
        line = editor.get("insert linestart", "insert")
        m = _LIST_SRC_RE.match(line)
        if m:
            indent, marker, gap, task, body = m.groups()
            if not body.strip():  # empty item: end the list instead
                editor.delete("insert linestart", "insert")
                return "break"
            if marker[-1] in ".)":
                try:
                    marker = f"{int(marker[:-1]) + 1}{marker[-1]}"
                except ValueError:
                    pass
            prefix = f"{indent}{marker}{gap}" + ("[ ] " if task else "")
            editor.insert("insert", "\n" + prefix)
            editor.see("insert")
            self.on_edit()
            return "break"
        m = re.match(r"^(\s*>[ \t]?)+", line)
        if m and line.strip() not in (">", ">>"):
            editor.insert("insert", "\n" + m.group(0))
            self.on_edit()
            return "break"
        m = re.match(r"^[ \t]+", line)
        if m:
            editor.insert("insert", "\n" + m.group(0))
            self.on_edit()
            return "break"
        return None

    def on_tab(self, _event):
        editor = self.editor
        if editor.tag_ranges("sel"):
            first, last = self._selected_lines()
            for line in range(first, last + 1):
                editor.insert(f"{line}.0", "  ")
            self.on_edit()
            return "break"
        editor.insert("insert", "  ")
        self.on_edit()
        return "break"

    def on_shift_tab(self, _event):
        editor = self.editor
        first, last = self._selected_lines()
        for line in range(first, last + 1):
            text = editor.get(f"{line}.0", f"{line}.end")
            strip = min(2, len(text) - len(text.lstrip(" ")))
            if strip:
                editor.delete(f"{line}.0", f"{line}.{strip}")
        self.on_edit()
        return "break"

    # -- help windows ------------------------------------------------------

    def _doc_window(self, title: str, markdown: str):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry(f"{self.px(760)}x{self.px(680)}")
        win.configure(background=self.theme["bg"])
        text = tk.Text(win, borderwidth=0, highlightthickness=0, state="disabled")
        scroll = ttk.Scrollbar(win, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        win.rowconfigure(0, weight=1)
        win.columnconfigure(0, weight=1)
        renderer = MarkdownRenderer(text, self.theme, self.base_size,
                                    flavor=self.flavor)
        text.configure(state="normal")
        renderer.render(P.parse(markdown, self.opts()), opts=self.opts())
        text.configure(state="disabled")
        text.bind("<Configure>", lambda e: renderer.resize_rules(e.width))
        text.bind("<MouseWheel>",
                  lambda e: (text.yview_scroll(int(-e.delta / 120), "units"), "break")[1])
        win.bind("<Escape>", lambda e: win.destroy())
        win.transient(self)
        return win

    def show_emulation_demo(self):
        return self._doc_window(
            f"Emulation modes - showing {self.flavor.name}", samples.EMULATION)

    def show_cheatsheet(self):
        return self._doc_window("Markdown cheat sheet", samples.CHEATSHEET)

    def show_welcome(self):
        return self._doc_window("Welcome to mdedit", samples.WELCOME)

    def show_about(self):
        messagebox.showinfo(
            "About mdedit",
            "mdedit - a Markdown editor in pure Python.\n\n"
            "Parser, renderer and HTML exporter are all hand-written on top of "
            "the standard library. No third-party packages, no network access: "
            "the only files touched are the ones you open.",
            parent=self,
        )

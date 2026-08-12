"""Draw a parsed Markdown document into a Tk ``Text`` widget.

Everything is done with Tk text tags, embedded frames (for rules) and
``PhotoImage`` (for local PNG/GIF images).  No HTML engine, no browser, no
network -- images are only ever loaded from local paths relative to the
document being previewed.

How the result looks is driven by the active flavour (see ``flavors.py``):
fonts, heading scale, and the treatment of quotes, tables, code blocks and
call-outs all come from there.
"""

from __future__ import annotations

import os
import re
import textwrap
import tkinter as tk
import tkinter.font as tkfont
from typing import List, Optional

from . import flavors
from . import parser as P

# Base chrome colours.  A flavour's palette is layered on top of these for
# the preview; the editor and the window furniture keep the base values.
LIGHT = {
    "name": "light",
    "bg": "#ffffff",
    "fg": "#24292f",
    "muted": "#57606a",
    "select": "#b6d7ff",
    "cursor": "#0969da",
    "link": "#0969da",
    "code_bg": "#eff1f3",
    "code_fg": "#8250df",
    "block_bg": "#f6f8fa",
    "quote_bg": "#f3f5f7",
    "quote_fg": "#4a5460",
    "rule": "#d8dee4",
    "table_head": "#eceff2",
    "zebra": "#fafbfc",
    "mark_bg": "#fff3b0",
    "tag_bg": "#eef1f5",
    "tag_fg": "#0969da",
    "panels": flavors.PANELS_LIGHT,
    "gutter_bg": "#f6f8fa",
    "gutter_fg": "#9aa4ae",
    "editor_bg": "#ffffff",
    "editor_fg": "#1f2328",
    "status_bg": "#f0f2f4",
    "match": "#ffe08a",
}

DARK = {
    "name": "dark",
    "bg": "#0d1117",
    "fg": "#e6edf3",
    "muted": "#9198a1",
    "select": "#264f78",
    "cursor": "#6cb0f8",
    "link": "#6cb0f8",
    "code_bg": "#262c36",
    "code_fg": "#d2a8ff",
    "block_bg": "#161b22",
    "quote_bg": "#151b23",
    "quote_fg": "#b3bcc6",
    "rule": "#30363d",
    "table_head": "#1c222b",
    "zebra": "#11161d",
    "mark_bg": "#6b5300",
    "tag_bg": "#1c2430",
    "tag_fg": "#6cb0f8",
    "panels": flavors.PANELS_DARK,
    "gutter_bg": "#0d1117",
    "gutter_fg": "#5a636d",
    "editor_bg": "#0d1117",
    "editor_fg": "#dfe6ee",
    "status_bg": "#161b22",
    "match": "#7a5d00",
}

THEMES = {"light": LIGHT, "dark": DARK}

#: Column dividers, row dividers, an outer frame, zebra striping.  These
#: follow the exported CSS rather than leading it: ``BASE_CSS`` puts a border
#: on every ``th``/``td``, so most modes really are a full grid on the page,
#: and only the two that clear it -- Visual Studio and Hugo, which keep just
#: ``border-bottom`` -- are row lines alone.  "plain" and "grid" therefore
#: draw the same box; what still separates them is the palette, the header
#: tint and the striping.
_TABLE_STYLES = {
    #            columns, rows,  frame, zebra
    "plain": (True, True, True, False),
    "zebra": (True, True, True, True),
    "grid": (True, True, True, False),
    "lines": (False, True, False, False),
}


#: Every flavor names its own preferred fonts (mostly Windows ones), which
#: this falls back past -- not to -- so a flavor that never heard of Menlo
#: or DejaVu Sans still ends up with *some* real body/mono family on macOS
#: and Linux, rather than silently landing on a fixed-font sentinel that
#: isn't an actual family name (see below).
_BODY_FALLBACKS = ["Segoe UI Variable Text", "Segoe UI", "Helvetica Neue",
                   "DejaVu Sans", "Arial"]
_MONO_FALLBACKS = ["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Menlo",
                   "Monaco", "Courier New"]


def _pick_family(candidates, extra_fallbacks, named_font):
    try:
        available = {f.lower() for f in tkfont.families()}
    except tk.TclError:  # pragma: no cover - needs a display
        return named_font
    for name in (*candidates, *extra_fallbacks):
        if name.lower() in available:
            return name
    # Every named candidate is missing -- fall back to whatever family is
    # actually behind Tk's own "TkDefaultFont"/"TkFixedFont", rather than
    # that name itself: it names a *font*, not a font *family*, and using
    # it as a family= value doesn't reliably resolve to it (on macOS it has
    # landed on the proportional system UI font even for TkFixedFont).
    try:
        return tkfont.nametofont(named_font).actual("family")
    except tk.TclError:  # pragma: no cover - needs a display
        return named_font


def body_family(candidates=None) -> str:
    return _pick_family(candidates or (), _BODY_FALLBACKS, "TkDefaultFont")


def mono_family(candidates=None) -> str:
    return _pick_family(candidates or (), _MONO_FALLBACKS, "TkFixedFont")


class MarkdownRenderer:
    """Renders a :class:`parser.Document` into a ``tk.Text`` widget."""

    def __init__(self, widget: tk.Text, theme: dict, base_size: int = 11,
                 on_link=None, flavor=None):
        self.text = widget
        self.flavor = flavor or flavors.DEFAULT
        self.base_theme = theme
        self.theme = self._merge(theme)
        self.base_size = base_size
        self.on_link = on_link
        self.scale = max(1.0, widget.winfo_fpixels("1i") / 96.0)
        self.base_dir = ""
        self._fonts = {}
        self._images: List[tk.PhotoImage] = []
        self._windows: List[tk.Widget] = []
        self._link_targets = {}
        self._link_seq = 0
        self._list_depth = 0
        self.opts = P.DEFAULT
        self._margin_stack: List[tuple] = []
        self._margin_color = self._probe_margin_color()
        self._doc: Optional[P.Document] = None
        self._build_fonts()
        self._configure_tags()

    # -- appearance --------------------------------------------------------

    def px(self, value: float) -> int:
        """Scale a design pixel to this display's density."""
        return int(round(value * self.scale))

    def _probe_margin_color(self) -> bool:
        """Tk 8.6.6+ can tint a paragraph's left margin; older Tk cannot."""
        try:
            self.text.tag_configure("_probe", lmargincolor="#000000")
            self.text.tag_delete("_probe")
            return True
        except tk.TclError:
            return False

    def _merge(self, base: dict) -> dict:
        merged = dict(base)
        merged.update(self.flavor.palette(base.get("name", "light")))
        merged["name"] = base.get("name", "light")
        return merged

    def _metric(self, key, default=None):
        return self.flavor.metric(key, default)

    def _size(self) -> int:
        return max(7, self.base_size + int(self._metric("size_delta", 0)))

    def _build_fonts(self):
        s = self._size()
        body = body_family(self._metric("body_fonts"))
        mono = mono_family(self._metric("mono_fonts"))
        ms = max(7, s + int(self._metric("mono_delta", -1)))
        f = self._fonts
        f["body"] = tkfont.Font(family=body, size=s)
        f["bold"] = tkfont.Font(family=body, size=s, weight="bold")
        f["italic"] = tkfont.Font(family=body, size=s, slant="italic")
        f["bolditalic"] = tkfont.Font(
            family=body, size=s, weight="bold", slant="italic"
        )
        f["small"] = tkfont.Font(family=body, size=max(6, s - 3))
        f["mono"] = tkfont.Font(family=mono, size=ms)
        f["mono_bold"] = tkfont.Font(family=mono, size=ms, weight="bold")
        f["mono_italic"] = tkfont.Font(family=mono, size=ms, slant="italic")
        f["mono_bolditalic"] = tkfont.Font(
            family=mono, size=ms, weight="bold", slant="italic"
        )
        scale = self._metric("headings",
                             {1: 2.0, 2: 1.5, 3: 1.25, 4: 1.1, 5: 1.0, 6: 0.9})
        for level in range(1, 7):
            size = max(7, int(round(s * scale.get(level, 1.0))))
            f[f"h{level}"] = tkfont.Font(family=body, size=size, weight="bold")
            f[f"h{level}i"] = tkfont.Font(
                family=body, size=size, weight="bold", slant="italic"
            )

    def _configure_tags(self):
        t, th, f = self.text, self.theme, self._fonts
        for name in t.tag_names():
            if name.startswith(("ind_", "mar_", "sty_")):
                t.tag_delete(name)

        t.configure(
            background=th["bg"], foreground=th["fg"], insertbackground=th["cursor"],
            selectbackground=th["select"], font=f["body"], wrap="word",
            padx=self.px(self._metric("pad_x", 22)), pady=self.px(16),
            spacing1=0, spacing2=2, spacing3=self.px(2),
            borderwidth=0, highlightthickness=0,
        )

        for level in range(1, 7):
            t.tag_configure(
                f"h{level}",
                font=f[f"h{level}"],
                foreground=th["muted"] if level == 6 else th["fg"],
                spacing1=int(f["body"].metrics("linespace")
                             * (1.1 if level < 3 else 0.8)),
                spacing3=self.px(4),
            )

        t.tag_configure(
            "p", spacing3=int(f["body"].metrics("linespace")
                              * float(self._metric("para_gap", 0.55)))
        )

        # Inline styles, in a proportional and a monospaced flavour.
        t.tag_configure("b", font=f["bold"])
        t.tag_configure("i", font=f["italic"])
        t.tag_configure("bi", font=f["bolditalic"])
        t.tag_configure("mb", font=f["mono_bold"])
        t.tag_configure("mi", font=f["mono_italic"])
        t.tag_configure("mbi", font=f["mono_bolditalic"])
        t.tag_configure("s", overstrike=True, foreground=th["muted"])
        t.tag_configure("ms", overstrike=True, foreground=th["muted"])
        underline = bool(self._metric("link_underline", True))
        t.tag_configure("link", foreground=th["link"], underline=underline)
        t.tag_configure("mlink", foreground=th["link"], underline=underline)
        t.tag_configure("mark", background=th["mark_bg"], foreground=th["fg"])
        t.tag_configure("mmark", background=th["mark_bg"], foreground=th["fg"])
        t.tag_configure(
            "code", font=f["mono"], background=th["code_bg"],
            foreground=th["code_fg"],
        )
        t.tag_configure("mcode", font=f["mono"], foreground=th["code_fg"])

        t.tag_configure(
            "codeblock", font=f["mono"], background=th["block_bg"],
            foreground=th["fg"], spacing1=1, spacing2=1, spacing3=1,
        )
        t.tag_configure("codelang", font=f["mono"], foreground=th["muted"])
        t.tag_configure("codeborder", font=f["mono"], background=th["block_bg"],
                        foreground=th["rule"])
        quote_font = f["italic"] if self._metric("quote_italic") else f["body"]
        t.tag_configure("quote", background=th["quote_bg"],
                        foreground=th["quote_fg"], font=quote_font)
        t.tag_configure("quoteplain", foreground=th["quote_fg"],
                        font=quote_font)
        t.tag_configure("tagpill", background=th["tag_bg"],
                        foreground=th["tag_fg"])
        t.tag_configure("mtagpill", font=f["mono"], background=th["tag_bg"],
                        foreground=th["tag_fg"])
        t.tag_configure("template", font=f["mono"], background=th["code_bg"],
                        foreground=th["muted"])
        t.tag_configure("mtemplate", font=f["mono"], foreground=th["muted"])
        t.tag_configure("frontmatter", font=f["mono"], background=th["block_bg"],
                        foreground=th["fg"])
        t.tag_configure("fmkey", font=f["mono_bold"], background=th["block_bg"],
                        foreground=th["muted"])
        t.tag_configure("bullet", foreground=th["muted"])
        # Column alignment depends on every row staying on one physical
        # line; word-wrap would break a wide row at a different point than
        # its neighbours and throw the columns out of line with each other.
        # A wide table just runs past the pane edge instead -- scroll or
        # widen the window to see the rest of it.
        t.tag_configure("table", font=f["mono"], wrap="none")
        t.tag_configure("tablehead", font=f["mono_bold"],
                        background=th["table_head"])
        t.tag_configure("tablezebra", font=f["mono"], background=th["zebra"])
        t.tag_configure("tablerule", font=f["mono"], foreground=th["rule"])
        # Created after the row tags so it out-ranks them: a divider keeps the
        # rule colour and the upright font while still sitting on whatever
        # background its row has (the header tint, or a zebra stripe).
        t.tag_configure("tablesep", font=f["mono"], foreground=th["rule"])
        t.tag_configure("imgalt", font=f["italic"], foreground=th["muted"])

        for kind, (bg, accent) in th["panels"].items():
            t.tag_configure(f"panel_{kind}", background=bg)
            t.tag_configure(f"panelttl_{kind}", background=bg, foreground=accent,
                            font=f["bold"])

        t.tag_configure("search", background=th["match"], foreground=th["fg"])
        t.tag_raise("search")

    def set_theme(self, theme: dict):
        self.base_theme = theme
        self.theme = self._merge(theme)
        self._configure_tags()

    def set_flavor(self, flavor):
        self.flavor = flavor or flavors.DEFAULT
        self.theme = self._merge(self.base_theme)
        self._build_fonts()
        self._configure_tags()

    def set_base_size(self, size: int):
        self.base_size = max(7, min(32, size))
        self._build_fonts()
        self._configure_tags()

    # -- rendering ---------------------------------------------------------

    def render(self, doc: P.Document, base_dir: str = "", opts=None):
        self._doc = doc
        self.base_dir = base_dir
        self.opts = opts or P.DEFAULT
        t = self.text
        state = t.cget("state")
        t.configure(state="normal")
        for w in self._windows:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._windows.clear()
        self._images.clear()
        for name in self._link_targets:
            t.tag_delete(name)
        self._link_targets.clear()
        self._link_seq = 0
        self._list_depth = 0
        self._margin_stack.clear()
        t.delete("1.0", "end")

        for block in doc.children:
            self._block(block, indent=0, tags=())
        t.delete("end-1c", "end")  # drop the final stray newline
        t.configure(state=state if state != "normal" else "normal")
        self.resize_rules()

    # ``_ins`` is the single place text reaches the widget.
    def _ins(self, s: str, tags=()):
        self.text.insert("end", s, tuple(tags))

    def _indent_tag(self, first: int, hanging: int, color: str = "") -> str:
        prefix = "mar" if color else "ind"
        name = f"{prefix}_{first}_{hanging}_{color.lstrip('#')}"
        if name not in self.text.tag_names():
            opts = dict(lmargin1=first, lmargin2=hanging, rmargin=self.px(8))
            if color and self._margin_color:
                opts["lmargincolor"] = color
            self.text.tag_configure(name, **opts)
        return name

    def _blank_line(self, indent: int, tags: tuple):
        """A spacer line after a block, carrying the block's indentation."""
        ind = (self._indent_tag(indent, indent),) if indent else ()
        self._ins("\n", tuple(tags) + ind)

    def _block(self, node, indent: int, tags: tuple):
        base = tuple(tags) + ((self._margin_indent(indent),) if indent else ())

        if isinstance(node, P.Heading):
            self._inlines(node.children, base + (f"h{node.level}",),
                          heading=node.level)
            self._ins("\n", base + (f"h{node.level}",))
            if node.level in self._metric("heading_rules", (1, 2)):
                self._rule(thin=True)

        elif isinstance(node, P.Paragraph):
            self._inlines(node.children, base + ("p",))
            self._ins("\n", base + ("p",))

        elif isinstance(node, P.CodeBlock):
            self._code_block(node, indent, tags)

        elif isinstance(node, P.BlockQuote):
            self._quote(node, indent, tags)

        elif isinstance(node, P.Panel):
            self._panel(node, indent, tags)

        elif isinstance(node, P.FrontMatter):
            self._front_matter(node, indent, tags)

        elif isinstance(node, P.HtmlBlock):
            for child in node.children:  # already converted to real nodes
                self._block(child, indent, tags)

        elif isinstance(node, P.ThematicBreak):
            self._rule()

        elif isinstance(node, P.ListBlock):
            self._list(node, indent, tags)

        elif isinstance(node, P.Table):
            self._table(node, indent, tags)

    # -- coloured margins (quote bars and panel edges) ---------------------

    def _push_margin(self, width: int, color: str):
        self._margin_stack.append((width, color))

    def _pop_margin(self):
        if self._margin_stack:
            self._margin_stack.pop()

    def _margin_indent(self, indent: int) -> str:
        """An indent tag that keeps any enclosing coloured margin."""
        if self._margin_stack:
            width, color = self._margin_stack[-1]
            if indent >= width:
                return self._indent_tag(indent, indent, color)
        return self._indent_tag(indent, indent)

    # -- individual blocks -------------------------------------------------

    def _quote(self, node: P.BlockQuote, indent: int, tags: tuple):
        style = self._metric("quote_style", "tint")
        bar = self.px(self._metric("quote_bar", 7))
        if style == "tint":
            inner = indent + self.px(18)
            extra: tuple = ("quote",)
        else:
            inner = indent + bar
            extra = ("quoteplain",) if style == "bar" else ("quote",)
            self._push_margin(inner, self.theme["rule"])
        for child in node.children:
            self._block(child, inner, tuple(tags) + extra)
        if style != "tint":
            self._pop_margin()

    def _panel(self, node: P.Panel, indent: int, tags: tuple):
        kind = node.kind if node.kind in self.theme["panels"] else "note"
        bg, accent = self.theme["panels"][kind]
        inner = indent + self.px(self._metric("quote_bar", 7))
        self._push_margin(inner, accent)
        style = (f"panel_{kind}",)

        title = node.title
        if not title and self._metric("panel_labels", True):
            title = flavors.PANEL_LABELS[kind]
        if title:
            self._ins(f" {flavors.PANEL_ICONS[kind]}  {title}\n",
                      tuple(tags) + (self._margin_indent(inner),
                                     f"panelttl_{kind}"))
        for child in node.children:
            self._block(child, inner, tuple(tags) + style)
        self._pop_margin()

    def _front_matter(self, node: P.FrontMatter, indent: int, tags: tuple):
        """The metadata header, shown the way the platform shows it."""
        if not self._metric("show_front_matter", True) or not node.pairs:
            return
        pad = indent + self.px(10)
        ind = self._margin_indent(pad)
        base = tuple(tags) + (ind, "frontmatter")
        keys = [k for k, _ in node.pairs if k]
        key_width = min(max((len(k) for k in keys), default=0) + 2, 24)
        rows = [(f" {k}".ljust(key_width) if k else "", v)
                for k, v in node.pairs]
        width = min(max((key_width + len(v) + 2 for _, v in rows), default=0), 160)

        self._ins(" " * width + "\n", base)
        for key, value in rows:
            if key:
                self._ins(key, tuple(tags) + (ind, "fmkey"))
            self._ins(f" {value}".ljust(max(0, width - len(key))) + "\n", base)
        self._ins(" " * width + "\n", base)
        self._blank_line(indent, tags)

    def _code_block(self, node: P.CodeBlock, indent: int, tags: tuple):
        pad = indent + self.px(14)
        ind = self._margin_indent(pad)
        base = tuple(tags) + (ind, "codeblock")
        lines = node.text.split("\n")
        while lines and not lines[-1].strip():
            lines.pop()
        width = min(max((len(l) for l in lines), default=0) + 3, 160)
        bordered = self._metric("code_style", "filled") == "bordered"

        if bordered:
            self._ins("─" * width + "\n", tuple(tags) + (ind, "codeborder"))
        if node.lang:
            self._ins(f" {node.lang}".ljust(width) + "\n",
                      tuple(tags) + (ind, "codeblock", "codelang"))
        elif not bordered:
            self._ins(" " * width + "\n", base)
        for line in lines:
            self._ins((" " + line).ljust(width) + "\n", base)
        if bordered:
            self._ins("─" * width + "\n", tuple(tags) + (ind, "codeborder"))
        else:
            self._ins(" " * width + "\n", base)
        self._blank_line(indent, tags)

    def _list(self, node: P.ListBlock, indent: int, tags: tuple):
        body = self._fonts["body"]
        self._list_depth += 1
        color = self._margin_stack[-1][1] if self._margin_stack else ""
        for k, item in enumerate(node.items):
            if item.task is not None:
                marker = "☑  " if item.task else "☐  "
            elif node.ordered:
                marker = f"{node.start + k}.  "
            else:
                marker = "•  "
            hang = indent + body.measure(marker) + self.px(4)
            tag = self._indent_tag(indent + self.px(4), hang, color)
            self._ins(marker, tuple(tags) + (tag, "bullet"))

            children = item.children or [P.Paragraph(children=[])]
            first = children[0]
            if isinstance(first, P.Paragraph):
                self._inlines(first.children, tuple(tags) + (tag,))
                self._ins("\n", tuple(tags) + (tag,)
                          + (("p",) if not node.tight else ()))
                rest = children[1:]
            else:
                self._ins("\n", tuple(tags) + (tag,))
                rest = children
            for child in rest:
                self._block(child, hang, tags)
        self._list_depth -= 1
        if not self._list_depth:  # only the outermost list gets trailing space
            self._blank_line(indent, tags)

    def _table(self, node: P.Table, indent: int, tags: tuple):
        cols = len(node.aligns)
        if not cols:
            return
        seps, row_rule, frame, zebra = _TABLE_STYLES.get(
            self._metric("table_style", "plain"), _TABLE_STYLES["plain"])

        header = [P.plain_text(c) for c in node.header]
        body_rows = [[P.plain_text(c) for c in row] for row in node.rows]
        widths = [len(header[c]) for c in range(cols)]
        for row in body_rows:
            for c in range(cols):
                widths[c] = max(widths[c], len(row[c]))
        widths = [min(w, 40) for w in widths]

        ind = self._margin_indent(indent + self.px(8))
        base = tuple(tags) + (ind, "table")

        def pad(plain: str, width: int, align: str):
            gap = max(0, width - len(plain))
            if align == "right":
                return " " * gap, ""
            if align == "center":
                left = gap // 2
                return " " * left, " " * (gap - left)
            return "", " " * gap

        def emit(cells, plains, style):
            # A cell longer than its column's 40-char cap wraps onto extra
            # physical lines rather than stretching the column or getting
            # cut off -- but only cells that actually need it: one that
            # fits stays a single line rendered from the real inline
            # nodes, keeping its bold/code/link formatting. A cell that
            # wraps loses that formatting for the lines it wraps onto
            # (wrapping happens on plain text, not the styled node tree),
            # and the row grows to whichever cell wrapped the most.
            wrapped = [
                None if len(plains[c]) <= widths[c]
                else (textwrap.wrap(plains[c], widths[c]) or [""])
                for c in range(cols)
            ]
            height = max((len(w) for w in wrapped if w is not None), default=1)
            for line_no in range(height):
                if frame:
                    self._ins("│", base + style + ("tablesep",))
                for c in range(cols):
                    width, lines = widths[c], wrapped[c]
                    if lines is None:
                        if line_no == 0:
                            left, right = pad(plains[c], width, node.aligns[c])
                            self._ins(" " + left, base + style)
                            self._inlines(cells[c], base + style, mono=True)
                            self._ins(right + " ", base + style)
                        else:
                            self._ins(" " + " " * width + " ", base + style)
                    else:
                        text = lines[line_no] if line_no < len(lines) else ""
                        left, right = pad(text, width, node.aligns[c])
                        self._ins(" " + left + text + right + " ", base + style)
                    if c < cols - 1:
                        if seps:
                            self._ins("│", base + style + ("tablesep",))
                        else:
                            self._ins(" ", base + style)
                if frame:
                    self._ins("│", base + style + ("tablesep",))
                # The row's tint stops at the frame: a tagged newline would
                # run the header or zebra background on to the pane edge.
                self._ins("\n", base)

        def hline(kind: str):
            """A horizontal line, junctioned so it meets the verticals."""
            if not seps:
                span = sum(w + 2 for w in widths) + cols - 1
                self._ins("─" * span + "\n", base + ("tablerule",))
                return
            left, mid, right = {"top": "┌┬┐", "mid": "├┼┤", "bot": "└┴┘"}[kind]
            cells = ("─" * (widths[c] + 2) for c in range(cols))
            self._ins(left + mid.join(cells) + right + "\n",
                      base + ("tablerule",))

        if frame:
            hline("top")
        emit(node.header, header, ("tablehead",))
        for k, (row, plains) in enumerate(zip(node.rows, body_rows)):
            if k == 0 or row_rule:
                hline("mid")
            emit(row, plains, ("tablezebra",) if zebra and k % 2 else ())
        hline("bot")
        self._blank_line(indent, tags)

    def _rule(self, thin: bool = False):
        frame = tk.Frame(
            self.text, height=self.px(1) if thin else self.px(2),
            background=self.theme["rule"], borderwidth=0,
        )
        self._windows.append(frame)
        self.text.window_create("end", window=frame, padx=self.px(4),
                                pady=self.px(2) if thin else self.px(9))
        self._ins("\n", ("p",) if thin else ())

    def resize_rules(self, width: Optional[int] = None):
        """Stretch horizontal rules to the current widget width."""
        if width is None:
            width = self.text.winfo_width()
        span = max(80, width - self.px(60))
        for frame in self._windows:
            try:
                frame.configure(width=span)
            except tk.TclError:
                pass

    # -- inline ------------------------------------------------------------

    def _inlines(self, nodes, tags: tuple, styles=(), mono: bool = False,
                 heading: int = 0):
        pfx = "m" if mono else ""
        for node in nodes:
            if isinstance(node, P.Text):
                self._ins(node.text, tags + self._style_tags(styles, pfx, heading))
            elif isinstance(node, P.Code):
                self._ins(node.text, tags + (pfx + "code",) + tuple(
                    t for t in self._style_tags(styles, pfx, heading)
                    if t.endswith("link")))
            elif isinstance(node, P.Emph):
                self._inlines(node.children, tags, tuple(styles) + ("i",),
                              mono, heading)
            elif isinstance(node, P.Strong):
                self._inlines(node.children, tags, tuple(styles) + ("b",),
                              mono, heading)
            elif isinstance(node, P.Strike):
                self._inlines(node.children, tags, tuple(styles) + ("s",),
                              mono, heading)
            elif isinstance(node, P.Mark):
                self._inlines(node.children, tags, tuple(styles) + ("mk",),
                              mono, heading)
            elif isinstance(node, P.Styled):
                extra = self._styled_tag(node)
                self._inlines(node.children, tags + extra, styles, mono, heading)
            elif isinstance(node, P.Link):
                tag = self._link_tag(node.href, node.title)
                self._inlines(node.children, tags + (tag,),
                              tuple(styles) + ("link",), mono, heading)
            elif isinstance(node, P.Image):
                self._image(node, tags)
            elif isinstance(node, P.WikiLink):
                self._wikilink(node, tags, styles, mono, heading)
            elif isinstance(node, P.Tag):
                self._ins(f" #{node.name} ",
                          tags + (pfx + "tagpill",))
            elif isinstance(node, P.Template):
                self._ins(node.text, tags + (pfx + "template",))
            elif isinstance(node, P.HardBreak):
                self._ins("\n", tags)
            elif isinstance(node, P.SoftBreak):
                self._ins(" ", tags)

    def _style_tags(self, styles, pfx: str, heading: int = 0) -> tuple:
        styles = set(styles)
        out = []
        bold, italic = "b" in styles, "i" in styles
        if heading:
            if italic:
                out.append(f"h{heading}i")
        elif bold and italic:
            out.append(pfx + "bi")
        elif bold:
            out.append(pfx + "b")
        elif italic:
            out.append(pfx + "i")
        if "s" in styles:
            out.append(pfx + "s")
        if "mk" in styles:
            out.append(pfx + "mark")
        if "link" in styles:
            out.append(pfx + "link")
        return tuple(out)

    def _styled_tag(self, node: P.Styled) -> tuple:
        """A tag carrying inline HTML presentation: colour, u, sup, sub."""
        key = f"sty_{node.color}_{node.background}_{node.variant}"
        name = re.sub(r"[^A-Za-z0-9_]", "", key)
        if name in self.text.tag_names():
            return (name,)
        opts = {}
        if node.color:
            opts["foreground"] = node.color
        if node.background:
            opts["background"] = node.background
        if node.variant == "u":
            opts["underline"] = True
        elif node.variant == "sup":
            opts["offset"] = self.px(5)
            opts["font"] = self._fonts["small"]
        elif node.variant == "sub":
            opts["offset"] = -self.px(3)
            opts["font"] = self._fonts["small"]
        try:
            self.text.tag_configure(name, **opts)
        except tk.TclError:  # a colour Tk does not know
            opts.pop("foreground", None)
            opts.pop("background", None)
            self.text.tag_configure(name, **opts)
        return (name,)

    def _link_tag(self, href: str, title: str = "") -> str:
        self._link_seq += 1
        name = f"lnk{self._link_seq}"
        self._link_targets[name] = href
        t = self.text
        t.tag_configure(name)
        t.tag_bind(name, "<Enter>", lambda e, h=href: self._hover(h, True))
        t.tag_bind(name, "<Leave>", lambda e, h=href: self._hover(h, False))
        t.tag_bind(name, "<Button-1>", lambda e, h=href: self._click(h))
        return name

    def _hover(self, href: str, entering: bool):
        self.text.configure(cursor="hand2" if entering else "")
        if self.on_link:
            self.on_link(href, "enter" if entering else "leave")

    def _click(self, href: str):
        if self.on_link:
            self.on_link(href, "click")

    def _wikilink(self, node: P.WikiLink, tags: tuple, styles, mono: bool,
                  heading: int):
        """[[Note]] links to a file in the same folder; ![[pic]] embeds it."""
        target = node.target.split("#")[0].split("^")[0].strip() or node.target
        stem, ext = os.path.splitext(target)
        if node.embed and ext.lower() in (".png", ".gif", ".pgm", ".ppm"):
            self._image(P.Image(alt=node.display, src=target), tags)
            return
        href = target if ext else target + ".md"
        tag = self._link_tag(href)
        label = ("⧉ " if node.embed else "") + node.display
        self._ins(label, tags + (tag,)
                  + self._style_tags(tuple(styles) + ("link",),
                                     "m" if mono else "", heading))

    def _image(self, node: P.Image, tags: tuple):
        path = node.src
        loaded = None
        if path and "://" not in path and self.opts.images:
            full = path if os.path.isabs(path) else os.path.join(self.base_dir, path)
            if os.path.isfile(full) and \
                    full.lower().endswith((".png", ".gif", ".pgm", ".ppm")):
                try:
                    img = tk.PhotoImage(file=full)
                    avail = max(120, self.text.winfo_width() - self.px(80))
                    if img.width() > avail:
                        factor = img.width() // avail + 1
                        img = img.subsample(factor, factor)
                    loaded = img
                except tk.TclError:
                    loaded = None
        if loaded is not None:
            self._images.append(loaded)
            self.text.image_create("end", image=loaded, padx=2, pady=4)
        else:
            label = node.alt or os.path.basename(path) or "image"
            self._ins(f"\U0001f5bc {label}", tags + ("imgalt",))

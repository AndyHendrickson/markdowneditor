"""Turn a useful subset of HTML into the node tree Markdown already uses.

The point is that everything downstream stays simple: ``<table>`` becomes a
:class:`parser.Table`, ``<ul>`` a :class:`parser.ListBlock`, ``<b>`` a
:class:`parser.Strong`.  The Tk preview then draws HTML with the same code
that draws Markdown, and the HTML exporter can pass the original source
straight through.

Built on ``html.parser`` from the standard library -- no engine, no network.

Tags that could fetch or run something (``script``, ``style``, ``iframe`` and
friends) are dropped along with their content, so an exported page cannot
reach the network no matter what the document contains.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import List

from . import parser as P

#: Dropped entirely, content and all: these load or execute things.
DROPPED = {
    "script", "style", "iframe", "object", "embed", "applet", "noscript",
    "link", "meta", "base", "form", "input", "button", "select", "textarea",
    "svg", "canvas", "audio", "video", "source", "track", "portal",
}

VOID = {"br", "hr", "img", "wbr", "col", "area"}

#: Inline elements that map onto an existing node type.
INLINE_WRAPPERS = {
    "b": "strong", "strong": "strong",
    "i": "em", "em": "em", "cite": "em", "dfn": "em", "address": "em",
    "s": "del", "del": "del", "strike": "del",
    "mark": "mark", "ins": "u", "u": "u",
    "sup": "sup", "sub": "sub",
}

#: Inline elements whose text becomes a code span.
CODEISH = {"code", "kbd", "samp", "tt", "var"}

#: Elements that contribute nothing themselves; their children float up.
TRANSPARENT = {
    "div", "section", "article", "main", "header", "footer", "aside", "nav",
    "figure", "figcaption", "picture", "span", "font", "small", "big",
    "abbr", "acronym", "time", "data", "label", "center", "colgroup",
    "hgroup", "html", "body", "head", "title", "dl", "dt", "dd", "menu",
    "fieldset", "legend", "caption", "template", "slot", "ruby", "bdi", "bdo",
    "q", "output", "progress", "meter", "map", "param", "optgroup", "option",
}

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "center", "dd", "details",
    "dialog", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer",
    "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr",
    "iframe", "li", "main", "menu", "nav", "ol", "p", "pre", "script",
    "section", "source", "style", "summary", "table", "tbody", "td", "tfoot",
    "th", "thead", "tr", "ul", "html", "body", "head", "caption", "col",
    "colgroup", "legend", "noscript", "optgroup", "option", "param",
    "textarea", "title", "track",
}

_ATTR_RE = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s"'>]+))?"""
)
_COLOR_RE = re.compile(r"(?:^|;)\s*color\s*:\s*([^;]+)", re.I)
_BG_RE = re.compile(r"(?:^|;)\s*background(?:-color)?\s*:\s*([^;]+)", re.I)
_ALIGN_RE = re.compile(r"(?:^|;)\s*text-align\s*:\s*(left|right|center)", re.I)
_SAFE_COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20}|rgba?\([^)]*\))$")


def parse_attrs(text: str) -> dict:
    """Attributes from the inside of a tag, lower-cased and unquoted."""
    out = {}
    for name, value in _ATTR_RE.findall(text):
        if value and value[:1] in "\"'":
            value = value[1:-1]
        out[name.lower()] = value
    return out


def colors_of(attrs: dict) -> tuple:
    """(foreground, background) from a style="" or colour attribute."""
    style = attrs.get("style", "")
    fg = attrs.get("color", "")
    bg = attrs.get("bgcolor", "")
    m = _COLOR_RE.search(style)
    if m:
        fg = m.group(1).strip()
    m = _BG_RE.search(style)
    if m:
        bg = m.group(1).strip()
    return _safe_color(fg), _safe_color(bg)


def _safe_color(value: str) -> str:
    value = (value or "").strip()
    return value if _SAFE_COLOR_RE.match(value) else ""


def align_of(attrs: dict) -> str:
    align = (attrs.get("align") or "").lower()
    if align not in ("left", "right", "center"):
        m = _ALIGN_RE.search(attrs.get("style", ""))
        align = m.group(1).lower() if m else ""
    return align or "left"


def wrap_inline(kind: str, children: List[object]) -> object:
    """Build the node for an inline wrapper tag."""
    if kind == "strong":
        return P.Strong(children=children)
    if kind == "em":
        return P.Emph(children=children)
    if kind == "del":
        return P.Strike(children=children)
    if kind == "mark":
        return P.Mark(children=children)
    return P.Styled(children=children, variant=kind)  # u / sup / sub


class _Frame:
    __slots__ = ("tag", "kind", "attrs", "blocks", "inlines", "text", "extra")

    def __init__(self, tag: str, kind: str, attrs: dict = None):
        self.tag = tag
        self.kind = kind
        self.attrs = attrs or {}
        self.blocks: List[object] = []
        self.inlines: List[object] = []
        self.text: List[str] = []
        self.extra: dict = {}


class _Builder(HTMLParser):
    """Assembles nodes as the tag stream arrives."""

    def __init__(self, opts: P.Options):
        super().__init__(convert_charrefs=True)
        self.opts = opts
        self.frames = [_Frame("#root", "block")]
        self.skip = 0          # depth inside a dropped element
        self.raw_tag = ""      # inside <pre>, collect text verbatim

    # -- frame helpers -----------------------------------------------------

    @property
    def top(self) -> _Frame:
        return self.frames[-1]

    def _flush_inlines(self, frame: _Frame = None):
        frame = frame or self.top
        if any(not isinstance(n, P.Text) or n.text.strip() for n in frame.inlines):
            frame.blocks.append(P.Paragraph(children=frame.inlines))
        frame.inlines = []

    def _add_inline(self, node):
        self.top.inlines.append(node)

    def _add_block(self, node):
        self._flush_inlines()
        self.top.blocks.append(node)

    def _push(self, tag: str, kind: str, attrs: dict = None):
        self.frames.append(_Frame(tag, kind, attrs))

    def _pop_to(self, tag: str):
        """Close frames until *tag* is closed, tolerating bad nesting."""
        if not any(f.tag == tag for f in self.frames[1:]):
            return
        while len(self.frames) > 1:
            frame = self.frames.pop()
            self._finish(frame)
            if frame.tag == tag:
                return

    # -- HTMLParser hooks --------------------------------------------------

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.skip:
            if tag not in VOID:
                self.skip += 1
            return
        if self.raw_tag:
            return
        if tag in DROPPED:
            if tag not in VOID:
                self.skip = 1
            return

        attrd = {k.lower(): (v or "") for k, v in attrs}

        if tag == "br":
            self._add_inline(P.HardBreak())
        elif tag == "hr":
            self._add_block(P.ThematicBreak())
        elif tag == "img":
            self._add_inline(P.Image(alt=attrd.get("alt", ""),
                                     src=attrd.get("src", ""),
                                     title=attrd.get("title", "")))
        elif tag == "wbr":
            pass
        elif tag == "pre":
            self._flush_inlines()
            self.raw_tag = "pre"
            self._push(tag, "raw", attrd)
        elif tag in CODEISH:
            self._push(tag, "code", attrd)
        elif tag == "a":
            self._push(tag, "link", attrd)
        elif tag in INLINE_WRAPPERS:
            self._push(tag, "inline", attrd)
        elif tag in ("span", "font"):
            fg, bg = colors_of(attrd)
            self._push(tag, "inline" if (fg or bg) else "transparent", attrd)
        elif tag in ("p", "li", "td", "th", "summary", "blockquote", "details",
                     "ul", "ol", "table", "thead", "tbody", "tfoot", "tr"):
            self._flush_inlines()
            self._push(tag, tag, attrd)
        elif re.fullmatch(r"h[1-6]", tag):
            self._flush_inlines()
            self._push(tag, "heading", attrd)
        else:
            self._push(tag, "transparent", attrd)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.skip:
            if tag not in VOID:
                self.skip -= 1
            return
        if self.raw_tag:
            if tag != self.raw_tag:
                return
            self.raw_tag = ""
        if tag in DROPPED or tag in VOID:
            return
        self._pop_to(tag)

    def handle_data(self, data):
        if self.skip:
            return
        if self.raw_tag or self.top.kind in ("raw", "code"):
            self.top.text.append(data)
            return
        if not data:
            return
        text = re.sub(r"[ \t]*\n[ \t]*", " ", data)  # HTML folds whitespace
        if not text.strip() and not self.top.inlines:
            return
        self._add_inline(P.Text(text))

    def handle_comment(self, data):
        pass

    # -- turning a finished frame into nodes -------------------------------

    def _finish(self, frame: _Frame):
        parent = self.top
        kind = frame.kind

        if kind == "transparent":
            self._flush_inlines(frame)
            parent.inlines.extend(frame.inlines)
            if frame.blocks:
                self._flush_inlines(parent)
                parent.blocks.extend(frame.blocks)
            return

        if kind == "raw":
            text = "".join(frame.text)
            parent.blocks.append(P.CodeBlock(text=text.strip("\n"), lang=""))
            return

        if kind == "code":
            parent.inlines.append(P.Code("".join(frame.text).strip()))
            return

        if kind == "link":
            parent.inlines.append(P.Link(children=frame.inlines,
                                         href=frame.attrs.get("href", ""),
                                         title=frame.attrs.get("title", "")))
            return

        if kind == "inline":
            children = frame.inlines
            if frame.tag in INLINE_WRAPPERS:
                node = wrap_inline(INLINE_WRAPPERS[frame.tag], children)
            else:
                fg, bg = colors_of(frame.attrs)
                node = P.Styled(children=children, color=fg, background=bg)
            parent.inlines.append(node)
            return

        if kind == "heading":
            self._flush_inlines(frame)
            level = int(frame.tag[1])
            inlines = frame.inlines or _first_paragraph(frame.blocks)
            self._flush_inlines(parent)
            parent.blocks.append(P.Heading(level=level, children=inlines))
            return

        if kind == "p":
            self._flush_inlines(frame)
            self._flush_inlines(parent)
            parent.blocks.extend(frame.blocks)
            return

        if kind == "blockquote":
            self._flush_inlines(frame)
            self._flush_inlines(parent)
            parent.blocks.append(P.BlockQuote(children=frame.blocks))
            return

        if kind == "details":
            self._flush_inlines(frame)
            self._flush_inlines(parent)
            parent.blocks.append(P.Panel(kind="note",
                                         title=frame.extra.get("summary", ""),
                                         children=frame.blocks))
            return

        if kind == "summary":
            self._flush_inlines(frame)
            title = P.plain_text(_first_paragraph(frame.blocks))
            for outer in reversed(self.frames):
                if outer.kind == "details":
                    outer.extra["summary"] = title or "Details"
                    return
            parent.blocks.append(P.Paragraph(children=[P.Strong(
                children=_first_paragraph(frame.blocks))]))
            return

        if kind in ("ul", "ol"):
            self._flush_inlines(frame)
            items = [n for n in frame.blocks if isinstance(n, P.ListItem)]
            start = 1
            try:
                start = int(frame.attrs.get("start", 1))
            except ValueError:
                pass
            self._flush_inlines(parent)
            parent.blocks.append(P.ListBlock(
                ordered=kind == "ol", start=start,
                tight=all(len(i.children) <= 1 for i in items), items=items))
            return

        if kind == "li":
            self._flush_inlines(frame)
            task = None
            checkbox = frame.extra.get("checkbox")
            if checkbox is not None:
                task = checkbox
            parent.blocks.append(P.ListItem(children=frame.blocks, task=task))
            return

        if kind == "table":
            self._flush_inlines(frame)
            self._flush_inlines(parent)
            parent.blocks.append(_build_table(frame))
            return

        if kind in ("thead", "tbody", "tfoot"):
            self._flush_inlines(frame)
            parent.extra.setdefault("rows", []).extend(
                frame.extra.get("rows", []))
            if kind == "thead":
                parent.extra["header_rows"] = frame.extra.get("rows", [])
            return

        if kind == "tr":
            self._flush_inlines(frame)
            cells = frame.extra.get("cells", [])
            row = {"cells": [c[0] for c in cells],
                   "aligns": [c[1] for c in cells],
                   "header": all(c[2] for c in cells) and bool(cells)}
            parent.extra.setdefault("rows", []).append(row)
            return

        if kind in ("td", "th"):
            self._flush_inlines(frame)
            inlines = frame.inlines or _first_paragraph(frame.blocks)
            parent.extra.setdefault("cells", []).append(
                (inlines, align_of(frame.attrs), kind == "th"))
            return

        # anything unexpected behaves like a transparent wrapper
        self._flush_inlines(frame)
        parent.blocks.extend(frame.blocks)

    def result(self) -> List[object]:
        while len(self.frames) > 1:
            self._finish(self.frames.pop())
        self._flush_inlines(self.frames[0])
        return self.frames[0].blocks


def _first_paragraph(blocks: List[object]) -> List[object]:
    for node in blocks:
        if isinstance(node, P.Paragraph):
            return node.children
    return []


def _build_table(frame: _Frame) -> P.Table:
    rows = frame.extra.get("rows", [])
    header_rows = frame.extra.get("header_rows", [])
    if not rows:
        return P.Table(header=[], aligns=[], rows=[])

    head = None
    body = list(rows)
    if header_rows:
        head = header_rows[0]
        body = [r for r in rows if r is not head]
    elif rows[0]["header"]:
        head, body = rows[0], rows[1:]
    else:
        head, body = rows[0], rows[1:]  # no <th>: the first row leads

    aligns = head["aligns"] or ["left"] * len(head["cells"])
    width = len(head["cells"])
    out_rows = []
    for row in body:
        cells = (row["cells"] + [[]] * width)[:width]
        out_rows.append(cells)
    return P.Table(header=head["cells"], aligns=aligns, rows=out_rows)


_DROP_ELEMENT_RE = re.compile(
    r"<(%s)\b[^>]*>.*?</\1\s*>|<(?:%s)\b[^>]*/?>"
    % ("|".join(sorted(DROPPED)), "|".join(sorted(DROPPED))),
    re.I | re.S,
)
_EVENT_ATTR_RE = re.compile(r"""\son[a-zA-Z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""",
                            re.I)
_JS_URL_RE = re.compile(
    r"""\b(href|src|action|formaction|data|poster)\s*=\s*("|')?\s*"""
    r"""(?:javascript|vbscript|data:text/html)[^"'\s>]*("|')?""", re.I)


def sanitize(raw: str) -> str:
    """Strip anything that could fetch or run: exported pages stay offline."""
    cleaned = _DROP_ELEMENT_RE.sub("", raw)
    cleaned = _EVENT_ATTR_RE.sub("", cleaned)
    cleaned = _JS_URL_RE.sub("", cleaned)
    return cleaned


def html_to_nodes(source: str, opts: P.Options = None) -> List[object]:
    """Convert an HTML fragment into Markdown-style nodes."""
    builder = _Builder(opts or P.DEFAULT)
    try:
        builder.feed(source)
        builder.close()
    except Exception:  # a malformed fragment should never take the app down
        pass
    return builder.result()

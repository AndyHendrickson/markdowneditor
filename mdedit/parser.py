"""A self-contained Markdown parser.

Turns Markdown source into a small document tree.  Only the standard library
is used, and no I/O of any kind happens here -- text in, nodes out.

Core syntax: ATX and setext headings, paragraphs, fenced and indented code
blocks, block quotes (nested), ordered/unordered/task lists (nested),
thematic breaks, pipe tables, and the usual inline constructs (emphasis,
strong, strikethrough, code spans, links, images, autolinks, hard line
breaks, backslash escapes and HTML entities).

Dialect differences between platforms are expressed as :class:`Options`; see
``flavors.py`` for the presets that emulate GitHub, Confluence and Visual
Studio.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field, replace
from typing import List, Optional

# --------------------------------------------------------------------------
# Dialect options
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Options:
    """Which Markdown features are switched on.

    Most are parse-time: with ``tables`` off the pipe rows stay ordinary
    paragraph text.  ``images`` is honoured by the renderers instead, which
    show the alt text in place of the picture.
    """

    tables: bool = True             # | pipe | tables |
    task_lists: bool = True         # - [x] items
    strikethrough: bool = True      # ~~text~~
    bare_autolinks: bool = True     # https://x and www.x linkified in text
    hard_breaks: bool = False       # a single newline ends the line
    mark: bool = True               # ==highlight==
    containers: bool = True         # ::: note ... ::: blocks
    alerts: bool = True             # GitHub "> [!NOTE]" call-outs
    quote_panels: bool = False      # "> **Note:** ..." becomes a panel
    images: bool = True             # draw local images, or show the alt text


DEFAULT = Options()


@dataclass(frozen=True)
class Feature:
    """One switchable feature, described once for the CLI and the dialog."""

    key: str     # the Options field
    flag: str    # the CLI flag stem: --flag / --no-flag
    label: str   # what the dialog calls it
    hint: str    # what turning it off does


FEATURES = (
    Feature("tables", "tables", "Tables",
            "Pipe tables become tables; off leaves the rows as plain text."),
    Feature("task_lists", "task-lists", "Task lists",
            "\"- [x] item\" gets a check box; off leaves the brackets."),
    Feature("strikethrough", "strikethrough", "Strikethrough",
            "~~text~~ is struck through; off leaves the tildes."),
    Feature("bare_autolinks", "autolinks", "Bare URLs",
            "https://... in ordinary text becomes a link."),
    Feature("hard_breaks", "hard-breaks", "Hard line breaks",
            "A single newline ends the line instead of flowing on."),
    Feature("mark", "highlight", "Highlight",
            "==text== is highlighted; off leaves the equals signs."),
    Feature("containers", "containers", "Containers",
            "\"::: note\" blocks become call-outs."),
    Feature("alerts", "alerts", "Alerts",
            "\"> [!NOTE]\" quotes become call-outs."),
    Feature("quote_panels", "panels", "Labelled panels",
            "\"> **Note:** ...\" quotes become call-outs."),
    Feature("images", "images", "Images",
            "Local PNG/GIF images are drawn; off shows the alt text."),
)

FEATURE_KEYS = tuple(f.key for f in FEATURES)
FEATURES_BY_KEY = {f.key: f for f in FEATURES}
FEATURES_BY_FLAG = {f.flag: f for f in FEATURES}


def with_overrides(opts: Options, overrides) -> Options:
    """Return *opts* with the given ``{field: bool}`` overrides applied."""
    if not overrides:
        return opts
    changes = {k: bool(v) for k, v in overrides.items() if k in FEATURES_BY_KEY}
    return replace(opts, **changes) if changes else opts


def differences(opts: Options, base: Options) -> tuple:
    """The feature keys where *opts* departs from *base*."""
    return tuple(k for k in FEATURE_KEYS
                 if getattr(opts, k) != getattr(base, k))

_PANEL_ALIASES = {
    "note": "note", "info": "info", "information": "info", "tip": "tip",
    "hint": "tip", "success": "success", "check": "success", "warning":
    "warning", "caution": "warning", "danger": "danger", "error": "danger",
    "important": "info", "question": "info", "example": "note",
}


def panel_kind(word: str) -> Optional[str]:
    return _PANEL_ALIASES.get(word.strip().lower())


# --------------------------------------------------------------------------
# Node types
# --------------------------------------------------------------------------


@dataclass
class Document:
    children: List[object] = field(default_factory=list)


@dataclass
class Heading:
    level: int
    children: List[object] = field(default_factory=list)


@dataclass
class Paragraph:
    children: List[object] = field(default_factory=list)


@dataclass
class CodeBlock:
    text: str
    lang: str = ""


@dataclass
class BlockQuote:
    children: List[object] = field(default_factory=list)


@dataclass
class Panel:
    """A call-out box: Confluence panels, Markdig ``:::`` containers."""

    kind: str = "note"
    title: str = ""
    children: List[object] = field(default_factory=list)


@dataclass
class ListItem:
    children: List[object] = field(default_factory=list)
    task: Optional[bool] = None  # None = not a task item, else checked state


@dataclass
class ListBlock:
    ordered: bool = False
    start: int = 1
    tight: bool = True
    items: List[ListItem] = field(default_factory=list)


@dataclass
class ThematicBreak:
    pass


@dataclass
class Table:
    header: List[List[object]] = field(default_factory=list)
    aligns: List[str] = field(default_factory=list)  # "left" | "center" | "right"
    rows: List[List[List[object]]] = field(default_factory=list)


# Inline nodes ------------------------------------------------------------


@dataclass
class Text:
    text: str


@dataclass
class Code:
    text: str


@dataclass
class Emph:
    children: List[object] = field(default_factory=list)


@dataclass
class Strong:
    children: List[object] = field(default_factory=list)


@dataclass
class Strike:
    children: List[object] = field(default_factory=list)


@dataclass
class Mark:
    children: List[object] = field(default_factory=list)


@dataclass
class Link:
    children: List[object] = field(default_factory=list)
    href: str = ""
    title: str = ""


@dataclass
class Image:
    alt: str = ""
    src: str = ""
    title: str = ""


@dataclass
class SoftBreak:
    pass


@dataclass
class HardBreak:
    pass


# --------------------------------------------------------------------------
# Block level
# --------------------------------------------------------------------------

_ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_ATX_CLOSE_RE = re.compile(r"[ \t]+#+[ \t]*$")
_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*(\S*)[^`]*$")
_HR_RE = re.compile(r"^ {0,3}([-*_])[ \t]*(?:\1[ \t]*){2,}$")
_BQ_RE = re.compile(r"^ {0,3}>[ \t]?")
_UL_RE = re.compile(r"^( {0,3})([-*+])([ \t]+\S|[ \t]*$)")
_OL_RE = re.compile(r"^( {0,3})(\d{1,9})([.)])([ \t]+\S|[ \t]*$)")
_SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_TABLE_DELIM_RE = re.compile(
    r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$"
)
_TASK_RE = re.compile(r"^\[([ xX])\][ \t]+")
_CONTAINER_RE = re.compile(r"^ {0,3}(:{3,})[ \t]*(\w+)?[ \t]*(.*?)[ \t]*$")
_GH_ALERT_RE = re.compile(r"^\[!(\w+)\][ \t]*$")
_QUOTE_LABEL_RE = re.compile(
    r"^[\s*_]*(note|info|information|tip|hint|success|check|warning|caution|"
    r"danger|error|important|question|example)\s*:[\s*_]*",
    re.I,
)


def parse(source: str, opts: Options = DEFAULT) -> Document:
    """Parse Markdown *source* into a :class:`Document`."""
    text = source.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    return Document(children=_parse_blocks(text.split("\n"), opts))


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_block_start(line: str, opts: Options = DEFAULT) -> bool:
    """True if *line* would begin a new block, interrupting a paragraph."""
    if not line.strip():
        return True
    if _ATX_RE.match(line) or _HR_RE.match(line) or _BQ_RE.match(line):
        return True
    if _FENCE_RE.match(line) and line.lstrip()[:3] in ("```", "~~~"):
        return True
    if opts.containers and line.lstrip()[:3] == ":::":
        return True
    if _UL_RE.match(line):
        return True
    m = _OL_RE.match(line)
    if m and m.group(2) == "1":  # only "1." may interrupt a paragraph
        return True
    return False


def _parse_blocks(lines: List[str], opts: Options = DEFAULT) -> List[object]:
    blocks: List[object] = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        # Fenced code -----------------------------------------------------
        stripped = line.lstrip()
        if stripped[:3] in ("```", "~~~"):
            m = _FENCE_RE.match(line)
            if m:
                node, i = _parse_fence(lines, i, m)
                blocks.append(node)
                continue

        # Call-out container ----------------------------------------------
        if opts.containers and stripped[:3] == ":::":
            m = _CONTAINER_RE.match(line)
            if m and m.group(2):
                node, i = _parse_container(lines, i, m, opts)
                blocks.append(node)
                continue

        # ATX heading -----------------------------------------------------
        m = _ATX_RE.match(line)
        if m:
            body = m.group(2) or ""
            body = _ATX_CLOSE_RE.sub("", body) if body.rstrip().endswith("#") else body
            blocks.append(
                Heading(level=len(m.group(1)), children=parse_inlines(body, opts))
            )
            i += 1
            continue

        # Thematic break (checked before lists: "- - -" is a rule) ---------
        if _HR_RE.match(line):
            blocks.append(ThematicBreak())
            i += 1
            continue

        # Block quote -----------------------------------------------------
        if _BQ_RE.match(line):
            node, i = _parse_quote(lines, i, opts)
            blocks.append(node)
            continue

        # Table -----------------------------------------------------------
        if opts.tables and "|" in line and i + 1 < n and \
                _TABLE_DELIM_RE.match(lines[i + 1]):
            result = _parse_table(lines, i, opts)
            if result is not None:
                node, i = result
                blocks.append(node)
                continue

        # Lists -----------------------------------------------------------
        if _UL_RE.match(line) or _OL_RE.match(line):
            node, i = _parse_list(lines, i, opts)
            blocks.append(node)
            continue

        # Indented code ---------------------------------------------------
        if line.startswith("    "):
            node, i = _parse_indented_code(lines, i)
            blocks.append(node)
            continue

        # Paragraph / setext heading --------------------------------------
        node, i = _parse_paragraph(lines, i, opts)
        if node is not None:
            blocks.append(node)

    return blocks


def _parse_fence(lines: List[str], i: int, m: re.Match) -> tuple:
    pad, fence, lang = len(m.group(1)), m.group(2), m.group(3)
    char, size = fence[0], len(fence)
    i += 1
    body: List[str] = []
    closed = False
    n = len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        if s and s[0] == char and s == char * len(s) and len(s) >= size:
            i += 1
            closed = True
            break
        body.append(line[pad:] if line[:pad].strip() == "" else line.lstrip())
        i += 1
    if not closed:  # ran to the end of the document
        while body and not body[-1].strip():
            body.pop()
    return CodeBlock(text="\n".join(body), lang=lang.strip()), i


def _parse_container(lines: List[str], i: int, m: re.Match, opts: Options) -> tuple:
    """``::: warning Title`` ... ``:::`` -- Markdig / pandoc style call-outs."""
    marker = m.group(1)
    kind = panel_kind(m.group(2) or "") or "note"
    title = m.group(3) or ""
    i += 1
    body: List[str] = []
    n = len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        if s and set(s) == {":"} and len(s) >= len(marker):
            i += 1
            break
        body.append(line)
        i += 1
    return Panel(kind=kind, title=title, children=_parse_blocks(body, opts)), i


def _parse_indented_code(lines: List[str], i: int) -> tuple:
    body: List[str] = []
    pending: List[str] = []
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("    "):
            body.extend(pending)
            pending = []
            body.append(line[4:])
            i += 1
        elif not line.strip():
            pending.append("")
            i += 1
        else:
            break
    return CodeBlock(text="\n".join(body), lang=""), i


def _parse_quote(lines: List[str], i: int, opts: Options = DEFAULT) -> tuple:
    inner: List[str] = []
    n = len(lines)
    while i < n:
        line = lines[i]
        m = _BQ_RE.match(line)
        if m:
            inner.append(line[m.end():])
            i += 1
        elif line.strip() and inner and inner[-1].strip() and \
                not _is_block_start(line, opts):
            inner.append(line.lstrip())  # lazy continuation
            i += 1
        else:
            break
    children = _parse_blocks(inner, opts)
    panel = _quote_panel(children, opts)
    if panel is not None:
        return panel, i
    return BlockQuote(children=children), i


def _quote_panel(children: List[object], opts: Options) -> Optional[Panel]:
    """Recognise the call-out conventions a flavour supports."""
    if not children or not isinstance(children[0], Paragraph):
        return None
    inlines = list(children[0].children)
    if not inlines:
        return None

    # GitHub alerts:  > [!NOTE]
    if opts.alerts and isinstance(inlines[0], Text):
        m = _GH_ALERT_RE.match(inlines[0].text.strip())
        if m:
            kind = panel_kind(m.group(1))
            if kind:
                rest = inlines[1:]
                while rest and isinstance(rest[0], (SoftBreak, HardBreak)):
                    rest = rest[1:]
                body = ([Paragraph(children=rest)] if rest else []) + children[1:]
                return Panel(kind=kind, title="", children=body)

    if not opts.quote_panels:
        return None

    first = inlines[0]
    label = ""
    if isinstance(first, (Strong, Emph)):
        label = plain_text([first])
        rest = inlines[1:]
    elif isinstance(first, Text):
        label = first.text
        rest = inlines
    else:
        return None

    m = _QUOTE_LABEL_RE.match(label)
    if not m:
        return None
    kind = panel_kind(m.group(1)) or "note"

    if isinstance(first, (Strong, Emph)):
        if not _QUOTE_LABEL_RE.fullmatch(label):
            return None
    else:
        rest = [Text(first.text[m.end():])] + inlines[1:]
    while rest and isinstance(rest[0], Text) and not rest[0].text.strip():
        rest = rest[1:]
    if rest and isinstance(rest[0], Text):
        rest[0] = Text(rest[0].text.lstrip())

    body = [Paragraph(children=rest)] + children[1:] if rest else children[1:]
    return Panel(kind=kind, title="", children=body)


def _marker_info(line: str):
    """Return (ordered, start, marker_end, content_indent) or None."""
    m = _UL_RE.match(line)
    if m:
        ordered, start = False, 1
        marker_end = m.start(2) + 1
    else:
        m = _OL_RE.match(line)
        if not m:
            return None
        ordered, start = True, int(m.group(2))
        marker_end = m.start(2) + len(m.group(2)) + 1

    rest = line[marker_end:]
    spaces = len(rest) - len(rest.lstrip(" "))
    if not rest.strip():
        spaces = 1
    elif spaces > 4:  # content after 5+ spaces starts an indented code block
        spaces = 1
    return ordered, start, marker_end, marker_end + spaces


def _parse_list(lines: List[str], i: int, opts: Options = DEFAULT) -> tuple:
    info = _marker_info(lines[i])
    ordered, start, _, _ = info
    lst = ListBlock(ordered=ordered, start=start, tight=True, items=[])
    n = len(lines)
    loose = False

    while i < n:
        info = _marker_info(lines[i])
        if info is None or info[0] != ordered:
            break
        marker_indent = _indent_of(lines[i])
        if marker_indent >= 4 and lst.items:
            break
        _, _, marker_end, content_indent = info

        item_lines = [lines[i][content_indent:]]
        i += 1
        blanks: List[str] = []
        while i < n:
            line = lines[i]
            if not line.strip():
                blanks.append("")
                i += 1
                continue
            if _indent_of(line) >= content_indent:
                if blanks:
                    item_lines.extend(blanks)
                    loose = True
                    blanks = []
                item_lines.append(line[content_indent:])
                i += 1
                continue
            if blanks or _is_block_start(line, opts) or _marker_info(line) is not None:
                break  # a sibling item ends this one, whatever its number
            item_lines.append(line.lstrip())  # lazy continuation
            i += 1

        # Task-list marker
        task = None
        if item_lines and opts.task_lists:
            tm = _TASK_RE.match(item_lines[0])
            if tm:
                task = tm.group(1).lower() == "x"
                item_lines[0] = item_lines[0][tm.end():]

        children = _parse_blocks(item_lines, opts)
        lst.items.append(ListItem(children=children, task=task))

        # A blank line followed by another item makes the whole list loose.
        if blanks and i < n and _marker_info(lines[i]) and \
                _marker_info(lines[i])[0] == ordered:
            loose = True

    lst.tight = not loose
    return lst, i


def _split_row(line: str) -> List[str]:
    """Split a table row on unescaped pipes that are not inside code spans."""
    cells: List[str] = []
    buf: List[str] = []
    in_code = False
    k = 0
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    while k < len(line):
        c = line[k]
        if c == "\\" and k + 1 < len(line):
            buf.append(line[k:k + 2])
            k += 2
            continue
        if c == "`":
            in_code = not in_code
        if c == "|" and not in_code:
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
        k += 1
    cells.append("".join(buf).strip())
    return cells


def _parse_table(lines: List[str], i: int, opts: Options = DEFAULT):
    header = _split_row(lines[i])
    delim = _split_row(lines[i + 1])
    if len(delim) != len(header):
        return None

    aligns = []
    for d in delim:
        d = d.strip()
        if not d or set(d) - set(":-"):
            return None
        left, right = d.startswith(":"), d.endswith(":")
        aligns.append(
            "center" if left and right else "right" if right else "left"
        )

    rows: List[List[List[object]]] = []
    i += 2
    n = len(lines)
    while i < n and lines[i].strip() and "|" in lines[i]:
        cells = _split_row(lines[i])
        cells = (cells + [""] * len(header))[: len(header)]
        rows.append([parse_inlines(c, opts) for c in cells])
        i += 1

    return Table(
        header=[parse_inlines(c, opts) for c in header], aligns=aligns, rows=rows
    ), i


def _parse_paragraph(lines: List[str], i: int, opts: Options = DEFAULT) -> tuple:
    buf: List[str] = []
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            break
        m = _SETEXT_RE.match(line)
        if m and buf:
            level = 1 if m.group(1)[0] == "=" else 2
            text = "\n".join(buf).strip()
            return Heading(level=level, children=parse_inlines(text, opts)), i + 1
        if buf and _is_block_start(line, opts):
            break
        buf.append(line.rstrip() if not line.endswith("  ") else line)
        i += 1

    text = "\n".join(s.lstrip() for s in buf).rstrip()
    if not text:
        return None, i
    return Paragraph(children=parse_inlines(text, opts)), i


# --------------------------------------------------------------------------
# Inline level
# --------------------------------------------------------------------------

_PUNCT = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_AUTOLINK_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9+.\-]{1,31}:[^<>\s]*)>")
_EMAIL_RE = re.compile(r"<([^\s<>@]+@[^\s<>@]+\.[^\s<>@]+)>")
_BR_TAG_RE = re.compile(r"<br\s*/?>", re.I)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_ENTITY_RE = re.compile(r"&(?:#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[a-zA-Z][a-zA-Z0-9]{1,31});")
_BARE_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\[\]`]+", re.I)
_TRAILING_PUNCT = "?!.,:;*_~'\""


def parse_inlines(text: str, opts: Options = DEFAULT,
                  in_link: bool = False) -> List[object]:
    nodes: List[object] = []
    buf: List[str] = []
    i, n = 0, len(text)

    def flush():
        if buf:
            nodes.append(Text("".join(buf)))
            buf.clear()

    while i < n:
        c = text[i]

        # Backslash escapes and backslash hard breaks
        if c == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "\n":
                flush()
                nodes.append(HardBreak())
                i += 2
                continue
            if nxt in _PUNCT:
                buf.append(nxt)
                i += 2
                continue

        # Line breaks
        if c == "\n":
            tail = "".join(buf)
            if tail.endswith("  "):
                buf.clear()
                buf.append(tail.rstrip(" "))
                flush()
                nodes.append(HardBreak())
            else:
                flush()
                nodes.append(HardBreak() if opts.hard_breaks else SoftBreak())
            i += 1
            continue

        # Code spans
        if c == "`":
            span = _code_span(text, i)
            if span:
                node, i = span
                flush()
                nodes.append(node)
                continue

        # Images and links
        if c == "!" and text.startswith("![", i):
            res = _link_like(text, i + 1, True, opts)
            if res:
                node, i = res
                flush()
                nodes.append(node)
                continue
        if c == "[" and not in_link:
            res = _link_like(text, i, False, opts)
            if res:
                node, i = res
                flush()
                nodes.append(node)
                continue

        # Raw HTML we understand: <br>, comments, autolinks
        if c == "<":
            m = _BR_TAG_RE.match(text, i)
            if m:
                flush()
                nodes.append(HardBreak())
                i = m.end()
                continue
            m = _COMMENT_RE.match(text, i)
            if m:
                i = m.end()
                continue
            m = _AUTOLINK_RE.match(text, i)
            if m:
                flush()
                nodes.append(Link(children=[Text(m.group(1))], href=m.group(1)))
                i = m.end()
                continue
            m = _EMAIL_RE.match(text, i)
            if m:
                flush()
                nodes.append(
                    Link(children=[Text(m.group(1))], href="mailto:" + m.group(1))
                )
                i = m.end()
                continue

        # Bare URLs (GitHub-style linkification)
        if opts.bare_autolinks and not in_link and (c in "hHwW") and \
                (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "/@.-")):
            m = _BARE_URL_RE.match(text, i)
            if m:
                url = _trim_url(m.group(0))
                if len(url) > 8:
                    flush()
                    href = url if "://" in url else "https://" + url
                    nodes.append(Link(children=[Text(url)], href=href))
                    i += len(url)
                    continue

        # HTML entities
        if c == "&":
            m = _ENTITY_RE.match(text, i)
            if m:
                decoded = _html.unescape(m.group(0))
                if decoded != m.group(0):
                    buf.append(decoded)
                    i = m.end()
                    continue

        # Emphasis / strong / strikethrough / highlight
        if c in "*_" or (c == "~" and opts.strikethrough) or \
                (c == "=" and opts.mark):
            res = _emphasis(text, i, opts)
            if res:
                node, i = res
                flush()
                nodes.append(node)
                continue

        buf.append(c)
        i += 1

    flush()
    return nodes


def _trim_url(url: str) -> str:
    """Drop sentence punctuation and unbalanced brackets from a bare URL."""
    while url and url[-1] in _TRAILING_PUNCT:
        url = url[:-1]
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    return url


def _skip_atomic(text: str, i: int) -> Optional[int]:
    """If an escape or code span starts at *i*, return the index just past it."""
    if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in _PUNCT:
        return i + 2
    if text[i] == "`":
        span = _code_span(text, i)
        if span:
            return span[1]
    return None


def _code_span(text: str, i: int):
    n = len(text)
    k = i
    while k < n and text[k] == "`":
        k += 1
    size = k - i
    j = k
    while j < n:
        if text[j] == "`":
            e = j
            while e < n and text[e] == "`":
                e += 1
            if e - j == size:
                body = text[k:j].replace("\n", " ")
                if len(body) > 1 and body.startswith(" ") and body.endswith(" "):
                    body = body[1:-1]
                return Code(body), e
            j = e
        else:
            j += 1
    return None


def _match_bracket(text: str, i: int) -> Optional[int]:
    """Index of the ']' closing the '[' at *i*, honouring nesting."""
    depth = 0
    k = i
    n = len(text)
    while k < n:
        skip = _skip_atomic(text, k)
        if skip is not None:
            k = skip
            continue
        c = text[k]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return k
        k += 1
    return None


def _link_like(text: str, i: int, image: bool, opts: Options = DEFAULT):
    close = _match_bracket(text, i)
    if close is None:
        return None
    label = text[i + 1:close]
    k = close + 1
    if k >= len(text) or text[k] != "(":
        return None

    depth = 0
    n = len(text)
    end = None
    while k < n:
        skip = _skip_atomic(text, k)
        if skip is not None:
            k = skip
            continue
        if text[k] == "(":
            depth += 1
        elif text[k] == ")":
            depth -= 1
            if depth == 0:
                end = k
                break
        k += 1
    if end is None:
        return None

    dest, title = _split_dest(text[close + 2:end])
    if image:
        return Image(
            alt=_plain(parse_inlines(label, opts, in_link=True)),
            src=dest, title=title,
        ), end + 1
    return Link(
        children=parse_inlines(label, opts, in_link=True), href=dest, title=title
    ), end + 1


def _split_dest(raw: str) -> tuple:
    raw = raw.strip()
    title = ""
    if raw.startswith("<"):
        gt = raw.find(">")
        if gt != -1:
            dest, rest = raw[1:gt], raw[gt + 1:].strip()
        else:
            dest, rest = raw, ""
    else:
        parts = raw.split(None, 1)
        dest = parts[0] if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""
    if len(rest) >= 2 and rest[0] in "\"'(" and rest[-1] in "\"')":
        title = rest[1:-1]
    return dest.replace("\\ ", " "), title


def _emphasis(text: str, i: int, opts: Options = DEFAULT):
    char = text[i]
    n = len(text)
    k = i
    while k < n and text[k] == char:
        k += 1
    run = k - i

    if char in "~=":
        if run < 2:
            return None
        lengths = [2]
    else:
        lengths = [ln for ln in (3, 2, 1) if ln <= run]

    for length in lengths:
        after = i + length
        if after >= n or text[after].isspace():
            continue
        if char == "_" and i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_"):
            continue  # intra-word underscores are literal
        close = _find_closer(text, after, char, length)
        if close is None:
            continue
        if char == "_":
            tail = close + length
            if tail < n and (text[tail].isalnum() or text[tail] == "_"):
                continue
        inner = parse_inlines(text[after:close], opts)
        if char == "~":
            node = Strike(children=inner)
        elif char == "=":
            node = Mark(children=inner)
        elif length == 3:
            node = Strong(children=[Emph(children=inner)])
        elif length == 2:
            node = Strong(children=inner)
        else:
            node = Emph(children=inner)
        return node, close + length
    return None


def _find_closer(text: str, start: int, char: str, length: int) -> Optional[int]:
    """Index of the delimiter run that closes an opener of *length* chars.

    Runs of exactly the wanted length win, so ``*a **b** c*`` closes the
    single ``*`` on the final one rather than eating into the strong run.  A
    longer run is only used when no exact match exists.
    """
    n = len(text)
    runs = []
    k = start
    while k < n:
        skip = _skip_atomic(text, k)
        if skip is not None:
            k = skip
            continue
        if text[k] == char:
            e = k
            while e < n and text[e] == char:
                e += 1
            if not text[k - 1].isspace() and e - k >= length:
                runs.append((k, e))
            k = e
            continue
        k += 1

    for k, e in runs:
        if e - k == length:
            return k
    for k, e in runs:
        return e - length
    return None


def _plain(nodes: List[object]) -> str:
    """Flatten inline nodes to their plain-text content."""
    out: List[str] = []
    for node in nodes:
        if isinstance(node, (Text, Code)):
            out.append(node.text)
        elif isinstance(node, Image):
            out.append(node.alt)
        elif isinstance(node, (SoftBreak, HardBreak)):
            out.append(" ")
        elif hasattr(node, "children"):
            out.append(_plain(node.children))
    return "".join(out)


def plain_text(nodes: List[object]) -> str:
    """Public alias for flattening inline nodes to plain text."""
    return _plain(nodes)


def outline(doc: Document) -> List[tuple]:
    """Return [(level, title), ...] for every heading in *doc*."""
    return [
        (b.level, _plain(b.children))
        for b in doc.children
        if isinstance(b, Heading)
    ]

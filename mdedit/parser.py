"""A self-contained Markdown parser.

Turns Markdown source into a small document tree.  Only the standard library
is used, and no I/O of any kind happens here -- text in, nodes out.

Core syntax: ATX and setext headings, paragraphs, fenced and indented code
blocks, block quotes (nested), ordered/unordered/task lists (nested),
thematic breaks, pipe tables, and the usual inline constructs (emphasis,
strong, strikethrough, code spans, links, images, autolinks, hard line
breaks, backslash escapes and HTML entities).  A ``mermaid`` fence is handed
to :mod:`mermaid` and becomes a :class:`Diagram` when it can be read.

Dialect differences between platforms are expressed as :class:`Options`; see
``flavors.py`` for the presets that emulate GitHub, Confluence and Visual
Studio.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field, replace
from typing import List, Optional

from . import mermaid

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
    mermaid: bool = True            # ```mermaid fences become diagrams
    front_matter: bool = True       # --- YAML / +++ TOML header block
    callout_titles: bool = False    # "> [!note] A title" keeps the title
    wikilinks: bool = False         # [[Note]], [[Note|alias]], ![[embed]]
    hashtags: bool = False          # #tag in running text
    comments: bool = False          # %% hidden from the reader %%
    template_tags: bool = False     # {{ liquid }}, {%- -%}, {{< shortcode >}}
    smart_typography: bool = False  # curly quotes, en/em dashes, ellipsis
    render_html: bool = True        # draw embedded HTML, or show its tags


DEFAULT = Options()


@dataclass(frozen=True)
class Feature:
    """One switchable feature, described once for the CLI and the dialog."""

    key: str     # the Options field
    flag: str    # the CLI flag stem: --flag / --no-flag
    label: str   # what the dialog calls it
    hint: str    # what turning it off does
    group: str = "Structure"


FEATURES = (
    Feature("tables", "tables", "Tables",
            "Pipe tables become tables; off leaves the rows as plain text."),
    Feature("task_lists", "task-lists", "Task lists",
            "\"- [x] item\" gets a check box; off leaves the brackets."),
    Feature("images", "images", "Images",
            "Local PNG/GIF images are drawn; off shows the alt text."),
    Feature("mermaid", "mermaid", "Mermaid diagrams",
            "A ```mermaid fence is drawn as a diagram; off shows the source."),
    Feature("front_matter", "front-matter", "Front matter",
            "A leading --- or +++ header is metadata, not a rule and a "
            "heading."),
    Feature("hard_breaks", "hard-breaks", "Hard line breaks",
            "A single newline ends the line instead of flowing on."),
    Feature("render_html", "html", "HTML",
            "Embedded HTML renders; off shows the tags as written."),

    Feature("strikethrough", "strikethrough", "Strikethrough",
            "~~text~~ is struck through; off leaves the tildes.", "Inline"),
    Feature("bare_autolinks", "autolinks", "Bare URLs",
            "https://... in ordinary text becomes a link.", "Inline"),
    Feature("mark", "highlight", "Highlight",
            "==text== is highlighted; off leaves the equals signs.", "Inline"),
    Feature("smart_typography", "smart-typography", "Smart typography",
            "Straight quotes curl, -- becomes a dash, ... an ellipsis.",
            "Inline"),
    Feature("wikilinks", "wikilinks", "Wiki links",
            "[[Note]] and ![[embed]] link to another note.", "Inline"),
    Feature("hashtags", "hashtags", "Hashtags",
            "#tag in running text renders as a tag.", "Inline"),
    Feature("template_tags", "template-tags", "Template tags",
            "{{ liquid }} and {{< shortcodes >}} show as template markers.",
            "Inline"),
    Feature("comments", "comments", "Hidden comments",
            "%% text %% is hidden from the reader.", "Inline"),

    Feature("containers", "containers", "Containers",
            "\"::: note\" blocks become call-outs.", "Call-outs"),
    Feature("alerts", "alerts", "Alerts",
            "\"> [!NOTE]\" quotes become call-outs.", "Call-outs"),
    Feature("callout_titles", "callout-titles", "Call-out titles",
            "\"> [!note] A title\" keeps its title line.", "Call-outs"),
    Feature("quote_panels", "panels", "Labelled panels",
            "\"> **Note:** ...\" quotes become call-outs.", "Call-outs"),
)

GROUPS = ("Structure", "Inline", "Call-outs")

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
    # Obsidian's callout vocabulary
    "abstract": "note", "summary": "note", "tldr": "note", "todo": "info",
    "faq": "info", "help": "info", "done": "success", "bug": "danger",
    "failure": "danger", "fail": "danger", "missing": "danger",
    "quote": "note", "cite": "note", "attention": "warning",
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
class Diagram:
    """A ```mermaid fence whose contents were understood.

    *model* is what :mod:`mermaid` made of the source -- a flowchart, a
    sequence diagram or a class diagram.  A fence mermaid cannot read stays a
    :class:`CodeBlock`, so this node always has something to draw.
    """

    source: str
    kind: str = ""
    model: object = None


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
class HtmlBlock:
    """Embedded HTML: *raw* for the exporter, *children* for the preview."""

    raw: str = ""
    children: List[object] = field(default_factory=list)


@dataclass
class FrontMatter:
    """The metadata header Obsidian, Jekyll and Hugo files start with."""

    fmt: str = "yaml"                                   # "yaml" | "toml"
    pairs: List[tuple] = field(default_factory=list)    # [(key, value), ...]
    raw: str = ""


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
class Styled:
    """Inline HTML that carries presentation: colour, underline, sup, sub."""

    children: List[object] = field(default_factory=list)
    color: str = ""
    background: str = ""
    variant: str = ""  # "" | "u" | "sup" | "sub"


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
class WikiLink:
    """``[[Note]]``, ``[[Note|alias]]`` or an ``![[embed]]``."""

    target: str = ""
    alias: str = ""
    embed: bool = False

    @property
    def display(self) -> str:
        return self.alias or self.target


@dataclass
class Tag:
    name: str = ""


@dataclass
class Template:
    """A Liquid tag or a Hugo shortcode, shown as a marker rather than run."""

    text: str = ""


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
_GH_ALERT_RE = re.compile(r"^\[!(\w+)\]([+-]?)[ \t]*(.*)$")
_QUOTE_LABEL_RE = re.compile(
    r"^[\s*_]*(note|info|information|tip|hint|success|check|warning|caution|"
    r"danger|error|important|question|example)\s*:[\s*_]*",
    re.I,
)


#: Files whose whole contents are one diagram, with no fence around them.
DIAGRAM_SUFFIXES = (".mermaid",)


def is_diagram_file(name: str) -> bool:
    """Is this the name of a file holding a diagram and nothing else?"""
    return name.lower().endswith(DIAGRAM_SUFFIXES)


def as_diagram(source: str) -> str:
    """Bare diagram source with its fence put back, ready for :func:`parse`.

    A ``.mermaid`` file holds the diagram the way mermaid's own tools want
    it -- unfenced -- so the editor keeps it that way and the fence is added
    here, for the parser alone.  What gets saved is still the bare source.
    """
    return "```mermaid\n" + source.strip("\n") + "\n```\n"


def parse(source: str, opts: Options = DEFAULT) -> Document:
    """Parse Markdown *source* into a :class:`Document`."""
    text = source.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    lines = text.split("\n")
    blocks: List[object] = []
    if opts.front_matter:
        header, lines = _parse_front_matter(lines)
        if header is not None:
            blocks.append(header)
    blocks.extend(_parse_blocks(lines, opts))
    return Document(children=blocks)


def _parse_front_matter(lines: List[str]):
    """Peel a leading ``---`` (YAML) or ``+++`` (TOML) header off the file."""
    if not lines or lines[0].strip() not in ("---", "+++"):
        return None, lines
    fence = lines[0].strip()
    fmt = "toml" if fence == "+++" else "yaml"
    for k in range(1, len(lines)):
        if lines[k].strip() == fence:
            body = lines[1:k]
            return _front_matter_node(fmt, body), lines[k + 1:]
    return None, lines  # never closed: it was a thematic break after all


def _front_matter_node(fmt: str, body: List[str]) -> FrontMatter:
    sep = "=" if fmt == "toml" else ":"
    pairs = []
    for line in body:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1].isspace() or stripped.startswith("- "):
            if pairs:  # a nested value belongs to the key above it
                key, value = pairs[-1]
                pairs[-1] = (key, f"{value} {stripped}".strip())
            continue
        key, found, value = stripped.partition(sep)
        if found:
            pairs.append((key.strip(), value.strip().strip("\"'")))
        else:
            pairs.append(("", stripped))
    return FrontMatter(fmt=fmt, pairs=pairs, raw="\n".join(body))


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
    if opts.render_html and _html_block_start(line):
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
                node, i = _parse_fence(lines, i, m, opts)
                blocks.append(node)
                continue

        # Call-out container ----------------------------------------------
        if opts.containers and stripped[:3] == ":::":
            m = _CONTAINER_RE.match(line)
            if m and m.group(2):
                node, i = _parse_container(lines, i, m, opts)
                blocks.append(node)
                continue

        # Embedded HTML ---------------------------------------------------
        if opts.render_html and stripped.startswith("<") and _html_block_start(line):
            node, moved = _parse_html_block(lines, i, opts)
            if moved > i:
                i = moved
                if node is not None:
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


_HTML_LINE_RE = re.compile(r"^ {0,3}<(/?)([a-zA-Z][a-zA-Z0-9-]*)")
_HTML_RAW_TAGS = ("script", "style", "pre", "textarea")
_HTML_ONLY_TAG_RE = re.compile(
    r"^ {0,3}</?[a-zA-Z][a-zA-Z0-9-]*(?:\s[^>]*)?/?>[ \t]*$")


def _html_block_start(line: str) -> bool:
    """Does *line* open a block of raw HTML?"""
    stripped = line.lstrip()
    if not stripped.startswith("<"):
        return False
    if stripped.startswith("<!--"):
        return True
    m = _HTML_LINE_RE.match(line)
    if not m:
        return False
    from .htmlparse import BLOCK_TAGS

    return (m.group(2).lower() in BLOCK_TAGS
            or bool(_HTML_ONLY_TAG_RE.match(line)))


def _parse_html_block(lines: List[str], i: int, opts: Options):
    """Collect an HTML block and convert it to nodes.  CommonMark-ish rules:
    raw-text elements run to their close tag, everything else to a blank line.
    """
    from .htmlparse import BLOCK_TAGS, html_to_nodes

    n = len(lines)
    stripped = lines[i].lstrip()

    if stripped.startswith("<!--"):  # comments are for the author, not the page
        while i < n and "-->" not in lines[i]:
            i += 1
        return None, min(i + 1, n)

    m = _HTML_LINE_RE.match(lines[i])
    if not m:
        return None, i
    name = m.group(2).lower()
    chunk: List[str] = []

    if name in _HTML_RAW_TAGS:
        closer = f"</{name}"  # raw-text elements run to their closing tag
        while i < n:
            chunk.append(lines[i])
            i += 1
            if closer in chunk[-1].lower():
                break
    elif name in BLOCK_TAGS or _HTML_ONLY_TAG_RE.match(lines[i]):
        while i < n and lines[i].strip():
            chunk.append(lines[i])
            i += 1
    else:
        return None, i

    raw = "\n".join(chunk)
    return HtmlBlock(raw=raw, children=html_to_nodes(raw, opts)), i


def _parse_fence(lines: List[str], i: int, m: re.Match,
                 opts: Options = DEFAULT) -> tuple:
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
    text, lang = "\n".join(body), lang.strip()
    if opts.mermaid and lang.lower() == "mermaid":
        model = mermaid.parse(text)
        if model is not None:
            return Diagram(source=text, kind=model.kind, model=model), i
    return CodeBlock(text=text, lang=lang), i


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

    # Alerts and callouts:  > [!NOTE]   /   > [!note]- With a title
    if opts.alerts and isinstance(inlines[0], Text):
        brk = next((k for k, node in enumerate(inlines)
                    if isinstance(node, (SoftBreak, HardBreak))), None)
        head = inlines if brk is None else inlines[:brk]
        rest = [] if brk is None else inlines[brk + 1:]
        m = _GH_ALERT_RE.match(_plain(head).strip())
        if m:
            kind = panel_kind(m.group(1))
            title = m.group(3).strip()
            # GitHub wants the marker alone on its line; Obsidian allows a
            # title and a fold marker after it.
            if kind and (opts.callout_titles or not (title or m.group(2))):
                body = ([Paragraph(children=rest)] if rest else []) + children[1:]
                return Panel(kind=kind,
                             title=title if opts.callout_titles else "",
                             children=body)

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
_WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+?)(?:\|([^\[\]]*))?\]\]")
_HASHTAG_RE = re.compile(r"#([A-Za-z0-9_][\w/-]*)")
_COMMENT_MD_RE = re.compile(r"%%.*?%%", re.S)
_TEMPLATE_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
_SMART_DASH_RE = re.compile(r"(?<!-)---(?!-)")
_SMART_NDASH_RE = re.compile(r"(?<!-)--(?!-)")
_OPENING_BEFORE = " \t\n([{<-–—“‘/"


def smarten(text: str) -> str:
    """Curly quotes, en/em dashes and ellipses, the way a typographer wants."""
    text = text.replace("...", "…")
    text = _SMART_DASH_RE.sub("—", text)
    text = _SMART_NDASH_RE.sub("–", text)
    out = []
    prev = " "
    for ch in text:
        if ch == '"':
            out.append("“" if prev in _OPENING_BEFORE else "”")
        elif ch == "'":
            out.append("‘" if prev in _OPENING_BEFORE else "’")
        else:
            out.append(ch)
        prev = ch
    return "".join(out)


def parse_inlines(text: str, opts: Options = DEFAULT,
                  in_link: bool = False) -> List[object]:
    nodes: List[object] = []
    buf: List[str] = []
    i, n = 0, len(text)

    def flush():
        if buf:
            body = "".join(buf)
            nodes.append(Text(smarten(body) if opts.smart_typography else body))
            buf.clear()

    while i < n:
        c = text[i]

        # Hidden comments and template tags: shown as markers, never run
        if c == "%" and opts.comments and text.startswith("%%", i):
            m = _COMMENT_MD_RE.match(text, i)
            if m:
                flush()
                i = m.end()
                continue
        if c == "{" and opts.template_tags:
            m = _TEMPLATE_RE.match(text, i)
            if m:
                flush()
                nodes.append(Template(m.group(0)))
                i = m.end()
                continue

        # Wiki links and embeds
        if opts.wikilinks and (c == "[" or c == "!"):
            start = i + 1 if c == "!" else i
            if text.startswith("[[", start):
                m = _WIKILINK_RE.match(text, start)
                if m:
                    flush()
                    nodes.append(WikiLink(target=m.group(1).strip(),
                                          alias=(m.group(2) or "").strip(),
                                          embed=c == "!"))
                    i = m.end()
                    continue

        # Hashtags, but not "#" glued to a word or a bare number
        if c == "#" and opts.hashtags and not in_link and \
                (i == 0 or text[i - 1] in " \t\n([{-—" or text[i - 1] in _PUNCT
                 and text[i - 1] not in "#\\"):
            m = _HASHTAG_RE.match(text, i)
            if m and not m.group(1).isdigit():
                flush()
                nodes.append(Tag(m.group(1)))
                i = m.end()
                continue

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
            if opts.render_html:
                res = _inline_html(text, i, opts, in_link)
                if res is not None:
                    found, i = res
                    flush()
                    nodes.extend(found)
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


_INLINE_TAG_RE = re.compile(
    r"""<(/?)([a-zA-Z][a-zA-Z0-9-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>""")


def _find_close(text: str, start: int, name: str):
    """Where the matching ``</name>`` begins and ends, honouring nesting."""
    depth = 1
    pos = start
    lowered = name.lower()
    while pos < len(text):
        m = _INLINE_TAG_RE.search(text, pos)
        if not m:
            return None
        if m.group(2).lower() == lowered:
            if m.group(1):
                depth -= 1
                if depth == 0:
                    return m.start(), m.end()
            elif not m.group(3).rstrip().endswith("/"):
                depth += 1
        pos = m.end()
    return None


def _inline_html(text: str, i: int, opts: Options, in_link: bool):
    """Render an inline HTML tag.  Returns (nodes, next index) or None."""
    from .htmlparse import (CODEISH, DROPPED, INLINE_WRAPPERS, VOID,
                            colors_of, parse_attrs, wrap_inline)

    m = _INLINE_TAG_RE.match(text, i)
    if not m:
        return None
    closing, name, attr_text = m.group(1), m.group(2).lower(), m.group(3)
    self_closed = attr_text.rstrip().endswith("/")
    if closing:
        return [], m.end()  # a stray end tag renders as nothing
    attrs = parse_attrs(attr_text)

    if name in DROPPED:
        found = _find_close(text, m.end(), name)
        return [], found[1] if found else m.end()

    if name == "br":
        return [HardBreak()], m.end()
    if name == "img":
        return [Image(alt=attrs.get("alt", ""), src=attrs.get("src", ""),
                      title=attrs.get("title", ""))], m.end()
    if name in VOID or self_closed:
        return [], m.end()

    found = _find_close(text, m.end(), name)
    if found is None:
        return [], m.end()  # unclosed: the tag itself just disappears
    inner = text[m.end():found[0]]
    end = found[1]

    if name in CODEISH:
        return [Code(re.sub(r"<[^>]*>", "", inner).strip())], end
    if name == "a" and not in_link:
        return [Link(children=parse_inlines(inner, opts, in_link=True),
                     href=attrs.get("href", ""),
                     title=attrs.get("title", ""))], end

    children = parse_inlines(inner, opts, in_link)
    if name in INLINE_WRAPPERS:
        return [wrap_inline(INLINE_WRAPPERS[name], children)], end
    fg, bg = colors_of(attrs)
    if fg or bg:
        return [Styled(children=children, color=fg, background=bg)], end
    return children, end  # any other tag is transparent


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
        if isinstance(node, (Text, Code, Template)):
            out.append(node.text)
        elif isinstance(node, Image):
            out.append(node.alt)
        elif isinstance(node, WikiLink):
            out.append(node.display)
        elif isinstance(node, Tag):
            out.append("#" + node.name)
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

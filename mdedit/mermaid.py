"""Read mermaid diagram source into a small model.

Text goes in and plain data comes out: no drawing, no tkinter, no network.
``diagram.py`` turns what comes out of here into shapes, which ``tkrender``
paints on a canvas and ``html_export`` writes as inline SVG.

Three diagram types are understood -- flowcharts (``graph`` / ``flowchart``),
sequence diagrams and class diagrams.  Anything else (gantt, state, ER, pie,
journey...) returns ``None``, and the caller goes on showing the fence as an
ordinary code block, which is also what happens if a diagram turns out to be
empty.  Inside a diagram the rule is the same but per line: a statement this
module does not recognise is skipped rather than failing the whole block, so
one exotic line does not cost you the picture.

This is a careful approximation of mermaid's own dialect, not a clone of it.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------


@dataclass
class Node:
    """One flowchart box."""

    id: str
    text: str = ""
    shape: str = "rect"


@dataclass
class Edge:
    """A link between two flowchart boxes."""

    src: str
    dst: str
    text: str = ""
    stroke: str = "solid"       # solid | dotted | thick
    src_head: str = ""          # "" | arrow | circle | cross
    dst_head: str = "arrow"


@dataclass
class Subgraph:
    """A ``subgraph``: a titled box drawn around its members."""

    id: str
    title: str = ""
    members: List[str] = field(default_factory=list)
    parent: Optional[str] = None


@dataclass
class Flowchart:
    kind: str = "flowchart"
    direction: str = "TB"                                   # TB | BT | LR | RL
    nodes: Dict[str, Node] = field(default_factory=dict)    # in first-seen order
    edges: List[Edge] = field(default_factory=list)
    subgraphs: List[Subgraph] = field(default_factory=list)


@dataclass
class Participant:
    id: str
    label: str = ""
    actor: bool = False


@dataclass
class Message:
    src: str
    dst: str
    text: str = ""
    stroke: str = "solid"       # solid | dotted
    head: str = "arrow"         # "" | arrow | cross | async
    back_head: str = ""         # the <<->> forms point both ways
    activate: bool = False      # "->>+" starts an activation on the target
    deactivate: bool = False    # "->>-" ends one on the source


@dataclass
class Note:
    text: str = ""
    placement: str = "over"     # over | left | right
    targets: List[str] = field(default_factory=list)


@dataclass
class Block:
    """``loop`` / ``alt`` / ``opt`` / ``par`` / ``critical`` / ``break``."""

    kind: str = "loop"
    title: str = ""
    sections: List[str] = field(default_factory=list)  # extra "else"/"and" rows
    events: List[object] = field(default_factory=list)  # events, with Section
    hidden: bool = False        # "box" and "rect" group without a frame


@dataclass
class Section:
    """An ``else`` / ``and`` divider inside a :class:`Block`."""

    title: str = ""


@dataclass
class Lifecycle:
    """A bare ``activate`` / ``deactivate`` statement."""

    target: str = ""
    start: bool = True


@dataclass
class Sequence:
    kind: str = "sequence"
    title: str = ""
    autonumber: bool = False
    participants: Dict[str, Participant] = field(default_factory=dict)
    events: List[object] = field(default_factory=list)


@dataclass
class ClassBox:
    id: str
    name: str = ""
    stereotype: str = ""                                # interface, abstract...
    attributes: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)


@dataclass
class Relation:
    left: str
    right: str
    text: str = ""
    line: str = "solid"         # solid | dashed
    left_head: str = ""         # triangle | diamond | odiamond | arrow | ""
    right_head: str = ""
    left_card: str = ""
    right_card: str = ""


@dataclass
class ClassDiagram:
    kind: str = "class"
    direction: str = "TB"
    title: str = ""
    classes: Dict[str, ClassBox] = field(default_factory=dict)
    relations: List[Relation] = field(default_factory=list)


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

_HEADER_RE = re.compile(
    r"^\s*(graph|flowchart(?:-elk)?|sequencediagram|classdiagram(?:-v2)?)\b"
    r"[ \t]*(.*)$", re.I)

#: ``%%{init: ...}%%`` directives and plain ``%%`` comments alike: mermaid
#: treats both as out-of-band, and neither changes what is drawn here.
_DIRECTIVE_RE = re.compile(r"%%\{.*?\}%%")
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
#: mermaid spells entities with a hash -- ``#quot;``, ``#35;`` -- so that they
#: survive its own parser; turn them back into the HTML ones before unescaping.
_HASH_ENTITY_RE = re.compile(r"#(\w{2,8}|\d{1,6}|x[0-9a-fA-F]{1,6});")


def parse(source: str):
    """Parse mermaid *source*, or return ``None`` if it isn't understood."""
    lines = _clean_lines(source)
    if not lines:
        return None
    m = _HEADER_RE.match(lines[0])
    if not m:
        return None
    keyword = m.group(1).lower()
    rest = m.group(2).strip()
    body = lines[1:]
    try:
        if keyword.startswith(("graph", "flowchart")):
            return _parse_flowchart(rest, body)
        if keyword == "sequencediagram":
            return _parse_sequence(rest, body)
        return _parse_class(rest, body)
    except (ValueError, IndexError, KeyError, RecursionError):
        # A malformed diagram falls back to being shown as source, which is
        # more use than half a picture.
        return None


def _clean_lines(source: str) -> List[str]:
    """Drop comments, directives and blank lines; keep the indentation."""
    out = []
    for raw in source.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _DIRECTIVE_RE.sub("", raw)
        cut = _comment_at(line)
        if cut is not None:
            line = line[:cut]
        if line.strip():
            out.append(line.rstrip())
    return out


def _comment_at(line: str) -> Optional[int]:
    """Where a ``%%`` comment starts, ignoring one inside a quoted string."""
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch == "%" and line[i + 1:i + 2] == "%":
            return i
    return None


def _clean_label(text: str) -> str:
    """A node/edge label as the reader should see it."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    text = _BR_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _HASH_ENTITY_RE.sub(r"&\1;", text)
    return _html.unescape(text).strip()


def _split_statements(line: str) -> List[str]:
    """Split on ``;``, but not inside quotes or a bracketed node label."""
    parts, buf, depth, quoted = [], [], 0, False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        elif not quoted:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
            elif ch == ";" and depth == 0:
                parts.append("".join(buf))
                buf = []
                continue
        buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


# --------------------------------------------------------------------------
# Flowcharts
# --------------------------------------------------------------------------

_DIRECTIONS = {"TB": "TB", "TD": "TB", "BT": "BT", "LR": "LR", "RL": "RL"}

#: Node wrappers, longest opener first so ``[[`` wins over ``[``.  The last
#: field is the shape name, or a pair chosen by which closer actually turns up
#: (``[/x/]`` is a parallelogram, ``[/x\]`` a trapezoid).
_SHAPES = (
    ("(((", (")))",), "doublecircle"),
    ("((", ("))",), "circle"),
    ("([", ("])",), "stadium"),
    ("[[", ("]]",), "subroutine"),
    ("[(", (")]",), "cylinder"),
    ("{{", ("}}",), "hexagon"),
    ("[/", ("/]", "\\]"), ("parallelogram", "trapezoid")),
    ("[\\", ("\\]", "/]"), ("parallelogram_alt", "trapezoid_alt")),
    ("[", ("]",), "rect"),
    ("(", (")",), "round"),
    ("{", ("}",), "rhombus"),
    (">", ("]",), "asymmetric"),
)

_ID_RE = re.compile(r'"[^"]*"|[^\s\[\](){}<>|&;,"]+')
#: A single dash belongs to an id (``Web-Server``); two, or a dash and a dot,
#: start a link, so ``A-->B`` has to break after the ``A``.
_LINK_START_RE = re.compile(r"--|==|-\.")

_LINK_RE = re.compile(r"""
      (?P<lhead>[<ox])?
      (?:
          (?P<dotlbl>-\.(?P<dlabel>[^.\n|]*?)\.-)     #  -. text .-
        | (?P<dotplain>-\.+-)                         #  -.-  -..-
        | (?P<thicklbl>={2,}(?P<tlabel>[^=\n|]*?)={2,})
        | (?P<thickplain>={2,})
        | (?P<sollbl>-{2,}(?P<slabel>[^->\n|]*?)-{2,})
        | (?P<solplain>-{2,})
      )
      (?P<rhead>[>ox])?
""", re.X)

_HEADS = {">": "arrow", "o": "circle", "x": "cross", "<": "arrow"}

_SUBGRAPH_RE = re.compile(r"^subgraph\b[ \t]*(.*)$", re.I)
#: Statements that change styling or behaviour rather than structure.  They
#: are recognised only so they can be skipped without warning.
_IGNORED_RE = re.compile(
    r"^(?:style|classDef|class|linkStyle|click|direction|accTitle|accDescr)\b",
    re.I)


def _parse_flowchart(head: str, body: List[str]) -> Optional[Flowchart]:
    chart = Flowchart()
    m = re.match(r"^([A-Za-z]{2})\b[ \t]*(.*)$", head)
    if m and m.group(1).upper() in _DIRECTIONS:
        chart.direction = _DIRECTIONS[m.group(1).upper()]
        head = m.group(2)

    stack: List[Subgraph] = []
    statements: List[str] = []
    for line in ([head] if head.strip() else []) + body:
        statements.extend(_split_statements(line))

    anon = 0
    for stmt in statements:
        low = stmt.lower()
        if low == "end":
            if stack:
                stack.pop()
            continue

        m = _SUBGRAPH_RE.match(stmt)
        if m:
            anon += 1
            sub = _subgraph(m.group(1), anon)
            sub.parent = stack[-1].id if stack else None
            chart.subgraphs.append(sub)
            stack.append(sub)
            continue

        if _IGNORED_RE.match(stmt):
            continue

        added = _parse_chain(stmt, chart)
        if added and stack:
            stack[-1].members.extend(
                n for n in added if n not in stack[-1].members)

    # A subgraph's own box counts as a member of the one enclosing it.
    for sub in chart.subgraphs:
        if sub.parent:
            for outer in chart.subgraphs:
                if outer.id == sub.parent and sub.id not in outer.members:
                    outer.members.append(sub.id)
    _link_subgraphs(chart)
    return chart if chart.nodes else None


def _link_subgraphs(chart: Flowchart):
    """``one --> two`` between two subgraphs, rather than to boxes of that name.

    Mermaid lets a link name a subgraph and draws it to the cluster; here the
    cluster is not a node, so the link is pointed at a node inside it instead.
    Without this the id would quietly become a box of its own.
    """
    subs = {s.id: s for s in chart.subgraphs}
    if not subs:
        return

    def anchor(sid: str, seen=()) -> Optional[str]:
        if sid in seen:
            return None
        for member in subs[sid].members:
            if member in subs:
                inner = anchor(member, tuple(seen) + (sid,))
                if inner:
                    return inner
            elif member in chart.nodes and member not in subs:
                return member
        return None

    for edge in chart.edges:
        for end in ("src", "dst"):
            name = getattr(edge, end)
            if name in subs:
                inside = anchor(name)
                if inside:
                    setattr(edge, end, inside)

    for sid in subs:
        touched = any(e.src == sid or e.dst == sid for e in chart.edges)
        node = chart.nodes.get(sid)
        if node is not None and not touched and node.text == sid:
            del chart.nodes[sid]                # only ever a name, not a box
            for sub in chart.subgraphs:
                if sid in sub.members and sub.id != sid:
                    sub.members.remove(sid)


def _subgraph(rest: str, anon: int) -> Subgraph:
    """``subgraph id[Title]``, ``subgraph Title`` or a bare ``subgraph``."""
    rest = rest.strip()
    m = re.match(r'^([^\s\[]+)[ \t]*\[(.*)\]$', rest)
    if m:
        return Subgraph(id=m.group(1), title=_clean_label(m.group(2)))
    if rest:
        return Subgraph(id=rest, title=_clean_label(rest))
    return Subgraph(id=f"__sub{anon}", title="")


def _parse_chain(stmt: str, chart: Flowchart) -> List[str]:
    """``A[x] --> B & C -.text.-> D``: nodes, links and the ids they touch."""
    pos = 0
    left, pos = _node_group(stmt, pos, chart)
    if left is None:
        return []
    touched = list(left)
    while pos < len(stmt):
        link = _LINK_RE.match(stmt, _skip_space(stmt, pos))
        if not link:
            break
        pos = link.end()
        stroke, text = _link_kind(link)
        pos, piped = _pipe_label(stmt, pos)
        if piped is not None:
            text = piped
        right, pos = _node_group(stmt, pos, chart)
        if right is None:
            break
        src_head = _HEADS.get(link.group("lhead") or "", "")
        dst_head = _HEADS.get(link.group("rhead") or "", "")
        for a in left:
            for b in right:
                chart.edges.append(Edge(src=a, dst=b, text=text, stroke=stroke,
                                        src_head=src_head, dst_head=dst_head))
        touched.extend(n for n in right if n not in touched)
        left = right
    return touched


def _link_kind(link: re.Match) -> tuple:
    if link.group("dotlbl") or link.group("dotplain"):
        return "dotted", _clean_label(link.group("dlabel") or "")
    if link.group("thicklbl") or link.group("thickplain"):
        return "thick", _clean_label(link.group("tlabel") or "")
    return "solid", _clean_label(link.group("slabel") or "")


def _pipe_label(text: str, pos: int) -> tuple:
    """The ``|yes|`` that may follow an arrow."""
    i = _skip_space(text, pos)
    if text[i:i + 1] != "|":
        return pos, None
    close = text.find("|", i + 1)
    if close < 0:
        return pos, None
    return close + 1, _clean_label(text[i + 1:close])


def _skip_space(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in " \t":
        pos += 1
    return pos


def _node_group(text: str, pos: int, chart: Flowchart):
    """One or more nodes joined by ``&``, registering each as it is read."""
    ids = []
    while True:
        node_id, pos = _node_ref(text, pos, chart)
        if node_id is None:
            return (ids or None), pos
        ids.append(node_id)
        nxt = _skip_space(text, pos)
        if text[nxt:nxt + 1] != "&":
            return ids, pos
        pos = nxt + 1


def _node_ref(text: str, pos: int, chart: Flowchart):
    pos = _skip_space(text, pos)
    m = _ID_RE.match(text, pos)
    if not m:
        return None, pos
    raw = m.group(0)
    if not raw.startswith('"'):
        cut = _LINK_START_RE.search(raw)        # "A-->B" is a link, not an id
        if cut:
            if not cut.start():
                return None, pos
            raw = raw[:cut.start()]
    pos = m.start() + len(raw)
    node_id = raw[1:-1] if raw.startswith('"') else raw
    node_id = node_id.split(":::")[0]          # a style class, not part of it
    label, shape, pos = _node_shape(text, pos)
    node = chart.nodes.get(node_id)
    if node is None:
        node = Node(id=node_id, text=label if label is not None else node_id)
        chart.nodes[node_id] = node
    if label is not None:                       # a later mention may name it
        node.text = label
        node.shape = shape
    return node_id, pos


def _node_shape(text: str, pos: int):
    """The ``[...]`` / ``{...}`` / ``(...)`` that may follow an id."""
    for opener, closers, shape in _SHAPES:
        if not text.startswith(opener, pos):
            continue
        found = _find_closer(text, pos + len(opener), closers)
        if found is None:
            continue
        end, which = found
        label = _clean_label(text[pos + len(opener):end])
        name = shape[which] if isinstance(shape, tuple) else shape
        return label, name, end + len(closers[which])
    return None, "rect", pos


def _find_closer(text: str, start: int, closers) -> Optional[tuple]:
    """Scan for the first of *closers*, ignoring anything inside quotes."""
    i, quoted = start, False
    while i < len(text):
        ch = text[i]
        if ch == '"':
            quoted = not quoted
        elif not quoted:
            for k, closer in enumerate(closers):
                if text.startswith(closer, i):
                    return i, k
        i += 1
    return None


# --------------------------------------------------------------------------
# Sequence diagrams
# --------------------------------------------------------------------------

_SEQ_PARTICIPANT_RE = re.compile(
    r"^(participant|actor)\s+(.+?)(?:\s+as\s+(.+))?$", re.I)
#: The source id is lazy so that the arrow matches as early as it can: with a
#: greedy one, ``B-->>-A: hi`` reads its first dash as part of the name.
_SEQ_MSG_RE = re.compile(r"""
    ^(?P<src>[^\s:]+?)[ \t]*
     (?P<arrow><<-->>|<<->>|-->>|--\)|--x|-->|--|->>|-\)|-x|->)
     [ \t]*(?P<flag>[+-])?[ \t]*
     (?P<dst>[^:]+?)[ \t]*:[ \t]*(?P<text>.*)$
""", re.X)
_SEQ_NOTE_RE = re.compile(
    r"^note\s+(over|left of|right of)\s+([^:]+):\s*(.*)$", re.I)
_SEQ_BLOCKS = ("loop", "alt", "opt", "par", "critical", "break", "rect", "box")
_SEQ_SECTIONS = ("else", "and", "option")


def _parse_sequence(head: str, body: List[str]) -> Optional[Sequence]:
    seq = Sequence()
    if head.strip():
        body = [head] + body
    stack: List[Block] = []

    def emit(event):
        (stack[-1].events if stack else seq.events).append(event)

    for raw in body:
        stmt = raw.strip()
        low = stmt.lower()

        if low == "end":
            if stack:
                done = stack.pop()
                (stack[-1].events if stack else seq.events).append(done)
            continue

        if low.startswith("autonumber"):
            seq.autonumber = True
            continue

        if low.startswith("title"):
            seq.title = _clean_label(stmt[5:].lstrip(": "))
            continue

        m = _SEQ_PARTICIPANT_RE.match(stmt)
        if m:
            name = _clean_label(m.group(2))
            label = _clean_label(m.group(3)) if m.group(3) else name
            _participant(seq, name, label, m.group(1).lower() == "actor")
            continue

        m = _SEQ_NOTE_RE.match(stmt)
        if m:
            where = m.group(1).lower().split()[0]
            targets = [_clean_label(t) for t in m.group(2).split(",")]
            for t in targets:
                _participant(seq, t, t, False)
            emit(Note(text=_clean_label(m.group(3)), placement=where,
                      targets=targets))
            continue

        word = low.split()[0] if low.split() else ""
        if word in _SEQ_BLOCKS:
            title = _clean_label(stmt[len(word):])
            block = Block(kind=word, title=title, hidden=word in ("rect", "box"))
            if word == "rect":
                block.title = ""
            stack.append(block)
            continue
        if word in _SEQ_SECTIONS and stack:
            title = _clean_label(stmt[len(word):])
            stack[-1].sections.append(title)
            stack[-1].events.append(Section(title=title))
            continue

        if word in ("activate", "deactivate"):
            target = _clean_label(stmt[len(word):])
            _participant(seq, target, target, False)
            emit(Lifecycle(target=target, start=word == "activate"))
            continue

        m = _SEQ_MSG_RE.match(stmt)
        if m:
            emit(_sequence_message(seq, m))
            continue
        # Anything else -- links, styling, accessibility text -- is skipped.

    while stack:                                    # an unclosed loop/alt/opt
        done = stack.pop()
        (stack[-1].events if stack else seq.events).append(done)
    return seq if seq.participants else None


def _participant(seq: Sequence, name: str, label: str, actor: bool):
    name = name.strip()
    if not name:
        return
    known = seq.participants.get(name)
    if known is None:
        seq.participants[name] = Participant(id=name, label=label or name,
                                             actor=actor)
    else:
        if label and label != name:
            known.label = label
        known.actor = known.actor or actor


def _sequence_message(seq: Sequence, m: re.Match) -> Message:
    arrow = m.group("arrow")
    src = _clean_label(m.group("src"))
    dst_raw = m.group("dst").strip()
    flag = m.group("flag") or ""
    if dst_raw[-1:] in "+-" and not flag:           # "A->>B-: done"
        flag, dst_raw = dst_raw[-1], dst_raw[:-1]
    dst = _clean_label(dst_raw)
    _participant(seq, src, src, False)
    _participant(seq, dst, dst, False)

    body = arrow[2:] if arrow.startswith("<<") else arrow
    stroke = "dotted" if body.startswith("--") else "solid"
    tail = body.lstrip("-")
    head = {">>": "arrow", "x": "cross", ")": "async", ">": "",
            "": ""}.get(tail, "arrow")
    return Message(
        src=src, dst=dst, text=_clean_label(m.group("text")), stroke=stroke,
        head=head, back_head="arrow" if arrow.startswith("<<") else "",
        activate=flag == "+", deactivate=flag == "-",
    )


# --------------------------------------------------------------------------
# Class diagrams
# --------------------------------------------------------------------------

_REL_RE = re.compile(r"""
    ^(?P<left>[\w~]+)[ \t]*
     (?:"(?P<lcard>[^"]*)"[ \t]*)?
     (?P<ldec><\||\*|o|<)?(?P<line>--|\.\.)(?P<rdec>\|>|\*|o|>)?
     [ \t]*(?:"(?P<rcard>[^"]*)"[ \t]*)?
     (?P<right>[\w~]+)[ \t]*
     (?::[ \t]*(?P<label>.*))?$
""", re.X)
_CLASS_RE = re.compile(r"^class\s+([\w~]+)(?:\[[^\]]*\])?\s*(\{)?\s*$", re.I)
_MEMBER_RE = re.compile(r"^([\w~]+)\s*:\s*(.+)$")
_STEREOTYPE_RE = re.compile(r"^<<(.+?)>>\s*(.*)$")
_DECORATIONS = {"<|": "triangle", "|>": "triangle", "*": "diamond",
                "o": "odiamond", "<": "arrow", ">": "arrow"}


def _parse_class(head: str, body: List[str]) -> Optional[ClassDiagram]:
    dia = ClassDiagram()
    if head.strip():
        body = [head] + body

    open_class: Optional[ClassBox] = None
    for raw in body:
        stmt = raw.strip()
        low = stmt.lower()

        if open_class is not None:                  # inside "class X { ... }"
            if stmt.startswith("}"):
                open_class = None
            else:
                _add_member(open_class, stmt)
            continue

        if low.startswith("direction "):
            want = stmt.split()[1].upper()
            if want in _DIRECTIONS:
                dia.direction = _DIRECTIONS[want]
            continue
        if low.startswith("title"):
            dia.title = _clean_label(stmt[5:].lstrip(": "))
            continue
        if low.startswith(("namespace", "click", "style", "classdef",
                           "cssclass", "note", "acctitle", "accdescr")):
            continue

        m = _CLASS_RE.match(stmt)
        if m:
            box = _class_box(dia, m.group(1))
            if m.group(2):
                open_class = box
            continue

        m = _STEREOTYPE_RE.match(stmt)              # "<<interface>> Shape"
        if m and m.group(2):
            _class_box(dia, m.group(2).strip()).stereotype = m.group(1).strip()
            continue

        m = _REL_RE.match(stmt)
        if m:
            dia.relations.append(_relation(dia, m))
            continue

        m = _MEMBER_RE.match(stmt)                  # "Animal : +int age"
        if m:
            _add_member(_class_box(dia, m.group(1)), m.group(2))
            continue

    return dia if dia.classes else None


def _class_box(dia: ClassDiagram, name: str) -> ClassBox:
    name = name.split(":::")[0].strip()
    box = dia.classes.get(name)
    if box is None:
        box = ClassBox(id=name, name=_generics(name))
        dia.classes[name] = box
    return box


def _generics(name: str) -> str:
    """``List~int~`` is how mermaid spells ``List<int>``."""
    parts = name.split("~")
    if len(parts) >= 3:
        return f"{parts[0]}<{parts[1]}>{''.join(parts[2:])}"
    return name


def _add_member(box: ClassBox, line: str):
    line = line.strip().rstrip(";")
    if not line:
        return
    m = _STEREOTYPE_RE.match(line)
    if m:
        box.stereotype = m.group(1).strip()
        if not m.group(2):
            return
        line = m.group(2).strip()
    text = _generics(_clean_label(line))
    (box.methods if "(" in text else box.attributes).append(text)


def _relation(dia: ClassDiagram, m: re.Match) -> Relation:
    left = _class_box(dia, m.group("left")).id
    right = _class_box(dia, m.group("right")).id
    # A hollow triangle on a dashed line is realisation rather than
    # inheritance; both are drawn the same way, and the line tells them apart.
    ldec, rdec = m.group("ldec") or "", m.group("rdec") or ""
    return Relation(
        left=left, right=right, text=_clean_label(m.group("label") or ""),
        line="dashed" if m.group("line") == ".." else "solid",
        left_head=_DECORATIONS.get(ldec, ""),
        right_head=_DECORATIONS.get(rdec, ""),
        left_card=(m.group("lcard") or "").strip(),
        right_card=(m.group("rcard") or "").strip(),
    )

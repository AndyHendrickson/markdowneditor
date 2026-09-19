"""Turn a mermaid model into shapes.

:mod:`mermaid` reads the source; this lays it out and says what to draw, as a
:class:`Scene` of rectangles, ellipses, polygons, polylines and text.  Two
renderers consume that scene -- ``tkrender`` paints it on a ``tk.Canvas``,
``html_export`` writes it as inline SVG -- so the preview and the exported
page are the same drawing twice, not two drawings.

Nothing here imports tkinter, and nothing measures a real font on its own: a
caller that *can* measure text passes a ``measure`` callable in the
:class:`Style`, and everything else falls back to :func:`approx_width`, a
table of average glyph widths for a sans-serif face.

Flowcharts and class diagrams share one layered layout -- rank the nodes,
order each rank to keep the crossings down, then place them -- which is the
same family of algorithm mermaid uses, at a fraction of the sophistication.
Sequence diagrams are laid out top to bottom in one pass instead.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import mermaid as MM

# --------------------------------------------------------------------------
# Palettes
# --------------------------------------------------------------------------

#: Close to mermaid's own ``default`` theme: lavender nodes, dark strokes.
LIGHT = {
    "node_fill": "#ececff", "node_stroke": "#9370db", "node_text": "#1f2328",
    "edge": "#333333", "edge_text": "#333333", "label_bg": "#ffffff",
    "cluster_fill": "#fffbe6", "cluster_stroke": "#b9a53a",
    "cluster_text": "#5c5220",
    "note_fill": "#fff5ad", "note_stroke": "#b8a736", "note_text": "#333333",
    "actor_fill": "#ececff", "actor_stroke": "#6b6b8a", "actor_text": "#1f2328",
    "lifeline": "#8a8aa0", "frame": "#8a8aa0", "frame_tab": "#f0f0f8",
    "hollow": "#ffffff", "title": "#1f2328",
}

#: And its ``dark`` theme, tuned to sit on mdedit's dark background.
DARK = {
    "node_fill": "#252b33", "node_stroke": "#8ba6d8", "node_text": "#e6edf3",
    "edge": "#b1bac4", "edge_text": "#c9d1d9", "label_bg": "#0d1117",
    "cluster_fill": "#1a1f27", "cluster_stroke": "#6e7681",
    "cluster_text": "#c9d1d9",
    "note_fill": "#3b3620", "note_stroke": "#8a7f3a", "note_text": "#ece4c0",
    "actor_fill": "#252b33", "actor_stroke": "#8ba6d8", "actor_text": "#e6edf3",
    "lifeline": "#6e7681", "frame": "#6e7681", "frame_tab": "#1a1f27",
    "hollow": "#0d1117", "title": "#e6edf3",
}

PALETTES = {"light": LIGHT, "dark": DARK}

#: How many shuffled orderings to try on top of the structured ones.  Two is
#: where the corpus stops improving; more only costs time.
RESTARTS = 2

#: Fixed, so that one document always draws the same picture.
SHUFFLE_SEED = 20260918


# --------------------------------------------------------------------------
# Text metrics
# --------------------------------------------------------------------------

#: Average glyph widths as a fraction of the font size, for a Helvetica-like
#: face.  Only used when the caller cannot measure the real font; the
#: geometry is padded enough that being a few per cent out does not show.
_NARROW = "ijlt!.,;:'|()[]{}`I"
_WIDE = "mwMW@%"
_UPPER = "ABCDEFGHKLNOPQRSTUVXYZ&"


def approx_width(text: str, size: float, bold: bool = False) -> float:
    """Roughly how wide *text* is at *size* pixels."""
    total = 0.0
    for ch in text:
        if ch in _NARROW:
            total += 0.30
        elif ch in _WIDE:
            total += 0.90
        elif ch in _UPPER:
            total += 0.68
        elif ch == " ":
            total += 0.28
        elif ord(ch) > 0x2E80:          # CJK and friends are square
            total += 1.0
        else:
            total += 0.55
    return total * size * (1.06 if bold else 1.0)


@dataclass
class Style:
    """Colours, type size, and a way to measure text."""

    palette: Dict[str, str] = field(default_factory=lambda: dict(LIGHT))
    size: float = 14.0
    measure: Optional[Callable[[str, float, bool], float]] = None
    #: How wide a label may run before it wraps.  Mermaid wraps at 200px and
    #: this is the same idea: without it one long label sets the width of a
    #: whole rank, and the diagram comes out wider than any screen.
    wrap: float = 0.0

    def width(self, text: str, size: float = 0.0, bold: bool = False) -> float:
        size = size or self.size
        if self.measure is not None:
            return self.measure(text, size, bold)
        return approx_width(text, size, bold)

    def block(self, lines, size: float = 0.0, bold: bool = False) -> tuple:
        """The width and height of a run of lines."""
        size = size or self.size
        width = max((self.width(l, size, bold) for l in lines), default=0.0)
        return width, len(lines) * self.line_h(size)

    def lines(self, text: str, size: float = 0.0, bold: bool = False,
              limit: float = 0.0) -> List[str]:
        """The author's own line breaks, then wrapping for what is still long.

        A single word wider than the limit is left alone: breaking inside
        ``TruthTableManager`` would cost more than the width it saves.
        """
        size = size or self.size
        limit = limit or self.wrap or self.size * 15
        out: List[str] = []
        for para in text.split("\n"):
            if self.width(para, size, bold) <= limit:
                out.append(para)
                continue
            line = ""
            for word in para.split(" "):
                trial = f"{line} {word}" if line else word
                if line and self.width(trial, size, bold) > limit:
                    out.append(line)
                    line = word
                else:
                    line = trial
            out.append(line)
        return out or [""]

    def line_h(self, size: float = 0.0) -> float:
        return (size or self.size) * 1.45

    def color(self, key: str) -> str:
        return self.palette.get(key, "#888888")


def style_for(theme: str = "light", size: float = 14.0, measure=None) -> Style:
    return Style(palette=dict(PALETTES.get(theme, LIGHT)), size=size,
                 measure=measure)


# --------------------------------------------------------------------------
# Scene primitives
# --------------------------------------------------------------------------


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float
    fill: str = ""
    stroke: str = ""
    rx: float = 0.0
    width: float = 1.0
    dash: str = ""          # "" | "dash" | "dot"


@dataclass
class Ellipse:
    cx: float
    cy: float
    rx: float
    ry: float
    fill: str = ""
    stroke: str = ""
    width: float = 1.0
    dash: str = ""


@dataclass
class Poly:
    points: List[Tuple[float, float]] = field(default_factory=list)
    fill: str = ""
    stroke: str = ""
    width: float = 1.0
    dash: str = ""


@dataclass
class Line:
    """An open polyline: one or more joined segments."""

    points: List[Tuple[float, float]] = field(default_factory=list)
    stroke: str = ""
    width: float = 1.0
    dash: str = ""


@dataclass
class Text:
    """A single line of text, positioned by its *vertical centre*."""

    x: float
    y: float
    text: str
    fill: str = "#000000"
    size: float = 14.0
    anchor: str = "middle"          # start | middle | end
    bold: bool = False
    italic: bool = False
    mono: bool = False


@dataclass
class Scene:
    width: float = 0.0
    height: float = 0.0
    items: List[object] = field(default_factory=list)


MARGIN = 8.0


def render(model, style: Optional[Style] = None) -> Optional[Scene]:
    """Lay *model* out into a :class:`Scene`, or ``None`` if it cannot be."""
    style = style or Style()
    kind = getattr(model, "kind", "")
    try:
        if kind == "flowchart":
            return _flowchart_scene(model, style)
        if kind == "sequence":
            return _sequence_scene(model, style)
        if kind == "class":
            return _class_scene(model, style)
    except (ValueError, KeyError, IndexError, ZeroDivisionError,
            RecursionError, OverflowError):
        return None
    return None


# --------------------------------------------------------------------------
# Layered layout, shared by flowcharts and class diagrams
# --------------------------------------------------------------------------


def _rank_nodes(ids: List[str], links: List[tuple]) -> Dict[str, int]:
    """Longest-path ranks, with edges that close a cycle left out."""
    adj: Dict[str, List[str]] = {i: [] for i in ids}
    for src, dst in links:
        if src != dst and src in adj and dst in adj:
            adj[src].append(dst)

    # Depth-first colouring: an edge back into the current path would make
    # the ranking impossible, so it does not get a say in it.
    color = {i: 0 for i in ids}     # 0 unseen, 1 on the stack, 2 finished
    back = set()
    for root in ids:
        if color[root]:
            continue
        color[root] = 1
        stack = [(root, iter(adj[root]))]
        while stack:
            node, it = stack[-1]
            for nxt in it:
                if color[nxt] == 1:
                    back.add((node, nxt))
                elif color[nxt] == 0:
                    color[nxt] = 1
                    stack.append((nxt, iter(adj[nxt])))
                    break
            else:
                color[node] = 2
                stack.pop()

    forward = [(s, d) for s, d in links
               if s != d and (s, d) not in back and s in adj and d in adj]
    indeg = {i: 0 for i in ids}
    for _, dst in forward:
        indeg[dst] += 1
    rank = {i: 0 for i in ids}
    queue = [i for i in ids if not indeg[i]]
    out: Dict[str, List[str]] = {i: [] for i in ids}
    for src, dst in forward:
        out[src].append(dst)
    while queue:
        node = queue.pop(0)
        for nxt in out[node]:
            rank[nxt] = max(rank[nxt], rank[node] + 1)
            indeg[nxt] -= 1
            if not indeg[nxt]:
                queue.append(nxt)

    # Longest-path puts every node as early as it will go, which leaves the
    # edges into a shared sink stretched across the whole depth of the
    # picture -- exactly what a dependency graph is, with everything reaching
    # down to one root.  Slide each node along its slack to where its own
    # edges are shortest: the median of the ranks it connects to, which is
    # what minimises the distance to all of them at once.
    ins: Dict[str, List[str]] = {i: [] for i in ids}
    for src, dst in forward:
        ins[dst].append(src)
    for _ in range(8):
        moved = False
        for node in ids:
            if not out[node] or not ins[node]:
                continue                # a source or a sink is already home
            low = max(rank[p] for p in ins[node]) + 1
            high = min(rank[c] for c in out[node]) - 1
            if low > high:
                continue
            near = sorted(rank[n] for n in ins[node] + out[node])
            want = min(max(near[len(near) // 2], low), high)
            if want != rank[node]:
                rank[node] = want
                moved = True
        if not moved:
            break
    return rank


def _between(upper: List[str], lower: List[str], neighbours) -> int:
    """How many edges cross in the band between two neighbouring ranks."""
    spot = {n: i for i, n in enumerate(lower)}
    seq: List[int] = []
    for node in upper:
        seq.extend(sorted(spot[m] for m in neighbours(node) if m in spot))
    return sum(1 for i, a in enumerate(seq) for b in seq[i + 1:] if a > b)


def _crossings(layers: Dict[int, List[str]], ranks, neighbours) -> int:
    return sum(_between(layers[a], layers[b], neighbours)
               for a, b in zip(ranks, ranks[1:]))


def _transpose(layers: Dict[int, List[str]], ranks, neighbours,
               rounds: int = 4):
    """Swap neighbours within a rank while doing so removes a crossing.

    The median pass gets each rank roughly right but cannot tell two nodes
    with the same median apart, so it leaves such pairs in whatever order it
    found them.  This is what settles them.

    Whether a swap pays is worked out from the pair alone -- every edge of
    the one against every edge of the other, and which way round they run --
    rather than by counting the whole band again for each candidate.  The
    band count is the same arithmetic done over and over for edges that
    cannot have changed.
    """
    spots = {r: {n: i for i, n in enumerate(layers[r])} for r in ranks}

    def pays(left: str, right: str, other: int) -> int:
        """Crossings a swap of *left* and *right* would remove, one band."""
        spot = spots.get(other)
        if spot is None:
            return 0
        ours = [spot[n] for n in neighbours(left) if n in spot]
        theirs = [spot[n] for n in neighbours(right) if n in spot]
        if not ours or not theirs:
            return 0
        return (sum(1 for a in ours for b in theirs if a > b)
                - sum(1 for a in ours for b in theirs if a < b))

    for _ in range(rounds):
        moved = False
        for r in ranks:
            row = layers[r]
            for i in range(len(row) - 1):
                left, right = row[i], row[i + 1]
                if pays(left, right, r - 1) + pays(left, right, r + 1) > 0:
                    row[i], row[i + 1] = right, left
                    spots[r][left], spots[r][right] = i + 1, i
                    moved = True
        if not moved:
            break


def _order_layers(layers: Dict[int,
                  List[str]],
                  neighbours,
                  cluster_of,
                  passes: int = 8) -> int:
    """Cut down crossings: sort each rank by where its neighbours sit.

    Returns how many crossings the arrangement it settled on has, so that
    the caller can try more than one starting point and keep the tidiest.
    """
    ranks = sorted(layers)
    best = {r: list(layers[r]) for r in ranks}
    best_score = _crossings(layers, ranks, neighbours)
    for step in range(passes):
        sweep = ranks[1:] if step % 2 == 0 else ranks[-2::-1]
        other = -1 if step % 2 == 0 else 1
        for r in sweep:
            index = {n: i for i, n in enumerate(layers.get(r + other, ()))}
            if not index:
                continue
            current = {n: i for i, n in enumerate(layers[r])}

            def key(node, index=index, current=current):
                spots = [index[n] for n in neighbours(node) if n in index]
                if not spots:
                    return (current[node], current[node])
                spots.sort()
                mid = spots[len(spots) // 2] if len(spots) % 2 else \
                    (spots[len(spots) // 2 - 1] + spots[len(spots) // 2]) / 2
                return (mid * len(layers[r]) / max(1, len(index)), current[node])

            layers[r].sort(key=key)

        # A sweep can end worse than it started, so keep the best
        # arrangement seen rather than whichever one came last.
        _transpose(layers, ranks, neighbours)
        score = _crossings(layers, ranks, neighbours)
        if score < best_score:
            best_score = score
            best = {r: list(layers[r]) for r in ranks}
    for r in ranks:
        layers[r][:] = best[r]

    if not cluster_of:
        return best_score
    # Keep the members of a subgraph together, so its box does not have to
    # swallow half the diagram to reach them all.
    for r in ranks:
        spots = {n: i for i, n in enumerate(layers[r])}
        means: Dict[str, float] = {}
        for node in layers[r]:
            cid = cluster_of(node)
            if cid:
                means.setdefault(cid, 0.0)
        for cid in means:
            members = [spots[n] for n in layers[r] if cluster_of(n) == cid]
            means[cid] = sum(members) / len(members)
        layers[r].sort(key=lambda n: (means.get(cluster_of(n), spots[n]),
                                      spots[n]))
    return _crossings(layers, ranks, neighbours)


def _priority_place(order, want, size, gaps, pos, priority):
    """Give each node what it wants, best-ranked first.

    A node is only ever shoved aside by one that outranks it.  That is what
    keeps a long edge's run of invisible nodes on one straight line: without
    it the boxes on every rank the edge crosses each nudge it a little
    further off, and what should be a straight line comes out as a wander.
    """
    n = len(order)
    rung = {node: priority(node) for node in order}

    def left_edge(i):
        return pos[order[i]] - size[order[i]] / 2

    def right_edge(i):
        return pos[order[i]] + size[order[i]] / 2

    for i in sorted(range(n), key=lambda k: (-rung[order[k]], k)):
        node = order[i]
        target = want.get(node)
        if target is None:
            continue
        mine = rung[node]

        # How far it may go before it would have to move its betters: walk
        # back from the first node that outranks it, subtracting what has to
        # fit in between.
        stop = next((j for j in range(i + 1, n) if rung[order[j]] >= mine), n)
        if stop < n:
            x = left_edge(stop)
            for j in range(stop - 1, i, -1):
                x -= gaps[j + 1] + size[order[j]]
            high = x - gaps[i + 1] - size[node] / 2
        else:
            high = 1e9
        stop = next((j for j in range(i - 1, -1, -1)
                     if rung[order[j]] >= mine), -1)
        if stop >= 0:
            x = right_edge(stop)
            for j in range(stop + 1, i):
                x += gaps[j] + size[order[j]]
            low = x + gaps[i] + size[node] / 2
        else:
            low = -1e9
        if low > high:              # no room to move at all
            continue
        pos[node] = min(max(target, low), high)

        edge = pos[node] + size[node] / 2       # and take the room it needs
        for j in range(i + 1, n):
            need = edge + gaps[j] + size[order[j]] / 2
            if pos[order[j]] >= need:
                break
            pos[order[j]] = need
            edge = need + size[order[j]] / 2
        edge = pos[node] - size[node] / 2
        for j in range(i - 1, -1, -1):
            need = edge - gaps[j + 1] - size[order[j]] / 2
            if pos[order[j]] <= need:
                break
            pos[order[j]] = need
            edge = need - size[order[j]] / 2
    return pos


def _place(order: List[str], want: Dict[str, float], size: Dict[str, float],
           gap: float, extra=None, priority=None) -> Dict[str, float]:
    """Positions as near *want* as the sizes and *gap* allow, in order.

    *extra* asks for more room between one particular pair than the standard
    gap -- it is what keeps a subgraph's box from swallowing the node next
    door, which belongs to nobody.
    """
    gaps = [gap] * max(0, len(order))
    if extra is not None:
        for i in range(1, len(order)):
            gaps[i] = gap + extra(order[i - 1], order[i])
    pos: Dict[str, float] = {}
    edge = -1e9
    for i, node in enumerate(order):
        half = size[node] / 2
        floor = edge + (gaps[i] if i else gap) + half
        pos[node] = max(want.get(node, floor), floor)
        edge = pos[node] + half
    if priority is not None:
        return _priority_place(order, want, size, gaps, pos, priority)
    # Pull back to the left wherever there is slack, so a rank that was
    # pushed right by one wide node does not drag the rest along with it.
    edge = 1e9
    for i in range(len(order) - 1, -1, -1):
        node = order[i]
        half = size[node] / 2
        target = want.get(node, pos[node])
        if target < pos[node]:
            room = gaps[i + 1] if i + 1 < len(order) else gap
            pos[node] = max(target, min(pos[node], edge - room - half))
        edge = pos[node] - half
    return pos


@dataclass
class _Layout:
    pos: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    routes: List[List[Tuple[float, float]]] = field(default_factory=list)
    boxes: Dict[str, Tuple[float, float, float, float]] = field(
        default_factory=dict)
    #: Where each labelled link's caption goes, by link index.
    captions: Dict[int, Tuple[float, float]] = field(default_factory=dict)
    width: float = 0.0
    height: float = 0.0


def _graph_layout(ids, sizes, links, direction, style, clusters=(),
                  labels=None) -> _Layout:
    """Rank, order and place *ids*; route *links* through the result.

    *labels* maps a link's index to the size of its caption.  A caption is
    laid out like a node of that size, sitting on the link's own route: that
    is what stops it from landing on a box it has nothing to do with.
    """
    horizontal = direction in ("LR", "RL")
    gap_cross = style.size * 1.8
    labels = labels or {}
    # Ranks are counted in halves only when something needs the half: a
    # caption rides on the rank between its link's two ends.  With no
    # captions to place, the empty half-ranks buy nothing and cost every
    # link an invisible node, which is one more place for it to kink.
    halves = 2 if labels else 1
    gap_rank = style.size * (2.0 if horizontal else 1.5) * (3 - halves)
    dummy_cross = style.size * 0.9

    def cross_size(nid):
        w, h = sizes[nid]
        return h if horizontal else w

    def rank_size(nid):
        w, h = sizes[nid]
        return w if horizontal else h

    rank = {n: halves * r for n, r in _rank_nodes(ids, links).items()}

    # Chains: a link travels as an invisible node on every rank it crosses,
    # which is what keeps a long one from cutting through the boxes in
    # between.  The half-rank next to its start is where its caption rides.
    chains: List[List[str]] = []
    dummies: Dict[str, float] = {}
    spans: Dict[str, Tuple[float, float]] = {}
    captions: Dict[int, str] = {}
    for k, (src, dst) in enumerate(links):
        if src == dst or src not in rank or dst not in rank:
            chains.append([])
            continue
        lo, hi = rank[src], rank[dst]
        step = 1 if hi >= lo else -1
        chain = [src]
        for r in range(lo + step, hi, step):
            name = f"\x00d{k}_{r}"
            dummies[name] = r
            chain.append(name)
        chain.append(dst)
        chains.append(chain)
        if k in labels and len(chain) > 2:
            mark = chain[len(chain) // 2]
            captions[k] = mark
            width, height = labels[k]
            spans[mark] = (height, width) if horizontal else (width, height)

    adjacent: Dict[str, List[str]] = {}
    forward: Dict[str, List[str]] = {}
    for chain in chains:
        for a, b in zip(chain, chain[1:]):
            adjacent.setdefault(a, []).append(b)
            adjacent.setdefault(b, []).append(a)
            forward.setdefault(a, []).append(b)

    # Seed each rank's order by walking the graph from its starting points,
    # rather than by how the nodes happened to be written down.  A long edge
    # travels as an invisible node on every rank it crosses, and this is what
    # puts that line of them beside the node they came from instead of out at
    # the edge of the picture with all the other long edges.
    written = {nid: k for k, nid in enumerate(ids)}

    def walk(starts, flip: bool) -> Dict[int, List[str]]:
        out: Dict[int, List[str]] = {}
        seen: set = set()
        for start in starts:
            stack = [start]
            while stack:
                node = stack.pop()
                if node in seen:
                    continue
                seen.add(node)
                out.setdefault(_rank_of(node, rank, dummies), []).append(node)
                kids = forward.get(node, ())
                for nxt in (kids if flip else tuple(reversed(kids))):
                    if nxt not in seen:
                        stack.append(nxt)
        for name, r in dummies.items():     # anything the walk never reached
            if name not in seen:
                seen.add(name)
                out.setdefault(r, []).append(name)
        return out

    # Several starting points, not one.  The median and the swaps only ever
    # walk downhill from where they begin, so the arrangement they settle on
    # is decided by the order the graph happened to be walked in -- and the
    # first walk is no more likely to be the right one than any other.
    # Trying a few and keeping the tidiest is what gets past that.
    by_rank = sorted(ids, key=lambda n: (rank[n], written[n]))
    seeds = [walk(by_rank, False),                          # as written
             walk(by_rank, True),                           # children reversed
             walk(sorted(ids, key=lambda n: (rank[n], -written[n])), False),
             walk(sorted(ids, key=lambda n: (rank[n], -len(adjacent.get(n, ())),
                                             written[n])), False)]   # busiest
    shuffler = random.Random(SHUFFLE_SEED)
    for _ in range(RESTARTS):
        shuffled = list(ids)
        shuffler.shuffle(shuffled)
        seeds.append(walk(sorted(shuffled, key=lambda n: rank[n]), False))

    home = {}
    for cid, members in clusters:
        for member in members:
            home.setdefault(member, cid)

    grouped = (lambda n: home.get(n, "")) if clusters else None
    layers, fewest = seeds[0], None
    for seed in seeds:
        score = _order_layers(seed, lambda n: adjacent.get(n, ()), grouped)
        if fewest is None or score < fewest:
            layers, fewest = seed, score
            if not fewest:              # nothing crosses; nothing to beat
                break

    span = {n: (cross_size(n) if n in sizes
                else spans[n][0] if n in spans else dummy_cross)
            for r in layers for n in layers[r]}

    def apart(left: str, right: str) -> float:
        """More room at a subgraph's edge than inside it, so its box has
        somewhere to go without landing on the node next door."""
        return 0.0 if home.get(left, "") == home.get(right, "") \
            else style.size * 1.7

    cross: Dict[str, float] = {}
    for r in sorted(layers):
        cross.update(_place(layers[r], {}, span, gap_cross, apart))
    # Settle: pull each node towards the average of everything it connects
    # to, on the rank above *and* the one below, then push apart whatever
    # that put on top of something else.  Looking only one way at a time --
    # the obvious way to write this -- lets a long chain lag by a little on
    # every rank, and a diagram that should be one column comes out as a
    # wide diagonal staircase.
    # An invisible node outranks every real box: one long edge drawn
    # straight is worth more than any single box sitting exactly on the
    # average of its neighbours.  A caption is the exception -- it still
    # claims the room its text needs, but it gives way on where that room
    # is, because a caption dragging its whole edge sideways to sit exactly
    # on the line costs far more than the caption sitting a little off it.
    def rung(node):
        if node in spans:
            return 500
        return 1000 if node in dummies else len(adjacent.get(node, ()))

    for step in range(8):
        ranks = sorted(layers)
        sweep = ranks if step % 2 == 0 else ranks[::-1]
        for r in sweep:
            want = {}
            for node in layers[r]:
                near = [cross[n] for n in adjacent.get(node, ())
                        if n in cross and _rank_of(n, rank, dummies) != r]
                if near:
                    want[node] = sum(near) / len(near)
            cross.update(_place(layers[r], want, span, gap_cross, apart,
                                priority=rung))

    # The rank axis: each rank sits below (or right of) the deepest node on
    # the one before it.
    depth: Dict[int, float] = {}
    offset: Dict[int, float] = {}
    # A subgraph's title needs a clear band above its first rank, or it lands
    # on whatever box happens to sit at the top of the box it titles.
    titled = set()
    for cid, members in clusters:
        inside = [_rank_of(m, rank, dummies) for m in members
                  if m in rank or m in dummies]
        if inside:
            titled.add(min(inside))
    run = 0.0
    for r in sorted(layers):
        if r in titled:
            run += style.size * 1.6
        deep = max([rank_size(n) for n in layers[r] if n in sizes]
                   + [spans[n][1] for n in layers[r] if n in spans],
                   default=0.0)
        depth[r] = deep
        offset[r] = run + deep / 2
        run += deep + gap_rank
    total_rank = max(0.0, run - gap_rank)
    low = min((cross[n] - span[n] / 2 for n in cross), default=0.0)
    high = max((cross[n] + span[n] / 2 for n in cross), default=0.0)
    total_cross = high - low

    def point(node):
        r = _rank_of(node, rank, dummies)
        c = cross[node] - low
        d = offset[r]
        if direction == "TB":
            return c, d
        if direction == "BT":
            return c, total_rank - d
        if direction == "LR":
            return d, c
        return total_rank - d, c

    out = _Layout()
    for nid in ids:
        out.pos[nid] = point(nid)
    for chain in chains:
        out.routes.append([point(n) for n in chain])
    for k, mark in captions.items():
        out.captions[k] = point(mark)
    out.width = (total_cross if not horizontal else total_rank)
    out.height = (total_rank if not horizontal else total_cross)

    if clusters:
        out.boxes = _cluster_boxes(clusters, out.pos, sizes, style)
    return out


def _rank_of(node, rank, dummies):
    return dummies[node] if node in dummies else rank[node]


def _cluster_boxes(clusters, pos, sizes, style):
    """A padded box round each subgraph, innermost ones first."""
    members = {cid: list(names) for cid, names in clusters}
    boxes: Dict[str, tuple] = {}

    def box_for(cid, seen=()):
        if cid in boxes:
            return boxes[cid]
        if cid in seen:
            return None
        pad = style.size * 0.9
        top = style.size * 2.0
        x0 = y0 = 1e9
        x1 = y1 = -1e9
        for name in members.get(cid, ()):
            if name in pos:
                cx, cy = pos[name]
                w, h = sizes[name]
                x0, y0 = min(x0, cx - w / 2), min(y0, cy - h / 2)
                x1, y1 = max(x1, cx + w / 2), max(y1, cy + h / 2)
            elif name in members:
                inner = box_for(name, tuple(seen) + (cid,))
                if inner:
                    x0, y0 = min(x0, inner[0]), min(y0, inner[1])
                    x1 = max(x1, inner[0] + inner[2])
                    y1 = max(y1, inner[1] + inner[3])
        if x1 < x0:
            return None
        boxes[cid] = (x0 - pad, y0 - top, x1 - x0 + 2 * pad,
                      y1 - y0 + top + pad)
        return boxes[cid]

    for cid, _ in clusters:
        box_for(cid)
    return boxes


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------


def _boundary(shape: str, cx, cy, w, h, px, py):
    """Where the ray from the centre towards (px, py) leaves the shape."""
    dx, dy = px - cx, py - cy
    if not dx and not dy:
        return cx, cy
    rx, ry = max(w / 2, 0.5), max(h / 2, 0.5)
    if shape in ("circle", "doublecircle"):
        t = 1.0 / math.hypot(dx / rx, dy / ry)
    elif shape == "rhombus":
        t = 1.0 / (abs(dx) / rx + abs(dy) / ry)
    else:
        t = min(rx / abs(dx) if dx else 1e9, ry / abs(dy) if dy else 1e9)
    return cx + dx * t, cy + dy * t


def _smooth(points: List[Tuple[float, float]],
            steps: int = 8) -> List[Tuple[float, float]]:
    """Round a route off into a curve that still passes through its points.

    A route runs straight between the slots kept for it on every rank it
    crosses, so drawn as it stands it turns a visible corner at each one.
    This is a centripetal Catmull-Rom through the same points: it keeps
    them, because those slots are what hold the line clear of the boxes,
    and only rounds off the corners in between.
    """
    if len(points) < 3:
        return list(points)
    pts = [points[0]] + list(points) + [points[-1]]
    out: List[Tuple[float, float]] = [points[0]]
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        # Centripetal parametrisation -- knots spaced by the square root of
        # the distance.  It is what stops a tight turn from looping back on
        # itself, which the plain uniform form does.
        knots = [0.0]
        for a, b in ((p0, p1), (p1, p2), (p2, p3)):
            step = math.dist(a, b) ** 0.5
            knots.append(knots[-1] + (step if step > 1e-6 else 1e-6))
        t0, t1, t2, t3 = knots

        def blend(lo, hi, a, b, u):
            """The point *u* of the way from *a* at *lo* to *b* at *hi*."""
            return [((hi - u) * a[j] + (u - lo) * b[j]) / (hi - lo)
                    for j in (0, 1)]

        for k in range(1, steps + 1):
            u = t1 + (t2 - t1) * k / steps
            a1 = blend(t0, t1, p0, p1, u)
            a2 = blend(t1, t2, p1, p2, u)
            a3 = blend(t2, t3, p2, p3, u)
            b1 = blend(t0, t2, a1, a2, u)
            b2 = blend(t1, t3, a2, a3, u)
            out.append(tuple(blend(t1, t2, b1, b2, u)))

    # Most of a route is straight, and a straight run needs two points, not
    # sixteen: drop whatever sits on the line between its neighbours.
    kept = [out[0]]
    for before, here, after in zip(out, out[1:], out[2:]):
        ax, ay = here[0] - before[0], here[1] - before[1]
        bx, by = after[0] - here[0], after[1] - here[1]
        if abs(ax * by - ay * bx) > 0.12 * (math.hypot(ax, ay)
                                            + math.hypot(bx, by)):
            kept.append(here)
    kept.append(out[-1])
    return kept


def _hits_a_box(run, skip, pos, sizes) -> bool:
    """Does *run* cross a box that is not one of its own two ends?

    Segment against rectangle, not point against rectangle: a line can pass
    clean through a box without any of the points it is drawn from landing
    inside it.
    """
    boxes = [(cx, cy, sizes[nid][0] / 2 - 0.5, sizes[nid][1] / 2 - 0.5)
             for nid, (cx, cy) in pos.items()
             if nid not in skip and nid in sizes]
    for (x1, y1), (x2, y2) in zip(run, run[1:]):
        dx, dy = x2 - x1, y2 - y1
        for cx, cy, hw, hh in boxes:
            near, far = 0.0, 1.0
            for step, room in ((-dx, x1 - (cx - hw)), (dx, (cx + hw) - x1),
                               (-dy, y1 - (cy - hh)), (dy, (cy + hh) - y1)):
                if not step:
                    if room < 0:
                        break
                    continue
                edge = room / step
                if step < 0:
                    if edge > far:
                        break
                    near = max(near, edge)
                else:
                    if edge < near:
                        break
                    far = min(far, edge)
            else:
                return True
    return False


def _off_line(a, b, p) -> float:
    """How far *p* sits off the line from *a* to *b*."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = math.hypot(dx, dy)
    if span < 1e-9:
        return math.dist(a, p)
    return abs(dx * (a[1] - p[1]) - dy * (a[0] - p[0])) / span


def _simplify(points, skip, pos, sizes, slack: float, keep=()):
    """Take out the turns a route does not need.

    A route bends at every rank it crosses, because it is made of the slots
    kept for it on each one, and most of those bends hold the line away from
    nothing: where the straight run between a slot's two neighbours is still
    clear of every box, the slot is not earning its corner.

    Only the small wanderings go.  A slot further than *slack* off the line
    is kept whatever else is true: it is a real detour the route is making,
    and pulling it straight would march the line across the picture rather
    than tidy it.
    """
    if len(points) < 3:
        return list(points)
    anchors = [a for a in keep if a]
    out = list(points)
    i = 1
    while i < len(out) - 1:
        if any(math.dist(out[i], a) < 0.01 for a in anchors):
            i += 1                      # a caption rides on this one
        elif _off_line(out[i - 1], out[i + 1], out[i]) > slack:
            i += 1                      # too far off to be a wobble
        elif _hits_a_box((out[i - 1], out[i + 1]), skip, pos, sizes):
            i += 1                      # the slot is doing a job
        else:
            del out[i]
            i = max(1, i - 1)           # the turn before may go too now
    return out


def _rounded(points, skip, pos, sizes):
    """The route with its corners rounded off, unless that costs too much.

    Rounding bulges the line a little to the outside of every turn, and now
    and then that is enough to put it across a box the straight run cleared.
    Where that happens the straight run is kept: a corner is easier to read
    than a line through a box.
    """
    curved = _smooth(points)
    if _hits_a_box(curved, skip, pos, sizes)             and not _hits_a_box(points, skip, pos, sizes):
        return points
    return curved


def _shorten(x1, y1, x2, y2, amount):
    """Pull (x2, y2) back along the segment, to leave room for an arrow."""
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist <= amount or not dist:
        return x2, y2
    f = (dist - amount) / dist
    return x1 + (x2 - x1) * f, y1 + (y2 - y1) * f


def _head_length(kind: str, style: Style) -> float:
    return {"arrow": style.size * 0.78, "triangle": style.size * 1.0,
            "diamond": style.size * 1.2, "odiamond": style.size * 1.2,
            "circle": style.size * 0.5, "cross": 0.0,
            "async": 0.0}.get(kind, 0.0)


def _head_items(kind: str, tip, tail, style: Style, color: str,
                hollow: str = "") -> List[object]:
    """The decoration drawn at one end of an edge, pointing at *tip*."""
    if not kind:
        return []
    tx, ty = tip
    angle = math.atan2(ty - tail[1], tx - tail[0])
    size = style.size
    fill = hollow or color

    def at(dist, side):
        return (tx - dist * math.cos(angle) - side * math.sin(angle),
                ty - dist * math.sin(angle) + side * math.cos(angle))

    if kind in ("arrow", "triangle"):
        length = _head_length(kind, style)
        half = length * (0.42 if kind == "arrow" else 0.5)
        pts = [(tx, ty), at(length, half), at(length, -half)]
        return [Poly(points=pts, fill=color if kind == "arrow" else fill,
                     stroke=color, width=1.0)]
    if kind in ("diamond", "odiamond"):
        length = _head_length(kind, style)
        half = length * 0.28
        pts = [(tx, ty), at(length / 2, half), at(length, 0.0),
               at(length / 2, -half)]
        return [Poly(points=pts, fill=color if kind == "diamond" else fill,
                     stroke=color, width=1.0)]
    if kind == "circle":
        r = size * 0.25
        return [Ellipse(cx=tx - r * math.cos(angle), cy=ty - r * math.sin(angle),
                        rx=r, ry=r, fill=fill, stroke=color)]
    if kind == "cross":
        r = size * 0.3
        return [Line(points=[at(-r, -r), at(r, r)], stroke=color, width=1.4),
                Line(points=[at(-r, r), at(r, -r)], stroke=color, width=1.4)]
    if kind == "async":            # the open half-arrow of "-)" messages
        length = size * 0.7
        return [Line(points=[at(length, length * 0.5), (tx, ty),
                             at(length, -length * 0.5)],
                     stroke=color, width=1.2)]
    return []


def _dash_for(stroke: str) -> str:
    return {"dotted": "dot", "dashed": "dash", "thick": ""}.get(stroke, "")


def _label_items(text: str, cx, cy, style: Style, color: str,
                 backdrop: str = "", size: float = 0.0) -> List[object]:
    """Centred text with an optional patch of background behind it."""
    if not text:
        return []
    size = size or style.size * 0.86
    lines = style.lines(text, size, limit=style.wrap or style.size * 11)
    w, h = style.block(lines, size)
    items: List[object] = []
    if backdrop:
        items.append(Rect(x=cx - w / 2 - 3, y=cy - h / 2 - 1, w=w + 6, h=h + 2,
                          fill=backdrop, rx=2))
    top = cy - h / 2 + style.line_h(size) / 2
    for k, line in enumerate(lines):
        items.append(Text(x=cx, y=top + k * style.line_h(size), text=line,
                          fill=color, size=size))
    return items


def _translate(items: List[object], dx: float, dy: float):
    for item in items:
        if isinstance(item, (Rect,)):
            item.x += dx
            item.y += dy
        elif isinstance(item, Ellipse):
            item.cx += dx
            item.cy += dy
        elif isinstance(item, Text):
            item.x += dx
            item.y += dy
        elif isinstance(item, (Poly, Line)):
            item.points = [(x + dx, y + dy) for x, y in item.points]
    return items


# --------------------------------------------------------------------------
# Flowcharts
# --------------------------------------------------------------------------


def _node_size(lines: List[str], shape: str,
               style: Style) -> Tuple[float, float]:
    """How big a box holding *lines* has to be, for the shape it is drawn in."""
    tw, th = style.block(lines)
    pad_x, pad_y = style.size * 0.85, style.size * 0.5
    w, h = tw + 2 * pad_x, max(th + 2 * pad_y, style.size * 2.2)
    if shape in ("circle", "doublecircle"):
        d = math.hypot(tw, th) + style.size * 1.1
        if shape == "doublecircle":
            d += style.size * 0.6
        return max(d, style.size * 3), max(d, style.size * 3)
    if shape == "rhombus":
        return 2 * (tw / 2 + pad_x * 2 + th), 2 * (th / 2 + pad_y * 2 + th / 2)
    if shape == "hexagon":
        return w + h * 0.6, h
    if shape in ("parallelogram", "parallelogram_alt"):
        return w + h * 0.5, h
    if shape in ("trapezoid", "trapezoid_alt"):
        return w + h * 1.0, h
    if shape == "cylinder":
        return w, h + style.size * 0.9
    if shape == "subroutine":
        return w + style.size * 1.2, h
    if shape == "asymmetric":
        return w + style.size * 0.9, h
    if shape == "stadium":
        return w + style.size * 0.6, h
    return max(w, style.size * 3), h


def _node_items(shape: str, x, y, w, h, style: Style) -> List[object]:
    """The outline of one flowchart box, at its final place."""
    fill, stroke = style.color("node_fill"), style.color("node_stroke")
    cx, cy = x + w / 2, y + h / 2
    if shape == "rect":
        return [Rect(x=x, y=y, w=w, h=h, fill=fill, stroke=stroke)]
    if shape == "round":
        return [Rect(x=x, y=y, w=w, h=h, fill=fill, stroke=stroke,
                     rx=min(style.size * 0.55, h / 2))]
    if shape == "stadium":
        return [Rect(x=x, y=y, w=w, h=h, fill=fill, stroke=stroke, rx=h / 2)]
    if shape == "subroutine":
        inset = style.size * 0.45
        return [Rect(x=x, y=y, w=w, h=h, fill=fill, stroke=stroke),
                Line(points=[(x + inset, y), (x + inset, y + h)], stroke=stroke),
                Line(points=[(x + w - inset, y), (x + w - inset, y + h)],
                     stroke=stroke)]
    if shape == "cylinder":
        lid = style.size * 0.45
        return [Ellipse(cx=cx, cy=y + h - lid, rx=w / 2, ry=lid, fill=fill,
                        stroke=stroke),
                Rect(x=x, y=y + lid, w=w, h=h - 2 * lid, fill=fill),
                Line(points=[(x, y + lid), (x, y + h - lid)], stroke=stroke),
                Line(points=[(x + w, y + lid), (x + w, y + h - lid)],
                     stroke=stroke),
                Ellipse(cx=cx, cy=y + lid, rx=w / 2, ry=lid, fill=fill,
                        stroke=stroke)]
    if shape == "circle":
        return [Ellipse(cx=cx, cy=cy, rx=w / 2, ry=h / 2, fill=fill,
                        stroke=stroke)]
    if shape == "doublecircle":
        gap = style.size * 0.3
        return [Ellipse(cx=cx, cy=cy, rx=w / 2, ry=h / 2, fill=fill,
                        stroke=stroke),
                Ellipse(cx=cx, cy=cy, rx=w / 2 - gap, ry=h / 2 - gap, fill="",
                        stroke=stroke)]
    if shape == "rhombus":
        return [Poly(points=[(cx, y), (x + w, cy), (cx, y + h), (x, cy)],
                     fill=fill, stroke=stroke)]
    if shape == "hexagon":
        cut = min(h * 0.3, w * 0.25)
        return [Poly(points=[(x + cut, y), (x + w - cut, y), (x + w, cy),
                             (x + w - cut, y + h), (x + cut, y + h), (x, cy)],
                     fill=fill, stroke=stroke)]
    if shape in ("parallelogram", "parallelogram_alt"):
        lean = min(h * 0.5, w * 0.3)
        pts = ([(x + lean, y), (x + w, y), (x + w - lean, y + h), (x, y + h)]
               if shape == "parallelogram" else
               [(x, y), (x + w - lean, y), (x + w, y + h), (x + lean, y + h)])
        return [Poly(points=pts, fill=fill, stroke=stroke)]
    if shape in ("trapezoid", "trapezoid_alt"):
        lean = min(h * 0.55, w * 0.3)
        pts = ([(x + lean, y), (x + w - lean, y), (x + w, y + h), (x, y + h)]
               if shape == "trapezoid" else
               [(x, y), (x + w, y), (x + w - lean, y + h), (x + lean, y + h)])
        return [Poly(points=pts, fill=fill, stroke=stroke)]
    if shape == "asymmetric":
        notch = min(style.size * 0.9, w * 0.25)
        return [Poly(points=[(x, y), (x + w - notch, y), (x + w, cy),
                             (x + w - notch, y + h), (x, y + h),
                             (x + notch, cy)], fill=fill, stroke=stroke)]
    return [Rect(x=x, y=y, w=w, h=h, fill=fill, stroke=stroke)]


def _flowchart_scene(chart: MM.Flowchart, style: Style) -> Optional[Scene]:
    ids = list(chart.nodes)
    if not ids:
        return None
    # Wrap once: the size of a box and the text drawn in it have to come
    # from the very same lines, or the label spills out of its shape.
    labels = {nid: style.lines(chart.nodes[nid].text or nid) for nid in ids}
    sizes = {nid: _node_size(labels[nid], chart.nodes[nid].shape, style)
             for nid in ids}
    links = [(e.src, e.dst) for e in chart.edges]
    clusters = [(s.id, s.members) for s in chart.subgraphs if s.members]
    captions = {k: _caption_size(e.text, style)
                for k, e in enumerate(chart.edges) if e.text}
    lay = _graph_layout(ids, sizes, links, chart.direction, style, clusters,
                        captions)

    items: List[object] = []
    titles: List[object] = []       # subgraph titles, drawn over everything
    # Subgraph boxes go down first so everything else sits on top of them.
    for sub in chart.subgraphs:
        box = lay.boxes.get(sub.id)
        if not box:
            continue
        x, y, w, h = box
        items.append(Rect(x=x, y=y, w=w, h=h, fill=style.color("cluster_fill"),
                          stroke=style.color("cluster_stroke"), rx=style.size * 0.4,
                          dash="dash"))
        if sub.title:
            # Titled from the top left, on its own patch of the box's colour.
            # Centred, it lands on whatever node happens to sit at the top of
            # the box; the corner is nearly always clear.
            size = style.size * 0.92
            pad = style.size * 0.5
            wide = style.width(sub.title, size, True)
            titles.append(Rect(x=x + pad / 2, y=y + pad / 2, w=wide + pad,
                               h=style.line_h(size),
                               fill=style.color("cluster_fill"), rx=2))
            titles.append(Text(x=x + pad, y=y + pad / 2 + style.line_h(size) / 2,
                               text=sub.title, fill=style.color("cluster_text"),
                               size=size, anchor="start", bold=True))

    # Lines first, then the boxes, then the labels that go with the lines:
    # a label belongs on top of whatever its edge happens to pass over,
    # otherwise a box lands on it and leaves a stray letter showing.
    over: List[object] = []
    for k, (edge, route) in enumerate(zip(chart.edges, lay.routes)):
        drawn, label = _edge_items(edge, route, chart, sizes, lay, style,
                                   lay.captions.get(k))
        items.extend(drawn)
        over.extend(label)

    for nid in ids:
        node = chart.nodes[nid]
        cx, cy = lay.pos[nid]
        w, h = sizes[nid]
        items.extend(_node_items(node.shape, cx - w / 2, cy - h / 2, w, h, style))
        lines = labels[nid]
        _, th = style.block(lines)
        top = cy - th / 2 + style.line_h() / 2
        for k, line in enumerate(lines):
            items.append(Text(x=cx, y=top + k * style.line_h(), text=line,
                              fill=style.color("node_text"), size=style.size))

    return _finish(items + titles + over, style)


def _caption_size(text: str, style: Style) -> Tuple[float, float]:
    """The room an edge label needs, as the layout has to reserve it."""
    size = style.size * 0.86
    w, h = style.block(style.lines(text, size, limit=style.wrap or
                                   style.size * 11), size)
    return w + style.size * 0.8, h + style.size * 0.5


def _edge_items(edge, route, chart, sizes, lay, style, spot=None) -> tuple:
    """One edge, as (what to draw under the boxes, what to draw over them)."""
    color = style.color("edge")
    width = 2.2 if edge.stroke == "thick" else 1.3
    dash = _dash_for(edge.stroke)

    if edge.src == edge.dst or len(route) < 2:      # a loop back to itself
        if edge.src not in lay.pos:
            return [], []
        cx, cy = lay.pos[edge.src]
        w, h = sizes[edge.src]
        out = w / 2 + style.size * 1.6
        pts = _smooth([(cx + w / 2, cy - h / 4), (cx + out, cy - h / 4),
                       (cx + out, cy + h / 4), (cx + w / 2, cy + h / 4)])
        items = [Line(points=pts, stroke=color, width=width, dash=dash)]
        items += _head_items(edge.dst_head, pts[-1], pts[-2], style, color)
        return items, _label_items(edge.text, cx + out + style.size, cy, style,
                                   style.color("edge_text"),
                                   style.color("label_bg"))

    points = _simplify(list(route), (edge.src, edge.dst), lay.pos, sizes,
                       style.size * 1.4, (spot,))
    src_shape = chart.nodes[edge.src].shape
    dst_shape = chart.nodes[edge.dst].shape
    sw, sh = sizes[edge.src]
    dw, dh = sizes[edge.dst]
    points[0] = _boundary(src_shape, points[0][0], points[0][1], sw, sh,
                          *points[1])
    points[-1] = _boundary(dst_shape, points[-1][0], points[-1][1], dw, dh,
                           *points[-2])
    # The heads take their angle from the curve, not the route behind it.
    points = _rounded(points, (edge.src, edge.dst), lay.pos, sizes)
    tip, tail = points[-1], points[-2]
    back_tip, back_tail = points[0], points[1]
    items: List[object] = []
    drawn = list(points)
    if edge.dst_head:
        drawn[-1] = _shorten(*tail, *tip, _head_length(edge.dst_head, style))
    if edge.src_head:
        drawn[0] = _shorten(*back_tail, *back_tip,
                            _head_length(edge.src_head, style))
    items.append(Line(points=drawn, stroke=color, width=width, dash=dash))
    items += _head_items(edge.dst_head, tip, tail, style, color)
    items += _head_items(edge.src_head, back_tip, back_tail, style, color)

    caption: List[object] = []
    if edge.text:
        if spot is not None:            # the slot the layout kept for it
            lx, ly = spot
        else:                           # no slot: the middle of the route
            mid = len(points) // 2
            lx = (points[mid - 1][0] + points[mid][0]) / 2
            ly = (points[mid - 1][1] + points[mid][1]) / 2
        caption = _label_items(edge.text, lx, ly, style,
                               style.color("edge_text"),
                               style.color("label_bg"))
    return items, caption


def _finish(items: List[object], style: Style) -> Scene:
    """Shift everything into view and measure the result."""
    x0 = y0 = 1e9
    x1 = y1 = -1e9
    for item in items:
        for x, y in _extent(item, style):
            x0, y0 = min(x0, x), min(y0, y)
            x1, y1 = max(x1, x), max(y1, y)
    if x1 < x0:
        return Scene(width=1, height=1, items=[])
    _translate(items, MARGIN - x0, MARGIN - y0)
    return Scene(width=x1 - x0 + 2 * MARGIN, height=y1 - y0 + 2 * MARGIN,
                 items=items)


def _extent(item, style: Style):
    if isinstance(item, Rect):
        return [(item.x, item.y), (item.x + item.w, item.y + item.h)]
    if isinstance(item, Ellipse):
        return [(item.cx - item.rx, item.cy - item.ry),
                (item.cx + item.rx, item.cy + item.ry)]
    if isinstance(item, (Poly, Line)):
        return item.points
    if isinstance(item, Text):
        w = style.width(item.text, item.size, item.bold)
        half = w / 2 if item.anchor == "middle" else (0 if item.anchor == "start"
                                                      else w)
        return [(item.x - half, item.y - item.size),
                (item.x - half + w, item.y + item.size)]
    return []


# --------------------------------------------------------------------------
# Class diagrams
# --------------------------------------------------------------------------


def _class_size(box: MM.ClassBox, style: Style) -> Tuple[float, float]:
    pad = style.size * 0.7
    small = style.size * 0.92
    title_w, title_h = style.block([box.name], style.size, bold=True)
    if box.stereotype:
        sw, sh = style.block([f"«{box.stereotype}»"], small)
        title_w, title_h = max(title_w, sw), title_h + sh
    body = box.attributes + box.methods
    body_w, _ = style.block(body, small) if body else (0.0, 0.0)
    height = title_h + 2 * pad
    for group in (box.attributes, box.methods):
        if group:
            height += len(group) * style.line_h(small) + pad
    if not body:
        height += pad * 0.2
    return max(title_w, body_w) + 2 * pad, height


def _class_items(box: MM.ClassBox, x, y, w, h, style: Style) -> List[object]:
    pad = style.size * 0.7
    small = style.size * 0.92
    fill, stroke = style.color("node_fill"), style.color("node_stroke")
    text = style.color("node_text")
    items: List[object] = [Rect(x=x, y=y, w=w, h=h, fill=fill, stroke=stroke,
                                rx=style.size * 0.15)]
    cy = y + pad + style.line_h() / 2
    if box.stereotype:
        items.append(Text(x=x + w / 2, y=y + pad + style.line_h(small) / 2,
                          text=f"«{box.stereotype}»", fill=text, size=small,
                          italic=True))
        cy += style.line_h(small)
    items.append(Text(x=x + w / 2, y=cy, text=box.name, fill=text,
                      size=style.size, bold=True))
    line = cy + style.line_h() / 2 + pad
    for group in (box.attributes, box.methods):
        if not group:
            continue
        items.append(Line(points=[(x, line), (x + w, line)], stroke=stroke))
        for k, member in enumerate(group):
            items.append(Text(x=x + pad, y=line + pad / 2 +
                              (k + 0.5) * style.line_h(small), text=member,
                              fill=text, size=small, anchor="start"))
        line += len(group) * style.line_h(small) + pad
    return items


def _class_scene(dia: MM.ClassDiagram, style: Style) -> Optional[Scene]:
    ids = list(dia.classes)
    if not ids:
        return None
    sizes = {cid: _class_size(dia.classes[cid], style) for cid in ids}
    links = [(r.left, r.right) for r in dia.relations]
    notes = {k: _caption_size(r.text, style)
             for k, r in enumerate(dia.relations) if r.text}
    lay = _graph_layout(ids, sizes, links, dia.direction, style, (), notes)

    color = style.color("edge")
    hollow = style.color("hollow")
    items: List[object] = []
    captions: List[object] = []     # labels and cardinalities, drawn on top
    for k, (rel, route) in enumerate(zip(dia.relations, lay.routes)):
        if len(route) < 2 or rel.left == rel.right:
            continue
        points = _simplify(list(route), (rel.left, rel.right), lay.pos,
                           sizes, style.size * 1.4, (lay.captions.get(k),))
        lw, lh = sizes[rel.left]
        rw, rh = sizes[rel.right]
        points[0] = _boundary("rect", points[0][0], points[0][1], lw, lh,
                              *points[1])
        points[-1] = _boundary("rect", points[-1][0], points[-1][1], rw, rh,
                               *points[-2])
        points = _rounded(points, (rel.left, rel.right), lay.pos, sizes)
        drawn = list(points)
        if rel.right_head:
            drawn[-1] = _shorten(*points[-2], *points[-1],
                                 _head_length(rel.right_head, style))
        if rel.left_head:
            drawn[0] = _shorten(*points[1], *points[0],
                                _head_length(rel.left_head, style))
        items.append(Line(points=drawn, stroke=color, width=1.3,
                          dash=_dash_for(rel.line)))
        items += _head_items(rel.right_head, points[-1], points[-2], style,
                             color, hollow)
        items += _head_items(rel.left_head, points[0], points[1], style,
                             color, hollow)
        if rel.text:
            spot = lay.captions.get(k)
            if spot is not None:
                lx, ly = spot
            else:
                mid = len(points) // 2
                lx = (points[mid - 1][0] + points[mid][0]) / 2
                ly = (points[mid - 1][1] + points[mid][1]) / 2
            captions += _label_items(rel.text, lx, ly, style,
                                     style.color("edge_text"),
                                     style.color("label_bg"))
        for card, near, far in ((rel.left_card, points[0], points[1]),
                                (rel.right_card, points[-1], points[-2])):
            if not card:
                continue
            step = style.size * 1.1
            dist = math.hypot(far[0] - near[0], far[1] - near[1]) or 1
            fx = (far[0] - near[0]) / dist
            fy = (far[1] - near[1]) / dist
            captions += _label_items(
                card, near[0] + fx * step - fy * step * 0.8,
                near[1] + fy * step + fx * step * 0.8, style,
                style.color("edge_text"), "", style.size * 0.8)

    for cid in ids:
        cx, cy = lay.pos[cid]
        w, h = sizes[cid]
        items.extend(_class_items(dia.classes[cid], cx - w / 2, cy - h / 2,
                                  w, h, style))

    scene = _finish(items + captions, style)
    return _with_title(scene, dia.title, style)


def _with_title(scene: Scene, title: str, style: Style) -> Scene:
    if not title:
        return scene
    size = style.size * 1.15
    head = style.line_h(size) + style.size * 0.4
    _translate(scene.items, 0, head)
    scene.items.insert(0, Text(x=scene.width / 2, y=MARGIN + head / 2,
                               text=title, fill=style.color("title"),
                               size=size, bold=True))
    scene.width = max(scene.width, style.width(title, size, True) + 2 * MARGIN)
    scene.height += head
    return scene


# --------------------------------------------------------------------------
# Sequence diagrams
# --------------------------------------------------------------------------


class _SeqLayout:
    """Walks a sequence diagram's events, top to bottom."""

    def __init__(self, seq: MM.Sequence, style: Style):
        self.seq = seq
        self.st = style
        self.items: List[object] = []
        self.ids = list(seq.participants)
        self.number = 0
        self.active: Dict[str, List[float]] = {i: [] for i in self.ids}
        self.bars: List[tuple] = []
        # Actors are drawn as a stick figure above their name, so a diagram
        # with one in it needs a taller band across the top.
        self.head_h = style.size * (
            3.3 if any(p.actor for p in seq.participants.values()) else 2.4)
        self.gap = style.size * 0.9
        self.widths = {}
        self.x = {}
        self.y = 0.0
        self.right = 0.0
        self.tail = 0.0     # room past the last lifeline, for a self-message

    # -- horizontal ------------------------------------------------------

    def columns(self):
        st = self.st
        for pid in self.ids:
            part = self.seq.participants[pid]
            label = part.label or pid
            self.widths[pid] = max(st.width(label, st.size, True) + st.size * 1.6,
                                   st.size * 4.5)
        need = {k: st.size * 2.2 for k in range(len(self.ids) - 1)}
        number = st.size * 1.8 if self.seq.autonumber else 0.0

        # A message label sits centred over the span it crosses, so that span
        # has to be at least as wide as the label is -- shared out evenly when
        # the message reaches past its neighbour.
        for msg, span in self._messages():
            if not span or not msg:
                continue
            a, b = span
            width = max((st.width(line, st.size * 0.9)
                         for line in msg.split("\n")), default=0.0)
            width += st.size * 1.5 + number
            if a == b:                      # a message to itself, drawn beside
                if a < len(self.ids) - 1:
                    need[a] = max(need[a], width + st.size * 3)
                else:                       # nothing to its right: widen
                    self.tail = max(self.tail, width + st.size * 3)
                continue
            share = width / (b - a)
            for k in range(a, b):
                need[k] = max(need[k], share)

        x = self.widths[self.ids[0]] / 2
        for k, pid in enumerate(self.ids):
            self.x[pid] = x
            if k < len(self.ids) - 1:
                nxt = self.ids[k + 1]
                x += max(need[k],
                         (self.widths[pid] + self.widths[nxt]) / 2 + st.size)
        self.right = x + self.widths[self.ids[-1]] / 2 + self.tail

    def _messages(self):
        """Every message text with the column pair it has to fit between."""
        index = {pid: k for k, pid in enumerate(self.ids)}

        def walk(events):
            for ev in events:
                if isinstance(ev, MM.Message):
                    a, b = index.get(ev.src, 0), index.get(ev.dst, 0)
                    yield ev.text, (min(a, b), max(a, b))
                elif isinstance(ev, MM.Note):
                    spots = [index[t] for t in ev.targets if t in index]
                    if spots:
                        yield ev.text, (min(spots), max(spots))
                elif isinstance(ev, MM.Block):
                    if ev.title:
                        yield ev.title, (0, min(1, len(self.ids) - 1))
                    yield from walk(ev.events)

        return list(walk(self.seq.events))

    # -- vertical --------------------------------------------------------

    def run(self) -> Optional[Scene]:
        st = self.st
        if not self.ids:
            return None
        self.columns()
        self.y = self.head_h + st.size * 1.4
        self.walk(self.seq.events, depth=0)
        self.y += st.size * 0.8

        bottom = self.y
        for pid in self.ids:                      # anything still activated
            for start in self.active[pid]:
                self.bars.append((pid, start, bottom, 0))

        base: List[object] = []
        for pid in self.ids:
            x = self.x[pid]
            base.append(Line(points=[(x, self.head_h), (x, bottom)],
                             stroke=st.color("lifeline"), width=1.0, dash="dash"))
        for pid, top, end, level in self.bars:
            w = st.size * 0.55
            base.append(Rect(x=self.x[pid] - w / 2 + level * w * 0.7, y=top,
                             w=w, h=max(end - top, st.size * 0.6),
                             fill=st.color("actor_fill"),
                             stroke=st.color("actor_stroke")))
        heads = []
        for pid in self.ids:
            heads += self._head(pid, 0.0)
            heads += self._head(pid, bottom + st.size * 0.6, bottom=True)

        items = base + self.items + heads
        scene = _finish(items, st)
        return _with_title(scene, self.seq.title, st)

    def _head(self, pid: str, top: float, bottom: bool = False) -> List[object]:
        st = self.st
        part = self.seq.participants[pid]
        x, w = self.x[pid], self.widths[pid]
        label = part.label or pid
        if part.actor:
            r = st.size * 0.4
            stroke = st.color("actor_stroke")
            neck = top + 2 * r
            waist = neck + st.size * 0.7
            return [
                Ellipse(cx=x, cy=top + r, rx=r, ry=r, fill=st.color("actor_fill"),
                        stroke=stroke),
                Line(points=[(x, neck), (x, waist)], stroke=stroke),
                Line(points=[(x - r * 1.5, neck + st.size * 0.25),
                             (x + r * 1.5, neck + st.size * 0.25)], stroke=stroke),
                Line(points=[(x - r * 1.3, waist + st.size * 0.55), (x, waist),
                             (x + r * 1.3, waist + st.size * 0.55)],
                     stroke=stroke),
                Text(x=x, y=top + self.head_h - st.size * 0.45, text=label,
                     fill=st.color("actor_text"), size=st.size, bold=True),
            ]
        height = st.size * 2.0
        top += max(0.0, (self.head_h - st.size * 0.5 - height) / 2)
        return [Rect(x=x - w / 2, y=top, w=w, h=height,
                     fill=st.color("actor_fill"), stroke=st.color("actor_stroke"),
                     rx=st.size * 0.2),
                Text(x=x, y=top + height / 2, text=label,
                     fill=st.color("actor_text"), size=st.size, bold=True)]

    def walk(self, events, depth: int):
        for ev in events:
            if isinstance(ev, MM.Message):
                self.message(ev)
            elif isinstance(ev, MM.Note):
                self.note(ev)
            elif isinstance(ev, MM.Lifecycle):
                if ev.start:
                    self.active.setdefault(ev.target, []).append(self.y)
                else:
                    self.close(ev.target, self.y)
            elif isinstance(ev, MM.Block):
                self.block(ev, depth)

    def close(self, pid: str, end: float):
        stack = self.active.get(pid)
        if stack:
            start = stack.pop()
            self.bars.append((pid, start, end, len(stack)))

    def message(self, msg: MM.Message):
        st = self.st
        text = msg.text
        if self.seq.autonumber and text:
            self.number += 1
            text = f"{self.number}. {text}"
        lines = text.split("\n") if text else []
        _, th = st.block(lines, st.size * 0.9) if lines else (0.0, 0.0)
        color = st.color("edge")
        dash = _dash_for(msg.stroke)
        x1 = self.x.get(msg.src, 0.0)
        x2 = self.x.get(msg.dst, 0.0)
        if msg.activate:
            self.active.setdefault(msg.dst, []).append(self.y + th + st.size * 0.6)

        if msg.src == msg.dst:                          # a call to itself
            top = self.y + th + st.size * 0.3
            out = x1 + st.size * 2.6
            drop = st.size * 1.8
            pts = [(x1 + self._bar_edge(msg.src), top), (out, top),
                   (out, top + drop), (x1 + self._bar_edge(msg.src), top + drop)]
            self.items.append(Line(points=pts, stroke=color, width=1.2,
                                   dash=dash))
            self.items += _head_items(msg.head, pts[-1], pts[-2], st, color)
            for k, line in enumerate(lines):
                self.items.append(
                    Text(x=out + st.size * 0.5,
                         y=self.y + (k + 0.5) * st.line_h(st.size * 0.9),
                         text=line, fill=st.color("edge_text"),
                         size=st.size * 0.9, anchor="start"))
            self.y = top + drop + st.size * 0.9
        else:
            forward = x2 > x1
            start = x1 + self._bar_edge(msg.src) * (1 if forward else -1)
            end = x2 - self._bar_edge(msg.dst) * (1 if forward else -1)
            line_y = self.y + th + st.size * 0.35
            tip = _shorten(start, line_y, end, line_y,
                           _head_length(msg.head, st))
            self.items.append(Line(points=[(start, line_y), tip], stroke=color,
                                   width=1.2, dash=dash))
            self.items += _head_items(msg.head, (end, line_y), (start, line_y),
                                      st, color)
            if msg.back_head:
                self.items += _head_items(msg.back_head, (start, line_y),
                                          (end, line_y), st, color)
            for k, line in enumerate(lines):
                self.items.append(
                    Text(x=(start + end) / 2,
                         y=self.y + (k + 0.5) * st.line_h(st.size * 0.9),
                         text=line, fill=st.color("edge_text"),
                         size=st.size * 0.9))
            self.y = line_y + st.size * 1.1
        if msg.deactivate:
            self.close(msg.src, self.y - st.size * 0.6)

    def _bar_edge(self, pid: str) -> float:
        """Half the width of an activation bar, when one is open."""
        depth = len(self.active.get(pid, ()))
        return 0.0 if not depth else self.st.size * 0.3 + (depth - 1) * \
            self.st.size * 0.4

    def note(self, note: MM.Note):
        st = self.st
        lines = note.text.split("\n")
        tw, th = st.block(lines, st.size * 0.9)
        w = tw + st.size * 1.4
        h = th + st.size * 0.9
        spots = [self.x[t] for t in note.targets if t in self.x] or [0.0]
        if note.placement == "over":
            centre = (min(spots) + max(spots)) / 2
            w = max(w, max(spots) - min(spots) + st.size * 3)
            x = centre - w / 2
        elif note.placement == "left":
            x = min(spots) - w - st.size * 1.2
        else:
            x = max(spots) + st.size * 1.2
        self.items.append(Rect(x=x, y=self.y, w=w, h=h,
                               fill=st.color("note_fill"),
                               stroke=st.color("note_stroke")))
        for k, line in enumerate(lines):
            self.items.append(
                Text(x=x + w / 2,
                     y=self.y + st.size * 0.45 + (k + 0.5) * st.line_h(st.size * 0.9),
                     text=line, fill=st.color("note_text"), size=st.size * 0.9))
        self.y += h + st.size * 0.7

    def block(self, block: MM.Block, depth: int):
        st = self.st
        if block.hidden:                                # "rect"/"box" grouping
            self.walk(block.events, depth)
            return
        inset = st.size * (0.8 + depth * 0.5)
        top = self.y
        self.y += st.line_h(st.size * 0.85) + st.size * 0.4
        marks: List[tuple] = []
        for ev in block.events:
            if isinstance(ev, MM.Section):
                marks.append((self.y, ev.title))
                self.y += st.line_h(st.size * 0.85) + st.size * 0.2
            else:
                self.walk([ev], depth + 1)
        self.y += st.size * 0.5
        left, right = inset, self.right - inset
        color = st.color("frame")
        frame: List[object] = [
            Rect(x=left, y=top, w=right - left, h=self.y - top, fill="",
                 stroke=color, dash="dash"),
        ]
        tab_w = st.width(block.kind, st.size * 0.85, True) + st.size * 0.9
        tab_h = st.line_h(st.size * 0.85)
        frame.append(Rect(x=left, y=top, w=tab_w, h=tab_h,
                          fill=st.color("frame_tab"), stroke=color))
        frame.append(Text(x=left + tab_w / 2, y=top + tab_h / 2,
                          text=block.kind, fill=st.color("edge_text"),
                          size=st.size * 0.85, bold=True))
        if block.title:
            frame.append(Text(x=left + tab_w + st.size * 0.6,
                              y=top + tab_h / 2, text=f"[{block.title}]",
                              fill=st.color("edge_text"), size=st.size * 0.85,
                              anchor="start"))
        for y, title in marks:
            frame.append(Line(points=[(left, y), (right, y)], stroke=color,
                              dash="dash"))
            if title:
                frame.append(Text(x=left + st.size * 0.6, y=y + tab_h / 2,
                                  text=f"[{title}]", fill=st.color("edge_text"),
                                  size=st.size * 0.85, anchor="start"))
        self.items = frame + self.items
        self.y += st.size * 0.4


def _sequence_scene(seq: MM.Sequence, style: Style) -> Optional[Scene]:
    return _SeqLayout(seq, style).run()


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------

_DASHES = {"dash": "6 4", "dot": "2 3"}
_SVG_BODY = ('-apple-system,"Segoe UI",Helvetica,Arial,sans-serif')
_SVG_MONO = ('ui-monospace,Consolas,"DejaVu Sans Mono",monospace')


def to_svg(scene: Scene, label: str = "") -> str:
    """The scene as an ``<svg>`` element: self-contained, no external refs."""
    w, h = max(1.0, scene.width), max(1.0, scene.height)
    out = [f'<svg class="mermaid" xmlns="http://www.w3.org/2000/svg" '
           f'viewBox="0 0 {_n(w)} {_n(h)}" width="{_n(w)}" height="{_n(h)}" '
           f'role="img" aria-label="{_esc(label or "diagram")}">']
    for item in scene.items:
        out.append(_svg_item(item))
    out.append("</svg>")
    return "\n".join(part for part in out if part)


def _n(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _stroke_attrs(stroke: str, width: float, dash: str) -> str:
    if not stroke:
        return ' stroke="none"'
    out = f' stroke="{stroke}" stroke-width="{_n(width)}"'
    if dash in _DASHES:
        out += f' stroke-dasharray="{_DASHES[dash]}"'
    return out


def _svg_item(item) -> str:
    if isinstance(item, Rect):
        fill = f'"{item.fill}"' if item.fill else '"none"'
        rx = f' rx="{_n(item.rx)}"' if item.rx else ""
        return (f'<rect x="{_n(item.x)}" y="{_n(item.y)}" width="{_n(item.w)}" '
                f'height="{_n(item.h)}"{rx} fill={fill}'
                f'{_stroke_attrs(item.stroke, item.width, item.dash)}/>')
    if isinstance(item, Ellipse):
        fill = f'"{item.fill}"' if item.fill else '"none"'
        return (f'<ellipse cx="{_n(item.cx)}" cy="{_n(item.cy)}" '
                f'rx="{_n(item.rx)}" ry="{_n(item.ry)}" fill={fill}'
                f'{_stroke_attrs(item.stroke, item.width, item.dash)}/>')
    if isinstance(item, Poly):
        pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in item.points)
        fill = f'"{item.fill}"' if item.fill else '"none"'
        return (f'<polygon points="{pts}" fill={fill}'
                f'{_stroke_attrs(item.stroke, item.width, item.dash)}/>')
    if isinstance(item, Line):
        pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in item.points)
        return (f'<polyline points="{pts}" fill="none"'
                f'{_stroke_attrs(item.stroke, item.width, item.dash)}'
                f' stroke-linecap="round" stroke-linejoin="round"/>')
    if isinstance(item, Text):
        family = _SVG_MONO if item.mono else _SVG_BODY
        weight = ' font-weight="bold"' if item.bold else ""
        slant = ' font-style="italic"' if item.italic else ""
        # The baseline is worked out here rather than left to
        # dominant-baseline, which older renderers disagree about.
        return (f'<text x="{_n(item.x)}" y="{_n(item.y + item.size * 0.35)}" '
                f'fill="{item.fill}" font-size="{_n(item.size)}" '
                f'font-family=\'{family}\' text-anchor="{item.anchor}"'
                f'{weight}{slant}>{_esc(item.text)}</text>')
    return ""

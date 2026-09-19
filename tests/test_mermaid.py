"""Mermaid tests: source -> model, model -> scene, scene -> SVG.

Run: python -m unittest discover tests
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mdedit import diagram as D, mermaid as M  # noqa: E402


def scene(src: str, theme: str = "light"):
    model = M.parse(src)
    assert model is not None, "source did not parse"
    return D.render(model, D.style_for(theme))


def texts(sc):
    return [item.text for item in sc.items if isinstance(item, D.Text)]


def layout(src: str, theme: str = "light"):
    """A flowchart's model and the layout chosen for it.

    The same setup ``_flowchart_scene`` does, stopping at the layout: the
    routes it picked are what the tidiness tests are about, and they are
    gone by the time the scene is a bag of lines.
    """
    chart = M.parse(src)
    assert chart is not None and chart.kind == "flowchart", "not a flowchart"
    style = D.style_for(theme)
    ids = list(chart.nodes)
    sizes = {n: D._node_size(style.lines(chart.nodes[n].text or n),
                             chart.nodes[n].shape, style) for n in ids}
    links = [(e.src, e.dst) for e in chart.edges]
    clusters = [(g.id, g.members) for g in chart.subgraphs if g.members]
    captions = {k: D._caption_size(e.text, style)
                for k, e in enumerate(chart.edges) if e.text}
    return chart, D._graph_layout(ids, sizes, links, chart.direction, style,
                                  clusters, captions)


#: A real dependency graph, and the shape that drove the layout work: a
#: deep spine with edges jumping most of it, and a box on every rank
#: competing for the room those edges need.
DEPENDENCIES = """flowchart TD
 Buffers --> Foundation
 EnumReflection --> Buffers
 SerialHelpers --> Buffers
 Debugging --> SerialHelpers
 SimpleLogger --> Buffers
 DataUtilities --> Debugging
 DataUtilities --> SimpleLogger
 FileSystem --> SimpleLogger
 Profiler --> Foundation
 Strings --> DataUtilities
 Threading --> Foundation
 NameMap --> FileSystem
 NameMap --> Profiler
 NameMap --> Strings
 NameMap --> Threading
 Logging --> NameMap
 Serialization --> Debugging
 Serialization --> SimpleLogger
 Math --> DataUtilities
 Math --> FileSystem
 Math --> Serialization
 CommandLine --> Logging
 ImageLoader --> Logging
 App --> CommandLine
 App --> EnumReflection
 App --> ImageLoader
 App --> Math
"""


#: The same graph with every edge labelled -- the include graph from the
#: same document.  A caption has to claim the room its text needs without
#: pulling the line it sits on out of true.
INCLUDES = """flowchart TD
 Buffers -->|GBuildTime.h +5| Foundation
 EnumReflection -->|GBuffer.h| Buffers
 SerialHelpers -->|GBuffer.h| Buffers
 Debugging -->|GSerialHelpers.h| SerialHelpers
 SimpleLogger -->|GBuffer.h +1| Buffers
 DataUtilities -->|GDebug.h| Debugging
 DataUtilities -->|SimpleLogger.h| SimpleLogger
 FileSystem -->|GMiniLogger.h| SimpleLogger
 Profiler -->|GBuildTime.h +3| Foundation
 Strings -->|GUtilities.h| DataUtilities
 Threading -->|GBuildTime.h +4| Foundation
 NameMap -->|declared only| FileSystem
 NameMap -->|declared only| Profiler
 NameMap -->|FixedSizeString.h +1| Strings
 NameMap -->|declared only| Threading
 Logging -->|LogInjectionWrapper.h +4| NameMap
 Serialization -->|GDebug.h| Debugging
 Serialization -->|SimpleLogger.h| SimpleLogger
 Math -->|GUtilities.h| DataUtilities
 Math -->|declared only| FileSystem
 Math -->|GSerialize.h| Serialization
 CommandLine -->|GLogging.h| Logging
 ImageLoader -->|GLogging.h| Logging
 App -->|GCommandLine.h| CommandLine
 App -->|EnumMacros.h| EnumReflection
 App -->|GImage.h +1| ImageLoader
 App -->|GArray.h +4| Math
"""


def bends(routes) -> int:
    """How many visible corners the routes turn through."""
    count = 0
    for route in routes:
        for a, b, c in zip(route, route[1:], route[2:]):
            first = (b[0] - a[0], b[1] - a[1])
            second = (c[0] - b[0], c[1] - b[1])
            n1, n2 = math.hypot(*first), math.hypot(*second)
            if n1 < 1e-6 or n2 < 1e-6:
                continue
            cos = (first[0] * second[0] + first[1] * second[1]) / (n1 * n2)
            if math.degrees(math.acos(max(-1.0, min(1.0, cos)))) > 8:
                count += 1
    return count


def turns(points, floor: float = 5.0) -> int:
    """How many times the run changes direction by more than *floor*."""
    count = 0
    for a, b, c in zip(points, points[1:], points[2:]):
        first = (b[0] - a[0], b[1] - a[1])
        second = (c[0] - b[0], c[1] - b[1])
        n1, n2 = math.hypot(*first), math.hypot(*second)
        if n1 < 1e-6 or n2 < 1e-6:
            continue
        cos = (first[0] * second[0] + first[1] * second[1]) / (n1 * n2)
        if math.degrees(math.acos(max(-1.0, min(1.0, cos)))) > floor:
            count += 1
    return count


def sharpest(points) -> float:
    """The widest turn the run makes, in degrees."""
    worst = 0.0
    for a, b, c in zip(points, points[1:], points[2:]):
        first = (b[0] - a[0], b[1] - a[1])
        second = (c[0] - b[0], c[1] - b[1])
        n1, n2 = math.hypot(*first), math.hypot(*second)
        if n1 < 1e-6 or n2 < 1e-6:
            continue
        cos = (first[0] * second[0] + first[1] * second[1]) / (n1 * n2)
        worst = max(worst, math.degrees(math.acos(max(-1.0, min(1.0, cos)))))
    return worst


def curves(src: str):
    """Every edge of a flowchart as it is drawn -- boundary to boundary."""
    chart, lay = layout(src)
    style = D.style_for("light")
    sizes = {n: D._node_size(style.lines(chart.nodes[n].text or n),
                             chart.nodes[n].shape, style) for n in chart.nodes}
    out = []
    for k, route in enumerate(lay.routes):
        edge = chart.edges[k]
        if len(route) < 2 or edge.src not in sizes or edge.dst not in sizes:
            out.append((list(route), list(route)))
            continue
        pts = D._simplify(list(route), (edge.src, edge.dst), lay.pos, sizes,
                          style.size * 1.4, (lay.captions.get(k),))
        sw, sh = sizes[edge.src]
        dw, dh = sizes[edge.dst]
        pts[0] = D._boundary(chart.nodes[edge.src].shape, *pts[0], sw, sh,
                             *pts[1])
        pts[-1] = D._boundary(chart.nodes[edge.dst].shape, *pts[-1], dw, dh,
                              *pts[-2])
        out.append((pts, D._smooth(pts)))
    return chart, lay, sizes, out


def crossings(routes) -> int:
    """How many times one route crosses another, as drawn."""
    def side(a, b, c):
        turn = ((b[0] - a[0]) * (c[1] - a[1])
                - (b[1] - a[1]) * (c[0] - a[0]))
        return (turn > 1e-9) - (turn < -1e-9)

    def meet(p, q, r, t):
        if (max(p[0], q[0]) < min(r[0], t[0]) - 1e-9
                or max(r[0], t[0]) < min(p[0], q[0]) - 1e-9
                or max(p[1], q[1]) < min(r[1], t[1]) - 1e-9
                or max(r[1], t[1]) < min(p[1], q[1]) - 1e-9):
            return False
        return (side(p, q, r) * side(p, q, t) < 0
                and side(r, t, p) * side(r, t, q) < 0)

    segments = [(k, a, b) for k, route in enumerate(routes)
                for a, b in zip(route, route[1:]) if a != b]
    return sum(1 for i, (ka, a1, a2) in enumerate(segments)
               for kb, b1, b2 in segments[i + 1:]
               if ka != kb and meet(a1, a2, b1, b2))


def wander(routes) -> float:
    """How much longer the routes are than a straight line would be."""
    total = straight = 0.0
    for route in routes:
        if len(route) < 2:
            continue
        total += sum(math.dist(a, b) for a, b in zip(route, route[1:]))
        straight += math.dist(route[0], route[-1])
    return total / straight if straight else 1.0


class TestDispatch(unittest.TestCase):
    def test_known_kinds(self):
        self.assertEqual(M.parse("graph TD\n A-->B\n").kind, "flowchart")
        self.assertEqual(M.parse("flowchart LR\n A-->B\n").kind, "flowchart")
        self.assertEqual(M.parse("sequenceDiagram\n A->>B: hi\n").kind,
                         "sequence")
        self.assertEqual(M.parse("classDiagram\n class A\n").kind, "class")

    def test_unknown_kinds_decline(self):
        for src in ("gantt\n title X\n", "erDiagram\n A ||--o{ B : has\n",
                    "stateDiagram-v2\n [*] --> S\n", "pie\n \"a\" : 10\n",
                    "", "   ", "not a diagram at all"):
            self.assertIsNone(M.parse(src), src)

    def test_empty_diagram_declines(self):
        self.assertIsNone(M.parse("flowchart TD\n"))
        self.assertIsNone(M.parse("classDiagram\n"))
        self.assertIsNone(M.parse("sequenceDiagram\n"))

    def test_comments_and_directives_ignored(self):
        chart = M.parse("%%{init: {'theme':'dark'}}%%\ngraph TD\n"
                        "  %% a comment\n  A-->B %% trailing\n")
        self.assertEqual(list(chart.nodes), ["A", "B"])


class TestFlowchartParsing(unittest.TestCase):
    def test_direction(self):
        for head, want in (("graph TD", "TB"), ("graph TB", "TB"),
                           ("flowchart LR", "LR"), ("flowchart BT", "BT"),
                           ("flowchart RL", "RL")):
            self.assertEqual(M.parse(head + "\n A-->B\n").direction, want)

    def test_default_direction(self):
        self.assertEqual(M.parse("graph\n A-->B\n").direction, "TB")

    def test_shapes(self):
        chart = M.parse(
            "flowchart LR\n"
            "  a[rect] --> b(round) --> c([stadium]) --> d[[subroutine]]\n"
            "  d --> e[(cylinder)] --> f((circle)) --> g{rhombus}\n"
            "  g --> h{{hexagon}} --> i[/para/] --> j[\\para2\\]\n"
            "  j --> k[/trap\\] --> l[\\trap2/] --> m>flag] --> n(((dbl)))\n")
        got = {nid: node.shape for nid, node in chart.nodes.items()}
        self.assertEqual(got, {
            "a": "rect", "b": "round", "c": "stadium", "d": "subroutine",
            "e": "cylinder", "f": "circle", "g": "rhombus", "h": "hexagon",
            "i": "parallelogram", "j": "parallelogram_alt", "k": "trapezoid",
            "l": "trapezoid_alt", "m": "asymmetric", "n": "doublecircle",
        })

    def test_labels(self):
        chart = M.parse('graph TD\n A["quoted &amp; escaped"] --> '
                        'B[two<br/>lines]\n C[#quot;hash#quot;]\n')
        self.assertEqual(chart.nodes["A"].text, "quoted & escaped")
        self.assertEqual(chart.nodes["B"].text, "two\nlines")
        self.assertEqual(chart.nodes["C"].text, '"hash"')

    def test_unlabelled_node_shows_its_id(self):
        self.assertEqual(M.parse("graph TD\n A --> B\n").nodes["A"].text, "A")

    def test_link_styles(self):
        chart = M.parse("graph LR\n A --> B\n B --- C\n C -.-> D\n"
                        "  D ==> E\n E ---- F\n")
        self.assertEqual([e.stroke for e in chart.edges],
                         ["solid", "solid", "dotted", "thick", "solid"])
        self.assertEqual([e.dst_head for e in chart.edges],
                         ["arrow", "", "arrow", "arrow", ""])

    def test_link_labels(self):
        chart = M.parse("graph LR\n A -->|pipe| B\n B -- middle --> C\n"
                        "  C -. dotted .-> D\n D == thick ==> E\n")
        self.assertEqual([e.text for e in chart.edges],
                         ["pipe", "middle", "dotted", "thick"])

    def test_arrow_ends(self):
        chart = M.parse("graph LR\n A <--> B\n B --o C\n C --x D\n")
        self.assertEqual([(e.src_head, e.dst_head) for e in chart.edges],
                         [("arrow", "arrow"), ("", "circle"), ("", "cross")])

    def test_chains_and_ampersand(self):
        chart = M.parse("graph LR\n A --> B --> C\n D & E --> F\n")
        pairs = [(e.src, e.dst) for e in chart.edges]
        self.assertEqual(pairs, [("A", "B"), ("B", "C"), ("D", "F"), ("E", "F")])

    def test_ids_with_dashes_in_labels_do_not_split(self):
        chart = M.parse("graph LR\n A[a -- b] --> B\n")
        self.assertEqual(chart.nodes["A"].text, "a -- b")
        self.assertEqual([(e.src, e.dst) for e in chart.edges], [("A", "B")])

    def test_semicolons_separate_statements(self):
        chart = M.parse("graph TD; A-->B; B-->C;\n")
        self.assertEqual(len(chart.edges), 2)

    def test_subgraphs(self):
        chart = M.parse("flowchart TB\n"
                        "  subgraph one [First]\n    A --> B\n  end\n"
                        "  subgraph two\n    C\n  end\n  B --> C\n")
        first, second = chart.subgraphs
        self.assertEqual((first.id, first.title), ("one", "First"))
        self.assertEqual(first.members, ["A", "B"])
        self.assertEqual((second.id, second.members), ("two", ["C"]))

    def test_nested_subgraph_is_a_member_of_its_parent(self):
        chart = M.parse("flowchart TB\n subgraph outer\n  subgraph inner\n"
                        "   A\n  end\n end\n")
        outer = [s for s in chart.subgraphs if s.id == "outer"][0]
        self.assertIn("inner", outer.members)

    def test_link_naming_a_subgraph_reaches_inside_it(self):
        chart = M.parse("flowchart LR\n subgraph one\n  a1-->a2\n end\n"
                        " subgraph two\n  b1-->b2\n end\n one --> two\n")
        self.assertEqual(list(chart.nodes), ["a1", "a2", "b1", "b2"])
        self.assertIn(("a1", "b1"), [(e.src, e.dst) for e in chart.edges])

    def test_styling_statements_are_skipped(self):
        chart = M.parse("graph TD\n A-->B\n style A fill:#f9f\n"
                        "  classDef big font-size:20px\n class A big\n"
                        "  click A href \"https://example.com\"\n"
                        "  linkStyle 0 stroke:red\n")
        self.assertEqual(list(chart.nodes), ["A", "B"])
        self.assertEqual(len(chart.edges), 1)

    def test_self_link(self):
        chart = M.parse("graph TD\n A --> A\n")
        self.assertEqual([(e.src, e.dst) for e in chart.edges], [("A", "A")])


class TestSequenceParsing(unittest.TestCase):
    def test_participants_and_labels(self):
        seq = M.parse("sequenceDiagram\n participant A as Alice\n actor B\n"
                      " A->>B: hi\n")
        self.assertEqual(seq.participants["A"].label, "Alice")
        self.assertTrue(seq.participants["B"].actor)

    def test_participants_appear_in_first_seen_order(self):
        seq = M.parse("sequenceDiagram\n C->>A: x\n B->>C: y\n")
        self.assertEqual(list(seq.participants), ["C", "A", "B"])

    def test_arrow_styles(self):
        seq = M.parse("sequenceDiagram\n A->B: a\n A-->B: b\n A->>B: c\n"
                      " A-->>B: d\n A-xB: e\n A--)B: f\n")
        self.assertEqual([(m.stroke, m.head) for m in seq.events], [
            ("solid", ""), ("dotted", ""), ("solid", "arrow"),
            ("dotted", "arrow"), ("solid", "cross"), ("dotted", "async"),
        ])

    def test_activation_flags(self):
        seq = M.parse("sequenceDiagram\n A->>+B: go\n B-->>-A: done\n")
        self.assertTrue(seq.events[0].activate)
        self.assertTrue(seq.events[1].deactivate)
        self.assertEqual(list(seq.participants), ["A", "B"])

    def test_dashed_name_is_not_part_of_the_arrow(self):
        seq = M.parse("sequenceDiagram\n Web-Server->>DB: query\n")
        self.assertEqual((seq.events[0].src, seq.events[0].dst),
                         ("Web-Server", "DB"))

    def test_blocks_nest(self):
        seq = M.parse("sequenceDiagram\n A->>B: x\n loop daily\n  A->>B: y\n"
                      "  alt ok\n   B->>A: z\n  else no\n   B->>A: w\n  end\n"
                      " end\n")
        loop = seq.events[1]
        self.assertEqual((loop.kind, loop.title), ("loop", "daily"))
        inner = [e for e in loop.events if isinstance(e, M.Block)][0]
        self.assertEqual(inner.sections, ["no"])

    def test_unclosed_block_still_lands(self):
        seq = M.parse("sequenceDiagram\n loop forever\n  A->>B: x\n")
        self.assertIsInstance(seq.events[0], M.Block)
        self.assertEqual(len(seq.events[0].events), 1)

    def test_notes(self):
        seq = M.parse("sequenceDiagram\n A->>B: x\n Note over A,B: shared\n"
                      " Note left of A: mine\n")
        over, left = seq.events[1], seq.events[2]
        self.assertEqual((over.placement, over.targets), ("over", ["A", "B"]))
        self.assertEqual((left.placement, left.text), ("left", "mine"))

    def test_title_and_autonumber(self):
        seq = M.parse("sequenceDiagram\n title A chat\n autonumber\n"
                      " A->>B: x\n")
        self.assertEqual(seq.title, "A chat")
        self.assertTrue(seq.autonumber)


class TestClassParsing(unittest.TestCase):
    def test_body_members_split_into_fields_and_methods(self):
        dia = M.parse("classDiagram\n class Animal {\n  +int age\n"
                      "  +String name\n  +isMammal() bool\n }\n")
        box = dia.classes["Animal"]
        self.assertEqual(box.attributes, ["+int age", "+String name"])
        self.assertEqual(box.methods, ["+isMammal() bool"])

    def test_colon_members(self):
        dia = M.parse("classDiagram\n Animal : +int age\n Animal : +run() void\n")
        box = dia.classes["Animal"]
        self.assertEqual((box.attributes, box.methods),
                         (["+int age"], ["+run() void"]))

    def test_stereotype(self):
        inline = M.parse("classDiagram\n class F {\n <<interface>>\n"
                         " +fly() void\n }\n")
        outside = M.parse("classDiagram\n class F\n <<interface>> F\n")
        self.assertEqual(inline.classes["F"].stereotype, "interface")
        self.assertEqual(outside.classes["F"].stereotype, "interface")

    def test_relations(self):
        dia = M.parse("classDiagram\n A <|-- B\n C *-- D\n E o-- F\n"
                      " G --> H\n I ..> J\n K ..|> L\n M -- N\n")
        got = [(r.left_head, r.right_head, r.line) for r in dia.relations]
        self.assertEqual(got, [
            ("triangle", "", "solid"), ("diamond", "", "solid"),
            ("odiamond", "", "solid"), ("", "arrow", "solid"),
            ("", "arrow", "dashed"), ("", "triangle", "dashed"),
            ("", "", "solid"),
        ])

    def test_cardinality_and_label(self):
        dia = M.parse('classDiagram\n Duck "1" --> "*" Egg : lays\n')
        rel = dia.relations[0]
        self.assertEqual((rel.left_card, rel.right_card, rel.text),
                         ("1", "*", "lays"))

    def test_generics(self):
        dia = M.parse("classDiagram\n class List~int~\n")
        self.assertEqual(dia.classes["List~int~"].name, "List<int>")

    def test_direction(self):
        self.assertEqual(M.parse("classDiagram\n direction LR\n class A\n"
                                 ).direction, "LR")


class TestLayout(unittest.TestCase):
    def test_flowchart_scene_has_shapes_and_labels(self):
        sc = scene("flowchart TD\n A[Start] --> B{Choose}\n B -->|yes| C\n")
        self.assertGreater(sc.width, 0)
        self.assertGreater(sc.height, 0)
        self.assertIn("Start", texts(sc))
        self.assertIn("yes", texts(sc))

    def test_nothing_is_drawn_outside_the_scene(self):
        sc = scene("flowchart LR\n subgraph s [Box]\n A --> B\n end\n"
                   " B --> C{Wide decision label here}\n C -.no.-> A\n")
        for item in sc.items:
            for x, y in D._extent(item, D.Style()):
                self.assertGreaterEqual(x, -1.0)
                self.assertGreaterEqual(y, -1.0)
                self.assertLessEqual(x, sc.width + 1.0)
                self.assertLessEqual(y, sc.height + 1.0)

    def test_boxes_do_not_overlap(self):
        sc = scene("flowchart TD\n A[One] --> B[Two]\n A --> C[Three]\n"
                   " B --> D[Four]\n C --> D\n")
        boxes = [i for i in sc.items if isinstance(i, D.Rect) and i.fill]
        for k, a in enumerate(boxes):
            for b in boxes[k + 1:]:
                apart = (a.x + a.w <= b.x + 0.5 or b.x + b.w <= a.x + 0.5
                         or a.y + a.h <= b.y + 0.5 or b.y + b.h <= a.y + 0.5)
                self.assertTrue(apart, f"{a} overlaps {b}")

    def test_direction_changes_the_aspect(self):
        src = " A[One] --> B[Two] --> C[Three]\n"
        down = scene("flowchart TD\n" + src)
        across = scene("flowchart LR\n" + src)
        self.assertGreater(down.height, down.width)
        self.assertGreater(across.width, across.height)

    def test_cycles_do_not_hang(self):
        sc = scene("flowchart TD\n A --> B\n B --> C\n C --> A\n A --> A\n")
        self.assertGreater(len(sc.items), 0)

    def test_sequence_scene(self):
        sc = scene("sequenceDiagram\n actor U\n participant S\n"
                   " U->>+S: ask\n S-->>-U: answer\n loop twice\n U->>S: x\n"
                   " end\n Note over U,S: done\n")
        labels = texts(sc)
        for want in ("U", "S", "ask", "answer", "loop", "done"):
            self.assertIn(want, labels)

    def test_class_scene(self):
        sc = scene("classDiagram\n class A {\n +int x\n +go() void\n }\n"
                   " A <|-- B\n")
        labels = texts(sc)
        self.assertIn("A", labels)
        self.assertIn("+int x", labels)
        self.assertIn("+go() void", labels)

    def test_measure_hook_is_used(self):
        calls = []

        def measure(text, size, bold):
            calls.append(text)
            return len(text) * size * 0.5

        model = M.parse("flowchart TD\n A[Some words] --> B\n")
        D.render(model, D.Style(measure=measure))
        self.assertIn("Some words", calls)

    def test_bigger_type_makes_a_bigger_picture(self):
        model = M.parse("flowchart TD\n A[Start] --> B[End]\n")
        small = D.render(model, D.Style(size=10))
        large = D.render(model, D.Style(size=20))
        self.assertGreater(large.width, small.width)
        self.assertGreater(large.height, small.height)

    def test_long_labels_wrap(self):
        text = "one two three four five six seven eight nine ten eleven"
        style = D.Style()
        lines = style.lines(text)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(style.width(line), style.size * 15 + 1)
        self.assertEqual(" ".join(lines), text)     # nothing lost

    def test_wrapping_keeps_the_authors_own_breaks(self):
        style = D.Style()
        self.assertEqual(style.lines("short\nlines"), ["short", "lines"])

    def test_one_long_word_is_left_alone(self):
        self.assertEqual(D.Style().lines("Supercalifragilistic" * 3),
                         ["Supercalifragilistic" * 3])

    def test_wrapping_keeps_a_node_narrow(self):
        long = ("flowchart TD\n A[one two three four five six seven eight "
                "nine ten eleven twelve thirteen fourteen fifteen sixteen "
                "seventeen eighteen nineteen twenty] --> B\n")
        wide = D.render(M.parse(long), D.Style(wrap=9999))
        wrapped = D.render(M.parse(long), D.Style())
        self.assertLess(wrapped.width, wide.width / 3)
        self.assertGreater(wrapped.height, wide.height)      # taller instead

    def test_label_text_matches_the_box_it_is_in(self):
        # Whatever the box was sized for has to be what is drawn in it.
        sc = scene("flowchart TD\n A[a much longer label than fits on a line]"
                   " --> B[short]\n")
        boxes = [i for i in sc.items if isinstance(i, D.Rect) and i.fill]
        for text in [i for i in sc.items if isinstance(i, D.Text)]:
            self.assertTrue(
                any(box.x - 1 <= text.x <= box.x + box.w + 1
                    and box.y - 1 <= text.y <= box.y + box.h + 1
                    for box in boxes), text.text)

    def test_edge_labels_are_drawn_over_the_boxes(self):
        sc = scene("flowchart TD\n A --> |a label| B\n")
        kinds = [type(i).__name__ for i in sc.items]
        self.assertIn("Text", kinds)
        label = max(i for i, k in enumerate(kinds) if k == "Text")
        last_box = max(i for i, item in enumerate(sc.items)
                       if isinstance(item, D.Rect) and item.fill)
        self.assertGreater(label, last_box)

    def test_edge_labels_get_room_of_their_own(self):
        plain = scene("flowchart TD\n A --> B\n")
        wordy = scene("flowchart TD\n A --> |a really quite long caption| B\n")
        self.assertGreater(wordy.width, plain.width)
        self.assertGreater(wordy.height, plain.height)

    def test_a_chain_does_not_drift_sideways(self):
        sc = scene("flowchart TD\n" + "\n".join(
            f" N{k}[Step number {k}] --> N{k + 1}[Step number {k + 1}]"
            for k in range(10)))
        boxes = [i for i in sc.items if isinstance(i, D.Rect) and i.fill]
        centres = sorted(b.x + b.w / 2 for b in boxes)
        self.assertLess(centres[-1] - centres[0], 40)

    def test_palettes_differ(self):
        light = scene("flowchart TD\n A --> B\n", "light")
        dark = scene("flowchart TD\n A --> B\n", "dark")
        fills = lambda sc: {i.fill for i in sc.items if isinstance(i, D.Rect)}
        self.assertNotEqual(fills(light), fills(dark))


class TestLayoutTidiness(unittest.TestCase):
    """A long edge goes straight, a rank gets ordered, and nothing is spent
    on half-ranks that no caption is ever going to use."""

    def test_a_long_edge_is_drawn_straight(self):
        # A --> E runs past the four ranks the spine occupies.  Every rank
        # it crosses has a box on it wanting the same room, and the edge is
        # what has to win, or it comes out as a staircase.
        _, lay = layout("flowchart TD\n A --> B\n B --> C\n C --> D\n"
                        " D --> E\n A --> E\n")
        route = lay.routes[4]
        self.assertGreater(len(route), 2)           # it does cross ranks
        self.assertLess(sum(math.dist(a, b) for a, b in zip(route, route[1:])),
                        math.dist(route[0], route[-1]) * 1.02)

    def test_a_real_dependency_graph_stays_tidy(self):
        # Before the layout ranked its invisible nodes above the boxes this
        # came out at 1.58 and 62 corners: a cloud of wandering lines.
        _, lay = layout(DEPENDENCIES)
        self.assertLess(wander(lay.routes), 1.25)
        self.assertLess(bends(lay.routes), 25)

    def test_a_tidy_graph_does_not_sprawl_sideways(self):
        # The wandering was width: the lines swung out to the right and the
        # picture had to grow to hold them.  It used to come out half as
        # wide again as it was tall.
        _, lay = layout(DEPENDENCIES)
        self.assertLess(lay.width, lay.height * 1.15)

    def test_no_half_rank_when_no_caption_wants_one(self):
        _, lay = layout("flowchart TD\n A --> B\n")
        self.assertEqual(len(lay.routes[0]), 2)     # straight from A to B

    def test_a_caption_still_gets_a_rank_of_its_own(self):
        _, lay = layout("flowchart TD\n A -->|why| B\n")
        self.assertEqual(len(lay.routes[0]), 3)     # A, the caption, B
        self.assertIn(0, lay.captions)

    def test_counting_crossings_between_two_ranks(self):
        adj = {"a": ("p",), "b": ("q",), "p": ("a",), "q": ("b",)}
        self.assertEqual(D._between(["a", "b"], ["p", "q"], adj.get), 0)
        self.assertEqual(D._between(["a", "b"], ["q", "p"], adj.get), 1)

    def test_transpose_undoes_a_crossing_the_median_cannot_see(self):
        adj = {"a": ("p",), "b": ("q",), "p": ("a",), "q": ("b",)}
        layers = {0: ["a", "b"], 1: ["q", "p"]}
        self.assertEqual(D._crossings(layers, [0, 1], adj.get), 1)
        D._transpose(layers, [0, 1], adj.get)
        self.assertEqual(D._crossings(layers, [0, 1], adj.get), 0)



    def test_a_caption_gives_way_rather_than_drag_its_edge(self):
        # Labelling the same graph used to cost it half again in wander --
        # every caption hauling its line across to sit exactly on it.
        _, lay = layout(INCLUDES)
        self.assertLess(wander(lay.routes), 1.25)

    def test_labels_do_not_make_the_picture_balloon(self):
        # Labelling every edge of a graph this size used to take it to
        # 1218px wide, with the captions hauling the lines out sideways.
        _, lay = layout(INCLUDES)
        self.assertLess(lay.width, 950)

    def test_more_than_one_starting_order_is_tried(self):
        # The median and the swaps only walk downhill, so a single starting
        # order settles wherever it happens to land -- 20 crossings on the
        # plain graph and 20 on the labelled one, and no amount of extra
        # sweeping moved either.  Several starts is what got past that.
        _, plain = layout(DEPENDENCIES)
        _, tagged = layout(INCLUDES)
        self.assertLess(crossings(plain.routes), 10)
        self.assertLess(crossings(tagged.routes), 12)

    def test_a_node_sits_near_what_it_connects_to(self):
        # Longest-path ranking alone puts D on rank 1, three ranks above the
        # only thing it points at.  It belongs just above E.
        _, lay = layout("flowchart TD\n A --> B\n B --> C\n C --> E\n"
                        " A --> D\n D --> E\n")
        rank_of = {n: round(p[1]) for n, p in lay.pos.items()}
        self.assertGreater(rank_of["D"], rank_of["B"])
        self.assertEqual(len(lay.routes[4]), 2)     # D --> E spans one rank

    def test_tightening_never_puts_a_node_below_what_it_needs(self):
        # Sliding nodes down must keep every edge pointing the same way.
        names = [f"N{k}" for k in range(9)]
        lines = ["flowchart TD"]
        lines += [f" {a} --> {b}" for a, b in zip(names, names[1:])]
        lines += [" N0 --> N8", " N2 --> N8", " N4 --> N8", " N1 --> N6"]
        _, lay = layout("\n".join(lines) + "\n")
        for route in lay.routes:
            self.assertLess(route[0][1], route[-1][1])   # always downhill


class TestEdgeCurves(unittest.TestCase):
    """An edge is drawn as a curve through its slots, not a run of corners."""

    def test_a_straight_run_is_left_alone(self):
        run = [(0.0, 0.0), (0.0, 80.0)]
        self.assertEqual(D._smooth(run), run)

    def test_a_corner_is_rounded_off(self):
        route = [(0.0, 0.0), (0.0, 60.0), (70.0, 120.0)]
        curve = D._smooth(route)
        self.assertGreater(len(curve), len(route))
        self.assertLess(sharpest(curve), sharpest(route) / 2)

    def test_the_curve_still_goes_through_its_slots(self):
        # The slots are what hold a long edge clear of the boxes it passes,
        # so the curve has to keep them, not cut the corner off them.
        route = [(0.0, 0.0), (0.0, 60.0), (70.0, 120.0), (70.0, 180.0)]
        curve = D._smooth(route)
        for slot in route:
            self.assertTrue(any(math.dist(slot, p) < 0.01 for p in curve),
                            f"{slot} is not on the curve")

    def test_rounding_never_puts_an_edge_through_a_box(self):
        # The slots hold a long edge clear of what it passes; rounding the
        # corners off between them must not undo that.  It is not enough for
        # the curve to be clear in general -- it has to be clear wherever
        # the straight route was, which is the thing being replaced.
        for name, src in (("plain", DEPENDENCIES), ("labelled", INCLUDES)):
            chart, lay, sizes, drawn = curves(src)

            def through(run, edge):
                for a, b in zip(run, run[1:]):
                    steps = max(2, int(math.dist(a, b) / 2))
                    for i in range(steps + 1):
                        x = a[0] + (b[0] - a[0]) * i / steps
                        y = a[1] + (b[1] - a[1]) * i / steps
                        for nid in chart.nodes:
                            if nid in (edge.src, edge.dst):
                                continue
                            cx, cy = lay.pos[nid]
                            w, h = sizes[nid]
                            if abs(x - cx) < w / 2 and abs(y - cy) < h / 2:
                                return True
                return False

            for k, (straight, curve) in enumerate(drawn):
                edge = chart.edges[k]
                if not through(straight, edge):
                    self.assertFalse(through(curve, edge),
                                     f"{name}: rounding {edge.src}->"
                                     f"{edge.dst} put it through a box")

    def test_the_picture_is_mostly_free_of_corners(self):
        # Every rank a long edge crossed used to put a corner in it.
        _, _, _, drawn = curves(DEPENDENCIES)
        sharp = sum(1 for _, curve in drawn if sharpest(curve) > 25)
        self.assertLess(sharp, 4)


    def test_a_transit_edge_does_not_wander(self):
        # An edge crossing several ranks used to pick up a change of
        # direction at nearly every one of them -- six on the plain graph
        # and twelve on the labelled one, for the same single edge.
        for name, src in (("plain", DEPENDENCIES), ("labelled", INCLUDES)):
            chart, lay, sizes, drawn = curves(src)
            worst = max((turns(straight), chart.edges[k].src + "->"
                         + chart.edges[k].dst)
                        for k, (straight, _) in enumerate(drawn))
            self.assertLess(worst[0], 5, f"{name}: {worst[1]}")

    def test_a_slot_doing_a_job_is_kept(self):
        # Straightening may only take out the wandering.  A slot that is
        # holding the line clear of a box has to stay, and the test that
        # nothing ends up through a box is what checks it did.
        chart, lay, sizes, drawn = curves(DEPENDENCIES)
        self.assertTrue(any(len(straight) > 2 for straight, _ in drawn),
                        "every route was straightened to a single run")

    def test_a_caption_keeps_its_place_on_the_line(self):
        # The label is drawn at the slot the layout kept for it, so that
        # slot must survive being straightened or the caption comes adrift.
        chart, lay, sizes, drawn = curves(INCLUDES)
        for k, (straight, _) in enumerate(drawn):
            spot = lay.captions.get(k)
            if spot is None:
                continue
            self.assertTrue(any(math.dist(spot, p) < 0.01 for p in straight),
                            f"{chart.edges[k].src}->{chart.edges[k].dst}"
                            f" lost the slot its caption sits on")


class TestSvg(unittest.TestCase):
    def test_svg_shape(self):
        svg = D.to_svg(scene("flowchart TD\n A[Start] --> B((End))\n"), "flow")
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.rstrip().endswith("</svg>"))
        self.assertIn("viewBox=", svg)
        self.assertIn("<rect", svg)
        self.assertIn("<ellipse", svg)
        self.assertIn("<polygon", svg)          # the arrow head
        self.assertIn(">Start</text>", svg)

    def test_svg_escapes_text(self):
        svg = D.to_svg(scene('flowchart TD\n A["a < b & c"] --> B\n'))
        self.assertIn("a &lt; b &amp; c", svg)
        self.assertNotIn("<b &", svg)

    def test_svg_has_no_external_references(self):
        svg = D.to_svg(scene("sequenceDiagram\n A->>B: hi\n"))
        for banned in ("<script", "<image", "href", "src=", "url(", "@import"):
            self.assertNotIn(banned, svg)
        # The one URL allowed is the SVG namespace, which is never fetched.
        self.assertEqual(svg.count("http"), 1)
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', svg)


class TestRobustness(unittest.TestCase):
    def test_odd_input_does_not_raise(self):
        for src in ("flowchart TD\n" + "A --> " * 200 + "B\n",
                    "flowchart TD\n A[" + "x" * 500 + "] --> B\n",
                    "flowchart TD\n A[unclosed --> B\n",
                    "flowchart TD\n --> \n A\n",
                    "flowchart TD\n A --> B\n subgraph s\n" * 20 + " end\n",
                    "sequenceDiagram\n A->>B\n B: no arrow\n",
                    "sequenceDiagram\n" + " end\n" * 10 + " A->>B: x\n",
                    "classDiagram\n class {\n }\n A <|-- \n",
                    "classDiagram\n A <|-- B\n B <|-- A\n"):
            model = M.parse(src)
            if model is not None:
                D.render(model, D.Style())      # must not hang or raise

    def test_long_chain_stays_sane(self):
        src = "flowchart TD\n" + "\n".join(
            f" N{k} --> N{k + 1}" for k in range(60))
        sc = scene(src)
        self.assertLess(sc.width, 4000)
        self.assertGreater(sc.height, 1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)

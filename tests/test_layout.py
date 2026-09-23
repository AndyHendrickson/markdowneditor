"""Preview layout: the measure, table fitting, and what a resize costs.

Anything that needs a real Tk window is skipped where there is no display,
so the suite still runs on a headless box.  Run: python -m unittest discover
tests
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mdedit import flavors, parser as P, tkrender  # noqa: E402
from mdedit.app import MarkdownApp  # noqa: E402

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.withdraw()
except Exception as exc:            # pragma: no cover - depends on the box
    tk = None
    _WHY = f"no usable tkinter display ({exc})"


def widget(width: int = 900, flavor: str = "mdedit", size: int = 11):
    """A preview widget of a known width, with a renderer on it."""
    top = tk.Toplevel(_root)
    top.geometry(f"{width}x600")
    text = tk.Text(top)
    text.pack(fill="both", expand=True)
    renderer = tkrender.MarkdownRenderer(text, tkrender.LIGHT, size,
                                         flavor=flavors.get(flavor))
    top.update()
    return top, text, renderer


class TestColumnFitting(unittest.TestCase):
    """``fit_columns`` is plain arithmetic -- no display needed."""

    def test_everything_fits(self):
        self.assertEqual(tkrender.fit_columns([5, 10, 15], 100), [5, 10, 15])

    def test_the_widest_column_gives_way(self):
        got = tkrender.fit_columns([6, 12, 90], 40)
        self.assertEqual(sum(got), 40)
        self.assertEqual(got[:2], [6, 12])      # the short ones are untouched

    def test_the_budget_is_shared_when_all_are_wide(self):
        got = tkrender.fit_columns([40, 40, 40], 60)
        self.assertEqual(got, [20, 20, 20])

    def test_leftovers_are_handed_back(self):
        got = tkrender.fit_columns([9, 9, 30], 40)
        self.assertEqual(sum(got), 40)

    def test_too_narrow_keeps_a_readable_minimum(self):
        got = tkrender.fit_columns([30, 30, 30], 6, minimum=8)
        self.assertEqual(got, [8, 8, 8])        # overflows, and scrolls

    def test_no_columns(self):
        self.assertEqual(tkrender.fit_columns([], 40), [])


@unittest.skipIf(tk is None, globals().get("_WHY", "no tkinter"))
class TestMeasure(unittest.TestCase):
    def test_narrow_pane_uses_what_it_has(self):
        top, _, r = widget(500)
        try:
            self.assertGreater(r.content_width(500), 400)
            self.assertLess(r.content_width(500), 500)
        finally:
            top.destroy()

    def test_wide_pane_caps_and_centres(self):
        top, text, r = widget(1600)
        try:
            column = r.content_width(1600)
            self.assertLess(column, 900)         # capped, not the full pane
            r.fit_width(1600)
            pad = int(text.cget("padx"))
            self.assertAlmostEqual(1600 - 2 * pad, column, delta=2)
        finally:
            top.destroy()

    def test_every_flavour_has_a_sane_measure(self):
        top, _, r = widget(1600)
        try:
            for key in flavors.ORDER:
                r.set_flavor(flavors.get(key))
                column = r.content_width(1600)
                self.assertGreater(column, 300, key)
                self.assertLess(column, 1500, key)
        finally:
            top.destroy()

    def test_bigger_text_gets_a_wider_column(self):
        top, _, r = widget(1600)
        try:
            small = r.content_width(1600)
            r.set_base_size(16)
            self.assertGreater(r.content_width(1600), small)
        finally:
            top.destroy()

    def test_chrome_steps_with_the_window(self):
        top, _, r = widget(1600, flavor="chrome")
        try:
            steps = [r.content_width(w) for w in (500, 800, 1100, 1500)]
            self.assertEqual(steps, sorted(steps))
            self.assertLess(steps[0], steps[-1])
        finally:
            top.destroy()


@unittest.skipIf(tk is None, globals().get("_WHY", "no tkinter"))
class TestTableFits(unittest.TestCase):
    SOURCE = (
        "| Step | File | Note |\n| --- | --- | --- |\n"
        "| Queue | `TEventManager.cpp` | " + "words that go on and on " * 8
        + "|\n"
    )

    def rendered_width(self, renderer, text) -> int:
        mono = renderer._fonts["mono"]
        return max((mono.measure(line)
                    for line in text.get("1.0", "end").split("\n")), default=0)

    def test_a_wide_table_widens_the_block(self):
        top, text, r = widget(1600)
        try:
            r.render(P.parse(self.SOURCE), "")
            top.update()
            drawn = self.rendered_width(r, text)
            # A grid is not prose, so it spreads past the text measure ...
            self.assertGreater(drawn, r.content_width())
            # ... but only as far as the block, which is room on the screen:
            # there is nothing to scroll sideways to.
            self.assertLessEqual(drawn, r._room())
            self.assertAlmostEqual(text.xview()[1], 1.0, places=3)
        finally:
            top.destroy()

    def test_prose_keeps_the_measure_beside_a_wide_table(self):
        top, text, r = widget(1600)
        try:
            prose = "A paragraph long enough to wrap. " * 12
            r.render(P.parse(prose + "\n\n" + self.SOURCE), "")
            top.update()
            column = r.content_width()
            first = text.dlineinfo("1.0")[2]          # width of a wrapped line
            self.assertLessEqual(first, column)       # held to the measure ...
            self.assertGreater(first, column / 2)     # ... and filling it
        finally:
            top.destroy()

    def test_a_tinted_margin_stays_a_bar(self):
        top, text, r = widget(1600)
        try:
            # The block is wider than the measure here.  A quote or panel
            # marks its own edge with a coloured margin, and that margin has
            # to stay the width of a bar -- not spread across the gap beside
            # the column, which is what a margin-based column offset does.
            r.render(P.parse("::: note\nA panel.\n:::\n\n" + self.SOURCE), "")
            top.update()
            tinted = [n for n in text.tag_names() if n.startswith("mar_")]
            self.assertTrue(tinted)
            for name in tinted:
                self.assertLess(int(text.tag_cget(name, "lmargin1")), 40)
        finally:
            top.destroy()

    def test_a_narrow_pane_gets_a_narrower_table(self):
        wide_top, wide_text, wide_r = widget(900)
        narrow_top, narrow_text, narrow_r = widget(420)
        try:
            wide_r.render(P.parse(self.SOURCE), "")
            narrow_r.render(P.parse(self.SOURCE), "")
            wide_top.update()
            narrow_top.update()
            self.assertLess(self.rendered_width(narrow_r, narrow_text),
                            self.rendered_width(wide_r, wide_text))
        finally:
            wide_top.destroy()
            narrow_top.destroy()

    def test_a_narrow_column_wraps_rather_than_dropping_text(self):
        top, text, r = widget(420)
        try:
            r.render(P.parse(self.SOURCE), "")
            top.update()
            shown = text.get("1.0", "end")
            # Nothing is cut off: every repetition is still there, wrapped
            # inside its cell.  A word longer than its column does get broken
            # across lines -- the grid has to hold together somehow.
            self.assertEqual(shown.count("words"), 8)
            self.assertIn("TEventManager", shown.replace("│", "")
                          .replace("\n", "").replace(" ", ""))
        finally:
            top.destroy()


@unittest.skipIf(tk is None, globals().get("_WHY", "no tkinter"))
class TestResize(unittest.TestCase):
    def test_a_real_change_asks_for_a_new_layout(self):
        top, _, r = widget(900)
        try:
            r.render(P.parse("| a | b |\n| --- | --- |\n| 1 | 2 |\n"), "")
            self.assertFalse(r.needs_relayout(900))
            self.assertTrue(r.needs_relayout(400))
        finally:
            top.destroy()

    def test_a_wider_pane_relays_out_for_the_grids(self):
        cells = " | ".join("a repository name" for _ in range(16))
        wide = (f"| {cells} |\n| {' | '.join('---' for _ in range(16))} |\n"
                f"| {cells} |\n")
        top, _, r = widget(1400)
        try:
            r.render(P.parse(wide), "")
            # This table wants more than either pane has, so the block is the
            # pane.  The text column is already at its measure and does not
            # move, but the block does, and the table is drawn to the block.
            self.assertEqual(r.content_width(1400), r.content_width(2000))
            self.assertTrue(r.needs_relayout(2000))
        finally:
            top.destroy()

    def test_nothing_to_lay_out_yet(self):
        top, _, r = widget(900)
        try:
            self.assertFalse(r.needs_relayout(400))
        finally:
            top.destroy()

    def test_diagrams_are_refitted_in_place(self):
        top, _, r = widget(1200)
        try:
            r.render(P.parse(
                "```mermaid\nflowchart LR\n"
                "  A[Ingest] --> B[Parse] --> C[Validate] --> D[Store]\n"
                "  D --> E[Notify] --> F[Finish]\n```\n"), "")
            top.update()
            wide = r._diagrams[0][0].winfo_reqwidth()
            r.resize_rules(500)
            top.update()
            self.assertLess(r._diagrams[0][0].winfo_reqwidth(), wide)
        finally:
            top.destroy()

    def test_rules_follow_the_column(self):
        top, _, r = widget(1600)
        try:
            r.render(P.parse("# Heading\n\ntext\n\n---\n\nmore\n"), "")
            top.update()
            r.resize_rules(1600)
            for frame in r._rules:
                self.assertLessEqual(int(frame.cget("width")),
                                     r.content_width(1600))
        finally:
            top.destroy()


@unittest.skipIf(tk is None, globals().get("_WHY", "no tkinter"))
class TestScrollSync(unittest.TestCase):
    """The panes follow each other -- both ways -- while sync is on.

    Scroll fractions are compared loosely, and a pane that should not have
    moved is checked by the line at its top instead.  Tk measures display
    lines lazily, so a freshly rendered preview reports a fraction that
    can still shift by a few percent without the view moving at all.
    """

    DOC = ("\n\n".join(
        f"## Section {n}\n\nProse in section {n}, long enough that"
        f" it wraps once or twice in a pane this wide."
        for n in range(1, 121)))

    @staticmethod
    def quiet(app):
        """Drop any queued re-render.

        A render re-centres the preview on the editor, which would move a
        pane for a reason that has nothing to do with the scroll link.
        """
        app._cancel(app._render_job)
        app._render_job = None

    @classmethod
    def app(cls):
        """A live app holding a document far taller than either pane."""
        app = MarkdownApp()
        app.geometry("1200x700")
        app.update()
        app.editor.delete("1.0", "end")
        app.editor.insert("1.0", cls.DOC)
        for _ in range(4):              # land the debounced render
            app.update()
            if app._render_job is None:
                break
            app._cancel(app._render_job)
            app.render_now()
        cls.quiet(app)
        return app

    def test_the_editor_drives_the_preview(self):
        app = self.app()
        try:
            app.editor.yview("moveto", 0.75)    # what its scrollbar does
            app.update()
            self.assertAlmostEqual(app.preview.yview()[0], 0.75, delta=0.1)
        finally:
            app.destroy()

    def test_the_preview_drives_the_editor(self):
        app = self.app()
        try:
            app.preview.yview("moveto", 0.45)
            app.update()
            self.assertAlmostEqual(app.editor.yview()[0], 0.45, delta=0.05)
        finally:
            app.destroy()

    def test_a_preview_scroll_does_not_ask_for_a_render(self):
        # A render re-centres the preview on the editor, so a preview
        # scroll that queued one would snap itself back mid-drag.
        app = self.app()
        try:
            self.quiet(app)
            app.preview.yview("moveto", 0.30)
            app.update()
            self.assertIsNone(app._render_job)
        finally:
            app.destroy()

    def test_sync_off_leaves_each_pane_alone(self):
        app = self.app()
        try:
            app.sync_scroll.set(False)
            app.preview.yview("moveto", 0.40)
            app.update()
            self.assertEqual(app.editor.yview()[0], 0.0)
            top = app.preview.index("@0,0")
            self.quiet(app)
            app.editor.yview("moveto", 0.90)
            app.update()
            self.assertEqual(app.preview.index("@0,0"), top)
        finally:
            app.destroy()

@unittest.skipIf(tk is None, globals().get("_WHY", "no tkinter"))
class TestDiagramFiles(unittest.TestCase):
    """Opening a ``.mermaid`` file draws it; saving leaves it bare."""

    SOURCE = "flowchart LR\n    A[Ingest] --> B[Parse] --> C[Store]\n"

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "graph.mermaid")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(self.SOURCE)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_it_opens_as_a_diagram(self):
        app = MarkdownApp(self.path)
        try:
            app.update()
            app.render_now()
            app.update()
            self.assertEqual(len(app.renderer._diagrams), 1)
            # Drawn, not shown: the source is on a canvas, not in the text.
            self.assertNotIn("flowchart", app.preview.get("1.0", "end"))
        finally:
            app.destroy()

    def test_the_file_keeps_its_own_shape(self):
        app = MarkdownApp(self.path)
        try:
            self.assertEqual(app.source().strip(), self.SOURCE.strip())
            again = os.path.join(self.dir, "again.mermaid")
            app._write(again)
            with open(again, encoding="utf-8") as fh:
                self.assertNotIn("```", fh.read())
        finally:
            app.destroy()

    def test_a_byte_order_mark_is_not_content(self):
        marked = os.path.join(self.dir, "marked.mermaid")
        with open(marked, "w", encoding="utf-8-sig") as fh:
            fh.write(self.SOURCE)
        app = MarkdownApp(marked)
        try:
            app.update()
            app.render_now()
            app.update()
            self.assertEqual(len(app.renderer._diagrams), 1)
            self.assertTrue(app.source().startswith("flowchart"))
        finally:
            app.destroy()

    def test_a_front_matter_prelude_still_draws(self):
        titled = os.path.join(self.dir, "titled.mermaid")
        with open(titled, "w", encoding="utf-8") as fh:
            fh.write("---\ntitle: Pipeline\n---\n" + self.SOURCE)
        app = MarkdownApp(titled)
        try:
            app.update()
            app.render_now()
            app.update()
            self.assertEqual(len(app.renderer._diagrams), 1)
        finally:
            app.destroy()
    def test_a_real_file_opens_as_a_picture(self):
        # The whole path, on the fixture the editor was reported failing
        # on: read the file, fence it, parse it, lay it out, draw it.
        here = os.path.dirname(os.path.abspath(__file__))
        app = MarkdownApp(os.path.join(here, "Seq.mermaid"))
        try:
            app.update()
            app.render_now()
            app.update()
            self.assertEqual(len(app.renderer._diagrams), 1)
            self.assertNotIn("sequenceDiagram",
                             app.preview.get("1.0", "end"))
        finally:
            app.destroy()
    def test_a_markdown_file_is_still_markdown(self):
        notes = os.path.join(self.dir, "notes.md")
        with open(notes, "w", encoding="utf-8") as fh:
            fh.write("# Title\n\n" + self.SOURCE)
        app = MarkdownApp(notes)
        try:
            app.update()
            app.render_now()
            app.update()
            self.assertEqual(app.renderer._diagrams, [])
            self.assertIn("flowchart", app.preview.get("1.0", "end"))
        finally:
            app.destroy()

if __name__ == "__main__":
    unittest.main(verbosity=2)

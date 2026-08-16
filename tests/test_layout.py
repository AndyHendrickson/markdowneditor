"""Preview layout: the measure, table fitting, and what a resize costs.

Anything that needs a real Tk window is skipped where there is no display,
so the suite still runs on a headless box.  Run: python -m unittest discover
tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mdedit import flavors, parser as P, tkrender  # noqa: E402

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

    def test_a_wide_table_fits_the_column(self):
        top, text, r = widget(900)
        try:
            r.render(P.parse(self.SOURCE), "")
            top.update()
            self.assertLessEqual(self.rendered_width(r, text),
                                 r.content_width())
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


if __name__ == "__main__":
    unittest.main(verbosity=2)

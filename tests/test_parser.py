"""Parser and HTML-export tests.  Run: python -m unittest discover tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mdedit import html_export, parser as P  # noqa: E402


def html(src: str) -> str:
    return html_export.to_html(P.parse(src), standalone=False)


class TestBlocks(unittest.TestCase):
    def test_atx_headings(self):
        doc = P.parse("# One\n\n### Three ###\n")
        self.assertEqual([type(b) for b in doc.children], [P.Heading, P.Heading])
        self.assertEqual(doc.children[0].level, 1)
        self.assertEqual(doc.children[1].level, 3)
        self.assertEqual(P.plain_text(doc.children[1].children), "Three")

    def test_setext_headings(self):
        doc = P.parse("Title\n=====\n\nSub\n---\n")
        levels = [b.level for b in doc.children if isinstance(b, P.Heading)]
        self.assertEqual(levels, [1, 2])

    def test_hash_not_heading_without_space(self):
        doc = P.parse("#tag line\n")
        self.assertIsInstance(doc.children[0], P.Paragraph)

    def test_paragraphs_and_soft_breaks(self):
        doc = P.parse("one\ntwo\n\nthree\n")
        self.assertEqual(len(doc.children), 2)
        self.assertIn(P.SoftBreak, [type(n) for n in doc.children[0].children])

    def test_hard_break_two_spaces(self):
        doc = P.parse("one  \ntwo\n")
        kinds = [type(n) for n in doc.children[0].children]
        self.assertIn(P.HardBreak, kinds)
        self.assertNotIn(P.SoftBreak, kinds)

    def test_hard_break_backslash(self):
        doc = P.parse("one\\\ntwo\n")
        self.assertIn(P.HardBreak, [type(n) for n in doc.children[0].children])

    def test_fenced_code(self):
        doc = P.parse("```python\nx = 1\n\ny = 2\n```\n")
        block = doc.children[0]
        self.assertIsInstance(block, P.CodeBlock)
        self.assertEqual(block.lang, "python")
        self.assertEqual(block.text, "x = 1\n\ny = 2")

    def test_fenced_code_keeps_markdown_literal(self):
        doc = P.parse("```\n# not a heading\n*not em*\n```\n")
        self.assertEqual(doc.children[0].text, "# not a heading\n*not em*")

    def test_tilde_fence_can_hold_backticks(self):
        doc = P.parse("~~~\n```\n~~~\n")
        self.assertEqual(doc.children[0].text, "```")

    def test_indented_code(self):
        doc = P.parse("text\n\n    line one\n    line two\n\nafter\n")
        block = doc.children[1]
        self.assertIsInstance(block, P.CodeBlock)
        self.assertEqual(block.text, "line one\nline two")

    def test_thematic_break_variants(self):
        for src in ("---\n", "***\n", "___\n", "- - -\n", " ** * ** * **\n"):
            doc = P.parse(src)
            self.assertIsInstance(doc.children[0], P.ThematicBreak, src)

    def test_blockquote_nested_and_lazy(self):
        doc = P.parse("> outer\n> continues\n>\n> > inner\n")
        quote = doc.children[0]
        self.assertIsInstance(quote, P.BlockQuote)
        self.assertIsInstance(quote.children[0], P.Paragraph)
        self.assertIsInstance(quote.children[1], P.BlockQuote)

    def test_unordered_list(self):
        doc = P.parse("- a\n- b\n- c\n")
        lst = doc.children[0]
        self.assertIsInstance(lst, P.ListBlock)
        self.assertFalse(lst.ordered)
        self.assertTrue(lst.tight)
        self.assertEqual(len(lst.items), 3)

    def test_ordered_list_start(self):
        doc = P.parse("3. three\n4. four\n")
        lst = doc.children[0]
        self.assertTrue(lst.ordered)
        self.assertEqual(lst.start, 3)

    def test_sibling_items_are_separate(self):
        # "2." may not interrupt a paragraph, but it must still end item 1.
        lst = P.parse("1. one\n2. two\n3. three\n").children[0]
        self.assertEqual(len(lst.items), 3)
        self.assertEqual(
            [P.plain_text(i.children[0].children) for i in lst.items],
            ["one", "two", "three"],
        )

    def test_item_lazy_continuation(self):
        lst = P.parse("- one\ncontinued\n- two\n").children[0]
        self.assertEqual(len(lst.items), 2)
        self.assertIn("continued", P.plain_text(lst.items[0].children[0].children))

    def test_nested_list(self):
        doc = P.parse("- a\n  - b\n    - c\n- d\n")
        top = doc.children[0]
        self.assertEqual(len(top.items), 2)
        nested = top.items[0].children[1]
        self.assertIsInstance(nested, P.ListBlock)
        self.assertIsInstance(nested.items[0].children[1], P.ListBlock)

    def test_loose_list(self):
        doc = P.parse("- a\n\n- b\n")
        self.assertFalse(doc.children[0].tight)

    def test_task_list(self):
        doc = P.parse("- [x] done\n- [ ] todo\n")
        items = doc.children[0].items
        self.assertEqual([i.task for i in items], [True, False])
        self.assertEqual(P.plain_text(items[0].children[0].children), "done")

    def test_list_interrupts_paragraph(self):
        doc = P.parse("text\n- a\n")
        self.assertEqual([type(b) for b in doc.children], [P.Paragraph, P.ListBlock])

    def test_table(self):
        src = "| a | b |\n|:--|--:|\n| 1 | 2 |\n| 3 | 4 |\n"
        table = P.parse(src).children[0]
        self.assertIsInstance(table, P.Table)
        self.assertEqual(table.aligns, ["left", "right"])
        self.assertEqual(len(table.rows), 2)
        self.assertEqual(P.plain_text(table.rows[1][1]), "4")

    def test_table_center_alignment(self):
        table = P.parse("a | b\n:-:|---\n1 | 2\n").children[0]
        self.assertEqual(table.aligns, ["center", "left"])

    def test_not_a_table(self):
        doc = P.parse("| a | b |\nnot a delimiter\n")
        self.assertIsInstance(doc.children[0], P.Paragraph)


class TestInlines(unittest.TestCase):
    def test_emphasis(self):
        self.assertEqual(html("*a*"), "<p><em>a</em></p>")
        self.assertEqual(html("_a_"), "<p><em>a</em></p>")
        self.assertEqual(html("**a**"), "<p><strong>a</strong></p>")
        self.assertEqual(html("__a__"), "<p><strong>a</strong></p>")
        self.assertEqual(
            html("***a***"), "<p><strong><em>a</em></strong></p>")

    def test_nested_emphasis(self):
        self.assertEqual(
            html("*a **b** c*"),
            "<p><em>a <strong>b</strong> c</em></p>",
        )

    def test_intraword_underscore_is_literal(self):
        self.assertEqual(html("snake_case_name"), "<p>snake_case_name</p>")

    def test_strikethrough(self):
        self.assertEqual(html("~~gone~~"), "<p><del>gone</del></p>")

    def test_code_span(self):
        self.assertEqual(html("`x = *1*`"), "<p><code>x = *1*</code></p>")
        self.assertEqual(html("``a ` b``"), "<p><code>a ` b</code></p>")

    def test_code_span_wins_over_emphasis(self):
        self.assertEqual(html("*a `b* c`"), "<p>*a <code>b* c</code></p>")

    def test_escapes(self):
        self.assertEqual(html(r"\*not em\*"), "<p>*not em*</p>")
        self.assertEqual(html(r"a \\ b"), "<p>a \\ b</p>")

    def test_link(self):
        self.assertEqual(
            html("[text](page.md)"), '<p><a href="page.md">text</a></p>')

    def test_link_with_title_and_nested_brackets(self):
        out = html('[a [b] c](x.md "Title")')
        self.assertIn('href="x.md"', out)
        self.assertIn('title="Title"', out)
        self.assertIn("a [b] c", out)

    def test_image(self):
        out = html("![alt text](pic.png)")
        self.assertIn('<img src="pic.png"', out)
        self.assertIn('alt="alt text"', out)

    def test_autolink(self):
        self.assertIn('<a href="https://example.com">', html("<https://example.com>"))

    def test_email_autolink(self):
        self.assertIn('href="mailto:a@b.com"', html("<a@b.com>"))

    def test_entities(self):
        self.assertEqual(html("&amp; &lt;"), "<p>&amp; &lt;</p>")

    def test_html_is_escaped(self):
        self.assertEqual(
            html("<script>alert(1)</script>"),
            "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>",
        )

    def test_unclosed_emphasis_is_literal(self):
        self.assertEqual(html("*dangling"), "<p>*dangling</p>")


class TestHtmlExport(unittest.TestCase):
    def test_standalone_document(self):
        out = html_export.to_html(P.parse("# Title\n\nBody.\n"))
        self.assertTrue(out.startswith("<!DOCTYPE html>"))
        self.assertIn("<title>Title</title>", out)
        self.assertIn("<style>", out)
        self.assertIn("<h1 id=\"title\">Title</h1>", out)

    def test_no_external_references(self):
        out = html_export.to_html(P.parse("# T\n\ntext\n"))
        for needle in ("http://", "https://", "//cdn", "<script"):
            self.assertNotIn(needle, out)

    def test_code_block_escaped(self):
        out = html("```\n<b> & 'x'\n```")
        self.assertIn("&lt;b&gt; &amp; &#x27;x&#x27;", out)

    def test_task_list_html(self):
        out = html("- [x] done\n")
        self.assertIn('type="checkbox" disabled checked', out)

    def test_table_html(self):
        out = html("| a |\n|--:|\n| 1 |\n")
        self.assertIn('<th style="text-align:right">a</th>', out)

    def test_tight_list_has_no_paragraphs(self):
        self.assertNotIn("<p>", html("- a\n- b\n"))

    def test_loose_list_has_paragraphs(self):
        self.assertIn("<p>", html("- a\n\n- b\n"))


class TestDialects(unittest.TestCase):
    def test_bare_url_linkified(self):
        out = html("see https://example.com/a_b now")
        self.assertIn('<a href="https://example.com/a_b">', out)

    def test_bare_url_trailing_punctuation(self):
        out = html("go to www.example.com.")
        self.assertIn('href="https://www.example.com"', out)
        self.assertTrue(out.rstrip().endswith(".</p>"))

    def test_bare_url_off(self):
        opts = P.Options(bare_autolinks=False)
        out = html_export.to_html(P.parse("see https://x.com", opts),
                                  standalone=False)
        self.assertNotIn("<a ", out)

    def test_no_nested_link_from_bare_url(self):
        out = html("[https://example.com](page.md)")
        self.assertEqual(out.count("<a "), 1)

    def test_hard_breaks_option(self):
        opts = P.Options(hard_breaks=True)
        out = html_export.to_html(P.parse("one\ntwo", opts), standalone=False)
        self.assertIn("<br>", out)
        self.assertNotIn("<br>", html("one\ntwo"))

    def test_mark(self):
        self.assertIn("<mark>hi</mark>", html("==hi=="))
        opts = P.Options(mark=False)
        self.assertNotIn(
            "<mark>", html_export.to_html(P.parse("==hi==", opts),
                                          standalone=False))

    def test_container(self):
        doc = P.parse("::: warning Heads up\nbody\n:::\n")
        panel = doc.children[0]
        self.assertIsInstance(panel, P.Panel)
        self.assertEqual(panel.kind, "warning")
        self.assertEqual(panel.title, "Heads up")
        self.assertEqual(P.plain_text(panel.children[0].children), "body")

    def test_container_off_is_literal(self):
        doc = P.parse("::: note\nbody\n:::\n", P.Options(containers=False))
        self.assertIsInstance(doc.children[0], P.Paragraph)

    def test_github_alert(self):
        doc = P.parse("> [!TIP]\n> be quick\n")
        panel = doc.children[0]
        self.assertIsInstance(panel, P.Panel)
        self.assertEqual(panel.kind, "tip")
        self.assertEqual(P.plain_text(panel.children[0].children), "be quick")

    def test_alert_unknown_kind_stays_a_quote(self):
        doc = P.parse("> [!NONSENSE]\n> text\n")
        self.assertIsInstance(doc.children[0], P.BlockQuote)

    def test_quote_panel_only_when_enabled(self):
        src = "> **Note:** watch out\n"
        self.assertIsInstance(P.parse(src).children[0], P.BlockQuote)
        panel = P.parse(src, P.Options(quote_panels=True)).children[0]
        self.assertIsInstance(panel, P.Panel)
        self.assertEqual(panel.kind, "note")
        self.assertEqual(P.plain_text(panel.children[0].children), "watch out")

    def test_quote_panel_ignores_ordinary_quotes(self):
        doc = P.parse("> just a quote\n", P.Options(quote_panels=True))
        self.assertIsInstance(doc.children[0], P.BlockQuote)

    def test_tables_can_be_disabled(self):
        doc = P.parse("| a |\n|---|\n| 1 |\n", P.Options(tables=False))
        self.assertNotIsInstance(doc.children[0], P.Table)

    def test_task_lists_can_be_disabled(self):
        lst = P.parse("- [x] a\n", P.Options(task_lists=False)).children[0]
        self.assertIsNone(lst.items[0].task)
        self.assertIn("[x]", P.plain_text(lst.items[0].children[0].children))

    def test_strikethrough_can_be_disabled(self):
        out = html_export.to_html(
            P.parse("~~x~~", P.Options(strikethrough=False)), standalone=False)
        self.assertNotIn("<del>", out)


class TestFeatureSwitches(unittest.TestCase):
    def test_registry_matches_options(self):
        import dataclasses

        fields = {f.name for f in dataclasses.fields(P.Options)}
        self.assertEqual(fields, set(P.FEATURE_KEYS))
        self.assertEqual(len(P.FEATURES), len({f.flag for f in P.FEATURES}))
        for feature in P.FEATURES:
            self.assertTrue(feature.label and feature.hint, feature.key)
            self.assertNotIn("_", feature.flag)  # CLI flags use dashes

    def test_with_overrides(self):
        base = P.Options()
        self.assertTrue(base.tables)
        cut = P.with_overrides(base, {"tables": False})
        self.assertFalse(cut.tables)
        self.assertTrue(cut.task_lists)   # everything else untouched
        self.assertTrue(base.tables)      # and the original is unchanged

    def test_with_overrides_ignores_unknown_keys(self):
        base = P.Options()
        self.assertEqual(P.with_overrides(base, {"nonsense": False}), base)
        self.assertEqual(P.with_overrides(base, {}), base)

    def test_differences(self):
        base = P.Options()
        other = P.with_overrides(base, {"tables": False, "images": False})
        self.assertEqual(set(P.differences(other, base)), {"tables", "images"})
        self.assertEqual(P.differences(base, base), ())

    def test_disabled_table_renders_as_text(self):
        opts = P.Options(tables=False)
        out = html_export.to_html(P.parse("| a | b |\n|---|---|\n| 1 | 2 |\n", opts),
                                  standalone=False, opts=opts)
        self.assertNotIn("<table>", out)
        self.assertIn("| a | b |", out)

    def test_images_off(self):
        opts = P.Options(images=False)
        doc = P.parse("![a picture](pic.png)", opts)
        out = html_export.to_html(doc, standalone=False, opts=opts)
        self.assertNotIn("<img", out)
        self.assertIn("a picture", out)
        self.assertIn("noimg", out)

    def test_images_on_by_default(self):
        self.assertIn("<img", html("![a](pic.png)"))

    def test_overrides_apply_on_top_of_a_flavor(self):
        from mdedit import flavors

        opts = P.with_overrides(flavors.GITHUB.opts, {"mark": True})
        self.assertTrue(opts.mark)                 # override wins
        self.assertFalse(opts.containers)          # rest of GitHub intact
        out = html_export.to_html(P.parse("==x==", opts), standalone=False,
                                  flavor=flavors.GITHUB, opts=opts)
        self.assertIn("<mark>", out)


class TestCli(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "doc.md")
        self.out = os.path.join(self.dir, "doc.html")
        with open(self.src, "w", encoding="utf-8") as fh:
            fh.write("| a | b |\n|---|---|\n| 1 | 2 |\n\n"
                     "![pic](p.png) and https://example.com\n")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.dir, ignore_errors=True)

    def _run(self, args):
        import contextlib
        import io

        from mdedit import cli

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(args)
        self.assertEqual(code, 0, buf.getvalue())
        return buf.getvalue()

    def _export(self, *flags):
        self._run(["--export", self.src, self.out, *flags])
        with open(self.out, encoding="utf-8") as fh:
            return fh.read()

    def test_export_default(self):
        out = self._export()
        self.assertIn("<table>", out)
        self.assertIn("<img", out)
        self.assertIn('<a href="https://example.com"', out)

    def test_no_tables_flag(self):
        out = self._export("--no-tables")
        self.assertNotIn("<table>", out)
        self.assertIn("| a | b |", out)

    def test_several_flags(self):
        out = self._export("--no-images", "--no-autolinks")
        self.assertNotIn("<img", out)
        self.assertNotIn("<a href", out)
        self.assertIn("<table>", out)   # untouched features still render

    def test_flag_overrides_the_flavor(self):
        out = self._export("--flavor", "github", "--highlight")
        self.assertIn("GitHub emulation", out)

    def test_report_mentions_disabled_features(self):
        report = self._run(["--export", self.src, self.out, "--no-tables"])
        self.assertIn("--no-tables", report)

    def test_list_features(self):
        report = self._run(["--list-features", "--flavor", "confluence"])
        for feature in P.FEATURES:
            self.assertIn(f"--{feature.flag}", report)
        self.assertIn("Confluence", report)

    def test_outline_honours_flags(self):
        with open(self.src, "w", encoding="utf-8") as fh:
            fh.write("# One\n\n::: note\n## Hidden inside a container\n:::\n")
        with_containers = self._run(["--outline", self.src])
        without = self._run(["--outline", self.src, "--no-containers"])
        self.assertNotIn("Hidden", with_containers)  # nested in the panel
        self.assertIn("Hidden", without)             # plain heading again


class TestFlavors(unittest.TestCase):
    def test_every_flavor_renders(self):
        from mdedit import flavors, samples

        for key in flavors.ORDER:
            fl = flavors.FLAVORS[key]
            doc = P.parse(samples.EMULATION, fl.opts)
            out = html_export.to_html(doc, flavor=fl)
            self.assertIn("<body>", out)
            self.assertIn(f"{fl.name} emulation", out)

    def test_flavor_css_is_self_contained(self):
        from mdedit import flavors

        for key in flavors.ORDER:
            css = flavors.FLAVORS[key].css()
            for needle in ("http://", "https://", "@import", "url("):
                self.assertNotIn(needle, css, key)

    def test_flavors_differ(self):
        from mdedit import flavors

        sheets = {k: flavors.FLAVORS[k].css() for k in flavors.ORDER}
        self.assertEqual(len(set(sheets.values())), len(sheets))

    def test_lookup_and_cycle(self):
        from mdedit import flavors

        self.assertIs(flavors.get("github"), flavors.GITHUB)
        self.assertIs(flavors.get("GitHub"), flavors.GITHUB)
        self.assertIs(flavors.get("nope"), flavors.DEFAULT)
        seen = []
        key = flavors.DEFAULT.key
        for _ in flavors.ORDER:
            key = flavors.next_key(key)
            seen.append(key)
        self.assertEqual(sorted(seen), sorted(flavors.ORDER))

    def test_metrics_are_explicit(self):
        """Preview and export must agree; no metric may fall back by accident."""
        from mdedit import flavors

        required = ("body_fonts", "mono_fonts", "headings", "heading_rules",
                    "quote_style", "table_style", "code_style",
                    "link_underline", "panel_labels", "pad_x", "para_gap")
        for key in flavors.ORDER:
            metrics = flavors.FLAVORS[key].metrics
            for name in required:
                self.assertIn(name, metrics, f"{key} is missing {name}")

    def test_panel_labels_match_between_preview_and_export(self):
        from mdedit import flavors

        for key in flavors.ORDER:
            fl = flavors.FLAVORS[key]
            src = "> [!NOTE]\n> x\n"
            out = html_export.to_html(P.parse(src, fl.opts),
                                      standalone=False, flavor=fl)
            self.assertEqual(fl.metric("panel_labels"),
                             "panel-title" in out, key)

    def test_panel_html(self):
        from mdedit import flavors

        out = html_export.to_html(P.parse("> [!WARNING]\n> careful\n"),
                                  standalone=False, flavor=flavors.GITHUB)
        self.assertIn('class="panel panel-warning"', out)
        self.assertIn("Warning", out)

    def test_github_ignores_containers_and_marks(self):
        from mdedit import flavors

        doc = P.parse("::: note\nx\n:::\n\n==y==", flavors.GITHUB.opts)
        out = html_export.to_html(doc, standalone=False, flavor=flavors.GITHUB)
        self.assertNotIn("<mark>", out)
        self.assertNotIn('class="panel', out)

    def test_confluence_breaks_lines(self):
        from mdedit import flavors

        out = html_export.to_html(P.parse("a\nb", flavors.CONFLUENCE.opts),
                                  standalone=False, flavor=flavors.CONFLUENCE)
        self.assertIn("<br>", out)


class TestRobustness(unittest.TestCase):
    def test_empty_document(self):
        self.assertEqual(P.parse("").children, [])
        self.assertEqual(html(""), "")

    def test_crlf_and_tabs(self):
        doc = P.parse("# Title\r\n\r\n\t- indented\r\n")
        self.assertIsInstance(doc.children[0], P.Heading)

    def test_unterminated_fence(self):
        doc = P.parse("```\nnever closed\n")
        self.assertIsInstance(doc.children[0], P.CodeBlock)
        self.assertEqual(doc.children[0].text, "never closed")

    def test_pathological_input_terminates(self):
        for src in ("*" * 400, "[" * 200, "`" * 200, "> " * 200,
                    "- " * 200, "|" * 200 + "\n" + "-|" * 100):
            P.parse(src)  # must not hang or raise

    def test_samples_round_trip(self):
        from mdedit import samples

        for text in (samples.WELCOME, samples.CHEATSHEET):
            out = html_export.to_html(P.parse(text))
            self.assertIn("<body>", out)

    def test_outline(self):
        doc = P.parse("# A\n\n## B\n\n### C\n")
        self.assertEqual(P.outline(doc), [(1, "A"), (2, "B"), (3, "C")])


if __name__ == "__main__":
    unittest.main(verbosity=2)

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

    def test_html_is_escaped_when_rendering_is_off(self):
        opts = P.Options(render_html=False)
        out = html_export.to_html(P.parse("<b>x</b> & <i>y</i>", opts),
                                  standalone=False, opts=opts)
        self.assertEqual(out, "<p>&lt;b&gt;x&lt;/b&gt; &amp; &lt;i&gt;y&lt;/i&gt;</p>")

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


class TestFrontMatter(unittest.TestCase):
    def test_yaml(self):
        doc = P.parse("---\ntitle: My Note\ndraft: true\n---\n\n# Body\n")
        header = doc.children[0]
        self.assertIsInstance(header, P.FrontMatter)
        self.assertEqual(header.fmt, "yaml")
        self.assertEqual(header.pairs, [("title", "My Note"), ("draft", "true")])
        self.assertIsInstance(doc.children[1], P.Heading)

    def test_toml(self):
        header = P.parse('+++\ntitle = "Post"\n+++\n\nBody\n').children[0]
        self.assertEqual(header.fmt, "toml")
        self.assertEqual(header.pairs, [("title", "Post")])

    def test_nested_values_fold_into_their_key(self):
        header = P.parse("---\ntags:\n  - one\n  - two\n---\n").children[0]
        self.assertEqual(header.pairs, [("tags", "- one - two")])

    def test_only_at_the_top_of_the_file(self):
        doc = P.parse("# Title\n\n---\nnot: metadata\n---\n")
        self.assertNotIsInstance(doc.children[0], P.FrontMatter)
        self.assertNotIn(P.FrontMatter, [type(b) for b in doc.children])

    def test_unclosed_is_a_thematic_break(self):
        doc = P.parse("---\n\nBody\n")
        self.assertIsInstance(doc.children[0], P.ThematicBreak)

    def test_switch_off_restores_old_behaviour(self):
        doc = P.parse("---\ntitle: x\n---\n", P.Options(front_matter=False))
        self.assertIsInstance(doc.children[0], P.ThematicBreak)

    def test_hidden_for_site_generators(self):
        from mdedit import flavors

        src = "---\ntitle: x\n---\n\nBody\n"
        for key, shown in (("obsidian", True), ("jekyll", False),
                           ("hugo", False), ("github", True)):
            fl = flavors.FLAVORS[key]
            out = html_export.to_html(P.parse(src, fl.opts), standalone=False,
                                      flavor=fl, opts=fl.opts)
            self.assertEqual(shown, "frontmatter" in out, key)
            self.assertIn("Body", out)


class TestVaultAndSiteSyntax(unittest.TestCase):
    OBS = P.Options(wikilinks=True, hashtags=True, comments=True,
                    callout_titles=True)

    def test_wikilink(self):
        doc = P.parse("See [[Other Note]].", self.OBS)
        link = doc.children[0].children[1]
        self.assertIsInstance(link, P.WikiLink)
        self.assertEqual(link.target, "Other Note")
        self.assertEqual(link.display, "Other Note")

    def test_wikilink_alias_and_embed(self):
        doc = P.parse("[[Deep/Note|alias]] ![[pic.png]]", self.OBS)
        alias, embed = [n for n in doc.children[0].children
                        if isinstance(n, P.WikiLink)]
        self.assertEqual((alias.target, alias.display), ("Deep/Note", "alias"))
        self.assertTrue(embed.embed)

    def test_wikilink_becomes_a_local_md_link_in_html(self):
        out = html_export.to_html(P.parse("[[Other Note]]", self.OBS),
                                  standalone=False, opts=self.OBS)
        self.assertIn('href="Other Note.md"', out)
        self.assertIn("wikilink", out)

    def test_wikilinks_off_stay_literal(self):
        self.assertIn("[[Other Note]]", html("[[Other Note]]"))

    def test_hashtag(self):
        doc = P.parse("Tagged #project/alpha here.", self.OBS)
        tag = doc.children[0].children[1]
        self.assertIsInstance(tag, P.Tag)
        self.assertEqual(tag.name, "project/alpha")

    def test_hashtag_needs_a_boundary_and_a_letter(self):
        for src in ("c#sharp is fine", "issue #123 stays text"):
            doc = P.parse(src, self.OBS)
            kinds = [type(n) for n in doc.children[0].children]
            self.assertNotIn(P.Tag, kinds, src)

    def test_comments_are_hidden(self):
        out = html_export.to_html(P.parse("Shown %% hidden %% shown.", self.OBS),
                                  standalone=False, opts=self.OBS)
        self.assertNotIn("hidden", out)
        self.assertIn("Shown", out)

    def test_callout_with_title(self):
        panel = P.parse("> [!tip]- Fold me\n> body\n", self.OBS).children[0]
        self.assertIsInstance(panel, P.Panel)
        self.assertEqual((panel.kind, panel.title), ("tip", "Fold me"))
        self.assertEqual(P.plain_text(panel.children[0].children), "body")

    def test_github_rejects_a_title_on_the_alert_line(self):
        from mdedit import flavors

        doc = P.parse("> [!NOTE] a title\n> body\n", flavors.GITHUB.opts)
        self.assertIsInstance(doc.children[0], P.BlockQuote)

    def test_liquid_and_shortcodes(self):
        opts = P.Options(template_tags=True)
        src = "{{ page.title }} {% include a.html %} {{< figure src=\"b\" >}}"
        nodes = P.parse(src, opts).children[0].children
        marks = [n.text for n in nodes if isinstance(n, P.Template)]
        self.assertEqual(len(marks), 3)
        out = html_export.to_html(P.parse(src, opts), standalone=False, opts=opts)
        self.assertIn('class="template"', out)
        self.assertIn("&lt;", out)  # escaped, never executed

    def test_template_tags_off_stay_literal(self):
        self.assertIn("{{ page.title }}", html("{{ page.title }}"))

    def test_smart_typography(self):
        opts = P.Options(smart_typography=True)
        out = html_export.to_html(
            P.parse("\"Quote\" it's 5--10... yes --- really", opts),
            standalone=False)
        for want in ("“Quote”", "’", "5–10", "…",
                     "yes — really"):
            self.assertIn(want, out)

    def test_smart_typography_leaves_code_alone(self):
        opts = P.Options(smart_typography=True)
        out = html_export.to_html(P.parse('`a "b" -- c`', opts), standalone=False)
        self.assertIn('a &quot;b&quot; -- c', out)


class TestRawHtml(unittest.TestCase):
    def test_inline_formatting(self):
        out = html("Some <b>bold</b>, <i>it</i>, <del>gone</del>, <code>c</code>.")
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn("<em>it</em>", out)
        self.assertIn("<del>gone</del>", out)
        self.assertIn("<code>c</code>", out)

    def test_inline_anchor(self):
        out = html('An <a href="p.md" title="T">anchor</a>.')
        self.assertIn('<a href="p.md" title="T">anchor</a>', out)

    def test_markdown_inside_inline_html(self):
        self.assertIn("<em>md</em>", html("<b>*md*</b>"))

    def test_unknown_inline_tag_is_transparent(self):
        self.assertEqual(html("<foo>kept</foo>"), "<p>kept</p>")

    def test_unclosed_inline_tag_does_not_eat_text(self):
        self.assertIn("after", html("<b>after"))

    def test_span_colour(self):
        out = html('<span style="color:#c00">red</span>')
        self.assertIn("color:#c00", out)
        self.assertIn("red", out)

    def test_sup_and_sub(self):
        out = html("E=mc<sup>2</sup> and H<sub>2</sub>O")
        self.assertIn("<sup>2</sup>", out)
        self.assertIn("<sub>2</sub>", out)

    def test_kbd_becomes_code(self):
        self.assertIn("<code>Ctrl</code>", html("Press <kbd>Ctrl</kbd>"))

    def test_br_and_img(self):
        self.assertIn("<br>", html("one<br>two"))
        self.assertIn('<img src="p.png"', html('<img src="p.png" alt="a">'))

    def test_block_table_round_trips(self):
        src = ("<table>\n<tr><th>A</th><th>B</th></tr>\n"
               "<tr><td>1</td><td>2</td></tr>\n</table>")
        doc = P.parse(src)
        block = doc.children[0]
        self.assertIsInstance(block, P.HtmlBlock)
        table = block.children[0]
        self.assertIsInstance(table, P.Table)
        self.assertEqual(P.plain_text(table.header[0]), "A")
        self.assertEqual(P.plain_text(table.rows[0][1]), "2")
        self.assertIn("<table>", html_export.to_html(doc, standalone=False))

    def test_block_list_and_quote(self):
        block = P.parse("<ul>\n<li>one</li>\n<li>two</li>\n</ul>").children[0]
        lst = block.children[0]
        self.assertIsInstance(lst, P.ListBlock)
        self.assertEqual(len(lst.items), 2)
        quote = P.parse("<blockquote>\n<p>said</p>\n</blockquote>").children[0]
        self.assertIsInstance(quote.children[0], P.BlockQuote)

    def test_details_becomes_a_panel(self):
        src = "<details>\n<summary>More</summary>\n<p>Hidden</p>\n</details>"
        panel = P.parse(src).children[0].children[0]
        self.assertIsInstance(panel, P.Panel)
        self.assertEqual(panel.title, "More")

    def test_html_heading_and_pre(self):
        block = P.parse("<h2>Title</h2>").children[0]
        self.assertIsInstance(block.children[0], P.Heading)
        self.assertEqual(block.children[0].level, 2)
        code = P.parse("<pre>\nx = 1\n</pre>").children[0].children[0]
        self.assertIsInstance(code, P.CodeBlock)
        self.assertIn("x = 1", code.text)

    def test_blank_line_lets_markdown_through(self):
        doc = P.parse('<div align="center">\n\n**md**\n\n</div>')
        kinds = [type(b) for b in doc.children]
        self.assertEqual(kinds, [P.HtmlBlock, P.Paragraph, P.HtmlBlock])
        self.assertIn("<strong>md</strong>",
                      html_export.to_html(doc, standalone=False))

    def test_scripts_are_dropped_everywhere(self):
        for src in ("<script>alert(1)</script>\n\nAfter.",
                    "text <script>alert(1)</script> more",
                    "<iframe src=\"http://x\"></iframe>\n\nAfter."):
            out = html_export.to_html(P.parse(src), standalone=False)
            self.assertNotIn("script", out.lower(), src)
            self.assertNotIn("iframe", out.lower(), src)
            self.assertNotIn("alert", out, src)

    def test_event_handlers_and_js_urls_are_stripped(self):
        src = '<div onclick="evil()"><a href="javascript:x">c</a></div>'
        out = html_export.to_html(P.parse(src), standalone=False)
        self.assertNotIn("onclick", out)
        self.assertNotIn("javascript", out)

    def test_exported_page_stays_offline(self):
        src = ('<script src="https://cdn/x.js"></script>\n\n'
               '<link rel="stylesheet" href="https://cdn/x.css">\n\nBody\n')
        out = html_export.to_html(P.parse(src))
        self.assertNotIn("https://cdn", out)
        self.assertIn("Body", out)

    def test_switch_off_shows_the_markup(self):
        opts = P.Options(render_html=False)
        doc = P.parse("<table><tr><td>x</td></tr></table>", opts)
        self.assertNotIn(P.HtmlBlock, [type(b) for b in doc.children])
        out = html_export.to_html(doc, standalone=False, opts=opts)
        self.assertIn("&lt;table&gt;", out)

    def test_html_comment_is_hidden(self):
        out = html("<!-- private note -->\n\nVisible\n")
        self.assertNotIn("private", out)
        self.assertIn("Visible", out)

    def test_malformed_html_does_not_raise(self):
        for src in ("<div><p>unclosed", "</div></p>", "<table><tr><td>",
                    "<b" + "<" * 50, "<a href=" + '"' * 20):
            html_export.to_html(P.parse(src))


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
                    "link_underline", "panel_labels", "pad_x", "para_gap",
                    "show_front_matter", "quote_italic")
        for key in flavors.ORDER:
            metrics = flavors.FLAVORS[key].metrics
            for name in required:
                self.assertIn(name, metrics, f"{key} is missing {name}")

    def test_panel_labels_match_between_preview_and_export(self):
        from mdedit import flavors

        for key in flavors.ORDER:
            fl = flavors.FLAVORS[key]
            if not fl.opts.alerts:
                continue  # this mode has no call-out syntax to label
            src = "> [!NOTE]\n> x\n"
            out = html_export.to_html(P.parse(src, fl.opts),
                                      standalone=False, flavor=fl)
            self.assertEqual(fl.metric("panel_labels"),
                             "panel-title" in out, key)

    def test_modes_without_alerts_keep_the_quote(self):
        from mdedit import flavors

        for key in flavors.ORDER:
            fl = flavors.FLAVORS[key]
            if fl.opts.alerts:
                continue
            doc = P.parse("> [!NOTE]\n> x\n", fl.opts)
            self.assertIsInstance(doc.children[0], P.BlockQuote, key)

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

    def test_table_styles_are_known_and_complete(self):
        """Every mode names a style the renderer can actually unpack."""
        from mdedit import flavors, tkrender

        for key in flavors.ORDER:
            style = flavors.FLAVORS[key].metric("table_style")
            self.assertIn(style, tkrender._TABLE_STYLES, key)
        for name, spec in tkrender._TABLE_STYLES.items():
            self.assertEqual(4, len(spec), name)

    def test_chrome_does_not_know_front_matter(self):
        """A browser has no idea what a --- header is, so it shows one."""
        from mdedit import flavors

        doc = P.parse("---\ntitle: x\n---\n\nBody\n", flavors.CHROME.opts)
        self.assertIsInstance(doc.children[0], P.ThematicBreak)
        self.assertIsInstance(doc.children[1], P.Heading)
        out = html_export.to_html(doc, standalone=False,
                                  flavor=flavors.CHROME, opts=flavors.CHROME.opts)
        self.assertNotIn("frontmatter", out)
        self.assertIn("title: x", out)

    def test_chrome_is_plain_gfm(self):
        """marked has no alerts, containers, marks or smart quotes."""
        from mdedit import flavors

        src = ('> [!NOTE]\n> a\n\n::: note\nb\n:::\n\n==c== and "d" -- e\n\n'
               "| x | y |\n|:--|--:|\n| 1 | 2 |\n")
        out = html_export.to_html(P.parse(src, flavors.CHROME.opts),
                                  standalone=False, flavor=flavors.CHROME)
        for absent in ('class="panel', "<mark>", "“", "–"):
            self.assertNotIn(absent, out)
        self.assertIn("&quot;d&quot;", out)  # quotes stay straight
        self.assertIn("==c==", out)
        self.assertIn("<blockquote>", out)
        self.assertIn("<table>", out)


class TestMermaid(unittest.TestCase):
    """The fence-level side of it; ``test_mermaid.py`` covers the drawing."""

    FENCE = "```mermaid\nflowchart TD\n  A[Start] --> B[End]\n```\n"

    def test_fence_becomes_a_diagram(self):
        node = P.parse(self.FENCE).children[0]
        self.assertIsInstance(node, P.Diagram)
        self.assertEqual(node.kind, "flowchart")
        self.assertIn("flowchart TD", node.source)

    def test_a_front_matter_prelude_is_skipped(self):
        # Mermaid takes a YAML block of its own before the diagram.
        src = ("```mermaid\n---\ntitle: Pipeline\n---\n"
               "flowchart TD\n  A[Start] --> B[End]\n```\n")
        node = P.parse(src).children[0]
        self.assertIsInstance(node, P.Diagram)
        self.assertEqual(node.kind, "flowchart")

    def test_a_prelude_may_close_with_dots(self):
        src = ("```mermaid\n---\nconfig:\n  theme: dark\n...\n"
               "flowchart TD\n  A --> B\n```\n")
        self.assertIsInstance(P.parse(src).children[0], P.Diagram)

    def test_an_unclosed_prelude_is_left_alone(self):
        # Not a prelude, then -- and without a header line it is not a
        # diagram either, so the source stands.
        src = "```mermaid\n---\ntitle: Pipeline\n```\n"
        self.assertIsInstance(P.parse(src).children[0], P.CodeBlock)

    def test_a_prelude_and_nothing_else_is_not_a_diagram(self):
        src = "```mermaid\n---\ntitle: Empty\n---\n```\n"
        self.assertIsInstance(P.parse(src).children[0], P.CodeBlock)
    def test_unreadable_diagram_stays_a_code_block(self):
        node = P.parse("```mermaid\ngantt\n  title Roadmap\n```\n").children[0]
        self.assertIsInstance(node, P.CodeBlock)
        self.assertEqual(node.lang, "mermaid")

    def test_other_languages_are_untouched(self):
        node = P.parse("```python\nflowchart = 1\n```\n").children[0]
        self.assertIsInstance(node, P.CodeBlock)

    def test_feature_off_keeps_the_source(self):
        opts = P.with_overrides(P.DEFAULT, {"mermaid": False})
        node = P.parse(self.FENCE, opts).children[0]
        self.assertIsInstance(node, P.CodeBlock)
        self.assertEqual(node.lang, "mermaid")

    def test_export_writes_inline_svg(self):
        out = html(self.FENCE)
        self.assertIn('<figure class="mermaid">', out)
        self.assertEqual(out.count("<svg"), 2)      # one light, one dark
        self.assertIn('class="on-light"', out)
        self.assertIn('class="on-dark"', out)
        self.assertNotIn("<pre>", out)

    def test_export_with_the_feature_off(self):
        opts = P.with_overrides(P.DEFAULT, {"mermaid": False})
        out = html_export.to_html(P.parse(self.FENCE, opts), standalone=False,
                                  opts=opts)
        self.assertIn('<code class="language-mermaid">', out)
        self.assertNotIn("<svg", out)

    def test_flavor_dialects(self):
        from mdedit import flavors

        for key, drawn in (("mdedit", True), ("github", True),
                           ("obsidian", True), ("confluence", False),
                           ("vs", False), ("jekyll", False), ("hugo", False),
                           ("chrome", False)):
            fl = flavors.get(key)
            node = P.parse(self.FENCE, fl.opts).children[0]
            self.assertIsInstance(node, P.Diagram if drawn else P.CodeBlock, key)

    def test_exported_page_stays_offline(self):
        page = html_export.to_html(P.parse(self.FENCE))
        self.assertNotIn("<script", page)
        self.assertNotIn("mermaid.js", page)
        self.assertEqual(page.count("http"), 2)     # the two svg namespaces


class TestDiagramFiles(unittest.TestCase):
    """A ``.mermaid`` file is one diagram, with no fence around it."""

    SOURCE = "flowchart TD" + chr(10) + "  A[Start] --> B[End]" + chr(10)

    def test_the_suffix_is_recognised(self):
        for name in ("graph.mermaid", "GRAPH.MERMAID",
                     "a/b/c.Mermaid", ".mermaid"):
            self.assertTrue(P.is_diagram_file(name), name)

    def test_other_names_are_markdown(self):
        for name in ("notes.md", "mermaid.md", "graph.mermaid.md",
                     "graph.mmd", "graph", "graph.txt"):
            self.assertFalse(P.is_diagram_file(name), name)

    def test_bare_source_parses_as_a_diagram(self):
        node = P.parse(P.as_diagram(self.SOURCE)).children[0]
        self.assertIsInstance(node, P.Diagram)
        self.assertEqual(node.kind, "flowchart")

    def test_blank_lines_around_it_do_not_matter(self):
        padded = chr(10) * 2 + self.SOURCE + chr(10) * 3
        node = P.parse(P.as_diagram(padded)).children[0]
        self.assertIsInstance(node, P.Diagram)

    def test_without_the_fence_it_is_only_text(self):
        # What the file holds is not Markdown, which is the whole reason
        # the fence has to be put back before parsing.
        node = P.parse(self.SOURCE).children[0]
        self.assertNotIsInstance(node, P.Diagram)

    def test_a_byte_order_mark_does_not_hide_the_diagram(self):
        import contextlib
        import io as _io
        import shutil
        import tempfile

        folder = tempfile.mkdtemp()
        try:
            src = os.path.join(folder, "graph.mermaid")
            out = os.path.join(folder, "graph.html")
            # What a Windows editor leaves at the front of a file.
            with open(src, "w", encoding="utf-8-sig") as fh:
                fh.write(self.SOURCE)
            from mdedit import cli
            with contextlib.redirect_stdout(_io.StringIO()):
                self.assertEqual(cli.main(["--export", src, out]), 0)
            with open(out, encoding="utf-8") as fh:
                page = fh.read()
            self.assertIn("<svg", page)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    def test_a_diagram_file_exports_as_svg(self):
        import shutil
        import tempfile

        folder = tempfile.mkdtemp()
        try:
            src = os.path.join(folder, "graph.mermaid")
            out = os.path.join(folder, "graph.html")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(self.SOURCE)
            from mdedit import cli
            import contextlib
            import io as _io
            with contextlib.redirect_stdout(_io.StringIO()):
                self.assertEqual(cli.main(["--export", src, out]), 0)
            with open(out, encoding="utf-8") as fh:
                page = fh.read()
            self.assertIn("<svg", page)
            self.assertNotIn("<pre>", page)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

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

        for text in (samples.WELCOME, samples.CHEATSHEET, samples.EMULATION):
            out = html_export.to_html(P.parse(text))
            self.assertIn("<body>", out)

    def test_outline(self):
        doc = P.parse("# A\n\n## B\n\n### C\n")
        self.assertEqual(P.outline(doc), [(1, "A"), (2, "B"), (3, "C")])


if __name__ == "__main__":
    unittest.main(verbosity=2)

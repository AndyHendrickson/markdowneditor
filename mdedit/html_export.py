"""Render the document tree to a standalone HTML file.

The generated page embeds its own CSS -- picked from the active emulation
flavour -- and references no external resource, so it opens correctly with no
network connection.

Feature switches (:class:`parser.Options`) that survive parsing are honoured
here too: with images off, an image is written as its alt text.
"""

from __future__ import annotations

import html
import os
import re
from typing import List

from . import diagram, flavors, htmlparse
from . import parser as P

_SLUG_RE = re.compile(r"[^a-z0-9\- ]")


def to_html(doc: P.Document, title: str = "", standalone: bool = True,
            flavor=None, opts: P.Options = None) -> str:
    """Render *doc*.  With ``standalone`` false, only the body markup."""
    w = _Writer(_flavor(flavor), opts or P.DEFAULT)
    body = w.document(doc)
    if not standalone:
        return body
    heading = title or _first_heading(doc) or "Markdown"
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(heading)}</title>\n"
        f"<!-- rendered by mdedit, {w.fl.name} emulation -->\n"
        f"<style>{w.fl.css()}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def _flavor(flavor) -> flavors.Flavor:
    if flavor is None:
        return flavors.DEFAULT
    if isinstance(flavor, str):
        return flavors.get(flavor)
    return flavor


def _first_heading(doc: P.Document) -> str:
    for b in doc.children:
        if isinstance(b, P.Heading):
            return P.plain_text(b.children)
    return ""


def _slug(text: str) -> str:
    return _SLUG_RE.sub("", text.lower()).strip().replace(" ", "-")


class _Writer:
    """Turns nodes into markup for one flavour and one set of features."""

    def __init__(self, fl: flavors.Flavor, opts: P.Options):
        self.fl = fl
        self.opts = opts

    def document(self, doc: P.Document) -> str:
        return "\n".join(self.block(b) for b in doc.children)

    def block(self, node) -> str:
        if isinstance(node, P.Heading):
            inner = self.inlines(node.children)
            anchor = _slug(P.plain_text(node.children))
            attr = f' id="{html.escape(anchor)}"' if anchor else ""
            return f"<h{node.level}{attr}>{inner}</h{node.level}>"

        if isinstance(node, P.Paragraph):
            return f"<p>{self.inlines(node.children)}</p>"

        if isinstance(node, P.CodeBlock):
            return self.code_block(node)

        if isinstance(node, P.Diagram):
            return self.diagram(node)

        if isinstance(node, P.BlockQuote):
            inner = "\n".join(self.block(c) for c in node.children)
            return f"<blockquote>\n{inner}\n</blockquote>"

        if isinstance(node, P.Panel):
            return self.panel(node)

        if isinstance(node, P.FrontMatter):
            return self.front_matter(node)

        if isinstance(node, P.HtmlBlock):
            # Pass the author's own markup through, minus anything that could
            # fetch or run; the page has to keep working offline.
            return htmlparse.sanitize(node.raw)

        if isinstance(node, P.ThematicBreak):
            return "<hr>"

        if isinstance(node, P.ListBlock):
            tag = "ol" if node.ordered else "ul"
            start = (f' start="{node.start}"'
                     if node.ordered and node.start != 1 else "")
            items = "\n".join(self.list_item(it, node.tight) for it in node.items)
            return f"<{tag}{start}>\n{items}\n</{tag}>"

        if isinstance(node, P.Table):
            return self.table(node)

        return ""

    def code_block(self, node: P.CodeBlock) -> str:
        cls = f' class="language-{html.escape(node.lang)}"' if node.lang else ""
        return f"<pre><code{cls}>{html.escape(node.text)}</code></pre>"

    def diagram(self, node: P.Diagram) -> str:
        """A mermaid diagram, drawn twice: once light, once dark.

        The picture is inline SVG with its colours baked in, so the page
        carries one of each and lets the reader's own colour scheme pick.
        Nothing is fetched and no script runs -- there is no mermaid here,
        only the shapes it would have drawn.
        """
        if not self.opts.mermaid:
            return self.code_block(P.CodeBlock(text=node.source, lang="mermaid"))
        drawn = []
        for mode in ("light", "dark"):
            scene = diagram.render(node.model, diagram.style_for(mode))
            if scene is None:
                return self.code_block(
                    P.CodeBlock(text=node.source, lang="mermaid"))
            svg = diagram.to_svg(scene, f"{node.kind} diagram")
            drawn.append(f'<span class="on-{mode}">{svg}</span>')
        return f'<figure class="mermaid">{"".join(drawn)}</figure>'

    def panel(self, node: P.Panel) -> str:
        kind = node.kind if node.kind in flavors.PANEL_LABELS else "note"
        inner = "\n".join(self.block(c) for c in node.children)
        title = node.title
        if not title and self.fl.metric("panel_labels", True):
            title = flavors.PANEL_LABELS[kind]
        head = ""
        if title:
            icon = flavors.PANEL_ICONS[kind]
            head = f'<p class="panel-title">{icon} {html.escape(title)}</p>\n'
        return f'<div class="panel panel-{kind}">\n{head}{inner}\n</div>'

    def front_matter(self, node: P.FrontMatter) -> str:
        """Metadata: a small table, or nothing at all for site generators."""
        if not self.fl.metric("show_front_matter", True) or not node.pairs:
            return ""
        rows = []
        for key, value in node.pairs:
            cells = (f"<th>{html.escape(key)}</th>" if key else "<th></th>")
            rows.append(f"<tr>{cells}<td>{html.escape(value)}</td></tr>")
        return '<table class="frontmatter">\n' + "\n".join(rows) + "\n</table>"

    def list_item(self, item: P.ListItem, tight: bool) -> str:
        parts = []
        for child in item.children:
            if tight and isinstance(child, P.Paragraph):
                parts.append(self.inlines(child.children))
            else:
                parts.append(self.block(child))
        body = "\n".join(p for p in parts if p)
        if item.task is None:
            return f"<li>{body}</li>"
        checked = " checked" if item.task else ""
        return (
            f'<li class="task"><input type="checkbox" disabled{checked}> {body}</li>'
        )

    def table(self, node: P.Table) -> str:
        out = ["<table>", "<thead>", "<tr>"]
        for cell, align in zip(node.header, node.aligns):
            out.append(f'<th style="text-align:{align}">{self.inlines(cell)}</th>')
        out += ["</tr>", "</thead>", "<tbody>"]
        for row in node.rows:
            out.append("<tr>")
            for cell, align in zip(row, node.aligns):
                out.append(
                    f'<td style="text-align:{align}">{self.inlines(cell)}</td>')
            out.append("</tr>")
        out += ["</tbody>", "</table>"]
        return "\n".join(out)

    def inlines(self, nodes: List[object]) -> str:
        out = []
        for node in nodes:
            if isinstance(node, P.Text):
                out.append(html.escape(node.text))
            elif isinstance(node, P.Code):
                out.append(f"<code>{html.escape(node.text)}</code>")
            elif isinstance(node, P.Emph):
                out.append(f"<em>{self.inlines(node.children)}</em>")
            elif isinstance(node, P.Strong):
                out.append(f"<strong>{self.inlines(node.children)}</strong>")
            elif isinstance(node, P.Strike):
                out.append(f"<del>{self.inlines(node.children)}</del>")
            elif isinstance(node, P.Mark):
                out.append(f"<mark>{self.inlines(node.children)}</mark>")
            elif isinstance(node, P.Styled):
                out.append(self.styled(node))
            elif isinstance(node, P.Link):
                title = f' title="{html.escape(node.title)}"' if node.title else ""
                href = html.escape(node.href, quote=True)
                out.append(
                    f'<a href="{href}"{title}>{self.inlines(node.children)}</a>')
            elif isinstance(node, P.Image):
                out.append(self.image(node))
            elif isinstance(node, P.WikiLink):
                out.append(self.wikilink(node))
            elif isinstance(node, P.Tag):
                out.append(f'<span class="tag">#{html.escape(node.name)}</span>')
            elif isinstance(node, P.Template):
                out.append(
                    f'<code class="template">{html.escape(node.text)}</code>')
            elif isinstance(node, P.HardBreak):
                out.append("<br>\n")
            elif isinstance(node, P.SoftBreak):
                out.append("\n")
        return "".join(out)

    def styled(self, node: P.Styled) -> str:
        inner = self.inlines(node.children)
        if node.variant in ("sup", "sub", "u"):
            return f"<{node.variant}>{inner}</{node.variant}>"
        css = []
        if node.color:
            css.append(f"color:{node.color}")
        if node.background:
            css.append(f"background:{node.background}")
        if not css:
            return inner
        return f'<span style="{html.escape(";".join(css), quote=True)}">{inner}</span>'

    def wikilink(self, node: P.WikiLink) -> str:
        target = node.target.split("#")[0].split("^")[0].strip() or node.target
        ext = os.path.splitext(target)[1]
        if node.embed and ext.lower() in (".png", ".gif", ".jpg", ".jpeg",
                                          ".svg", ".webp"):
            return self.image(P.Image(alt=node.display, src=target))
        href = html.escape(target if ext else target + ".md", quote=True)
        label = html.escape(node.display)
        mark = "⧉ " if node.embed else ""
        return f'<a class="wikilink" href="{href}">{mark}{label}</a>'

    def image(self, node: P.Image) -> str:
        if not self.opts.images:
            label = node.alt or node.src or "image"
            return f'<span class="noimg">\U0001f5bc {html.escape(label)}</span>'
        title = f' title="{html.escape(node.title)}"' if node.title else ""
        return (
            f'<img src="{html.escape(node.src, quote=True)}" '
            f'alt="{html.escape(node.alt, quote=True)}"{title}>'
        )

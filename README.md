# mdedit

A Markdown editor with a live rendered preview, written in pure Python.

No third-party packages, no build step, and no network access of any kind:
the parser, the renderer and the HTML exporter are all hand-written on top of
the standard library. The only files it touches are the ones you open.

```
python mdedit.py            # open the editor
python mdedit.py notes.md   # open a file
```

Requires Python 3.9+ with tkinter (bundled with the python.org and Windows
installers).

## Emulation modes

The **Emulate** menu (or `Ctrl+E`) switches how a document is read *and*
shown. A mode changes three things together: the **dialect** that is parsed,
the **styling** of the preview, and the **CSS** written by *Export HTML*.

| | Dialect | Look |
|:--|:--|:--|
| **mdedit** | every extension on | tinted quotes, header rule, filled code |
| **GitHub** | GFM: no `==mark==`, no `:::` containers, `> [!NOTE]` alerts | rules under H1-H2, left-bar quotes, zebra tables |
| **Confluence** | single newlines break the line, `> **Note:**` and `:::` become panels | Atlassian palette, small headings, full-grid tables, bordered code |
| **Visual Studio** | Markdig: `==mark==` and `:::` containers | IDE colours (light and dark), row-line tables, bordered code |
| **Obsidian** | `[[wiki links]]`, `#tags`, `%%comments%%`, `> [!note]` callouts *with titles*, single newlines break | default-theme purple, front matter shown as properties, grid tables |
| **Jekyll** | kramdown + GFM: single newlines break, quotes curl, `{{ liquid }}` markers | Minima: `#2a7ae2` links, italic quotes, lavender code, zebra tables |
| **Hugo** | Goldmark: typographer on, `{{< shortcodes >}}`, `+++` TOML front matter, no call-out syntax | Hugo pink accent, rule under H1, row-line tables, bordered code |

Front matter is understood by every mode — Obsidian shows it as properties,
GitHub renders it as a table, Jekyll and Hugo strip it from the page.

Per-mode dialect switches (the notable ones; `--list-features --flavor X`
prints the lot):

| Feature | mdedit | GitHub | Confl. | VS | Obsidian | Jekyll | Hugo |
|:--|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Tables, task lists, `~~strike~~`, bare URLs | on | on | on | on | on | on | on |
| Single newline breaks the line | off | off | **on** | off | **on** | **on** | off |
| `==highlight==` | on | off | off | **on** | **on** | off | off |
| `::: note` containers | on | off | on | on | off | off | off |
| `> [!NOTE]` alerts | on | on | on | on | on | off | off |
| Call-out titles after the marker | off | off | off | off | **on** | off | off |
| `> **Note:**` panels | off | off | **on** | off | off | off | off |
| `[[Wiki links]]`, `#tags`, `%%comments%%` | off | off | off | off | **on** | off | off |
| `{{ template }}` markers | off | off | off | off | off | **on** | **on** |
| Smart typography | off | off | off | off | off | **on** | **on** |

*Emulate > What this mode changes...* lists the same table for the current
mode; *Emulation demo document* opens a sample that exercises all of it.
These are careful approximations of each platform's presentation, not
pixel-exact clones — and fonts fall back to whatever the machine has.
Template tags are only ever *shown*, never executed.

## Choosing what to render

*Emulate > Rendering features...* (`Ctrl+R`) opens a dialog with a tick box
per feature. Untick one — tables, say — and its markup stays plain text in
the preview and in exported HTML, immediately. Each row shows the feature's
current state and, when you have changed it, what the mode would have done.

A box left matching the mode is not remembered, so it keeps following the
mode; one you change becomes an override that survives switching modes until
*Reset*. Overrides are saved in `~/.mdedit.json` and shown in the status bar.

The same switches exist as CLI flags — `--tables` / `--no-tables`,
`--images` / `--no-images` and so on, one pair per feature:

```
python -m mdedit --export notes.md --no-tables --no-images
python mdedit.py notes.md --flavor github --no-autolinks
python -m mdedit --list-features [--flavor confluence]
```

Flags beat the mode; anything you leave out follows it. The full list, in the
three groups the dialog uses:

- **Structure** — `--tables`, `--task-lists`, `--images`, `--front-matter`,
  `--hard-breaks`
- **Inline** — `--strikethrough`, `--autolinks`, `--highlight`,
  `--smart-typography`, `--wikilinks`, `--hashtags`, `--template-tags`,
  `--comments`
- **Call-outs** — `--containers`, `--alerts`, `--callout-titles`, `--panels`

## Features

**Editing**

- Split view: source on the left, formatted preview on the right, updating
  as you type.
- Line-number gutter, soft wrap, undo/redo, find & replace with case and
  regular-expression options.
- Formatting shortcuts that wrap the selection or toggle the line prefix:
  bold, italic, code, strikethrough, headings 1-6, bullet / numbered / task
  lists, block quotes.
- Insert helpers for links, local images, code blocks, tables, rules and a
  generated table of contents.
- Lists, quotes and indentation continue automatically when you press Enter;
  an empty list item ends the list.
- Document outline sidebar; clicking a heading jumps to it.
- Light and dark themes, adjustable text size, three layouts (split, editor
  only, preview only), synchronised scrolling. Preferences persist in
  `~/.mdedit.json`.

**Rendering**

Headings (ATX and setext), paragraphs with soft and hard breaks, fenced and
indented code blocks, nested block quotes, nested ordered/unordered/task
lists, thematic breaks, pipe tables with per-column alignment, YAML and TOML
front matter, call-out panels, emphasis, strong, strikethrough, highlight,
code spans, links, autolinks, wiki links, tags, template markers, local
images (PNG/GIF), backslash escapes and HTML entities.

Clicking a link in the preview that points at a local Markdown file opens
that file — a `[[wiki link]]` resolves the same way, to a note in the same
folder. External links are never fetched; the URL is copied to the clipboard
instead. `#anchor` links jump to the matching heading.

**Export**

`File > Export HTML...` writes a standalone page with its own embedded CSS
(light and dark aware) and no external references, so it renders correctly
offline.

## Command line

```
python mdedit.py                          open the editor
python mdedit.py notes.md                 open the editor on a file
python mdedit.py notes.md --flavor obsidian   open in an emulation mode
python mdedit.py notes.md --no-tables     open with a feature switched off
python -m mdedit --export notes.md [out.html] [--flavor hugo]
python -m mdedit --outline notes.md       print the heading outline
python -m mdedit --list-flavors           show the emulation modes
python -m mdedit --list-features          show the feature flags
```

## Keys

| Key | Action | Key | Action |
|:----|:-------|:----|:-------|
| `Ctrl+N` / `O` / `S` | New / open / save | `Ctrl+B` / `I` | Bold / italic |
| `Ctrl+Shift+S` | Save as | ``Ctrl+` `` | Inline code |
| `Ctrl+F` | Find & replace | `Ctrl+K` | Link |
| `Ctrl+1`…`6` | Heading level | `Esc` | Close the find bar |
| `Ctrl+P` | Cycle layout | `Ctrl+E` | Next emulation mode |
| `Ctrl+R` | Rendering features | `Ctrl+D` | Toggle dark theme |
| `Ctrl+Z` / `Y` | Undo / redo | `Tab` / `Shift+Tab` | Indent / outdent |
| `Ctrl+=` / `-` | Text bigger / smaller | `F1` | Markdown cheat sheet |

## Layout

```
mdedit.py              launcher
mdedit/
  parser.py            Markdown source -> document tree
  flavors.py           emulation modes: dialect + palette + CSS
  tkrender.py          document tree -> styled tkinter Text
  html_export.py       document tree -> standalone HTML
  app.py               the editor window
  cli.py               argument handling
  samples.py           welcome doc, cheat sheet, emulation demo
tests/test_parser.py   parser / exporter tests
```

`parser.py` is independent of tkinter, so it can be used on its own:

```python
from mdedit import flavors, parser, html_export

fl = flavors.get("confluence")
opts = parser.with_overrides(fl.opts, {"tables": False})
doc = parser.parse(open("notes.md", encoding="utf-8").read(), opts)
print(parser.outline(doc))
print(html_export.to_html(doc, flavor=fl, opts=opts))
```

## Tests

```
python -m unittest discover -s tests
```

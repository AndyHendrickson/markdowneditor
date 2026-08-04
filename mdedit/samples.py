"""Built-in documents: the welcome page and the syntax cheat sheet."""

WELCOME = """\
# Welcome to mdedit

A **Markdown editor** written in *pure Python* — standard library only, and it
never touches the network.

Type in the left pane; the preview on the right refreshes as you go.

## What it understands

### Text

Emphasis with `*stars*`, strong with `**double stars**`, both with
***three***, ~~strikethrough~~ with double tildes, and `inline code`
with backticks.  Escapes work too: \\*not italic\\*.

Two spaces at the end of a line
force a hard break.

### Lists

- Unordered items
- Nested ones:
  - second level
    - third level
- Back to the top level

1. Ordered items
2. Count on their own
3. And can nest as well

- [x] Task lists render as checkboxes
- [ ] Unchecked items too

### Quotes

> Block quotes stack up.
>
> > Including nested ones.

### Code

```python
def fib(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
```

### Tables

| Feature      | Status | Notes                |
|:-------------|:------:|---------------------:|
| Headings     |   ok   | six levels           |
| Tables       |   ok   | alignment honoured   |
| Images       |   ok   | local PNG/GIF        |

### Links

[Links are styled](./somewhere.md) and clicking one that points at a local
Markdown file opens it right here.

### Call-outs and emulation

> [!NOTE]
> GitHub-style alerts render as call-outs.

::: tip Markdig containers
Visual Studio mode understands `::: tip` blocks and ==highlighted text==.
:::

> **Warning:** in Confluence mode a labelled quote becomes a panel, and
> single newlines
> break the line.

Pick a mode from the **Emulate** menu (or press `Ctrl+E`) to see the same
document the way GitHub, Confluence or Visual Studio would show it.

---

## Handy keys

| Key            | Does                         |
|----------------|------------------------------|
| `Ctrl+S`       | Save                         |
| `Ctrl+O`       | Open                         |
| `Ctrl+B`/`I`   | Bold / italic the selection  |
| `Ctrl+K`       | Wrap the selection in a link |
| `Ctrl+F`       | Find and replace             |
| `Ctrl+P`       | Cycle the layout             |
| `Ctrl+D`       | Toggle the dark theme        |
| `Ctrl+=`/`-`   | Preview text bigger/smaller  |

Delete all of this and start writing.
"""

EMULATION = """\
---
title: Emulation modes
tags: [demo, markdown]
---

# Emulation modes

The same source, shown the way a given platform would show it. Switch with
the **Emulate** menu or `Ctrl+E`; the mode changes three things at once: the
**dialect** that is parsed, the **styling** of the preview, and the **CSS**
used by *File > Export HTML*.

That block at the top is front matter. Obsidian shows it as properties,
GitHub renders it as a table, Jekyll and Hugo strip it from the page.

| Feature                    | mdedit | GitHub | Confl. | VS  | Obsidian | Jekyll | Hugo |
|:---------------------------|:------:|:------:|:------:|:---:|:--------:|:------:|:----:|
| Pipe tables, task lists    |   on   |   on   |   on   | on  |    on    |   on   |  on  |
| Bare URLs linkified        |   on   |   on   |   on   | on  |    on    |   on   |  on  |
| Single newline breaks line |  off   |  off   |   on   | off |    on    |   on   | off  |
| `==highlight==`            |   on   |  off   |  off   | on  |    on    |  off   | off  |
| `::: note` containers      |   on   |  off   |   on   | on  |   off    |  off   | off  |
| `> [!NOTE]` alerts         |   on   |   on   |   on   | on  |    on    |  off   | off  |
| Call-out titles            |  off   |  off   |  off   | off |    on    |  off   | off  |
| `> **Note:**` panels       |  off   |  off   |   on   | off |   off    |  off   | off  |
| `[[Wiki links]]`, `#tags`  |  off   |  off   |  off   | off |    on    |  off   | off  |
| Template tags              |  off   |  off   |  off   | off |   off    |   on   |  on  |
| Smart typography           |  off   |  off   |  off   | off |   off    |   on   |  on  |

Any of these can be switched off on its own: *Emulate > Rendering features...*
(`Ctrl+R`), or `--no-tables`, `--no-images` and friends on the command line.
A feature that is off keeps its markup as plain text.

## Vault and site syntax

[[Another Note]] and [[Deep/Note|an alias]] are wiki links -- live in
Obsidian mode, literal everywhere else. So is a #tag in running text, and
%%this comment%% which only Obsidian hides.

Template markers stay markers, never run: {{ page.title }} is Liquid and
{{< figure src="x.png" >}} is a Hugo shortcode. Jekyll and Hugo modes set
them apart from the prose; the rest show the braces as written.

Typographer modes curl "quotes", turn -- into a dash and ... into an
ellipsis. Compare this line across Hugo and GitHub.

> [!tip]- A callout with a title
> Obsidian keeps the title after the marker and understands the fold
> character. GitHub wants the marker alone on its line, so in GitHub mode
> this stays an ordinary quote.

## Call-outs

Three ways to write one; which are recognised depends on the mode.

> [!WARNING]
> GitHub alerts. Recognised everywhere, drawn in the mode's own colours.

::: info Container
Markdig and pandoc style. Off in GitHub mode, where it stays literal text.
:::

> **Tip:** a labelled quote. Only Confluence mode turns this into a panel;
> everywhere else it stays an ordinary block quote.

## Line breaks

This paragraph has
a single newline in it.
Confluence mode breaks the lines; the others join them into one paragraph,
which is what CommonMark says to do.

## Highlighting

Text can be ==marked== -- a Markdig extension, so it renders in mdedit and
Visual Studio modes and stays literal in the others.

## Styling

| Mode          | Headings          | Quotes        | Tables         | Code      |
|:--------------|:------------------|:--------------|:---------------|:----------|
| mdedit        | rules under 1-2   | tinted block  | header rule    | filled    |
| GitHub        | rules under 1-2   | left bar      | zebra stripes  | filled    |
| Confluence    | no rules, smaller | panel         | full grid      | bordered  |
| Visual Studio | rule under 1      | left bar      | row lines only | bordered  |
| Obsidian      | no rules          | left bar      | full grid      | filled    |
| Jekyll        | no rules          | italic, bar   | zebra stripes  | filled    |
| Hugo          | rule under 1      | pink bar      | row lines only | bordered  |

Fonts, colours and spacing follow the same mode, in both the light and dark
themes -- and so does the stylesheet embedded in exported HTML.
"""

CHEATSHEET = """\
# Markdown cheat sheet

## Headings

    # H1
    ## H2
    ### H3 ... up to ###### H6

    Setext style
    ============

## Inline

| Write               | Get                    |
|---------------------|------------------------|
| `*italic*`          | *italic*               |
| `**bold**`          | **bold**               |
| `***both***`        | ***both***             |
| `~~struck~~`        | ~~struck~~             |
| `` `code` ``        | `code`                 |
| `[text](url)`       | [text](url)            |
| `![alt](image.png)` | an image               |
| `<https://a.b>`     | an autolink            |

End a line with two spaces for a hard break, or use a backslash.

## Blocks

    > a quote
    >> nested

    - bullet          1. numbered
    - bullet          2. numbered
      - nested          1. nested

    - [ ] todo
    - [x] done

    ---   (or *** or ___)  horizontal rule

Fenced code, with an optional language tag:

    ```python
    print("hello")
    ```

Indent four spaces for a code block without a fence.

## Tables

    | Left | Center | Right |
    |:-----|:------:|------:|
    | a    |   b    |     c |

The colons in the divider row set each column's alignment.

## Escapes

Put a backslash before any of ``\\ ` * _ { } [ ] ( ) # + - . ! |`` to show it
literally.
"""

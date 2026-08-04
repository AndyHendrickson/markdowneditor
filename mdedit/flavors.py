"""Emulation modes -- "flavours".

A flavour bundles three things:

* a **dialect** (:class:`parser.Options`): which Markdown extensions the
  target platform actually understands;
* a **palette** for light and dark preview;
* **metrics**: fonts, heading scale, and how quotes, tables and code blocks
  are drawn, plus the matching CSS used by the HTML exporter.

These are careful approximations of how each platform presents Markdown, not
pixel-exact clones -- and the fonts fall back to whatever the machine has.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .parser import Options

# --------------------------------------------------------------------------
# Call-out colours, shared unless a flavour overrides them
# --------------------------------------------------------------------------

PANELS_LIGHT = {
    "note": ("#f2f4f8", "#8b98a8"),
    "info": ("#e8f0fd", "#2f7bd8"),
    "tip": ("#e8f6ee", "#2da26a"),
    "success": ("#e8f6ee", "#2da26a"),
    "warning": ("#fdf3e2", "#d99013"),
    "danger": ("#fdecec", "#d63c3c"),
}

PANELS_DARK = {
    "note": ("#1b2029", "#6b7684"),
    "info": ("#12233b", "#4a91e2"),
    "tip": ("#122a20", "#3fa676"),
    "success": ("#122a20", "#3fa676"),
    "warning": ("#2b2415", "#d09b2c"),
    "danger": ("#2e1a1a", "#e05252"),
}

PANEL_ICONS = {
    "note": "✎", "info": "ℹ", "tip": "✦",
    "success": "✓", "warning": "⚠", "danger": "✖",
}

PANEL_LABELS = {
    "note": "Note", "info": "Info", "tip": "Tip",
    "success": "Success", "warning": "Warning", "danger": "Caution",
}


@dataclass(frozen=True)
class Flavor:
    key: str
    name: str
    blurb: str
    opts: Options
    light: Dict[str, object]
    dark: Dict[str, object]
    metrics: Dict[str, object]
    css_vars: str = ""

    def palette(self, mode: str) -> Dict[str, object]:
        return self.dark if mode == "dark" else self.light

    def metric(self, key: str, default=None):
        return self.metrics.get(key, default)

    def css(self) -> str:
        return BASE_CSS + self.css_vars


# --------------------------------------------------------------------------
# mdedit's own look: the default
# --------------------------------------------------------------------------

MDEDIT = Flavor(
    key="mdedit",
    name="mdedit",
    blurb="mdedit's own styling; every extension switched on.",
    opts=Options(),
    light={
        "bg": "#ffffff", "fg": "#24292f", "muted": "#57606a",
        "link": "#0969da", "code_bg": "#eff1f3", "code_fg": "#8250df",
        "block_bg": "#f6f8fa", "quote_bg": "#f3f5f7", "quote_fg": "#4a5460",
        "rule": "#d8dee4", "table_head": "#eceff2", "zebra": "#fafbfc",
        "mark_bg": "#fff3b0", "panels": PANELS_LIGHT,
    },
    dark={
        "bg": "#0d1117", "fg": "#e6edf3", "muted": "#9198a1",
        "link": "#6cb0f8", "code_bg": "#262c36", "code_fg": "#d2a8ff",
        "block_bg": "#161b22", "quote_bg": "#151b23", "quote_fg": "#b3bcc6",
        "rule": "#30363d", "table_head": "#1c222b", "zebra": "#11161d",
        "mark_bg": "#6b5300", "panels": PANELS_DARK,
    },
    metrics={
        "body_fonts": ["Segoe UI Variable Text", "Segoe UI", "Helvetica Neue",
                       "DejaVu Sans"],
        "mono_fonts": ["Cascadia Mono", "Consolas", "DejaVu Sans Mono"],
        "size_delta": 0, "mono_delta": -1,
        "headings": {1: 2.0, 2: 1.55, 3: 1.3, 4: 1.15, 5: 1.0, 6: 0.92},
        "heading_rules": (1, 2),
        "quote_style": "tint", "table_style": "plain", "code_style": "filled",
        "link_underline": True, "pad_x": 22, "para_gap": 0.55,
        "panel_labels": True,
    },
    css_vars="""
:root {
  --bg:#fff; --fg:#24292f; --muted:#57606a; --link:#0969da;
  --code-bg:#eff1f3; --code-fg:#8250df; --block-bg:#f6f8fa; --border:#d8dee4;
  --thead:#eceff2; --zebra:#fafbfc; --quote-fg:#4a5460; --quote-bg:#f3f5f7;
  --quote-bar:#c6ced8; --mark:#fff3b0;
  --font-body:"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;
  --font-mono:"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;
  --size:16px; --width:46rem; --radius:8px;
}
h1,h2 { border-bottom:1px solid var(--border); padding-bottom:.3em; }
blockquote { background:var(--quote-bg); border-left:.28em solid var(--quote-bar); }
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --link:#6cb0f8;
    --code-bg:#262c36; --code-fg:#d2a8ff; --block-bg:#161b22; --border:#30363d;
    --thead:#1c222b; --zebra:#11161d; --quote-fg:#b3bcc6; --quote-bg:#151b23;
    --quote-bar:#3d444d; --mark:#6b5300;
  }
}
""",
)


# --------------------------------------------------------------------------
# GitHub
# --------------------------------------------------------------------------

GITHUB = Flavor(
    key="github",
    name="GitHub",
    blurb="GitHub Flavored Markdown: tables, task lists, "
          "bare URLs linkified, > [!NOTE] alerts. No ::: containers.",
    opts=Options(
        tables=True, task_lists=True, strikethrough=True, bare_autolinks=True,
        hard_breaks=False, mark=False, containers=False, alerts=True,
        quote_panels=False,
    ),
    light={
        "bg": "#ffffff", "fg": "#1f2328", "muted": "#59636e",
        "link": "#0969da", "code_bg": "#eff1f3", "code_fg": "#1f2328",
        "block_bg": "#f6f8fa", "quote_bg": "#ffffff", "quote_fg": "#59636e",
        "rule": "#d1d9e0", "table_head": "#f6f8fa", "zebra": "#f6f8fa",
        "mark_bg": "#fff8c5", "panels": {
            "note": ("#ffffff", "#0969da"), "info": ("#ffffff", "#0969da"),
            "tip": ("#ffffff", "#1a7f37"), "success": ("#ffffff", "#1a7f37"),
            "warning": ("#ffffff", "#9a6700"), "danger": ("#ffffff", "#cf222e"),
        },
    },
    dark={
        "bg": "#0d1117", "fg": "#e6edf3", "muted": "#9198a1",
        "link": "#4493f8", "code_bg": "#262c36", "code_fg": "#e6edf3",
        "block_bg": "#151b23", "quote_bg": "#0d1117", "quote_fg": "#9198a1",
        "rule": "#3d444d", "table_head": "#151b23", "zebra": "#151b23",
        "mark_bg": "#5c4200", "panels": {
            "note": ("#0d1117", "#4493f8"), "info": ("#0d1117", "#4493f8"),
            "tip": ("#0d1117", "#3fb950"), "success": ("#0d1117", "#3fb950"),
            "warning": ("#0d1117", "#d29922"), "danger": ("#0d1117", "#f85149"),
        },
    },
    metrics={
        "body_fonts": ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "mono_fonts": ["Consolas", "Cascadia Mono", "DejaVu Sans Mono"],
        "size_delta": 0, "mono_delta": -1,
        "headings": {1: 2.0, 2: 1.5, 3: 1.25, 4: 1.0, 5: 0.875, 6: 0.85},
        "heading_rules": (1, 2),
        "quote_style": "bar", "table_style": "zebra", "code_style": "filled",
        "link_underline": False, "pad_x": 30, "para_gap": 0.6,
        "panel_labels": True,
    },
    css_vars="""
:root {
  --bg:#fff; --fg:#1f2328; --muted:#59636e; --link:#0969da;
  --code-bg:#eff1f3; --code-fg:#1f2328; --block-bg:#f6f8fa; --border:#d1d9e0;
  --thead:#f6f8fa; --zebra:#f6f8fa; --quote-fg:#59636e; --quote-bg:transparent;
  --quote-bar:#d1d9e0; --mark:#fff8c5;
  --font-body:-apple-system,"Segoe UI","Helvetica Neue",Arial,sans-serif;
  --font-mono:ui-monospace,Consolas,"Liberation Mono",monospace;
  --size:16px; --width:1012px; --radius:6px;
}
body { padding:2rem; }
h1,h2 { border-bottom:1px solid var(--border); padding-bottom:.3em; }
blockquote { border-left:.25em solid var(--quote-bar); }
table { border:1px solid var(--border); }
table tr:nth-child(2n) td { background:var(--zebra); }
a { text-decoration:none; }
a:hover { text-decoration:underline; }
.panel { background:transparent; border-left:.25em solid; border-radius:0; }
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --link:#4493f8;
    --code-bg:#262c36; --code-fg:#e6edf3; --block-bg:#151b23; --border:#3d444d;
    --thead:#151b23; --zebra:#151b23; --quote-fg:#9198a1; --quote-bar:#3d444d;
    --mark:#5c4200;
  }
}
""",
)


# --------------------------------------------------------------------------
# Confluence
# --------------------------------------------------------------------------

CONFLUENCE = Flavor(
    key="confluence",
    name="Confluence",
    blurb="Atlassian styling: single newlines break the line, "
          "\"> **Note:** ...\" and ::: blocks become panels.",
    opts=Options(
        tables=True, task_lists=True, strikethrough=True, bare_autolinks=True,
        hard_breaks=True, mark=False, containers=True, alerts=True,
        quote_panels=True,
    ),
    light={
        "bg": "#ffffff", "fg": "#172b4d", "muted": "#6b778c",
        "link": "#0052cc", "code_bg": "#f4f5f7", "code_fg": "#172b4d",
        "block_bg": "#f4f5f7", "quote_bg": "#f4f5f7", "quote_fg": "#42526e",
        "rule": "#dfe1e6", "table_head": "#f4f5f7", "zebra": "#ffffff",
        "mark_bg": "#fffae6", "panels": {
            "note": ("#eae6ff", "#5243aa"), "info": ("#deebff", "#0052cc"),
            "tip": ("#e3fcef", "#00875a"), "success": ("#e3fcef", "#00875a"),
            "warning": ("#fffae6", "#ff8b00"), "danger": ("#ffebe6", "#de350b"),
        },
    },
    dark={
        "bg": "#1b2638", "fg": "#b6c2cf", "muted": "#8c9bab",
        "link": "#579dff", "code_bg": "#22272b", "code_fg": "#c7d1db",
        "block_bg": "#22272b", "quote_bg": "#22272b", "quote_fg": "#9fadbc",
        "rule": "#38414a", "table_head": "#22272b", "zebra": "#1b2638",
        "mark_bg": "#533f04", "panels": {
            "note": ("#282249", "#8f7ee7"), "info": ("#1c2b41", "#579dff"),
            "tip": ("#1c3329", "#4bce97"), "success": ("#1c3329", "#4bce97"),
            "warning": ("#332e1b", "#e2b203"), "danger": ("#42221f", "#f87168"),
        },
    },
    metrics={
        "body_fonts": ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "mono_fonts": ["Consolas", "Cascadia Mono", "DejaVu Sans Mono"],
        "size_delta": -1, "mono_delta": -1,
        "headings": {1: 1.71, 2: 1.43, 3: 1.14, 4: 1.0, 5: 0.9, 6: 0.85},
        "heading_rules": (),
        "quote_style": "panel", "table_style": "grid", "code_style": "bordered",
        "link_underline": False, "pad_x": 28, "para_gap": 0.5,
        "panel_labels": False,
    },
    css_vars="""
:root {
  --bg:#fff; --fg:#172b4d; --muted:#6b778c; --link:#0052cc;
  --code-bg:#f4f5f7; --code-fg:#172b4d; --block-bg:#f4f5f7; --border:#dfe1e6;
  --thead:#f4f5f7; --zebra:#fff; --quote-fg:#42526e; --quote-bg:#f4f5f7;
  --quote-bar:#c1c7d0; --mark:#fffae6;
  --font-body:-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
  --font-mono:"SFMono-Medium","SF Mono",Consolas,monospace;
  --size:14px; --width:60rem; --radius:3px;
}
h1,h2,h3 { color:var(--fg); letter-spacing:-.008em; }
h1 { margin-top:2.2em; }
blockquote { border-left:2px solid var(--quote-bar); background:transparent; }
table { border:1px solid var(--border); }
th { text-align:left; }
pre { border:1px solid var(--border); border-radius:3px; }
.panel { border-left:3px solid; border-radius:3px; }
a { text-decoration:none; }
a:hover { text-decoration:underline; }
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#1b2638; --fg:#b6c2cf; --muted:#8c9bab; --link:#579dff;
    --code-bg:#22272b; --code-fg:#c7d1db; --block-bg:#22272b; --border:#38414a;
    --thead:#22272b; --zebra:#1b2638; --quote-fg:#9fadbc; --quote-bg:#22272b;
    --quote-bar:#454f59; --mark:#533f04;
  }
}
""",
)


# --------------------------------------------------------------------------
# Visual Studio
# --------------------------------------------------------------------------

VISUAL_STUDIO = Flavor(
    key="vs",
    name="Visual Studio",
    blurb="The IDE's Markdown preview: Markdig extensions "
          "(==mark==, ::: containers) with Visual Studio's colours.",
    opts=Options(
        tables=True, task_lists=True, strikethrough=True, bare_autolinks=True,
        hard_breaks=False, mark=True, containers=True, alerts=True,
        quote_panels=False,
    ),
    light={
        "bg": "#ffffff", "fg": "#1e1e1e", "muted": "#6d6d6d",
        "link": "#0066b8", "code_bg": "#f5f5f5", "code_fg": "#a31515",
        "block_bg": "#f5f5f5", "quote_bg": "#f5f5f5", "quote_fg": "#4a4a4a",
        "rule": "#cccedb", "table_head": "#f0f0f0", "zebra": "#fafafa",
        "mark_bg": "#fff2a8", "panels": PANELS_LIGHT,
    },
    dark={
        "bg": "#1f1f1f", "fg": "#d4d4d4", "muted": "#9a9a9a",
        "link": "#4da6ff", "code_bg": "#252526", "code_fg": "#ce9178",
        "block_bg": "#252526", "quote_bg": "#252526", "quote_fg": "#c0c0c0",
        "rule": "#3f3f46", "table_head": "#2d2d30", "zebra": "#232323",
        "mark_bg": "#5b4b00", "panels": PANELS_DARK,
    },
    metrics={
        "body_fonts": ["Segoe UI", "Helvetica Neue", "DejaVu Sans"],
        "mono_fonts": ["Cascadia Mono", "Consolas", "DejaVu Sans Mono"],
        "size_delta": 0, "mono_delta": 0,
        "headings": {1: 2.0, 2: 1.5, 3: 1.17, 4: 1.0, 5: 0.9, 6: 0.85},
        "heading_rules": (1,),
        "quote_style": "bar", "table_style": "lines", "code_style": "bordered",
        "link_underline": False, "pad_x": 20, "para_gap": 0.5,
        "panel_labels": True,
    },
    css_vars="""
:root {
  --bg:#fff; --fg:#1e1e1e; --muted:#6d6d6d; --link:#0066b8;
  --code-bg:#f5f5f5; --code-fg:#a31515; --block-bg:#f5f5f5; --border:#cccedb;
  --thead:#f0f0f0; --zebra:#fafafa; --quote-fg:#4a4a4a; --quote-bg:#f5f5f5;
  --quote-bar:#cccedb; --mark:#fff2a8;
  --font-body:"Segoe UI",system-ui,sans-serif;
  --font-mono:"Cascadia Mono",Consolas,monospace;
  --size:15px; --width:52rem; --radius:2px;
}
h1 { border-bottom:1px solid var(--border); padding-bottom:.3em; }
blockquote { border-left:4px solid var(--quote-bar); background:var(--quote-bg); }
pre { border:1px solid var(--border); border-radius:2px; }
table { border-collapse:collapse; }
th { border-bottom:2px solid var(--border); }
td { border:0; border-bottom:1px solid var(--border); }
a { text-decoration:none; }
a:hover { text-decoration:underline; }
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#1f1f1f; --fg:#d4d4d4; --muted:#9a9a9a; --link:#4da6ff;
    --code-bg:#252526; --code-fg:#ce9178; --block-bg:#252526; --border:#3f3f46;
    --thead:#2d2d30; --zebra:#232323; --quote-fg:#c0c0c0; --quote-bg:#252526;
    --quote-bar:#3f3f46; --mark:#5b4b00;
  }
}
""",
)


FLAVORS: Dict[str, Flavor] = {
    f.key: f for f in (MDEDIT, GITHUB, CONFLUENCE, VISUAL_STUDIO)
}
ORDER: List[str] = list(FLAVORS)
DEFAULT = MDEDIT


def get(key: str) -> Flavor:
    return FLAVORS.get((key or "").lower(), DEFAULT)


def next_key(key: str) -> str:
    return ORDER[(ORDER.index(get(key).key) + 1) % len(ORDER)]


# --------------------------------------------------------------------------
# Shared HTML skeleton
# --------------------------------------------------------------------------

BASE_CSS = """
* { box-sizing:border-box; }
body {
  margin:0 auto; padding:3rem 1.5rem; max-width:var(--width);
  font-family:var(--font-body); font-size:var(--size); line-height:1.65;
  color:var(--fg); background:var(--bg); word-wrap:break-word;
}
h1,h2,h3,h4,h5,h6 { line-height:1.25; margin:1.6em 0 .6em; font-weight:600; }
h1 { font-size:2em; } h2 { font-size:1.5em; } h3 { font-size:1.25em; }
h4 { font-size:1em; } h5 { font-size:.9em; } h6 { font-size:.85em; color:var(--muted); }
p,ul,ol,table,pre,blockquote,.panel { margin:0 0 1em; }
a { color:var(--link); }
code {
  font-family:var(--font-mono); font-size:.88em; background:var(--code-bg);
  color:var(--code-fg); padding:.18em .38em; border-radius:calc(var(--radius) - 2px);
}
pre {
  background:var(--block-bg); padding:1em; border-radius:var(--radius);
  overflow-x:auto;
}
pre code { background:none; color:inherit; padding:0; font-size:.875em; }
blockquote { padding:.2em 1em; color:var(--quote-fg); }
blockquote > :last-child { margin-bottom:0; }
hr { height:2px; border:0; background:var(--border); margin:2em 0; }
table { border-collapse:collapse; display:block; overflow-x:auto; }
th,td { border:1px solid var(--border); padding:.45em .8em; }
th { background:var(--thead); font-weight:600; }
img { max-width:100%; }
ul,ol { padding-left:2em; }
li { margin:.25em 0; }
li.task { list-style:none; margin-left:-1.4em; }
li.task input { margin-right:.5em; }
del { color:var(--muted); }
.noimg { color:var(--muted); font-style:italic; }
mark { background:var(--mark); color:inherit; padding:.1em .2em; border-radius:2px; }
.panel {
  padding:.8em 1em; border-radius:var(--radius); background:var(--block-bg);
  border-left:4px solid var(--border);
}
.panel > :last-child { margin-bottom:0; }
.panel-title { font-weight:600; margin:0 0 .4em; }
.panel-note { border-left-color:#8b98a8; }
.panel-info { border-left-color:#2f7bd8; }
.panel-tip, .panel-success { border-left-color:#2da26a; }
.panel-warning { border-left-color:#d99013; }
.panel-danger { border-left-color:#d63c3c; }
"""

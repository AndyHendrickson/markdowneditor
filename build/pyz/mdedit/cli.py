"""Command line front end.

    python -m mdedit                  open the editor
    python -m mdedit notes.md         open the editor on a file
    python -m mdedit --export notes.md [out.html]
    python -m mdedit --outline notes.md

Every renderable feature has a pair of flags, ``--tables`` / ``--no-tables``
and so on.  Unset means "whatever the emulation mode says"; set overrides it.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__, flavors, html_export, parser as P


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _add_feature_flags(ap: argparse.ArgumentParser):
    group = ap.add_argument_group(
        "features",
        "Turn a feature on or off, overriding the emulation mode. "
        "For example --no-tables leaves pipe tables as plain text.",
    )
    for feature in P.FEATURES:
        # BooleanOptionalAction adds the matching --no-<flag> itself.
        group.add_argument(
            f"--{feature.flag}", dest=f"feat_{feature.key}", default=None,
            action=argparse.BooleanOptionalAction, help=feature.hint,
        )


def _overrides(args) -> dict:
    return {f.key: getattr(args, f"feat_{f.key}")
            for f in P.FEATURES
            if getattr(args, f"feat_{f.key}") is not None}


def _print_features(flavor):
    width = max(len(f.flag) for f in P.FEATURES) + 6
    print(f"{'flag'.ljust(width)}{'in ' + flavor.name:<16}what it does")
    for group in P.GROUPS:
        members = [f for f in P.FEATURES if f.group == group]
        if not members:
            continue
        print(f"\n{group}")
        for f in members:
            state = "on" if getattr(flavor.opts, f.key) else "off"
            print(f"  --{f.flag.ljust(width - 4)}{state:<16}{f.hint}")
    print("\nPrefix any flag with --no- to switch the feature off.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="mdedit",
        description="Edit and render Markdown. Pure Python, entirely offline.",
    )
    ap.add_argument("file", nargs="?", help="Markdown file to open")
    ap.add_argument("output", nargs="?", help="output path for --export")
    ap.add_argument("--export", action="store_true",
                    help="write standalone HTML instead of opening the editor")
    ap.add_argument("--outline", action="store_true",
                    help="print the heading outline and exit")
    ap.add_argument("--flavor", "--flavour", dest="flavor",
                    choices=flavors.ORDER, default=None,
                    help="emulation mode: dialect and styling to use")
    ap.add_argument("--list-flavors", action="store_true",
                    help="list the emulation modes and exit")
    ap.add_argument("--list-features", action="store_true",
                    help="list the feature flags and their state, then exit")
    ap.add_argument("--version", action="version",
                    version=f"mdedit {__version__}")
    _add_feature_flags(ap)
    args = ap.parse_args(argv)

    if args.list_flavors:
        for key in flavors.ORDER:
            fl = flavors.FLAVORS[key]
            print(f"{key:<12}{fl.name:<16}{fl.blurb}")
        return 0

    flavor = flavors.get(args.flavor) if args.flavor else flavors.DEFAULT
    overrides = _overrides(args)
    opts = P.with_overrides(flavor.opts, overrides)

    if args.list_features:
        _print_features(flavor)
        return 0

    if args.export or args.outline:
        if not args.file:
            ap.error("a file is required with --export/--outline")
        if not os.path.isfile(args.file):
            print(f"mdedit: no such file: {args.file}", file=sys.stderr)
            return 1
        doc = P.parse(_read(args.file), opts)

        if args.outline:
            for level, title in P.outline(doc):
                print("  " * (level - 1) + title)
            return 0

        out = args.output or os.path.splitext(args.file)[0] + ".html"
        title = os.path.splitext(os.path.basename(args.file))[0]
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html_export.to_html(doc, title=title, flavor=flavor,
                                         opts=opts))
        off = [f"--no-{P.FEATURES_BY_KEY[k].flag}"
               for k in P.differences(opts, flavor.opts)
               if not getattr(opts, k)]
        extra = f", {' '.join(off)}" if off else ""
        print(f"wrote {out} ({flavor.name} emulation{extra})")
        return 0

    try:
        from .app import MarkdownApp
    except ImportError as exc:  # tkinter missing from the interpreter
        print(f"mdedit: the editor needs tkinter ({exc})", file=sys.stderr)
        return 2

    app = MarkdownApp(args.file)
    if args.flavor:
        app.set_flavor(args.flavor)
    if overrides:
        app.set_features(overrides)
    app.mainloop()
    return 0

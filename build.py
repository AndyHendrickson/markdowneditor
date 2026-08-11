#!/usr/bin/env python3
"""Build mdedit into something you can hand to someone else.

Three targets, all produced with the standard library alone -- no
PyInstaller, no compiler, no download:

  dist/mdedit.pyz        one file, runs on any Python 3.9+ that has tkinter
  dist/mdedit-windows/   a folder with mdedit.exe and its own interpreter,
                         so it runs on machines with no Python at all
  dist/mdedit.app        a double-clickable macOS app with its own
                         interpreter, so it runs on Macs with no Python

    python build.py              all targets for this platform, then check
    python build.py --pyz        just the single file
    python build.py --bundle     just the Windows folder
    python build.py --app        just the macOS app
    python build.py --clean      remove build/ and dist/

The Windows folder and the macOS app each copy the interpreter this script
is running under, so build it with the Python you want to ship.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import sysconfig
import time
import zipapp
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
PACKAGE = ROOT / "mdedit"

from mdedit import __version__ as MDEDIT_VERSION

#: Left out of the shipped standard library: test suites and tooling.
STDLIB_SKIP_DIRS = {
    "__pycache__", "site-packages", "test", "tests", "idlelib", "turtledemo",
    "ensurepip", "lib2to3", "distutils", "venv", "pydoc_data", "tkinter/test",
    "unittest/test", "sqlite3/test", "ctypes/test", "lib-dynload",
}

#: Same idea for the macOS app, but "lib-dynload" has to stay -- that's
#: where the compiled _tkinter.so extension module lives on POSIX.
MACOS_STDLIB_SKIP_DIRS = STDLIB_SKIP_DIRS - {"lib-dynload"}

BOOTSTRAP = '''\
"""Start mdedit when the bundled interpreter starts.

The launcher *is* the interpreter, so site.py imports this file and we take
over from there.  Anything the host machine had on sys.path is dropped first
-- the bundle only ever imports its own code.
"""

import os
import sys


def _report(root: str) -> int:
    import traceback

    text = traceback.format_exc()
    try:
        with open(os.path.join(root, "mdedit-error.log"), "w",
                  encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        pass
    try:
        import tkinter
        from tkinter import messagebox

        window = tkinter.Tk()
        window.withdraw()
        messagebox.showerror("mdedit could not start", text[-1500:])
        window.destroy()
    except Exception:
        print(text, file=sys.stderr)
    return 1


def _run() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    inside = os.path.normcase(root)
    sys.path[:] = [p for p in sys.path
                   if os.path.normcase(os.path.abspath(p)).startswith(inside)]
    archive = os.path.join(here, "mdedit.pyz")
    if archive not in sys.path:
        sys.path.insert(0, archive)

    # Handed an actual Python script, stay an interpreter and run it.
    if sys.argv and sys.argv[0].lower().endswith(".py"):
        return

    code = 0
    try:
        from mdedit.cli import main

        code = main([a for a in sys.argv if a]) or 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
    except BaseException:
        code = _report(root)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os._exit(code)


_run()
'''

README_TXT = """\
mdedit -- a Markdown editor with a live preview

Double-click mdedit.exe.  Nothing to install: this folder carries its own
Python and Tk, and the app never touches the network.

  mdedit.exe                    open the editor
  mdedit.exe notes.md           open a file
  mdedit.exe notes.md --export  a file first, then any flags

  mdedit-cli.cmd --help         the full command line, flags in any order
  mdedit-cli.cmd --export notes.md --flavor github --no-tables

mdedit.exe is the bundled interpreter itself, so a flag written *before* the
file name would be read by Python rather than by mdedit.  Use mdedit-cli.cmd
when you want flags first.

The whole folder is portable: copy it anywhere, or onto a USB stick.
"""

# macOS: unlike the Windows launcher, the bundled interpreter isn't renamed
# into taking mdedit's place -- an ordinary shell script runs it with -I
# (isolated mode), which drops PYTHONPATH, user site-packages and the
# script's own directory from sys.path just as effectively as the Windows
# _pth file does, without needing a sitecustomize bootstrap.
LAUNCHER_SCRIPT = """\
#!/bin/bash
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$HERE/.." && pwd)"
PYZ="$APP_ROOT/Resources/app/mdedit.pyz"
LOG_DIR="$HOME/Library/Logs"
LOG="$LOG_DIR/mdedit-error.log"
mkdir -p "$LOG_DIR" 2>/dev/null || LOG="/tmp/mdedit-error.log"

PYTHON=""
BUNDLED="$APP_ROOT/__PYTHON_REL__"
if [ -n "__PYTHON_REL__" ] && [ -x "$BUNDLED" ]; then
    PYTHON="$BUNDLED"
else
    PYTHON="$(command -v python3 || true)"
fi
if [ -z "$PYTHON" ]; then
    /usr/bin/osascript -e 'display alert "mdedit could not start" message "No Python 3 interpreter was found. Install Python 3.9+ from python.org and try again."' >/dev/null 2>&1
    exit 1
fi

"$PYTHON" -I "$PYZ" "$@" 2>"$LOG"
status=$?
if [ $status -ne 0 ] && [ -s "$LOG" ]; then
    export MDEDIT_ERR="$(tail -c 1500 "$LOG")"
    /usr/bin/osascript -e 'display alert "mdedit could not start" message (system attribute "MDEDIT_ERR")' >/dev/null 2>&1
fi
exit $status
"""

INFO_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>mdedit</string>
    <key>CFBundleDisplayName</key>
    <string>mdedit</string>
    <key>CFBundleIdentifier</key>
    <string>dev.mdedit.editor</string>
    <key>CFBundleVersion</key>
    <string>__VERSION__</string>
    <key>CFBundleShortVersionString</key>
    <string>__VERSION__</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>mdedit</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSSupportsAutomaticGraphicsSwitching</key>
    <true/>
</dict>
</plist>
"""

MACOS_README_TXT = """\
mdedit -- a Markdown editor with a live preview

Right-click mdedit.app and choose Open the first time -- it isn't signed by
an Apple Developer ID, so Gatekeeper needs that one confirmation. After that
it opens normally, including by double-click.

The app carries its own Python and never touches the network. If it can't
start, look at ~/Library/Logs/mdedit-error.log.

The command line lives inside the bundle:

  dist/mdedit.app/Contents/MacOS/mdedit                 open the editor
  dist/mdedit.app/Contents/MacOS/mdedit notes.md         open a file
  dist/mdedit.app/Contents/MacOS/mdedit --export notes.md --flavor github

The whole .app is portable: copy it anywhere, or onto a USB stick.
"""


def log(message: str) -> None:
    print(f"  {message}")


def clean() -> None:
    for path in (BUILD, DIST):
        if path.exists():
            shutil.rmtree(path)
            log(f"removed {path.relative_to(ROOT)}")


# --------------------------------------------------------------------------
# Target 1: the single-file zipapp
# --------------------------------------------------------------------------


def build_pyz() -> Path:
    print("Building dist/mdedit.pyz")
    staging = BUILD / "pyz"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(PACKAGE, staging / "mdedit",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    DIST.mkdir(parents=True, exist_ok=True)
    target = DIST / "mdedit.pyz"
    zipapp.create_archive(staging, target=target, main="mdedit.cli:main",
                          interpreter="/usr/bin/env python3", compressed=True)
    log(f"{target.relative_to(ROOT)}  ({target.stat().st_size / 1024:.0f} KB)")
    return target


# --------------------------------------------------------------------------
# Target 2: the Windows folder with its own interpreter
# --------------------------------------------------------------------------


def _skip(relative: Path, skip_dirs=STDLIB_SKIP_DIRS) -> bool:
    parts = [p.lower() for p in relative.parts]
    joined = "/".join(parts)
    return any(part in skip_dirs for part in parts) or \
        any(joined.startswith(skip) for skip in skip_dirs)


def _zip_stdlib(source: Path, target: Path) -> int:
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*.py")):
            relative = path.relative_to(source)
            if _skip(relative):
                continue
            archive.write(path, relative.as_posix())
            count += 1
    return count


def build_bundle(pyz: Path) -> Path:
    if os.name != "nt":
        print("Skipping the Windows bundle: this target needs Windows "
              f"(running on {sys.platform}).  dist/mdedit.pyz is built.")
        return None

    print("Building dist/mdedit-windows/")
    prefix = Path(sys.base_prefix)
    out = DIST / "mdedit-windows"
    if out.exists():
        shutil.rmtree(out)
    (out / "app").mkdir(parents=True)

    tag = f"python{sys.version_info.major}{sys.version_info.minor}"

    # The interpreter, once without a console for the GUI and once with it.
    launchers = {"mdedit.exe": "pythonw.exe", "mdedit-console.exe": "python.exe"}
    for name, source in launchers.items():
        shutil.copy2(prefix / source, out / name)
        (out / f"{Path(name).stem}._pth").write_text(
            f"{tag}.zip\nDLLs\napp\n.\nimport site\n", encoding="utf-8")
    log(f"launchers: {', '.join(launchers)}")

    for dll in [f"{tag}.dll", "vcruntime140.dll", "vcruntime140_1.dll",
                "python3.dll"]:
        if (prefix / dll).exists():
            shutil.copy2(prefix / dll, out / dll)

    # Extension modules and the Tcl/Tk libraries they load.
    shutil.copytree(prefix / "DLLs", out / "DLLs",
                    ignore=shutil.ignore_patterns("*.ico", "*_test*", "test_*"))
    tcl_source = prefix / "tcl"
    if tcl_source.exists():
        shutil.copytree(tcl_source, out / "tcl",
                        ignore=shutil.ignore_patterns("*.lib", "nmake",
                                                      "*.sh", "__pycache__"))
    log("runtime: DLLs, tcl")

    modules = _zip_stdlib(prefix / "Lib", out / f"{tag}.zip")
    log(f"standard library: {modules} modules -> {tag}.zip "
        f"({(out / f'{tag}.zip').stat().st_size / 1e6:.1f} MB)")

    shutil.copy2(pyz, out / "app" / "mdedit.pyz")
    (out / "app" / "sitecustomize.py").write_text(BOOTSTRAP, encoding="utf-8")
    (out / "mdedit-cli.cmd").write_text(
        '@echo off\r\n"%~dp0mdedit-console.exe" "%~dp0app\\mdedit.pyz" %*\r\n',
        encoding="utf-8")
    (out / "README.txt").write_text(README_TXT, encoding="utf-8")

    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    log(f"{out.relative_to(ROOT)}  ({size / 1e6:.0f} MB, "
        f"{sum(1 for _ in out.rglob('*') if _.is_file())} files)")
    return out


# --------------------------------------------------------------------------
# Target 3: the macOS app with its own interpreter
# --------------------------------------------------------------------------


def _framework_root(prefix: Path) -> Path | None:
    """The *.framework directory behind a framework build's base_prefix.

    python.org's macOS installer and Xcode's bundled Python both lay out
    base_prefix as .../Whatever.framework/Versions/3.9 -- copy that whole
    framework and the relative @executable_path/../Python3 link the
    interpreter uses to find its dylib keeps working.  A non-framework build
    (Homebrew's --without-framework, pyenv's own build) has nothing
    analogous to copy, so this returns None and the app falls back to
    'python3' on the host's PATH.
    """
    if prefix.parent.name == "Versions" and prefix.parent.parent.name.endswith(".framework"):
        return prefix.parent.parent
    return None


def _prune_framework(framework_dir: Path, version: str) -> int:
    lib = framework_dir / "Versions" / version / "lib" / f"python{version}"
    if not lib.exists():
        return 0
    removed = 0
    for child in sorted(lib.rglob("*")):
        if not child.exists() or not child.is_dir():
            continue
        relative = child.relative_to(lib)
        if _skip(relative, MACOS_STDLIB_SKIP_DIRS):
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


def build_macos_app(pyz: Path) -> Path:
    if sys.platform != "darwin":
        print("Skipping the macOS app: this target needs macOS "
              f"(running on {sys.platform}).  dist/mdedit.pyz is built.")
        return None

    print("Building dist/mdedit.app/")
    prefix = Path(sys.base_prefix)
    version = f"{sys.version_info.major}.{sys.version_info.minor}"

    out = DIST / "mdedit.app"
    if out.exists():
        shutil.rmtree(out)
    contents = out / "Contents"
    resources = contents / "Resources"
    macos_dir = contents / "MacOS"
    (resources / "app").mkdir(parents=True)
    macos_dir.mkdir(parents=True)

    python_rel = ""
    framework_root = _framework_root(prefix)
    if framework_root is not None:
        dest_fw = contents / "Frameworks" / framework_root.name
        dest_fw.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(framework_root, dest_fw, symlinks=True)
        removed = _prune_framework(dest_fw, version)
        # Not every framework build symlinks an unversioned "python3" into
        # its own bin/ (Homebrew's doesn't) -- fall back to the versioned
        # name, which every framework build has.
        bin_dir = dest_fw / "Versions" / version / "bin"
        bin_name = "python3" if (bin_dir / "python3").exists() else f"python{version}"
        python_rel = f"Frameworks/{framework_root.name}/Versions/{version}/bin/{bin_name}"
        log(f"framework: {framework_root} -> Contents/Frameworks/ "
            f"({removed} stdlib test/tooling dirs trimmed)")
    else:
        print("  no relocatable Python.framework behind this interpreter -- "
              "shipping without a bundled one. The app will run with "
              "'python3' from the host's PATH instead. Build with "
              "python.org's installer for a self-contained app.")

    shutil.copy2(pyz, resources / "app" / "mdedit.pyz")
    log("app: mdedit.pyz")

    (macos_dir / "mdedit").write_text(
        LAUNCHER_SCRIPT.replace("__PYTHON_REL__", python_rel), encoding="utf-8")
    (macos_dir / "mdedit").chmod(0o755)
    (contents / "Info.plist").write_text(
        INFO_PLIST.replace("__VERSION__", MDEDIT_VERSION), encoding="utf-8")

    dist_readme = DIST / "README-macOS.txt"
    dist_readme.write_text(MACOS_README_TXT, encoding="utf-8")

    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    log(f"{out.relative_to(ROOT)}  ({size / 1e6:.0f} MB, "
        f"{sum(1 for _ in out.rglob('*') if _.is_file())} files)")
    return out


# --------------------------------------------------------------------------
# Checking what we just built
# --------------------------------------------------------------------------


def check_pyz(pyz: Path) -> bool:
    print("Checking dist/mdedit.pyz")
    probe = [sys.executable, str(pyz), "--outline", str(ROOT / "README.md")]
    done = subprocess.run(probe, capture_output=True, text=True, timeout=90)
    ok = done.returncode == 0 and "mdedit" in done.stdout
    log(f"--outline: {'ok' if ok else 'FAILED ' + done.stderr[:200]}")
    return ok


def check_bundle(out: Path) -> bool:
    if out is None:
        return True
    print("Checking dist/mdedit-windows/")
    console = out / "mdedit-console.exe"
    ok = True

    # A clean environment: nothing may leak in from the host installation.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PYTHON")}
    env["PATH"] = "C:\\Windows\\system32;C:\\Windows"

    def run(command, **kw):
        try:
            return subprocess.run(command, capture_output=True, text=True,
                                  timeout=90, env=env, cwd=str(out), **kw)
        except subprocess.TimeoutExpired:
            return None

    probe = out / "app" / "probe.py"
    probe.write_text(
        "import os, sys, tkinter\n"
        "root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
        "outside = [p for p in sys.path if p and not\n"
        "           os.path.normcase(os.path.abspath(p)).startswith("
        "os.path.normcase(root))]\n"
        "window = tkinter.Tk(); window.destroy()\n"
        "from mdedit import parser, flavors, html_export\n"
        "doc = parser.parse('# Title\\n\\n| a |\\n|---|\\n| 1 |\\n')\n"
        "html = html_export.to_html(doc)\n"
        "print('PROBE', 'tk' + str(tkinter.TkVersion), len(flavors.ORDER),\n"
        "      '<table>' in html, 'outside=' + repr(outside))\n",
        encoding="utf-8")
    try:
        done = run([str(console), str(probe)])
        line = ""
        if done:
            line = next((l for l in done.stdout.splitlines()
                         if l.startswith("PROBE")), "")
        ok = bool(line) and "outside=[]" in line and "True" in line
        log(f"isolated run: {line or 'FAILED (' + (done.stderr[-300:] if done else 'timed out') + ')'}")
    finally:
        probe.unlink(missing_ok=True)

    done = run(f'"{out / "mdedit-cli.cmd"}" --list-flavors', shell=True)
    cli_ok = bool(done) and "obsidian" in done.stdout
    log(f"mdedit-cli.cmd --list-flavors: {'ok' if cli_ok else 'FAILED'}")

    done = run([str(console), str(ROOT / "README.md"), "--outline"])
    args_ok = bool(done) and "Emulation modes" in done.stdout
    log(f"arguments after the file name: {'ok' if args_ok else 'FAILED'}")
    return ok and cli_ok and args_ok


def check_macos_app(out: Path) -> bool:
    if out is None:
        return True
    print("Checking dist/mdedit.app/")
    launcher = out / "Contents" / "MacOS" / "mdedit"
    pyz = out / "Contents" / "Resources" / "app" / "mdedit.pyz"

    # A clean environment: nothing may leak in from the host installation.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PATH"] = "/usr/bin:/bin"

    def run(command):
        try:
            return subprocess.run(command, capture_output=True, text=True,
                                  timeout=90, env=env)
        except subprocess.TimeoutExpired:
            return None

    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    fw_dir = out / "Contents" / "Frameworks"
    bundled_python = None
    if fw_dir.exists():
        for bin_name in ("python3", f"python{version}"):
            match = next(fw_dir.glob(f"*.framework/Versions/{version}/bin/{bin_name}"), None)
            if match is not None:
                bundled_python = match
                break

    ok = True
    if bundled_python is not None:
        probe = BUILD / "macos_probe.py"
        probe.write_text(
            "import sys, tkinter\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "window = tkinter.Tk(); window.destroy()\n"
            "from mdedit import parser, flavors, html_export\n"
            "doc = parser.parse('# Title\\n\\n| a |\\n|---|\\n| 1 |\\n')\n"
            "html = html_export.to_html(doc)\n"
            "print('PROBE', 'tk' + str(tkinter.TkVersion), len(flavors.ORDER),\n"
            "      '<table>' in html)\n",
            encoding="utf-8")
        try:
            done = run([str(bundled_python), "-I", str(probe), str(pyz)])
            line = ""
            if done:
                line = next((l for l in done.stdout.splitlines()
                             if l.startswith("PROBE")), "")
            ok = bool(line) and "True" in line
            log(f"isolated interpreter: {line or 'FAILED (' + (done.stderr[-300:] if done else 'timed out') + ')'}")
        finally:
            probe.unlink(missing_ok=True)
    else:
        log("isolated interpreter: skipped (no bundled framework)")

    done = run([str(launcher), str(ROOT / "README.md"), "--outline"])
    args_ok = bool(done) and "Emulation modes" in done.stdout
    log(f"launcher: {'ok' if args_ok else 'FAILED ' + (done.stderr[-300:] if done else 'timed out')}")
    return ok and args_ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pyz", action="store_true", help="build only mdedit.pyz")
    ap.add_argument("--bundle", action="store_true",
                    help="build only the Windows folder")
    ap.add_argument("--app", action="store_true",
                    help="build only the macOS app")
    ap.add_argument("--clean", action="store_true",
                    help="delete build/ and dist/, then stop")
    ap.add_argument("--no-check", action="store_true",
                    help="skip running the built artefacts")
    args = ap.parse_args(argv)

    if args.clean:
        clean()
        return 0

    started = time.time()
    both = not (args.pyz or args.bundle or args.app)
    pyz = build_pyz() if (both or args.pyz or args.bundle or args.app) else None
    win_out = build_bundle(pyz) if (both or args.bundle) else None
    mac_out = build_macos_app(pyz) if (both or args.app) else None

    ok = True
    if not args.no_check:
        if pyz and (both or args.pyz):
            ok &= check_pyz(pyz)
        if both or args.bundle:
            ok &= check_bundle(win_out)
        if both or args.app:
            ok &= check_macos_app(mac_out)

    print(f"{'Done' if ok else 'FAILED'} in {time.time() - started:.1f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

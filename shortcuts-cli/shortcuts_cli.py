# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Agent-friendly wrapper for Cherri and macOS Shortcuts."""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SHORTCUTS_BIN = Path("/usr/bin/shortcuts")
OPEN_BIN = Path("/usr/bin/open")
OUTPUT_DIR = Path.home() / ".claude" / "outputs"


class CliError(Exception):
    """Raised for user-facing command errors."""


@dataclass(frozen=True)
class BuildOptions:
    source: Path
    output: Path | None
    open_after_build: bool
    comments: bool
    share: str | None = None


def require_macos() -> None:
    if platform.system() != "Darwin":
        msg = "shortcuts-cli build/import/run/list/view require macOS"
        raise CliError(msg)
    if not SHORTCUTS_BIN.exists():
        msg = "/usr/bin/shortcuts not found; install macOS Shortcuts support"
        raise CliError(msg)


def require_cherri() -> None:
    if shutil.which("cherri") is None:
        msg = "cherri not found in PATH"
        raise CliError(msg)


def default_output_path(source: Path) -> Path:
    return OUTPUT_DIR / f"{source.stem}.shortcut"


def default_decompile_output(source: str) -> Path:
    if source.startswith(("http://", "https://")):
        return OUTPUT_DIR / "imported.cherri"
    return OUTPUT_DIR / f"{Path(source).stem}.cherri"


def unsigned_output_path(output: Path) -> Path:
    return output.with_name(f"{output.stem}_unsigned{output.suffix}")


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, text=True)
    except FileNotFoundError as error:
        msg = f"command not found: {command[0]}"
        raise CliError(msg) from error
    except subprocess.CalledProcessError as error:
        msg = f"command failed with exit code {error.returncode}: {' '.join(command)}"
        raise CliError(msg) from error


def run_info(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=False, text=True)
    except FileNotFoundError as error:
        msg = f"command not found: {command[0]}"
        raise CliError(msg) from error


def build_cherri_command(options: BuildOptions) -> list[str]:
    output = options.output or default_output_path(options.source)
    command = [
        "cherri",
        str(options.source),
        f"--output={output}",
        "--no-ansi",
    ]
    if options.comments:
        command.append("--comments")
    if options.share:
        command.append(f"--share={options.share}")
    return command


def validate_cherri_command(source: Path, *, comments: bool) -> list[str]:
    command = [
        "cherri",
        str(source),
        "--skip-sign",
        "--no-ansi",
    ]
    if comments:
        command.append("--comments")
    return command


def ensure_source(source: Path) -> None:
    if not source.exists():
        msg = f"source file not found: {source}"
        raise CliError(msg)
    if source.suffix != ".cherri":
        msg = f"source file must end with .cherri: {source}"
        raise CliError(msg)


def cmd_build(args: argparse.Namespace) -> None:
    source = Path(args.file)
    ensure_source(source)
    require_macos()
    require_cherri()

    output = Path(args.output) if args.output else default_output_path(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    options = BuildOptions(
        source=source,
        output=output,
        open_after_build=args.open,
        comments=args.comments,
        share=args.share,
    )

    run(build_cherri_command(options))
    if not output.exists():
        msg = f"signed Shortcut was not created: {output}"
        raise CliError(msg)

    print(output)
    if options.open_after_build:
        if not OPEN_BIN.exists():
            msg = "/usr/bin/open not found"
            raise CliError(msg)
        run([str(OPEN_BIN), str(output)])
        print("Opened in Shortcuts. Confirm import in the app.")


def cmd_validate(args: argparse.Namespace) -> None:
    source = Path(args.file)
    ensure_source(source)
    require_cherri()

    unsigned = unsigned_output_path(source.with_suffix(".shortcut"))
    run(validate_cherri_command(source, comments=args.comments))
    if not unsigned.exists():
        msg = f"unsigned validation artifact was not created: {unsigned}"
        raise CliError(msg)
    unsigned.unlink()
    print(f"Valid: {source}")


def cmd_import(args: argparse.Namespace) -> None:
    require_macos()
    shortcut = Path(args.file)
    if not shortcut.exists():
        msg = f"Shortcut file not found: {shortcut}"
        raise CliError(msg)
    run([str(OPEN_BIN), str(shortcut)])
    print("Opened in Shortcuts. Confirm import in the app.")


def cmd_run(args: argparse.Namespace) -> None:
    require_macos()
    command = [str(SHORTCUTS_BIN), "run", args.name]
    for input_path in args.input_path or []:
        command.extend(["--input-path", input_path])
    if args.output_path:
        command.extend(["--output-path", args.output_path])
    if args.output_type:
        command.extend(["--output-type", args.output_type])
    run(command)


def cmd_list(_args: argparse.Namespace) -> None:
    require_macos()
    run([str(SHORTCUTS_BIN), "list"])


def cmd_view(args: argparse.Namespace) -> None:
    require_macos()
    run([str(SHORTCUTS_BIN), "view", args.name])


def cmd_actions(args: argparse.Namespace) -> None:
    require_cherri()
    query = args.query or ""
    run_info(["cherri", f"--action={query}", "--no-ansi"])


def cmd_docs(args: argparse.Namespace) -> None:
    require_cherri()
    command = ["cherri", f"--docs={args.category}", "--no-ansi"]
    if args.subcat:
        command.append(f"--subcat={args.subcat}")
    run_info(command)


def cmd_glyphs(args: argparse.Namespace) -> None:
    require_cherri()
    run_info(["cherri", f"--glyph={args.query}", "--no-ansi"])


def cmd_decompile(args: argparse.Namespace) -> None:
    require_cherri()
    output = Path(args.output) if args.output else default_decompile_output(args.input)
    output.parent.mkdir(parents=True, exist_ok=True)
    run(["cherri", f"--import={args.input}", f"--output={output}", "--no-ansi"])
    if not output.exists():
        msg = f"Cherri source was not created: {output}"
        raise CliError(msg)
    print(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shortcuts-cli",
        description="Build and run Apple Shortcuts from Cherri on macOS",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser_ = subparsers.add_parser("build", help="Build signed Shortcut")
    build_parser_.add_argument("file", help="Cherri source file")
    build_parser_.add_argument("--output", "-o", help="Output .shortcut path")
    build_parser_.add_argument("--open", action="store_true", help="Open after build")
    build_parser_.add_argument("--comments", "-c", action="store_true")
    build_parser_.add_argument(
        "--share",
        choices=["anyone", "contacts"],
        help="Shortcut signing share mode",
    )
    build_parser_.set_defaults(func=cmd_build)

    validate_parser = subparsers.add_parser("validate", help="Compile without signing")
    validate_parser.add_argument("file", help="Cherri source file")
    validate_parser.add_argument("--comments", "-c", action="store_true")
    validate_parser.set_defaults(func=cmd_validate)

    import_parser = subparsers.add_parser("import", help="Open Shortcut for import")
    import_parser.add_argument("file", help="Signed .shortcut file")
    import_parser.set_defaults(func=cmd_import)

    run_parser = subparsers.add_parser("run", help="Run installed Shortcut")
    run_parser.add_argument("name", help="Shortcut name or identifier")
    run_parser.add_argument("--input-path", action="append")
    run_parser.add_argument("--output-path")
    run_parser.add_argument("--output-type")
    run_parser.set_defaults(func=cmd_run)

    list_parser = subparsers.add_parser("list", help="List installed Shortcuts")
    list_parser.set_defaults(func=cmd_list)

    view_parser = subparsers.add_parser("view", help="View installed Shortcut")
    view_parser.add_argument("name", help="Shortcut name")
    view_parser.set_defaults(func=cmd_view)

    actions_parser = subparsers.add_parser("actions", help="Search Cherri actions")
    actions_parser.add_argument("query", nargs="?", help="Action name or search term")
    actions_parser.set_defaults(func=cmd_actions)

    docs_parser = subparsers.add_parser("docs", help="Print Cherri action docs")
    docs_parser.add_argument("category", help="Docs category, e.g. web, scripting")
    docs_parser.add_argument("--subcat", help="Optional docs subcategory")
    docs_parser.set_defaults(func=cmd_docs)

    glyphs_parser = subparsers.add_parser("glyphs", help="Search Shortcut glyphs")
    glyphs_parser.add_argument("query", help="Glyph search term")
    glyphs_parser.set_defaults(func=cmd_glyphs)

    decompile_parser = subparsers.add_parser(
        "decompile",
        help="Convert iCloud link or unsigned Shortcut to Cherri",
    )
    decompile_parser.add_argument("input", help="iCloud link or unsigned .shortcut")
    decompile_parser.add_argument("--output", "-o", help="Output .cherri path")
    decompile_parser.set_defaults(func=cmd_decompile)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except CliError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

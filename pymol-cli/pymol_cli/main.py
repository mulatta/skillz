"""Command line interface for local PyMOL XML-RPC sessions."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import socket
import subprocess
import sys
import time
import xmlrpc.client
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, NoReturn, cast

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9123
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
RESI_RE = re.compile(r"^[A-Za-z0-9_.:+,-]+$")
URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


class CLIError(Exception):
    """User-facing command error."""


def die(message: str, code: int = 1) -> NoReturn:
    print(f"pymol-cli: {message}", file=sys.stderr)
    raise SystemExit(code)


def validate_token(value: str, name: str) -> str:
    if not TOKEN_RE.fullmatch(value):
        raise CLIError(f"invalid {name}: {value!r}")
    return value


def validate_residue_list(value: str) -> str:
    if not RESI_RE.fullmatch(value):
        raise CLIError(f"invalid residue selector: {value!r}")
    return value


def split_csv(value: str) -> list[str]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if not parts:
        raise CLIError("comma-separated value is empty")
    return parts


def is_url(value: str) -> bool:
    return bool(URL_RE.match(value))


def server_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/RPC2"


def make_server(host: str, port: int, timeout: float) -> xmlrpc.client.ServerProxy:
    socket.setdefaulttimeout(timeout)
    return xmlrpc.client.ServerProxy(server_url(host, port), allow_none=True)


def read_pml(path: str) -> list[str]:
    text = sys.stdin.read() if path == "-" else Path(path).read_text()
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def connection_error(host: str, port: int, exc: OSError) -> CLIError:
    return CLIError(f"cannot connect to {server_url(host, port)}: {exc}")


def execute_commands(
    commands: Iterable[str], host: str, port: int, timeout: float
) -> list[Any]:
    server = make_server(host, port, timeout)
    results: list[Any] = []
    try:
        for command in commands:
            results.append(server.do(command))
    except OSError as exc:
        raise connection_error(host, port, exc) from exc
    return results


def resolve_ligand_chains(
    counts: dict[str, int], *, strict: bool, ligand: str
) -> tuple[list[str], list[str]]:
    present = [chain for chain, count in counts.items() if count > 0]
    missing = [chain for chain, count in counts.items() if count == 0]
    if not present or (strict and missing):
        missing_text = ",".join(missing)
        raise CLIError(f"ligand {ligand} not found in chains: {missing_text}")
    return present, missing


def validate_ligand_chains(
    *,
    object_name: str,
    ligand: str,
    chains: Sequence[str],
    host: str,
    port: int,
    timeout: float,
    strict: bool,
) -> tuple[list[str], list[str]]:
    server = make_server(host, port, timeout)
    counts: dict[str, int] = {}
    try:
        for chain in chains:
            selection = f"({object_name} and chain {chain} and resn {ligand})"
            counts[chain] = cast(int, server.count_atoms(selection))
    except OSError as exc:
        raise connection_error(host, port, exc) from exc
    return resolve_ligand_chains(counts, strict=strict, ligand=ligand)


def split_mark_residues(value: str) -> list[str]:
    return [residue for residue in re.split(r"[,+]", value) if residue]


def require_mark_residues(counts: dict[str, int]) -> None:
    missing = [residue for residue, count in counts.items() if count == 0]
    if missing:
        raise CLIError(f"marked residues not found: {','.join(missing)}")


def validate_mark_residues(
    *,
    object_name: str,
    marks: dict[str, str],
    chains: Sequence[str],
    host: str,
    port: int,
    timeout: float,
) -> None:
    server = make_server(host, port, timeout)
    counts: dict[str, int] = {}
    try:
        for chain in chains:
            for residue in split_mark_residues(marks.get(chain, "")):
                selection = f"({object_name} and chain {chain} and resi {residue})"
                counts[f"{chain}:{residue}"] = cast(int, server.count_atoms(selection))
    except OSError as exc:
        raise connection_error(host, port, exc) from exc
    require_mark_residues(counts)


def warn(message: str) -> None:
    print(f"pymol-cli: warning: {message}", file=sys.stderr)


def parse_mapping(
    items: Sequence[str], *, allow_residues: bool = False
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in items:
        if ":" not in item:
            raise CLIError(f"expected CHAIN:VALUE mapping, got {item!r}")
        chain, value = item.split(":", 1)
        validate_token(chain, "chain")
        if allow_residues:
            validate_residue_list(value)
        else:
            validate_token(value, "value")
        mapping[chain] = value
    return mapping


def chain_objects(chains: Sequence[str]) -> list[str]:
    return [f"site_{chain}" for chain in chains]


def selection_union(names: Sequence[str]) -> str:
    return " or ".join(names)


def pml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_pml(path: str, commands: Sequence[str]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(commands) + "\n")
    return output


def generate_load_pml(
    *,
    path: str,
    object_name: str,
    style: str,
    color: str | None,
    orient: bool,
    zoom_buffer: float,
    allow_url: bool,
) -> list[str]:
    validate_token(object_name, "object")
    if color is not None:
        validate_token(color, "color")
    if zoom_buffer < 0:
        raise CLIError("zoom buffer must be non-negative")
    if is_url(path) and not allow_url:
        raise CLIError("remote load URLs require --allow-url")
    lines = [f"load {pml_quote(path)}, {object_name}"]
    if style != "none":
        lines.append(f"hide everything, {object_name}")
        if style == "cartoon":
            lines.append(f"show cartoon, {object_name} and polymer")
        else:
            lines.append(f"show {style}, {object_name}")
    if color is not None:
        lines.append(f"color {color}, {object_name}")
    if orient:
        lines.extend([f"orient {object_name}", f"zoom {object_name}, {zoom_buffer:g}"])
    return lines


def generate_render_pml(
    *, output: str, width: int, height: int, dpi: int, ray: bool
) -> list[str]:
    if width <= 0 or height <= 0:
        raise CLIError("width and height must be positive")
    if dpi <= 0:
        raise CLIError("dpi must be positive")
    lines: list[str] = []
    if ray:
        lines.append(f"ray {width},{height}")
    lines.append(f"png {pml_quote(output)}, {width}, {height}, dpi={dpi}")
    return lines


def generate_ligand_pocket_pml(
    *,
    object_name: str,
    ligand: str,
    chains: Sequence[str],
    distance: float,
    colors: dict[str, str],
    marks: dict[str, str],
    grid: bool,
    scene: str | None,
    disable_source: bool,
    cleanup_chains: Sequence[str] | None = None,
) -> list[str]:
    validate_token(object_name, "object")
    validate_token(ligand, "ligand")
    validated_chains = [validate_token(chain, "chain") for chain in chains]
    cleanup_source = validated_chains if cleanup_chains is None else cleanup_chains
    validated_cleanup_chains = [
        validate_token(chain, "cleanup chain") for chain in cleanup_source
    ]
    for color in colors.values():
        validate_token(color, "color")
    for residues in marks.values():
        validate_residue_list(residues)
    if distance <= 0:
        raise CLIError("distance must be positive")

    sites = chain_objects(validated_chains)
    site_union = selection_union(sites)
    pocket_names = [f"pocket_{chain}" for chain in validated_chains]
    pocket_union = selection_union(pocket_names)
    mark_names = [f"mark_{chain}" for chain in validated_chains if chain in marks]
    mark_union = selection_union(mark_names)
    cleanup_sites = chain_objects(validated_cleanup_chains)
    cleanup_pockets = [f"pocket_{chain}" for chain in validated_cleanup_chains]
    cleanup_marks = [f"mark_{chain}" for chain in validated_cleanup_chains]
    cleanup = [*cleanup_sites, *cleanup_pockets, *cleanup_marks, "pocket_all"]

    lines = [f"delete {selection_union(cleanup)}"]
    if grid:
        lines.extend(["set grid_mode, 1", "set grid_slot, -1"])
    for chain, site in zip(validated_chains, sites):
        lines.append(f"create {site}, ({object_name} and chain {chain})")
    if disable_source:
        lines.append(f"disable {object_name}")
    lines.extend(
        [
            f"hide everything, ({site_union})",
            f"show cartoon, ({site_union}) and polymer",
            f"set cartoon_transparency, 0.65, ({site_union})",
        ]
    )
    for chain, color in colors.items():
        if chain in validated_chains:
            lines.append(f"color {color}, site_{chain} and polymer")
    for chain in validated_chains:
        lines.append(
            f"select pocket_{chain}, site_{chain} and byres "
            f"(polymer within {distance:g} of (site_{chain} and resn {ligand}))"
        )
    lines.extend(
        [
            f"select pocket_all, {pocket_union}",
            "show sticks, pocket_all",
            "color yelloworange, pocket_all",
            f"show sticks, ({site_union}) and resn {ligand}",
            f"color orange, ({site_union}) and resn {ligand}",
            f"show spheres, ({site_union}) and resn {ligand} and name FE",
            f"color tv_red, ({site_union}) and resn {ligand} and name FE",
        ]
    )
    for chain, residues in marks.items():
        if chain in validated_chains:
            selector = residues.replace(",", "+")
            lines.append(f"select mark_{chain}, site_{chain} and resi {selector}")
    if mark_union:
        lines.extend(
            [
                f"show sticks, {mark_union}",
                f"color magenta, {mark_union}",
            ]
        )
    for chain in validated_chains:
        lines.append(
            f'label (site_{chain} and resn {ligand} and name FE), "{chain} {ligand}"'
        )
    for chain in validated_chains:
        if chain in marks:
            lines.append(
                f'label (mark_{chain} and name CA), "{chain} %s%s" % (resn,resi)'
            )
    lines.extend(
        [
            "set label_color, black",
            "set label_size, 18",
            "set stick_radius, 0.18",
            "set sphere_scale, 0.35",
            f"orient ({site_union})",
            f"zoom ({site_union}) and (resn {ligand} or pocket_all), 5",
        ]
    )
    if scene:
        validate_token(scene, "scene")
        lines.append(f"scene {scene}, store")
    return lines


def build_launch_command(
    pymol_command: str,
    *,
    remote: bool,
    script: str | None,
    extra_args: Sequence[str],
) -> list[str]:
    command = shlex.split(pymol_command)
    if not command:
        raise CLIError("pymol command is empty")
    args = list(extra_args)
    if args and args[0] == "--":
        args = args[1:]
    if remote:
        command.append("-R")
    command.extend(args)
    if script:
        command.append(script)
    return command


def emit(data: Any, *, use_json: bool) -> None:
    if use_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    elif isinstance(data, list):
        for item in data:
            print(item)
    else:
        print(data)


def cmd_status(ns: argparse.Namespace) -> None:
    start = time.monotonic()
    try:
        server = make_server(ns.host, ns.port, ns.timeout)
        methods = cast(list[str], server.system.listMethods())
    except OSError as exc:
        raise CLIError(
            f"cannot connect to {server_url(ns.host, ns.port)}: {exc}"
        ) from exc
    elapsed_ms = round((time.monotonic() - start) * 1000, 1)
    payload = {
        "ok": True,
        "url": server_url(ns.host, ns.port),
        "method_count": len(methods),
        "has_do": "do" in methods,
        "elapsed_ms": elapsed_ms,
    }
    emit(
        payload if ns.json else f"connected {payload['url']} ({len(methods)} methods)",
        use_json=ns.json,
    )


def cmd_do(ns: argparse.Namespace) -> None:
    commands: list[str] = []
    commands.extend(ns.command)
    for file_path in ns.file:
        commands.extend(read_pml(file_path))
    if ns.stdin:
        commands.extend(read_pml("-"))
    if not commands:
        raise CLIError("no commands provided")
    if ns.dry_run:
        emit(commands, use_json=ns.json)
        return
    results = execute_commands(commands, ns.host, ns.port, ns.timeout)
    emit(results, use_json=ns.json)


def cmd_script(ns: argparse.Namespace) -> None:
    commands = read_pml(ns.path)
    if ns.dry_run:
        emit(commands, use_json=ns.json)
        return
    results = execute_commands(commands, ns.host, ns.port, ns.timeout)
    emit(results, use_json=ns.json)


def cmd_count(ns: argparse.Namespace) -> None:
    server = make_server(ns.host, ns.port, ns.timeout)
    try:
        count = server.count_atoms(ns.selection)
    except OSError as exc:
        raise connection_error(ns.host, ns.port, exc) from exc
    emit(
        {"selection": ns.selection, "count": count} if ns.json else count,
        use_json=ns.json,
    )


def cmd_load(ns: argparse.Namespace) -> None:
    commands = generate_load_pml(
        path=ns.path,
        object_name=ns.object,
        style=ns.style,
        color=ns.color,
        orient=not ns.no_orient,
        zoom_buffer=ns.zoom_buffer,
        allow_url=ns.allow_url,
    )
    output_path = write_pml(ns.output, commands) if ns.output else None
    if ns.dry_run:
        payload = {
            "commands": commands,
            "output": str(output_path) if output_path else None,
        }
        emit(payload if ns.json else commands, use_json=ns.json)
        return
    results = execute_commands(commands, ns.host, ns.port, ns.timeout)
    payload = {"results": results, "output": str(output_path) if output_path else None}
    emit(
        payload if ns.json else (str(output_path) if output_path else results),
        use_json=ns.json,
    )


def cmd_render(ns: argparse.Namespace) -> None:
    commands = generate_render_pml(
        output=ns.output,
        width=ns.width,
        height=ns.height,
        dpi=ns.dpi,
        ray=ns.ray,
    )
    if ns.dry_run:
        emit(commands, use_json=ns.json)
        return
    results = execute_commands(commands, ns.host, ns.port, ns.timeout)
    payload = {"output": ns.output, "commands": commands, "results": results}
    emit(payload if ns.json else ns.output, use_json=ns.json)


def cmd_launch(ns: argparse.Namespace) -> None:
    command = build_launch_command(
        ns.pymol_command,
        remote=not ns.no_remote,
        script=ns.script,
        extra_args=ns.extra_args,
    )
    if ns.dry_run:
        payload = {
            "command": command,
            "runner": "foreground" if ns.foreground else "pueue",
        }
        emit(payload if ns.json else shlex.join(command), use_json=ns.json)
        return
    if not ns.foreground:
        run_proc = subprocess.run(
            ["pueue", "add", "--print-task-id", "--", *command],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if run_proc.returncode != 0:
            raise CLIError(run_proc.stderr.strip() or "pueue launch failed")
        task_id = run_proc.stdout.strip()
        emit(
            {"task_id": task_id, "command": command} if ns.json else task_id,
            use_json=ns.json,
        )
        return
    popen_proc = subprocess.Popen(command)
    emit(
        {"pid": popen_proc.pid, "command": command} if ns.json else popen_proc.pid,
        use_json=ns.json,
    )


def cmd_ligand_pocket(ns: argparse.Namespace) -> None:
    chains = split_csv(ns.chains)
    requested_chains = chains
    colors = parse_mapping(ns.color)
    marks = parse_mapping(ns.mark, allow_residues=True)
    if ns.send and not ns.no_validate:
        chains, missing = validate_ligand_chains(
            object_name=ns.object,
            ligand=ns.ligand,
            chains=chains,
            host=ns.host,
            port=ns.port,
            timeout=ns.timeout,
            strict=ns.strict_chains,
        )
        if missing:
            warn(
                f"ligand {ns.ligand} missing from chains {','.join(missing)}; "
                "skipping those chains"
            )
        validate_mark_residues(
            object_name=ns.object,
            marks=marks,
            chains=chains,
            host=ns.host,
            port=ns.port,
            timeout=ns.timeout,
        )
    commands = generate_ligand_pocket_pml(
        object_name=ns.object,
        ligand=ns.ligand,
        chains=chains,
        distance=ns.distance,
        colors=colors,
        marks=marks,
        grid=ns.grid,
        scene=ns.scene,
        disable_source=not ns.keep_source,
        cleanup_chains=requested_chains,
    )
    output_path = write_pml(ns.output, commands) if ns.output else None
    if ns.send:
        results = execute_commands(commands, ns.host, ns.port, ns.timeout)
        payload = {
            "results": results,
            "output": str(output_path) if output_path else None,
        }
        emit(
            payload if ns.json else (str(output_path) if output_path else results),
            use_json=ns.json,
        )
        return
    if output_path:
        emit(
            {"path": str(output_path)} if ns.json else str(output_path),
            use_json=ns.json,
        )
        return
    emit(commands, use_json=ns.json)


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("-j", "--json", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pymol-cli")
    sub = parser.add_subparsers(dest="command_name", required=True)

    status = sub.add_parser("status", help="check PyMOL XML-RPC connectivity")
    add_connection_args(status)
    status.set_defaults(func=cmd_status)

    do = sub.add_parser("do", help="send one or more PyMOL commands")
    add_connection_args(do)
    do.add_argument("command", nargs="*")
    do.add_argument("--file", action="append", default=[])
    do.add_argument("--stdin", action="store_true")
    do.add_argument("--dry-run", action="store_true")
    do.set_defaults(func=cmd_do)

    script = sub.add_parser("script", help="send a .pml file or '-' stdin")
    add_connection_args(script)
    script.add_argument("path")
    script.add_argument("--dry-run", action="store_true")
    script.set_defaults(func=cmd_script)

    count = sub.add_parser("count", help="count atoms for a PyMOL selection")
    add_connection_args(count)
    count.add_argument("selection")
    count.set_defaults(func=cmd_count)

    load = sub.add_parser("load", help="load a structure and apply basic styling")
    add_connection_args(load)
    load.add_argument("path")
    load.add_argument("--object", required=True)
    load.add_argument(
        "--style", choices=["none", "cartoon", "sticks", "surface"], default="cartoon"
    )
    load.add_argument("--color")
    load.add_argument("--no-orient", action="store_true")
    load.add_argument("--zoom-buffer", type=float, default=8.0)
    load.add_argument("--allow-url", action="store_true")
    load.add_argument("--output")
    load.add_argument("--dry-run", action="store_true")
    load.set_defaults(func=cmd_load)

    render = sub.add_parser("render", help="write a PNG from the current PyMOL view")
    add_connection_args(render)
    render.add_argument("output")
    render.add_argument("--width", type=int, default=1600)
    render.add_argument("--height", type=int, default=1200)
    render.add_argument("--dpi", type=int, default=200)
    render.add_argument("--ray", action="store_true")
    render.add_argument("--dry-run", action="store_true")
    render.set_defaults(func=cmd_render)

    launch = sub.add_parser("launch", help="start PyMOL with XML-RPC enabled")
    launch.add_argument("--pymol-command", default="nix run nixpkgs#pymol --")
    launch.add_argument("--script")
    launch.add_argument("--no-remote", action="store_true")
    launch.add_argument("--foreground", action="store_true")
    launch.add_argument("--pueue", action="store_true", help=argparse.SUPPRESS)
    launch.add_argument("--dry-run", action="store_true")
    launch.add_argument("-j", "--json", action="store_true")
    launch.add_argument("extra_args", nargs=argparse.REMAINDER)
    launch.set_defaults(func=cmd_launch)

    pocket = sub.add_parser("ligand-pocket", help="generate or send ligand-pocket view")
    add_connection_args(pocket)
    pocket.add_argument("--object", default="all")
    pocket.add_argument("--ligand", default="HEM")
    pocket.add_argument("--chains", required=True)
    pocket.add_argument("--distance", type=float, default=4.0)
    pocket.add_argument("--color", action="append", default=[], help="CHAIN:COLOR")
    pocket.add_argument("--mark", action="append", default=[], help="CHAIN:RESI[,RESI]")
    pocket.add_argument("--grid", action="store_true")
    pocket.add_argument("--scene")
    pocket.add_argument("--keep-source", action="store_true")
    pocket.add_argument("--output")
    validation = pocket.add_mutually_exclusive_group()
    validation.add_argument("--no-validate", action="store_true")
    validation.add_argument("--strict-chains", action="store_true")
    pocket.add_argument("--send", action="store_true")
    pocket.set_defaults(func=cmd_ligand_pocket)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    ns = parser.parse_args(argv)
    try:
        ns.func(ns)
    except CLIError as exc:
        die(str(exc))
    except xmlrpc.client.Error as exc:
        die(f"xml-rpc error: {exc}")


if __name__ == "__main__":
    main()

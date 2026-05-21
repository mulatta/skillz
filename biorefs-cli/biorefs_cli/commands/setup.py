"""Setup command."""

from __future__ import annotations

import argparse
from pathlib import Path

from biorefs_cli.config import (
    check_configured_secrets,
    config_to_public_dict,
    default_config_path,
    load_config,
    merge_config,
    write_config,
)
from biorefs_cli.errors import ConfigError
from biorefs_cli.output import print_json


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("setup", help="Write or check biorefs-cli config")
    parser.add_argument("--email")
    parser.add_argument("--ncbi-api-key-command")
    parser.add_argument("--semantic-scholar-api-key-command")
    parser.add_argument("--timeout-seconds", type=positive_int)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    path = args.config or default_config_path()
    updates = {
        "email": args.email,
        "ncbi_api_key_command": args.ncbi_api_key_command,
        "semantic_scholar_api_key_command": args.semantic_scholar_api_key_command,
        "timeout_seconds": args.timeout_seconds,
    }
    changed = any(value is not None for value in updates.values())
    if args.check and not changed and not path.exists():
        msg = f"config file not found: {path}"
        raise ConfigError(msg)

    current = load_config(path)
    updated = merge_config(current, updates)
    if changed:
        path = write_config(updated, path)
    if args.check:
        results = check_configured_secrets(updated)
        print_json(
            {
                "status": "ok",
                "config_path": str(path),
                "checked": [result.name for result in results if result.ok],
            }
        )
        return 0
    if changed:
        print_json({"status": "ok", "config_path": str(path)})
        return 0
    print_json({"status": "ok", "config": config_to_public_dict(current)})
    return 0


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        msg = "must be a positive integer"
        raise argparse.ArgumentTypeError(msg) from exc
    if parsed <= 0:
        msg = "must be a positive integer"
        raise argparse.ArgumentTypeError(msg)
    return parsed

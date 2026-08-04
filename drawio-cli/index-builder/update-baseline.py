#!/usr/bin/env python3
# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

_HASH = re.compile(r"[0-9a-f]{64}")


def _object(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"manifest {key!r} must be an object")
    return value


def _integer(data: dict[str, Any], key: str, *, positive: bool = False) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"manifest {key!r} must be an integer")
    if positive and value <= 0:
        raise ValueError(f"manifest {key!r} must be positive")
    return value


def candidate_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("complete") is not True:
        raise ValueError("candidate manifest is incomplete")

    registrations = _integer(manifest, "registrations", positive=True)
    executed = _integer(manifest, "executedFactories", positive=True)
    if registrations != executed:
        raise ValueError("not all registered factories were executed")

    resources = _object(manifest, "resources")
    _integer(resources, "requested", positive=True)
    if _integer(resources, "failed") != 0 or _integer(resources, "remote") != 0:
        raise ValueError("candidate used failed or remote resources")

    canaries = _object(manifest, "canaries")
    if not canaries or any(value is not True for value in canaries.values()):
        raise ValueError("candidate is missing required canaries")

    kind_counts = _object(manifest, "kindCounts")
    if not kind_counts:
        raise ValueError("candidate has no shape kinds")
    normalized_kinds = {
        key: _integer(kind_counts, key, positive=True) for key in sorted(kind_counts)
    }
    entries = _integer(manifest, "entriesAfterDedup", positive=True)
    captured = _integer(manifest, "capturedItems", positive=True)
    if sum(normalized_kinds.values()) != entries:
        raise ValueError("shape kind counts do not match entry count")
    if captured < entries:
        raise ValueError("captured item count is smaller than entry count")

    version = manifest.get("drawioVersion")
    digest = manifest.get("indexSha256")
    if not isinstance(version, str) or not version:
        raise ValueError("manifest drawioVersion must be a non-empty string")
    if not isinstance(digest, str) or _HASH.fullmatch(digest) is None:
        raise ValueError("manifest indexSha256 must be a SHA-256 digest")

    return {
        "drawioVersion": version,
        "entryCount": entries,
        "indexSha256": digest,
        "registrations": registrations,
        "capturedItems": captured,
        "kindCounts": normalized_kinds,
    }


def _serialized(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=False) + "\n"


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", text=True
    )
    os.fchmod(descriptor, mode)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _diff(current: str, candidate: str, expected: Path) -> str:
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=str(expected),
            tofile="candidate-index-baseline.json",
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check or accept a generated draw.io shape index baseline"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--expected",
        type=Path,
        default=Path("drawio-cli/index-builder/expected-index.json"),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", dest="mode", action="store_const", const="check")
    mode.add_argument("--accept", dest="mode", action="store_const", const="accept")
    parser.set_defaults(mode="accept")
    return parser


def run(args: argparse.Namespace) -> int:
    manifest = _read_object(args.manifest)
    candidate = _serialized(candidate_summary(manifest))
    current = (
        args.expected.read_text(encoding="utf-8") if args.expected.exists() else ""
    )
    if current == candidate:
        print(f"shape index baseline is current: {args.expected}")
        return 0

    print(_diff(current, candidate, args.expected), end="")
    if args.mode == "check":
        print("shape index baseline drifted", file=sys.stderr)
        return 1

    _atomic_write(args.expected, candidate)
    print(f"updated shape index baseline: {args.expected}")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return run(args)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"update failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

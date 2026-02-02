#!/usr/bin/env python3
"""Verify CUDA linkage and RPATH in Nix-built binaries.

Checks for common CUDA packaging issues:
- Missing CUDA libraries
- Incorrect RPATH configuration
- Build path leakage (/build/ in strings)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# CUDA library to nixpkgs attribute mapping
CUDA_LIB_ATTRS = {
    "libcuda.so": None,  # Driver-provided, not packageable
    "libcudart.so": "cudaPackages.cuda_cudart",
    "libnvrtc.so": "cudaPackages.cuda_nvrtc",
    "libcublas.so": "cudaPackages.libcublas",
    "libcublasLt.so": "cudaPackages.libcublas",
    "libcudnn.so": "cudaPackages.cudnn",
    "libnccl.so": "cudaPackages.nccl",
    "libcufft.so": "cudaPackages.libcufft",
    "libcurand.so": "cudaPackages.libcurand",
    "libcusolver.so": "cudaPackages.libcusolver",
    "libcusparse.so": "cudaPackages.libcusparse",
    "libcupti.so": "cudaPackages.cuda_cupti",
    "libnvToolsExt.so": "cudaPackages.cuda_nvtx",
    "libnvJitLink.so": "cudaPackages.cuda_nvjitlink",
}

# Libraries that are driver-provided (ignore "not found")
DRIVER_PROVIDED = {"libcuda.so.1", "libcuda.so"}


def run_command(cmd: list[str]) -> tuple[int, str, str]:
    """Run command and return (returncode, stdout, stderr)."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout, result.stderr


def find_elf_files(path: Path) -> list[Path]:
    """Find all ELF binaries and shared libraries."""
    elfs = []
    if path.is_file():
        # Check if it's an ELF file
        _, stdout, _ = run_command(["file", "-b", str(path)])
        if "ELF" in stdout:
            elfs.append(path)
    elif path.is_dir():
        for subpath in path.rglob("*"):
            if subpath.is_file():
                _, stdout, _ = run_command(["file", "-b", str(subpath)])
                if "ELF" in stdout:
                    elfs.append(subpath)
    return elfs


def check_ldd(binary: Path) -> dict[str, Any]:
    """Analyze library dependencies with ldd."""
    _, stdout, _ = run_command(["ldd", str(binary)])

    libs: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    for raw_line in stdout.strip().split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        # Parse ldd output: "libname.so => /path/to/lib (addr)" or "libname.so => not found"
        if "=>" in line:
            parts = line.split("=>")
            lib_name = parts[0].strip().split()[0]
            location = parts[1].strip()

            if "not found" in location:
                # Check if it's a CUDA library
                base_name = lib_name.split(".so")[0] + ".so"
                if base_name in CUDA_LIB_ATTRS or lib_name in DRIVER_PROVIDED:
                    if lib_name in DRIVER_PROVIDED or base_name in DRIVER_PROVIDED:
                        libs[lib_name] = {"found": False, "driver_provided": True}
                    else:
                        libs[lib_name] = {"found": False, "path": None}
                        missing.append(lib_name)
            else:
                lib_path = location.split("(")[0].strip()
                if lib_path:
                    base_name = lib_name.split(".so")[0] + ".so"
                    if base_name in CUDA_LIB_ATTRS:
                        libs[lib_name] = {"found": True, "path": lib_path}

    return {"cuda_libs": libs, "missing": missing}


def check_rpath(binary: Path) -> list[str]:
    """Get RPATH entries."""
    _, stdout, _ = run_command(["patchelf", "--print-rpath", str(binary)])
    rpath = stdout.strip()
    if not rpath:
        return []
    return [p for p in rpath.split(":") if p]


def check_build_path_leak(binary: Path) -> bool:
    """Check for /build/ path contamination."""
    _, stdout, _ = run_command(["strings", str(binary)])
    return "/build/" in stdout


def generate_fix(lib_name: str) -> str | None:
    """Generate fix suggestion for missing library."""
    base_name = lib_name.split(".so")[0] + ".so"
    attr = CUDA_LIB_ATTRS.get(base_name)
    if attr:
        return f"Add {attr} to buildInputs"
    return None


def check_binary(binary: Path) -> dict[str, Any]:
    """Run all checks on a single binary."""
    result: dict[str, Any] = {
        "binary": str(binary),
        "issues": [],
    }

    # ldd check
    ldd_result = check_ldd(binary)
    result["cuda_libs"] = ldd_result["cuda_libs"]

    for lib in ldd_result["missing"]:
        fix = generate_fix(lib)
        base_name = lib.split(".so")[0] + ".so"
        result["issues"].append(
            {
                "type": "missing_lib",
                "lib": lib,
                "nix_attr": CUDA_LIB_ATTRS.get(base_name),
                "fix": fix,
            }
        )

    # RPATH check
    result["rpath"] = check_rpath(binary)

    # Build path leak check
    result["build_path_leak"] = check_build_path_leak(binary)
    if result["build_path_leak"]:
        result["issues"].append(
            {
                "type": "build_path_leak",
                "fix": "Add noAuditTmpdir = true; and use patchelf --shrink-rpath in postFixup",
            }
        )

    result["status"] = "PASS" if not result["issues"] else "FAIL"
    return result


def _shorten_nix_path(path: str) -> str:
    """Shorten /nix/store/... paths for display."""
    if path.startswith("/nix/store/"):
        return "/nix/store/..." + path[43:]
    return path


def _print_cuda_libs(cuda_libs: dict[str, dict[str, Any]]) -> None:
    """Print CUDA libraries section."""
    print("\nCUDA Libraries:")
    for lib, info in sorted(cuda_libs.items()):
        if info.get("driver_provided"):
            print(f"  ○ {lib:<24} driver-provided (OK)")
        elif info.get("found"):
            path = _shorten_nix_path(info.get("path", ""))
            print(f"  \033[32m✓\033[0m {lib:<24} {path}")
        else:
            print(f"  \033[31m✗\033[0m {lib:<24} NOT FOUND")


def _print_rpath(rpath: list[str]) -> None:
    """Print RPATH section."""
    print("\nRPATH:")
    for entry in rpath:
        print(f"  {_shorten_nix_path(entry)}")


def _print_issues(issues: list[dict[str, Any]]) -> None:
    """Print issues summary."""
    print(f"\n\033[33mIssues ({len(issues)}):\033[0m")
    for issue in issues:
        print(f"  • {issue['type']}: {issue.get('lib', '')}")
        if issue.get("fix"):
            print(f"    └─ Fix: {issue['fix']}")


def print_result(result: dict[str, Any], verbose: bool = False) -> None:
    """Print human-readable result."""
    status = result["status"]
    status_symbol = "\033[32m✓\033[0m" if status == "PASS" else "\033[31m✗\033[0m"
    print(f"\n{status_symbol} {result['binary']}")
    print("─" * 60)

    cuda_libs = result.get("cuda_libs", {})
    if cuda_libs or verbose:
        _print_cuda_libs(cuda_libs)

    if verbose and result.get("rpath"):
        _print_rpath(result["rpath"])

    if result.get("build_path_leak"):
        print("\n\033[31m✗\033[0m Build path leak: /build/ found in strings")

    issues = result.get("issues", [])
    if issues:
        _print_issues(issues)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify CUDA linkage in Nix-built binaries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cuda-check ./result/bin/train
  cuda-check /nix/store/xxx-package/
  cuda-check --json ./result/bin/app

Output:
  Checks CUDA library linkage, RPATH configuration,
  and build path contamination. Suggests fixes for
  common Nix CUDA packaging issues.
""",
    )
    parser.add_argument("path", type=Path, help="Binary or directory to check")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--all", action="store_true", help="Check all ELF files in directory"
    )

    args = parser.parse_args()

    if not args.path.exists():
        print(f"Error: {args.path} does not exist", file=sys.stderr)
        return 1

    # Find files to check
    if args.all or args.path.is_dir():
        files = find_elf_files(args.path)
        if not files:
            print(f"No ELF files found in {args.path}", file=sys.stderr)
            return 1
    else:
        files = [args.path]

    results = []
    has_issues = False

    for f in files:
        result = check_binary(f)
        results.append(result)
        if result["status"] == "FAIL":
            has_issues = True

    if args.json:
        if len(results) == 1:
            print(json.dumps(results[0], indent=2))
        else:
            print(json.dumps({"files": results}, indent=2))
    else:
        for result in results:
            print_result(result, args.verbose)

        # Summary
        if len(results) > 1:
            passed = sum(1 for r in results if r["status"] == "PASS")
            print(f"\n{'─' * 60}")
            print(f"Summary: {passed}/{len(results)} files passed")

    return 1 if has_issues else 0


if __name__ == "__main__":
    sys.exit(main())

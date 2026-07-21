from __future__ import annotations

import os
import tempfile
from pathlib import Path


def same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except FileNotFoundError:
        return left.resolve() == right.resolve()


def atomic_write_bytes(
    path: Path, data: bytes, mode: int | None = None, *, overwrite: bool = True
) -> None:
    """Publish complete bytes from a temporary file in the target directory."""
    path = path.resolve()
    parent = path.parent
    target_mode = mode
    if target_mode is None:
        target_mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=parent)
    os.fchmod(fd, target_mode)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            tmp.replace(path)
        else:
            os.link(tmp, path)
            tmp.unlink()
        dir_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

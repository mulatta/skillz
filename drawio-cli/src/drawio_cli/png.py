from __future__ import annotations

import zlib
from pathlib import Path

IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _validate_chunks(data: bytes, *, allow_missing_iend: bool = False) -> None:
    if not data.startswith(PNG_MAGIC):
        raise ValueError("invalid PNG signature")
    offset = len(PNG_MAGIC)
    first = True
    saw_idat = False
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError("invalid PNG truncated chunk")
        length = int.from_bytes(data[offset : offset + 4], "big")
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("invalid PNG truncated chunk")
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 4 : offset + 8 + length]
        expected_crc = int.from_bytes(data[offset + 8 + length : end], "big")
        if zlib.crc32(payload) != expected_crc:
            raise ValueError("invalid PNG chunk checksum")
        if first and (kind != b"IHDR" or length != 13):
            raise ValueError("invalid PNG IHDR")
        first = False
        saw_idat = saw_idat or kind == b"IDAT"
        offset = end
        if kind == b"IEND":
            if length != 0 or offset != len(data):
                raise ValueError("invalid PNG IEND")
            if not saw_idat:
                raise ValueError("invalid PNG missing IDAT")
            return
    if not allow_missing_iend:
        raise ValueError("invalid PNG missing IEND")
    if first or not saw_idat:
        raise ValueError("invalid PNG incomplete image")


def repair_png_iend(path: Path) -> bool:
    data = path.read_bytes()
    if data.endswith(IEND):
        return False
    try:
        _validate_chunks(data, allow_missing_iend=True)
    except ValueError:
        if not data.endswith(b"\x00\x00\x00\x00"):
            raise
        data = data[:-4]
        _validate_chunks(data, allow_missing_iend=True)
    path.write_bytes(data + IEND)
    return True


def assert_png(path: Path) -> None:
    _validate_chunks(path.read_bytes())

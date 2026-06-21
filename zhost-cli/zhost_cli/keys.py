"""Zotero object-key helpers.

A Zotero object key is exactly 8 characters from a 32-symbol alphabet that omits
the ambiguous 0/1/O/L. The sync client rejects anything else with "key is not
valid", and zhost validates the same invariant server-side (returns 400). The
CLI never mints keys: keyless writes let the server assign one. These helpers
exist only to validate user-supplied keys before a request round-trip.
"""

from __future__ import annotations

KEY_ALPHABET = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
KEY_LENGTH = 8


def valid_object_key(key: str) -> bool:
    return len(key) == KEY_LENGTH and all(ch in KEY_ALPHABET for ch in key)

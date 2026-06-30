"""Zotero object-key helpers.

A Zotero object key is exactly 8 characters from a 32-symbol alphabet that omits
the ambiguous 0/1/O/L. The sync client rejects anything else with "key is not
valid", and zhost validates the same invariant server-side (returns 400). The
CLI usually lets the server assign keys, but archive imports can mint keys
client-side so parent/collection references can be remapped before writes.
"""

from __future__ import annotations

import secrets
from collections.abc import Container

KEY_ALPHABET = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
KEY_LENGTH = 8


def mint_object_key(used: Container[str] = ()) -> str:
    """Mint a Zotero-style key that is not in `used`."""
    while True:
        key = "".join(secrets.choice(KEY_ALPHABET) for _ in range(KEY_LENGTH))
        if key not in used:
            return key


def valid_object_key(key: str) -> bool:
    return len(key) == KEY_LENGTH and all(ch in KEY_ALPHABET for ch in key)

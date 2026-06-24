"""Shared structure/protein identifier validation.

PDB ids and UniProt accessions are validated the same way wherever they appear
(the `structure` and `uniprot` commands), so the rules live here rather than
being copy-pasted per module.
"""

from __future__ import annotations

import re

from biorefs_cli.errors import CLIError

# Classic 4-character PDB id (1abc) plus the extended pdb_0000XXXX form.
PDB_ID_RE = re.compile(r"^[1-9][A-Za-z0-9]{3}$")
EXTENDED_PDB_ID_RE = re.compile(r"^pdb_[0-9a-z]{8}$")
# UniProtKB accession syntax, optional isoform suffix (e.g. P38398-2).
UNIPROT_ACCESSION_RE = re.compile(
    r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})"
    r"(?:-[0-9]+)?$"
)


def normalize_pdb_id(value: str) -> str:
    raw = value.strip()
    extended = raw.lower()
    if EXTENDED_PDB_ID_RE.fullmatch(extended):
        return extended
    upper = raw.upper()
    if PDB_ID_RE.fullmatch(upper):
        return upper
    msg = f"invalid PDB id: {value}"
    raise CLIError(msg, exit_code=2)


def normalize_uniprot_accession(value: str) -> str:
    accession = value.strip().upper()
    if not accession or not UNIPROT_ACCESSION_RE.fullmatch(accession):
        msg = f"invalid UniProt accession: {value}"
        raise CLIError(msg, exit_code=2)
    return accession

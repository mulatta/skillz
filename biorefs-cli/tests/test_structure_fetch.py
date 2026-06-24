from __future__ import annotations

from pathlib import Path

import pytest
from biorefs_cli.commands.structure import (
    AlphaFoldFile,
    FetchResult,
    FetchService,
    first_prediction,
    write_structure,
)
from biorefs_cli.errors import HTTPError
from biorefs_cli.main import main


class FakeBackend:
    def __init__(
        self,
        *,
        rcsb: bytes = b"",
        alphafold: AlphaFoldFile | None = None,
    ) -> None:
        self.rcsb_bytes = rcsb
        self.alphafold_file = alphafold
        self.rcsb_calls: list[tuple[str, str, int | None]] = []
        self.af_calls: list[tuple[str, str]] = []

    def rcsb_structure(
        self, pdb_id: str, fmt: str, assembly: int | None = None
    ) -> bytes:
        self.rcsb_calls.append((pdb_id, fmt, assembly))
        return self.rcsb_bytes

    def alphafold_structure(self, accession: str, fmt: str) -> AlphaFoldFile:
        self.af_calls.append((accession, fmt))
        assert self.alphafold_file is not None
        return self.alphafold_file


def test_fetch_rcsb_metadata() -> None:
    backend = FakeBackend(rcsb=b"data_1JM7\n")
    result = FetchService(backend).fetch_rcsb("1jm7", "cif")
    assert backend.rcsb_calls == [("1JM7", "cif", None)]
    assert result.filename == "1jm7.cif"
    assert result.payload["id"] == "1JM7"
    assert "files.rcsb.org/download/1JM7.cif" in str(result.payload["url"])


def test_fetch_rcsb_assembly() -> None:
    backend = FakeBackend(rcsb=b"x\n")
    result = FetchService(backend).fetch_rcsb("1JM7", "cif", assembly=1)
    assert backend.rcsb_calls == [("1JM7", "cif", 1)]
    assert result.filename == "1jm7-assembly1.cif"
    assert result.payload["assembly"] == 1


def test_fetch_alphafold_model_id() -> None:
    af = AlphaFoldFile(
        b"af\n",
        "https://alphafold.ebi.ac.uk/files/AF-P38398-F1-model_v4.cif",
        "AF-P38398-F1-model_v4",
    )
    result = FetchService(FakeBackend(alphafold=af)).fetch_alphafold("p38398", "cif")
    assert result.filename == "AF-P38398-F1-model_v4.cif"
    assert result.payload["source"] == "alphafold"


def test_write_structure(tmp_path: Path) -> None:
    result = FetchResult(b"abc", "1jm7.cif", {})
    path = write_structure(result, out_dir=str(tmp_path), output=None)
    assert path.read_bytes() == b"abc"


def test_first_prediction_parses_list() -> None:
    prediction = first_prediction(b'[{"cifUrl": "https://x/m.cif"}]')
    assert str(prediction["cifUrl"]).endswith("m.cif")
    with pytest.raises(HTTPError):
        first_prediction(b"[]")


def test_cli_requires_exactly_one_target(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["structure", "fetch"])
    assert status == 2
    assert "exactly one" in capsys.readouterr().err


def test_cli_assembly_rejected_with_uniprot(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["structure", "fetch", "--uniprot", "P38398", "--assembly", "1"])
    assert status == 2
    assert "--assembly" in capsys.readouterr().err

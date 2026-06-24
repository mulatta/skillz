from __future__ import annotations

import json
from pathlib import Path

import pytest
from biorefs_cli.commands.structure import (
    AlphaFoldFile,
    FetchClient,
    FetchResult,
    FetchService,
    first_prediction,
    write_structure,
)
from biorefs_cli.config import Config
from biorefs_cli.errors import CLIError, HTTPError
from biorefs_cli.http import HttpClient, HttpResponse
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


class StubHttp(HttpClient):
    """Return a canned prediction JSON, then canned file bytes, by URL."""

    def __init__(self, prediction: object) -> None:
        super().__init__(timeout_seconds=3)
        self.prediction = prediction
        self.fetched_urls: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_source: str | None = None,
    ) -> HttpResponse:
        self.fetched_urls.append(url)
        if "/api/prediction/" in url:
            body = json.dumps(self.prediction).encode("utf-8")
            return HttpResponse(status=200, headers={}, body=body)
        return HttpResponse(status=200, headers={}, body=b"data_AF\n")


def prediction(**urls: str) -> list[dict[str, str]]:
    return [{"entryId": "AF-P38398-F1", **urls}]


def test_alphafold_client_selects_cif_url_and_derives_model_id() -> None:
    http = StubHttp(
        prediction(
            cifUrl="https://alphafold.ebi.ac.uk/files/AF-P38398-F1-model_v4.cif",
            pdbUrl="https://alphafold.ebi.ac.uk/files/AF-P38398-F1-model_v4.pdb",
        )
    )
    client = FetchClient(config=Config(), http=http)

    result = client.alphafold_structure("P38398", "cif")

    assert result.model_id == "AF-P38398-F1-model_v4"
    assert result.url.endswith("model_v4.cif")
    assert result.content == b"data_AF\n"


def test_alphafold_client_selects_pdb_url() -> None:
    http = StubHttp(
        prediction(pdbUrl="https://alphafold.ebi.ac.uk/files/AF-P38398-F1-model_v4.pdb")
    )
    client = FetchClient(config=Config(), http=http)

    result = client.alphafold_structure("P38398", "pdb")

    assert result.url.endswith("model_v4.pdb")


def test_alphafold_client_raises_when_requested_format_missing() -> None:
    http = StubHttp(prediction(cifUrl="https://x/AF-P38398-F1-model_v4.cif"))
    client = FetchClient(config=Config(), http=http)

    with pytest.raises(CLIError, match="no pdb model"):
        client.alphafold_structure("P38398", "pdb")


def test_fetch_rcsb_pdb_format_extension() -> None:
    backend = FakeBackend(rcsb=b"data\n")
    result = FetchService(backend).fetch_rcsb("1JM7", "pdb")
    assert backend.rcsb_calls == [("1JM7", "pdb", None)]
    assert result.filename == "1jm7.pdb"
    assert str(result.payload["url"]).endswith("1JM7.pdb")


def test_cli_requires_exactly_one_target(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["structure", "fetch"])
    assert status == 2
    assert "exactly one" in capsys.readouterr().err


def test_cli_assembly_rejected_with_uniprot(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["structure", "fetch", "--uniprot", "P38398", "--assembly", "1"])
    assert status == 2
    assert "--assembly" in capsys.readouterr().err

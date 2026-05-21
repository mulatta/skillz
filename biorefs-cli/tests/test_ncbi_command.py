from __future__ import annotations

import json
import shlex
import sys
import urllib.parse
from typing import TYPE_CHECKING

import pytest
from biorefs_cli.commands import ncbi
from biorefs_cli.config import Config
from biorefs_cli.http import HttpClient, HttpResponse, RetryPolicy
from biorefs_cli.main import build_parser, main
from biorefs_cli.ncbi_client import NCBIClient
from biorefs_cli.rate_limit import RateLimiter, RateLimitPolicy

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


class RecordingLimiter(RateLimiter):
    def __init__(self) -> None:
        self.sources: list[str | RateLimitPolicy | None] = []

    def acquire(self, source: str | RateLimitPolicy | None) -> None:
        self.sources.append(source)


class RecordingHttpClient(HttpClient):
    def __init__(
        self,
        responses: list[HttpResponse],
        *,
        attempts: int = 3,
    ) -> None:
        self.limiter = RecordingLimiter()
        super().__init__(
            timeout_seconds=7,
            retry_policy=RetryPolicy(attempts=attempts, base_delay_seconds=0.5),
            rate_limiter=self.limiter,
        )
        self.responses = responses
        self.urls: list[str] = []
        self.sleep_calls: list[tuple[int, float | None]] = []

    def _get_once(self, url: str, *, headers: dict[str, str]) -> HttpResponse:
        assert headers is not None
        self.urls.append(url)
        return self.responses.pop(0)

    def _sleep(self, attempt: int, retry_after_seconds: float | None) -> None:
        self.sleep_calls.append((attempt, retry_after_seconds))


def json_response(
    payload: object,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> HttpResponse:
    return HttpResponse(
        status=status,
        headers=headers or {},
        body=json.dumps(payload).encode(),
    )


def text_response(
    payload: str,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> HttpResponse:
    return HttpResponse(status=status, headers=headers or {}, body=payload.encode())


def make_client(http: RecordingHttpClient) -> NCBIClient:
    return NCBIClient(config=Config(email="user@example.org"), http=http)


def parse_args(argv: list[str]) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def query_params(url: str) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


def test_search_constructs_esearch_query_and_uses_ncbi_rate_limit() -> None:
    http = RecordingHttpClient(
        [
            json_response(
                {
                    "esearchresult": {
                        "count": "2",
                        "retstart": "0",
                        "idlist": ["1", "2"],
                        "querytranslation": "BRCA1[Title/Abstract]",
                        "webenv": "NCBI_WE",
                        "querykey": "1",
                    },
                },
            ),
        ],
    )
    args = parse_args(
        [
            "ncbi",
            "search",
            "--db",
            "pubmed",
            "--query",
            "BRCA1[Title/Abstract]",
            "--limit",
            "20",
            "--use-history",
            "--json",
        ],
    )

    result = ncbi.execute(args, make_client(http))

    assert isinstance(result, dict)
    assert urllib.parse.urlparse(http.urls[0]).path.endswith("/esearch.fcgi")
    params = query_params(http.urls[0])
    assert params["db"] == ["pubmed"]
    assert params["term"] == ["BRCA1[Title/Abstract]"]
    assert params["retmax"] == ["20"]
    assert params["usehistory"] == ["y"]
    assert params["tool"] == ["biorefs-cli"]
    assert params["email"] == ["user@example.org"]
    assert "api_key" not in params
    assert http.limiter.sources == ["ncbi"]
    assert result["ids"] == ["1", "2"]
    assert result["history"] == {"webenv": "NCBI_WE", "query_key": "1"}


def test_summary_preserves_source_fields_and_adds_provenance() -> None:
    http = RecordingHttpClient(
        [
            json_response(
                {
                    "result": {
                        "uids": ["672"],
                        "672": {
                            "uid": "672",
                            "name": "BRCA1",
                            "description": "BRCA1 DNA repair associated",
                            "extra_field": {"kept": True},
                        },
                    },
                },
            ),
        ],
    )
    args = parse_args(["ncbi", "summary", "--db", "gene", "--id", "672", "--json"])

    result = ncbi.execute(args, make_client(http))

    assert isinstance(result, dict)
    records = result["records"]
    assert isinstance(records, list)
    assert records[0]["extra_field"] == {"kept": True}
    assert records[0]["provenance"]["endpoint"] == "esummary"
    assert query_params(http.urls[0])["retmode"] == ["json"]


def test_fetch_format_mapping_and_raw_body() -> None:
    assert ncbi.map_fetch_format("protein", "fasta") == ncbi.FetchFormatMapping(
        retmode="text",
        rettype="fasta",
    )
    assert ncbi.map_fetch_format("nuccore", "genbank") == ncbi.FetchFormatMapping(
        retmode="text",
        rettype="gbwithparts",
    )
    assert ncbi.map_fetch_format("protein", "genbank") == ncbi.FetchFormatMapping(
        retmode="text",
        rettype="gb",
    )
    assert ncbi.map_fetch_format("gene", "json") == ncbi.FetchFormatMapping(
        retmode="xml",
        rettype=None,
        native_json=False,
    )

    http = RecordingHttpClient([text_response(">NP_009225\nMEEP\n")])
    args = parse_args(
        [
            "ncbi",
            "fetch",
            "--db",
            "protein",
            "--id",
            "NP_009225",
            "--format",
            "fasta",
            "--raw",
        ],
    )

    result = ncbi.execute(args, make_client(http))

    assert result == ">NP_009225\nMEEP\n"
    params = query_params(http.urls[0])
    assert params["retmode"] == ["text"]
    assert params["rettype"] == ["fasta"]
    assert http.limiter.sources == ["ncbi"]


def test_fetch_json_wraps_xml_when_ncbi_has_no_native_json() -> None:
    http = RecordingHttpClient([text_response("<Entrezgene-Set />")])
    args = parse_args(
        ["ncbi", "fetch", "--db", "gene", "--id", "672", "--format", "json"],
    )

    result = ncbi.execute(args, make_client(http))

    assert isinstance(result, dict)
    assert result["content"] == "<Entrezgene-Set />"
    assert result["retmode"] == "xml"
    assert query_params(http.urls[0])["retmode"] == ["xml"]


def test_link_groups_linked_ids_by_linkname() -> None:
    http = RecordingHttpClient(
        [
            json_response(
                {
                    "linksets": [
                        {
                            "ids": ["672"],
                            "linksetdbs": [
                                {
                                    "dbto": "pubmed",
                                    "linkname": "gene_pubmed",
                                    "links": ["1", {"id": "2", "score": 91}],
                                },
                            ],
                        },
                    ],
                },
            ),
        ],
    )
    args = parse_args(
        [
            "ncbi",
            "link",
            "--dbfrom",
            "gene",
            "--db",
            "pubmed",
            "--id",
            "672",
            "--json",
        ],
    )

    result = ncbi.execute(args, make_client(http))

    assert isinstance(result, dict)
    linksets = result["linksets"]
    assert isinstance(linksets, list)
    assert linksets[0]["link_name"] == "gene_pubmed"
    assert linksets[0]["ids"] == ["1", "2"]
    assert linksets[0]["links"][1]["score"] == 91
    assert query_params(http.urls[0])["retmode"] == ["json"]


def test_429_retries_with_retry_after() -> None:
    http = RecordingHttpClient(
        [
            json_response({}, status=429, headers={"retry-after": "4"}),
            json_response({"esearchresult": {"count": "0", "idlist": []}}),
        ],
        attempts=2,
    )
    args = parse_args(
        ["ncbi", "search", "--db", "pubmed", "--query", "none", "--limit", "1"],
    )

    result = ncbi.execute(args, make_client(http))

    assert isinstance(result, dict)
    assert result["ids"] == []
    assert http.sleep_calls == [(0, 4.0)]
    assert len(http.urls) == 2


def test_429_retries_with_backoff_without_retry_after() -> None:
    http = RecordingHttpClient(
        [
            json_response({}, status=429),
            json_response({"esearchresult": {"count": "0", "idlist": []}}),
        ],
        attempts=2,
    )
    args = parse_args(
        ["ncbi", "search", "--db", "pubmed", "--query", "none", "--limit", "1"],
    )

    ncbi.execute(args, make_client(http))

    assert http.sleep_calls == [(0, None)]
    assert len(http.urls) == 2


def test_credential_command_output_not_leaked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_dir = tmp_path / "biorefs-cli"
    config_dir.mkdir()
    command = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
        "import sys; print('credential-output'); sys.exit(1)"
    )
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "email": "user@example.org",
                "ncbi_api_key_command": command,
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    status = main(
        ["ncbi", "search", "--db", "pubmed", "--query", "BRCA1", "--limit", "1"],
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "credential command failed" in captured.err
    assert "credential-output" not in captured.err
    assert command not in captured.err


def test_cli_argument_validation() -> None:
    with pytest.raises(SystemExit) as missing:
        parse_args(["ncbi", "search"])
    with pytest.raises(SystemExit) as bad_limit:
        parse_args(
            ["ncbi", "search", "--db", "pubmed", "--query", "BRCA1", "--limit", "0"],
        )
    with pytest.raises(SystemExit) as bad_format:
        parse_args(
            [
                "ncbi",
                "fetch",
                "--db",
                "gene",
                "--id",
                "672",
                "--format",
                "pdf",
            ],
        )
    with pytest.raises(SystemExit) as no_doctor:
        parse_args(["doctor"])

    assert missing.value.code == 2
    assert bad_limit.value.code == 2
    assert bad_format.value.code == 2
    assert no_doctor.value.code == 2

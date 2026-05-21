"""NCBI E-utilities client skeleton."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from biorefs_cli.config import Config, run_secret_command
from biorefs_cli.http import HttpClient, JsonObject

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL_NAME = "biorefs-cli"


@dataclass(frozen=True, slots=True)
class NCBIClient:
    config: Config
    http: HttpClient

    @classmethod
    def from_config(cls, config: Config) -> NCBIClient:
        return cls(
            config=config, http=HttpClient(timeout_seconds=config.timeout_seconds)
        )

    def eutils_url(self, endpoint: str, params: dict[str, str | int]) -> str:
        query = self.common_params() | {
            key: str(value) for key, value in params.items()
        }
        endpoint_name = endpoint if endpoint.endswith(".fcgi") else f"{endpoint}.fcgi"
        return f"{EUTILS_BASE_URL}/{endpoint_name}?{urlencode(query)}"

    def common_params(self) -> dict[str, str]:
        params = {"tool": TOOL_NAME}
        if self.config.email:
            params["email"] = self.config.email
        api_key = self.api_key()
        if api_key:
            params["api_key"] = api_key
        return params

    def api_key(self) -> str | None:
        if not self.config.ncbi_api_key_command:
            return None
        return run_secret_command(
            self.config.ncbi_api_key_command,
            timeout_seconds=self.config.timeout_seconds,
        )

    def request_json(self, endpoint: str, params: dict[str, str | int]) -> JsonObject:
        return self.http.get_json(
            self.eutils_url(endpoint, params), rate_limit_source="ncbi"
        )

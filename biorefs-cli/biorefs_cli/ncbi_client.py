# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""NCBI E-utilities client skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast
from urllib.parse import urlencode

from biorefs_cli.config import Config, run_secret_command
from biorefs_cli.http import HttpClient, JsonObject

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL_NAME = "biorefs-cli"
NCBI_RATE_LIMIT_SOURCE = "ncbi"
_API_KEY_UNSET = object()


@dataclass(frozen=True, slots=True)
class NCBIClient:
    config: Config
    http: HttpClient
    _api_key_cache: str | object | None = field(
        default=_API_KEY_UNSET,
        init=False,
        repr=False,
        compare=False,
    )

    @classmethod
    def from_config(cls, config: Config) -> NCBIClient:
        return cls(
            config=config,
            http=HttpClient(timeout_seconds=config.timeout_seconds),
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
        cached = self._api_key_cache
        if cached is not _API_KEY_UNSET:
            return cast("str | None", cached)
        if not self.config.ncbi_api_key_command:
            object.__setattr__(self, "_api_key_cache", None)
            return None
        api_key = run_secret_command(
            self.config.ncbi_api_key_command,
            timeout_seconds=self.config.timeout_seconds,
        )
        object.__setattr__(self, "_api_key_cache", api_key)
        return api_key

    def rate_limit_source(self, source: str = NCBI_RATE_LIMIT_SOURCE) -> str:
        if self.api_key():
            return f"{source}-key"
        return source

    def request_json(self, endpoint: str, params: dict[str, str | int]) -> JsonObject:
        url = self.eutils_url(endpoint, params)
        return self.http.get_json(url, rate_limit_source=self.rate_limit_source())

# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from weather_cli import main as weather

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_latlon_to_grid_for_seoul_city_hall() -> None:
    grid = weather.latlon_to_grid(37.5665, 126.9780)

    assert grid == weather.Grid(nx=60, ny=127)


def test_latest_ultra_short_observation_uses_previous_hour_before_release() -> None:
    now = datetime.fromisoformat("2026-05-07T00:39:00+09:00")

    assert weather.latest_ultra_ncst_time(now) == ("20260506", "2300")


def test_latest_village_forecast_uses_previous_base_before_release() -> None:
    now = datetime.fromisoformat("2026-05-07T02:10:00+09:00")

    assert weather.latest_vilage_fcst_time(now) == ("20260506", "2300")


def test_parse_nmap_geocode_output() -> None:
    parsed = weather.parse_nmap_geocode_output(
        "1. 경기도 성남시 분당구 불정로 6\n   Coordinates: 127.1054328, 37.3595963\n"
    )

    assert parsed == weather.Location(
        lat=37.3595963,
        lon=127.1054328,
        name="경기도 성남시 분당구 불정로 6",
    )


def test_geocode_with_nmap_cli_invokes_expected_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    args_file = tmp_path / "args"
    executable = tmp_path / "nmap-cli"
    executable.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {args_file}\n"
        "printf '1. 경기도 성남시 분당구 불정로 6\\n'\n"
        "printf '   Coordinates: 127.1054328, 37.3595963\\n'\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    parsed = weather.geocode_with_nmap_cli("판교")

    assert args_file.read_text().splitlines() == ["geocode", "판교", "--limit", "1"]
    assert parsed == weather.Location(
        lat=37.3595963,
        lon=127.1054328,
        name="경기도 성남시 분당구 불정로 6",
    )


def test_get_current_weather_parses_kma_items(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_kma_get(
        endpoint: str,
        service_key: str,
        params: dict[str, str],
    ) -> dict[str, object]:
        assert endpoint == "getUltraSrtNcst"
        assert service_key == "key"
        assert params["nx"] == "60"
        assert params["ny"] == "127"
        return {
            "body": {
                "items": {
                    "item": [
                        {
                            "baseDate": "20260507",
                            "baseTime": "0100",
                            "category": "T1H",
                            "obsrValue": "18.4",
                        },
                        {
                            "baseDate": "20260507",
                            "baseTime": "0100",
                            "category": "REH",
                            "obsrValue": "63",
                        },
                        {
                            "baseDate": "20260507",
                            "baseTime": "0100",
                            "category": "PTY",
                            "obsrValue": "1",
                        },
                    ]
                }
            }
        }

    monkeypatch.setattr(weather, "kma_get", fake_kma_get)
    result = weather.get_current_weather("key", weather.Grid(nx=60, ny=127))

    assert result.timestamp.isoformat() == "2026-05-07T01:00:00+09:00"
    assert result.values == {"T1H": "18.4", "REH": "63", "PTY": "1"}


def test_format_forecast_groups_days() -> None:
    slots = [
        weather.ForecastSlot(
            timestamp=datetime.fromisoformat("2026-05-07T09:00:00+09:00"),
            values={"TMP": "18", "TMN": "12", "SKY": "1", "PTY": "0", "POP": "10"},
        ),
        weather.ForecastSlot(
            timestamp=datetime.fromisoformat("2026-05-07T15:00:00+09:00"),
            values={"TMP": "23", "TMX": "25", "SKY": "3", "PTY": "0", "POP": "30"},
        ),
        weather.ForecastSlot(
            timestamp=datetime.fromisoformat("2026-05-08T09:00:00+09:00"),
            values={"TMP": "19", "SKY": "4", "PTY": "1", "POP": "80", "PCP": "5.0mm"},
        ),
    ]

    output = weather.format_forecast(slots, "서울", weather.Grid(nx=60, ny=127), 2)

    assert "2026-05-07: 12°C - 25°C" in output
    assert "강수확률 30%" in output
    assert "2026-05-08: 19°C - 19°C, 비, 강수확률 80%, 강수량 5.0mm" in output


def test_service_key_query_part_preserves_encoded_key() -> None:
    assert weather.service_key_query_part("abc%2Fdef") == "serviceKey=abc%2Fdef"
    assert weather.service_key_query_part("abc/def") == "serviceKey=abc%2Fdef"


def test_setup_writes_service_key_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    weather.setup("printf configured-key")

    config = json.loads((tmp_path / "weather-cli" / "config.json").read_text())
    assert config == {"service_key_command": "printf configured-key"}


def test_resolve_service_key_uses_config_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for name in ("KMA_SERVICE_KEY", "KMA_API_KEY", "DATA_GO_KR_SERVICE_KEY"):
        monkeypatch.delenv(name, raising=False)
    weather.save_config({"service_key_command": "printf 'configured-key\\nmetadata'"})

    assert weather.resolve_service_key(None) == "configured-key"

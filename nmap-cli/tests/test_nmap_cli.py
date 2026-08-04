# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Tests for nmap-cli."""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

MODULE_PATH = Path(__file__).parents[1] / "nmap_cli.py"
MODULE_SPEC = importlib.util.spec_from_file_location("nmap_cli", MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    msg = f"Could not load {MODULE_PATH}"
    raise RuntimeError(msg)
nmap_cli = cast("Any", importlib.util.module_from_spec(MODULE_SPEC))
sys.modules["nmap_cli"] = nmap_cli
MODULE_SPEC.loader.exec_module(nmap_cli)


def test_parse_coordinate_accepts_lng_lat() -> None:
    point = nmap_cli.parse_coordinate("127.1054328,37.3595963")

    assert point is not None
    assert point.x == "127.1054328"
    assert point.y == "37.3595963"


def test_parse_coordinate_rejects_plain_address() -> None:
    assert nmap_cli.parse_coordinate("분당구 불정로 6") is None


def test_formatters_use_human_readable_units() -> None:
    assert nmap_cli.format_distance(950) == "950 m"
    assert nmap_cli.format_distance(12345) == "12.3 km"
    assert nmap_cli.format_duration(65_000) == "1 min"
    assert nmap_cli.format_duration(7_500_000) == "2 h 5 min"
    assert nmap_cli.format_money(4800) == "4,800 KRW"


def test_setup_writes_command_config() -> None:
    with tempfile.TemporaryDirectory() as directory:
        config_path = Path(directory) / "config.json"

        nmap_cli.setup(
            config_path,
            "printf key-id",
            "printf secret",
        )

        data = json.loads(config_path.read_text())
        assert data == {
            "api_key_id_command": "printf key-id",
            "api_key_command": "printf secret",
        }
        credentials = nmap_cli.load_config(config_path)
        assert credentials.key_id == "key-id"
        assert credentials.key == "secret"


def test_load_config_uses_environment() -> None:
    old_key_id = os.environ.get("NCLOUD_MAPS_API_KEY_ID")
    old_key = os.environ.get("NCLOUD_MAPS_API_KEY")
    try:
        os.environ["NCLOUD_MAPS_API_KEY_ID"] = "key-id"
        os.environ["NCLOUD_MAPS_API_KEY"] = "secret"

        credentials = nmap_cli.load_config(None)

        assert credentials.key_id == "key-id"
        assert credentials.key == "secret"
    finally:
        if old_key_id is None:
            os.environ.pop("NCLOUD_MAPS_API_KEY_ID", None)
        else:
            os.environ["NCLOUD_MAPS_API_KEY_ID"] = old_key_id
        if old_key is None:
            os.environ.pop("NCLOUD_MAPS_API_KEY", None)
        else:
            os.environ["NCLOUD_MAPS_API_KEY"] = old_key


def test_build_naver_maps_url_uses_search_query() -> None:
    url = nmap_cli.build_naver_maps_url("서울역", "126.9707", "37.5547")

    assert (
        url
        == "https://map.naver.com/p/search/%EC%84%9C%EC%9A%B8%EC%97%AD?c=126.9707,37.5547,15,0,0,0,dh"
    )


def test_first_address_parses_geocoding_response() -> None:
    response: dict[str, object] = {
        "status": "OK",
        "addresses": [
            {
                "roadAddress": "경기도 성남시 분당구 불정로 6 NAVER그린팩토리",
                "jibunAddress": "경기도 성남시 분당구 정자동 178-1 NAVER그린팩토리",
                "englishAddress": "6, Buljeong-ro, Bundang-gu, Seongnam-si, Gyeonggi-do, Republic of Korea",
                "x": "127.1054328",
                "y": "37.3595963",
            }
        ],
    }

    address = nmap_cli.first_address(response)

    assert address is not None
    assert address.road_address.startswith("경기도 성남시")
    assert address.x == "127.1054328"
    assert address.y == "37.3595963"


def test_route_choice_selects_requested_option() -> None:
    response: dict[str, object] = {
        "code": 0,
        "route": {
            "traoptimal": [
                {
                    "summary": {
                        "distance": 42500,
                        "duration": 3_600_000,
                        "tollFare": 1800,
                        "taxiFare": 45000,
                        "fuelPrice": 6200,
                    },
                    "guide": [
                        {
                            "instructions": "직진",
                            "distance": 500,
                            "duration": 60_000,
                        }
                    ],
                }
            ]
        },
    }

    route = nmap_cli.route_choice(response, "traoptimal")

    assert route is not None
    assert route.summary["distance"] == 42500
    assert route.guide[0]["instructions"] == "직진"

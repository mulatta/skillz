# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Tests for kmap-cli."""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

MODULE_PATH = Path(__file__).parents[1] / "kmap_cli.py"
MODULE_SPEC = importlib.util.spec_from_file_location("kmap_cli", MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    msg = f"Could not load {MODULE_PATH}"
    raise RuntimeError(msg)
kmap_cli = cast("Any", importlib.util.module_from_spec(MODULE_SPEC))
sys.modules["kmap_cli"] = kmap_cli
MODULE_SPEC.loader.exec_module(kmap_cli)


def test_parse_coordinate_accepts_lng_lat() -> None:
    point = kmap_cli.parse_coordinate("127.0264006,37.5039195")

    assert point is not None
    assert point.x == "127.0264006"
    assert point.y == "37.5039195"


def test_parse_coordinate_rejects_address() -> None:
    assert kmap_cli.parse_coordinate("정돈 강남점") is None


def test_setup_writes_tmap_secret_command() -> None:
    with tempfile.TemporaryDirectory() as directory:
        config_path = Path(directory) / "config.json"

        kmap_cli.setup(config_path, "printf tmap-key")

        assert json.loads(config_path.read_text()) == {
            "tmap_app_key_command": "printf tmap-key"
        }
        credentials = kmap_cli.load_config(config_path)
        assert credentials.tmap_app_key == "tmap-key"


def test_load_config_uses_environment() -> None:
    old_key = os.environ.get("TMAP_APP_KEY")
    try:
        os.environ["TMAP_APP_KEY"] = "env-tmap"

        credentials = kmap_cli.load_config(None)

        assert credentials.tmap_app_key == "env-tmap"
    finally:
        if old_key is None:
            os.environ.pop("TMAP_APP_KEY", None)
        else:
            os.environ["TMAP_APP_KEY"] = old_key


def test_places_from_tmap_response_maps_poi_documents() -> None:
    response: dict[str, object] = {
        "searchPoiInfo": {
            "pois": {
                "poi": [
                    {
                        "id": "123",
                        "name": "정돈 강남점",
                        "telNo": "02-0000-0000",
                        "frontLon": "127.0264006",
                        "frontLat": "37.5039195",
                        "upperAddrName": "서울",
                        "middleAddrName": "강남구",
                        "lowerAddrName": "역삼동",
                        "roadName": "강남대로110길",
                        "firstNo": "19",
                        "secondNo": "1",
                        "upperBizName": "음식점",
                        "middleBizName": "일식",
                        "lowerBizName": "돈까스",
                        "radius": "0.1205",
                    }
                ]
            }
        }
    }

    places = kmap_cli.places_from_tmap_response(response)

    assert len(places) == 1
    assert places[0].provider == "tmap"
    assert places[0].id == "123"
    assert places[0].name == "정돈 강남점"
    assert places[0].category == "음식점 > 일식 > 돈까스"
    assert places[0].phone == "02-0000-0000"
    assert places[0].x == "127.0264006"
    assert places[0].y == "37.5039195"
    assert places[0].distance == 120.5


def test_transit_routes_from_response_maps_summary_and_legs() -> None:
    response: dict[str, object] = {
        "metaData": {
            "plan": {
                "itineraries": [
                    {
                        "fare": {"regular": {"totalFare": 1400}},
                        "totalTime": 986,
                        "transferCount": 1,
                        "totalWalkDistance": 115,
                        "totalDistance": 4233,
                        "totalWalkTime": 110,
                        "pathType": 3,
                        "legs": [
                            {
                                "mode": "WALK",
                                "sectionTime": 110,
                                "distance": 115,
                                "start": {"name": "출발지"},
                                "end": {"name": "수유역"},
                            },
                            {
                                "mode": "BUS",
                                "route": "지선:1128",
                                "sectionTime": 710,
                                "distance": 4118,
                                "start": {"name": "수유역"},
                                "end": {"name": "삼양동"},
                                "passStopList": {
                                    "stationList": [
                                        {"stationName": "수유역"},
                                        {"stationName": "신일병원"},
                                    ]
                                },
                            },
                        ],
                    }
                ]
            }
        }
    }

    routes = kmap_cli.transit_routes_from_response(response)

    assert len(routes) == 1
    assert routes[0].fare == 1400
    assert routes[0].total_time_seconds == 986
    assert routes[0].transfer_count == 1
    assert routes[0].path_type == 3
    assert len(routes[0].legs) == 2
    assert routes[0].legs[1].mode == "BUS"
    assert routes[0].legs[1].route == "지선:1128"
    assert routes[0].legs[1].stops == ["수유역", "신일병원"]


def test_geocode_places_from_response_maps_coordinates() -> None:
    response: dict[str, object] = {
        "coordinateInfo": {
            "coordinate": [
                {
                    "newLon": "126.9783882",
                    "newLat": "37.5666103",
                    "newAddressList": "서울 중구 세종대로 110",
                }
            ]
        }
    }

    places = kmap_cli.geocode_places_from_response(response, "서울시청")

    assert len(places) == 1
    assert places[0].x == "126.9783882"
    assert places[0].y == "37.5666103"
    assert places[0].category == "address"


def test_saved_places_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "places.json"
        saved = {
            "home": kmap_cli.SavedPlace(
                alias="home",
                name="집",
                x="127.0",
                y="37.5",
                address="서울",
                provider="tmap",
                provider_id="123",
            )
        }

        kmap_cli.save_saved_places(saved, path)
        loaded = kmap_cli.load_saved_places(path)

        assert loaded == saved


def test_build_search_urls_quote_query() -> None:
    assert kmap_cli.build_tmap_search_url("정돈 강남점").endswith(
        "%EC%A0%95%EB%8F%88%20%EA%B0%95%EB%82%A8%EC%A0%90"
    )
    assert kmap_cli.build_naver_search_url("정돈 강남점").startswith(
        "https://map.naver.com/p/search/"
    )
    assert kmap_cli.build_kakao_search_url("정돈 강남점").startswith(
        "https://map.kakao.com/link/search/"
    )


def test_build_kakao_route_url_uses_lat_lng_order() -> None:
    origin = kmap_cli.Place(
        provider="tmap",
        id="1",
        name="서울역",
        category="",
        phone="",
        address="",
        road_address="",
        x="126.96913336",
        y="37.55326112",
    )
    destination = kmap_cli.Place(
        provider="tmap",
        id="2",
        name="강남역",
        category="",
        phone="",
        address="",
        road_address="",
        x="127.02796290",
        y="37.49804637",
    )

    url = kmap_cli.build_route_url("kakao", "transit", origin, destination)

    assert url == (
        "https://map.kakao.com/link/by/traffic/"
        "%EC%84%9C%EC%9A%B8%EC%97%AD,37.55326112,126.96913336/"
        "%EA%B0%95%EB%82%A8%EC%97%AD,37.49804637,127.02796290"
    )


def test_build_naver_route_url_uses_direction_path() -> None:
    origin = kmap_cli.Place(
        provider="tmap",
        id="1",
        name="서울역",
        category="",
        phone="",
        address="",
        road_address="",
        x="126.96913336",
        y="37.55326112",
    )
    destination = kmap_cli.Place(
        provider="tmap",
        id="2",
        name="강남역",
        category="",
        phone="",
        address="",
        road_address="",
        x="127.02796290",
        y="37.49804637",
    )

    url = kmap_cli.build_route_url("naver", "transit", origin, destination)

    assert url.startswith("https://map.naver.com/p/directions/")
    assert url.endswith("/-/transit")


def test_parser_has_transit_and_route_url() -> None:
    parser = kmap_cli.build_parser()
    args = parser.parse_args(
        [
            "transit",
            "서울역",
            "강남역",
            "--via",
            "고속터미널",
            "--via",
            "교대역",
            "--count",
            "2",
            "--json",
        ]
    )

    assert args.command == "transit"
    assert args.via == ["고속터미널", "교대역"]
    assert args.count == 2
    assert args.use_json is True
    route_url_args = parser.parse_args(
        ["route-url", "서울역", "강남역", "--provider", "kakao", "--json"]
    )

    assert route_url_args.command == "route-url"
    assert route_url_args.provider == "kakao"
    assert route_url_args.use_json is True

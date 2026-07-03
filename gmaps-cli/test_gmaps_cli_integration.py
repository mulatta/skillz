#!/usr/bin/env python3
"""Integration tests for gmaps-cli using pytest."""

import importlib.util
import io
import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Self, TypeVar, cast

import pytest

MODULE_PATH = Path(__file__).with_name("gmaps_cli.py")
MODULE_SPEC = importlib.util.spec_from_file_location("gmaps_cli", MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    msg = f"Could not load {MODULE_PATH}"
    raise RuntimeError(msg)
gmaps_cli = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(gmaps_cli)
main = cast("Callable[[list[str] | None], None]", gmaps_cli.main)


F = TypeVar("F", bound=Callable[..., object])
pytest_fixture = cast("Callable[[F], F]", pytest.fixture)
pytest_parametrize = cast(
    "Callable[[object, object], Callable[[F], F]]", pytest.mark.parametrize
)
MapsUrlParams = cast("type[Any]", gmaps_cli.MapsUrlParams)
DirectionsProcessor = cast("type[Any]", gmaps_cli.DirectionsProcessor)
parse_datetime = cast("Callable[[str], str]", gmaps_cli.parse_datetime)
generate_maps_url = cast("Callable[[str, Any], str]", gmaps_cli.generate_maps_url)
search_place = cast(
    "Callable[[str, str], dict[str, Any] | None]", gmaps_cli.search_place
)


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = json.dumps(payload).encode()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


@pytest_fixture
def config_exists() -> bool:
    """Check if API key is configured."""
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    config_file = config_home / "gmaps-cli" / "config.json"
    if not config_file.exists():
        pytest.skip("No API key configured. Run 'gmaps-cli setup' first.")
    return True


def capture_cli_output(args: list[str]) -> str:
    """Helper to capture CLI output."""
    output = io.StringIO()
    try:
        with redirect_stdout(output):
            main(args)
    except SystemExit:
        pass  # Ignore exit codes
    return output.getvalue()


def test_generate_maps_url_prefers_place_id() -> None:
    params = MapsUrlParams()
    params.query = "Marienplatz Munich"
    params.place_id = "places/abc123"
    params.lat = 48.137
    params.lng = 11.575

    url = generate_maps_url("search", params)

    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query)
    assert parsed.path == "/maps/search/"
    assert query["api"] == ["1"]
    assert query["query"] == ["Marienplatz Munich"]
    assert query["query_place_id"] == ["places/abc123"]


def test_generate_maps_url_uses_coordinates_when_place_id_is_missing() -> None:
    params = MapsUrlParams()
    params.lat = 48.137
    params.lng = 11.575

    assert generate_maps_url("search", params).endswith(
        "/search/?api=1&query=48.137,11.575"
    )


def test_generate_maps_url_includes_non_default_travel_mode() -> None:
    params = MapsUrlParams()
    params.origin = "Munich Hauptbahnhof"
    params.destination = "Berlin Hauptbahnhof"
    params.mode = "transit"

    url = generate_maps_url("directions", params)

    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert query["origin"] == ["Munich Hauptbahnhof"]
    assert query["destination"] == ["Berlin Hauptbahnhof"]
    assert query["travelmode"] == ["transit"]


@pytest_parametrize(
    ("value", "expected_prefix"),
    [
        ("2026-07-05 09:30", "2026-07-05T09:30"),
        ("2026-07-05T09:30:00Z", "2026-07-05T09:30:00"),
        ("next Tuesday after lunch", "next Tuesday after lunch"),
    ],
)
def test_parse_datetime_handles_supported_formats_and_passthrough(
    value: str, expected_prefix: str
) -> None:
    assert parse_datetime(value).startswith(expected_prefix)


def test_search_place_parses_places_response(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_body: dict[str, Any] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: int) -> FakeResponse:
        assert timeout == 10
        data = request.data
        assert isinstance(data, bytes)
        seen_body.update(json.loads(data.decode()))
        return FakeResponse(
            {
                "places": [
                    {
                        "displayName": {"text": "Marienplatz"},
                        "formattedAddress": "Marienplatz, Munich, Germany",
                        "id": "places/marienplatz",
                        "rating": 4.7,
                        "userRatingCount": 1200,
                        "location": {"latitude": 48.137, "longitude": 11.575},
                    }
                ]
            }
        )

    monkeypatch.setattr(gmaps_cli.urllib.request, "urlopen", fake_urlopen)

    place = search_place("key", "Marienplatz Munich")

    assert seen_body == {"textQuery": "Marienplatz Munich", "maxResultCount": 1}
    assert place == {
        "name": "Marienplatz",
        "address": "Marienplatz, Munich, Germany",
        "place_id": "places/marienplatz",
        "rating": 4.7,
        "ratings_total": 1200,
        "lat": 48.137,
        "lng": 11.575,
    }


def test_directions_processor_parses_route_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_body: dict[str, Any] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: int) -> FakeResponse:
        assert timeout == 10
        data = request.data
        assert isinstance(data, bytes)
        seen_body.update(json.loads(data.decode()))
        return FakeResponse(
            {
                "routes": [
                    {
                        "distanceMeters": 1250,
                        "duration": "3900s",
                        "legs": [
                            {
                                "startLocation": {"address": "Munich"},
                                "endLocation": {"address": "Berlin"},
                                "steps": [
                                    {
                                        "navigationInstruction": {
                                            "instructions": "Board train"
                                        },
                                        "localizedValues": {
                                            "distance": {"text": "1.2 km"},
                                            "staticDuration": {"text": "1 hour"},
                                        },
                                        "transitDetails": {
                                            "transitLine": {
                                                "nameShort": "ICE",
                                                "vehicle": {"type": "TRAIN"},
                                            },
                                            "stopDetails": {
                                                "departureStop": {"name": "Munich Hbf"},
                                                "arrivalStop": {"name": "Berlin Hbf"},
                                            },
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        )

    monkeypatch.setattr(gmaps_cli.urllib.request, "urlopen", fake_urlopen)
    processor = DirectionsProcessor("key")

    route_result = processor.get_directions(
        "Munich", "Berlin", "transit", "2026-07-05T09:30:00+00:00", None
    )

    assert seen_body["travelMode"] == "TRANSIT"
    assert seen_body["departureTime"] == "2026-07-05T09:30:00+00:00"
    assert route_result == {
        "start_address": "Munich",
        "end_address": "Berlin",
        "distance": "1.2 km",
        "duration": "1 hour 5 mins",
        "steps": [
            {
                "instruction": "Board train",
                "distance": "1.2 km",
                "duration": "1 hour",
                "transit": {
                    "line": "ICE",
                    "vehicle": "TRAIN",
                    "departure_stop": "Munich Hbf",
                    "arrival_stop": "Berlin Hbf",
                },
            }
        ],
    }


def test_munich_to_berlin_route(config_exists: bool) -> None:
    """Test finding route from Munich to Berlin using the CLI."""
    # Call the CLI with route command
    result = capture_cli_output(
        ["route", "Munich, Germany", "Berlin, Germany", "-m", "driving"]
    )

    # Verify the output contains expected elements
    assert "Munich" in result or "München" in result
    assert "Berlin" in result
    assert "Distance:" in result
    assert "Duration:" in result
    assert "View on Google Maps:" in result
    assert "Directions:" in result

    # Check that distance is reasonable (500-700 km)
    lines = result.split("\n")
    distance_found = False
    for line in lines:
        if "Distance:" in line and "km" in line:
            distance_str = line.split(":")[1].strip()
            distance_val = float(distance_str.replace(" km", ""))
            assert 500 <= distance_val <= 700, f"Unexpected distance: {distance_val} km"
            distance_found = True
            break

    assert distance_found, "Distance not found in output"

    # Check for Google Maps URL
    url_found = False
    for line in lines:
        if "View on Google Maps:" in line:
            url = line.split(":", 1)[1].strip()
            assert url.startswith("https://www.google.com/maps/dir/")
            assert "Munich" in url or "M%C3%BCnchen" in url
            assert "Berlin" in url
            url_found = True
            break

    assert url_found, "Google Maps URL not found"


def test_transit_route(config_exists: bool) -> None:
    """Test Munich to Berlin using transit (train)."""
    result = capture_cli_output(
        ["route", "Munich Hauptbahnhof", "Berlin Hauptbahnhof", "-m", "transit"]
    )

    # Transit routes should show transit-specific information
    assert "transit" in result.lower() or "Transit" in result

    # Should have note about scheduled times
    assert "Note: Transit times shown are scheduled times" in result


def test_search_place(config_exists: bool) -> None:
    """Test searching for a specific place."""
    result = capture_cli_output(["search", "Marienplatz Munich"])

    # Should find Marienplatz
    assert "Marienplatz" in result or "marienplatz" in result.lower()
    assert "View on Google Maps:" in result

    # Check for coordinates
    lines = result.split("\n")
    found_coords = False
    for line in lines:
        if (
            ", " in line
            and line.replace(".", "")
            .replace(",", "")
            .replace(" ", "")
            .replace("-", "")
            .isdigit()
        ):
            # This looks like coordinates
            parts = line.split(", ")
            if len(parts) == 2:
                try:
                    lat = float(parts[0])
                    lng = float(parts[1])
                    # Munich is around 48.1°N, 11.5°E
                    if 47 < lat < 49 and 10 < lng < 13:
                        found_coords = True
                        break
                except ValueError:
                    pass

    assert found_coords, "Coordinates not found in output"


def test_nearby_restaurants(config_exists: bool) -> None:
    """Test finding restaurants near a location."""
    result = capture_cli_output(
        ["nearby", "restaurants", "-l", "Marienplatz Munich", "-n", "3"]
    )

    # Should find some restaurants
    lines = result.split("\n")
    restaurant_count = 0

    for line in lines:
        if line.strip().startswith(("1.", "2.", "3.")):
            restaurant_count += 1

    assert restaurant_count > 0, "No restaurants found"
    assert "Maps:" in result, "No Maps links found"


def test_help_command() -> None:
    """Test the help command."""
    result = capture_cli_output(["--help"])

    assert "usage:" in result.lower()
    assert "route" in result
    assert "search" in result
    assert "nearby" in result
    assert "setup" in result


def test_no_command() -> None:
    """Test behavior when no command is given."""
    result = capture_cli_output([])

    # Should show help when no command given
    assert "usage:" in result.lower()


@pytest_parametrize(
    ("origin", "destination", "mode"),
    [
        ("Munich, Germany", "Berlin, Germany", "driving"),
        ("Hamburg, Germany", "Frankfurt, Germany", "driving"),
        ("Munich Hauptbahnhof", "Berlin Hauptbahnhof", "transit"),
    ],
)
def test_various_routes(
    config_exists: bool, origin: str, destination: str, mode: str
) -> None:
    """Test various routes with different parameters."""
    result = capture_cli_output(["route", origin, destination, "-m", mode])

    assert "Distance:" in result
    assert "Duration:" in result
    assert "View on Google Maps:" in result


@pytest_parametrize(
    ("query", "expected_in_result"),
    [
        ("Brandenburger Tor Berlin", ["Brandenburg", "Berlin"]),
        ("Neuschwanstein Castle", ["Neuschwanstein"]),
        ("Cologne Cathedral", ["Cathedral", "Cologne"]),
    ],
)
def test_search_various_places(
    config_exists: bool, query: str, expected_in_result: list[str]
) -> None:
    """Test searching for various German landmarks."""
    result = capture_cli_output(["search", query])

    # Check that at least one of the expected terms is in the result
    assert any(term in result for term in expected_in_result)
    assert "View on Google Maps:" in result

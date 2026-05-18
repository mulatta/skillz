#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

CONFIG_SUBDIR = "kmap-cli"
CONFIG_FILE_NAME = "config.json"
DATA_FILE_NAME = "places.json"
TMAP_BASE_URL = "https://apis.openapi.sk.com"
TMAP_WEB_SEARCH_URL = "https://www.tmap.co.kr/search?keyword="
NAVER_MAP_SEARCH_URL = "https://map.naver.com/p/search/"
KAKAO_MAP_SEARCH_URL = "https://map.kakao.com/link/search/"
KAKAO_MAP_ROUTE_MODE = {
    "transit": "traffic",
    "driving": "car",
    "walking": "walk",
    "bicycle": "bicycle",
}
NAVER_MAP_ROUTE_MODE = {
    "transit": "transit",
    "driving": "car",
    "walking": "walk",
    "bicycle": "bike",
}


@dataclass(frozen=True)
class Point:
    x: str
    y: str


@dataclass(frozen=True)
class Place:
    provider: str
    id: str
    name: str
    category: str
    phone: str
    address: str
    road_address: str
    x: str
    y: str
    distance: float | None = None
    url: str = ""


@dataclass(frozen=True)
class SavedPlace:
    alias: str
    name: str
    x: str
    y: str
    address: str
    provider: str
    provider_id: str


@dataclass(frozen=True)
class TransitLeg:
    mode: str
    route: str
    start: str
    end: str
    duration_seconds: int
    distance_meters: int
    stops: list[str]


@dataclass(frozen=True)
class TransitRoute:
    total_time_seconds: int
    transfer_count: int
    total_walk_distance_meters: int
    total_distance_meters: int
    total_walk_time_seconds: int
    fare: int
    path_type: int | None
    legs: list[TransitLeg]


@dataclass(frozen=True)
class Credentials:
    tmap_app_key: str


class ConfigError(RuntimeError):
    """Configuration could not be loaded."""


class ApiError(RuntimeError):
    """Remote API request failed."""


class ResolveError(RuntimeError):
    """A user supplied location could not be resolved."""


def config_dir() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / CONFIG_SUBDIR
    return Path.home() / ".config" / CONFIG_SUBDIR


def data_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / CONFIG_SUBDIR
    return Path.home() / ".local" / "share" / CONFIG_SUBDIR


def config_file() -> Path:
    return config_dir() / CONFIG_FILE_NAME


def places_file() -> Path:
    return data_dir() / DATA_FILE_NAME


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        msg = f"config must be a JSON object: {path}"
        raise ConfigError(msg)
    return cast("dict[str, Any]", data)


def _run_secret_command(command: str) -> str | None:
    args = shlex.split(command)
    if not args:
        return None
    try:
        result = subprocess.run(
            args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as error:
        raise ConfigError(f"secret command failed: {error}") from error
    value = result.stdout.strip()
    return value or None


def _string_value(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def load_config(path: Path | None = None) -> Credentials:
    cfg = _load_json(path or config_file())

    tmap_app_key = os.environ.get("TMAP_APP_KEY")
    if not tmap_app_key:
        command = os.environ.get("TMAP_APP_KEY_COMMAND") or _string_value(
            cfg, "tmap_app_key_command"
        )
        if command:
            tmap_app_key = _run_secret_command(command)
    if not tmap_app_key:
        tmap_app_key = _string_value(cfg, "tmap_app_key")
    if not tmap_app_key:
        msg = (
            "TMAP app key missing; set TMAP_APP_KEY, TMAP_APP_KEY_COMMAND, "
            "or config tmap_app_key/tmap_app_key_command"
        )
        raise ConfigError(msg)

    return Credentials(tmap_app_key=tmap_app_key)


def setup(config_path: Path, tmap_app_key_command: str) -> None:
    if not shlex.split(tmap_app_key_command):
        msg = "tmap_app_key_command must not be empty"
        raise ConfigError(msg)
    data = {"tmap_app_key_command": tmap_app_key_command}
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def parse_coordinate(value: str) -> Point | None:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        return None
    try:
        lng = float(parts[0])
        lat = float(parts[1])
    except ValueError:
        return None
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return None
    return Point(x=parts[0], y=parts[1])


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value)))
    except ValueError:
        return None


def _join_nonempty(parts: list[str]) -> str:
    return " ".join(part for part in parts if part)


def _format_tmap_address(item: dict[str, Any]) -> str:
    return _join_nonempty(
        [
            str(item.get("upperAddrName", "")),
            str(item.get("middleAddrName", "")),
            str(item.get("lowerAddrName", "")),
            str(item.get("detailAddrName", "")),
        ]
    )


def _format_tmap_road_address(item: dict[str, Any]) -> str:
    road = str(item.get("roadName", ""))
    first = str(item.get("firstNo", ""))
    second = str(item.get("secondNo", ""))
    number = first
    if second and second != "0":
        number = f"{first}-{second}"
    return _join_nonempty(
        [
            str(item.get("upperAddrName", "")),
            str(item.get("middleAddrName", "")),
            road,
            number,
        ]
    )


def _format_tmap_category(item: dict[str, Any]) -> str:
    return " > ".join(
        part
        for part in [
            str(item.get("upperBizName", "")),
            str(item.get("middleBizName", "")),
            str(item.get("lowerBizName", "")),
            str(item.get("detailBizName", "")),
        ]
        if part
    )


def _tmap_distance_meters(item: dict[str, Any]) -> float | None:
    radius_km = _optional_float(item.get("radius"))
    if radius_km is not None:
        return radius_km * 1000
    return _optional_float(item.get("distance"))


def places_from_tmap_response(response: dict[str, Any]) -> list[Place]:
    search_info = response.get("searchPoiInfo")
    if not isinstance(search_info, dict):
        return []
    pois = search_info.get("pois")
    if not isinstance(pois, dict):
        return []
    raw_items = pois.get("poi", [])
    if isinstance(raw_items, dict):
        items = [raw_items]
    elif isinstance(raw_items, list):
        items = raw_items
    else:
        return []

    places: list[Place] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        x = str(item.get("frontLon") or item.get("noorLon") or item.get("lon") or "")
        y = str(item.get("frontLat") or item.get("noorLat") or item.get("lat") or "")
        name = str(item.get("name", ""))
        if not x or not y or not name:
            continue
        place_id = str(item.get("id", ""))
        places.append(
            Place(
                provider="tmap",
                id=place_id,
                name=name,
                category=_format_tmap_category(item),
                phone=str(item.get("telNo", "")),
                address=_format_tmap_address(item),
                road_address=_format_tmap_road_address(item),
                x=x,
                y=y,
                distance=_tmap_distance_meters(item),
                url=build_tmap_search_url(name),
            )
        )
    return places


def transit_routes_from_response(response: dict[str, Any]) -> list[TransitRoute]:
    metadata = response.get("metaData")
    if not isinstance(metadata, dict):
        return []
    plan = metadata.get("plan")
    if not isinstance(plan, dict):
        return []
    itineraries = plan.get("itineraries", [])
    if not isinstance(itineraries, list):
        return []

    routes: list[TransitRoute] = []
    for itinerary in itineraries:
        if not isinstance(itinerary, dict):
            continue
        fare_node = itinerary.get("fare")
        regular = fare_node.get("regular", {}) if isinstance(fare_node, dict) else {}
        fare = (
            _optional_int(
                regular.get("totalFare") if isinstance(regular, dict) else None
            )
            or 0
        )
        legs = _transit_legs_from_itinerary(itinerary)
        routes.append(
            TransitRoute(
                total_time_seconds=_optional_int(itinerary.get("totalTime")) or 0,
                transfer_count=_optional_int(itinerary.get("transferCount")) or 0,
                total_walk_distance_meters=_optional_int(
                    itinerary.get("totalWalkDistance")
                )
                or 0,
                total_distance_meters=_optional_int(itinerary.get("totalDistance"))
                or 0,
                total_walk_time_seconds=_optional_int(itinerary.get("totalWalkTime"))
                or 0,
                fare=fare,
                path_type=_optional_int(itinerary.get("pathType")),
                legs=legs,
            )
        )
    return routes


def _node_name(node: object) -> str:
    if isinstance(node, dict):
        return str(node.get("name", ""))
    return ""


def _station_names(pass_stop_list: object) -> list[str]:
    if not isinstance(pass_stop_list, dict):
        return []
    stations = pass_stop_list.get("stationList") or pass_stop_list.get("stations")
    if not isinstance(stations, list):
        return []
    names: list[str] = []
    for station in stations:
        if isinstance(station, dict):
            name = station.get("stationName") or station.get("name")
            if name:
                names.append(str(name))
    return names


def _transit_legs_from_itinerary(itinerary: dict[str, Any]) -> list[TransitLeg]:
    raw_legs = itinerary.get("legs", [])
    if not isinstance(raw_legs, list):
        return []
    legs: list[TransitLeg] = []
    for leg in raw_legs:
        if not isinstance(leg, dict):
            continue
        legs.append(
            TransitLeg(
                mode=str(leg.get("mode", "")),
                route=str(leg.get("route", "")),
                start=_node_name(leg.get("start")),
                end=_node_name(leg.get("end")),
                duration_seconds=_optional_int(leg.get("sectionTime")) or 0,
                distance_meters=_optional_int(leg.get("distance")) or 0,
                stops=_station_names(leg.get("passStopList")),
            )
        )
    return legs


class TmapClient:
    def __init__(self, app_key: str) -> None:
        self.app_key = app_key

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        url = f"{TMAP_BASE_URL}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json", "appKey": self.app_key}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            payload = error.read().decode("utf-8", errors="replace")
            msg = f"TMAP HTTP {error.code}: {payload or error.reason}"
            raise ApiError(msg) from error
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise ApiError(f"TMAP request failed: {error}") from error
        if not isinstance(parsed, dict):
            msg = "TMAP response was not a JSON object"
            raise ApiError(msg)
        return cast("dict[str, Any]", parsed)

    def search_places(
        self,
        query: str,
        *,
        size: int = 10,
        page: int = 1,
        center: Point | None = None,
        radius_km: int | None = None,
    ) -> list[Place]:
        params = {
            "version": "1",
            "searchKeyword": query,
            "searchType": "all",
            "searchtypCd": "R" if center is not None else "A",
            "reqCoordType": "WGS84GEO",
            "resCoordType": "WGS84GEO",
            "page": str(page),
            "count": str(size),
            "multiPoint": "N",
            "poiGroupYn": "N",
        }
        if center is not None:
            params["centerLon"] = center.x
            params["centerLat"] = center.y
            params["radius"] = str(radius_km or 1)
        response = self.request_json("GET", "/tmap/pois", params=params)
        return places_from_tmap_response(response)

    def transit_routes(
        self,
        origin: Point,
        destination: Point,
        *,
        count: int = 3,
        search_dttm: str | None = None,
    ) -> list[TransitRoute]:
        body: dict[str, object] = {
            "startX": origin.x,
            "startY": origin.y,
            "endX": destination.x,
            "endY": destination.y,
            "count": count,
            "lang": 0,
            "format": "json",
        }
        if search_dttm:
            body["searchDttm"] = search_dttm
        response = self.request_json("POST", "/transit/routes", body=body)
        return transit_routes_from_response(response)

    def geocode(self, address: str) -> list[Place]:
        params = {
            "version": "1",
            "format": "json",
            "coordType": "WGS84GEO",
            "fullAddr": address,
        }
        response = self.request_json("GET", "/tmap/geo/fullAddrGeo", params=params)
        return geocode_places_from_response(response, address)

    def reverse(self, point: Point, *, address_type: str = "A10") -> dict[str, Any]:
        params = {
            "version": "1",
            "format": "json",
            "coordType": "WGS84GEO",
            "lon": point.x,
            "lat": point.y,
            "addressType": address_type,
        }
        return self.request_json("GET", "/tmap/geo/reversegeocoding", params=params)


def geocode_places_from_response(response: dict[str, Any], query: str) -> list[Place]:
    coordinate_info = response.get("coordinateInfo")
    if not isinstance(coordinate_info, dict):
        return []
    coordinates = coordinate_info.get("coordinate", [])
    if isinstance(coordinates, dict):
        items = [coordinates]
    elif isinstance(coordinates, list):
        items = coordinates
    else:
        return []
    places: list[Place] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        x = str(item.get("newLon") or item.get("lon") or "")
        y = str(item.get("newLat") or item.get("lat") or "")
        if not x or not y:
            continue
        address = str(item.get("newAddressList") or item.get("fullAddress") or query)
        places.append(
            Place(
                provider="tmap",
                id="",
                name=address,
                category="address",
                phone="",
                address=address,
                road_address=address,
                x=x,
                y=y,
                url=build_tmap_search_url(address),
            )
        )
    return places


def build_tmap_search_url(query: str) -> str:
    return f"{TMAP_WEB_SEARCH_URL}{urllib.parse.quote(query)}"


def build_naver_search_url(query: str) -> str:
    return f"{NAVER_MAP_SEARCH_URL}{urllib.parse.quote(query)}"


def build_kakao_search_url(query: str) -> str:
    return f"{KAKAO_MAP_SEARCH_URL}{urllib.parse.quote(query)}"


def _quote_route_part(place: Place) -> str:
    return urllib.parse.quote(f"{place.name},{place.y},{place.x}", safe=",")


def build_kakao_route_url(mode: str, origin: Place, destination: Place) -> str:
    kakao_mode = KAKAO_MAP_ROUTE_MODE[mode]
    return (
        f"https://map.kakao.com/link/by/{kakao_mode}/"
        f"{_quote_route_part(origin)}/{_quote_route_part(destination)}"
    )


def _quote_naver_direction_part(place: Place) -> str:
    name = urllib.parse.quote(place.name, safe="")
    return f"{place.x},{place.y},{name},PLACE_POI"


def build_naver_route_url(mode: str, origin: Place, destination: Place) -> str:
    naver_mode = NAVER_MAP_ROUTE_MODE[mode]
    return (
        "https://map.naver.com/p/directions/"
        f"{_quote_naver_direction_part(origin)}/"
        f"{_quote_naver_direction_part(destination)}/-/{naver_mode}"
    )


def build_route_url(provider: str, mode: str, origin: Place, destination: Place) -> str:
    if provider == "kakao":
        return build_kakao_route_url(mode, origin, destination)
    if provider == "naver":
        return build_naver_route_url(mode, origin, destination)
    raise ResolveError(f"unsupported route URL provider: {provider}")


def load_saved_places(path: Path | None = None) -> dict[str, SavedPlace]:
    data_path = path or places_file()
    data = _load_json(data_path)
    raw_places = data.get("places", {})
    if not isinstance(raw_places, dict):
        return {}
    places: dict[str, SavedPlace] = {}
    for alias, item in raw_places.items():
        if not isinstance(alias, str) or not isinstance(item, dict):
            continue
        name = item.get("name")
        x = item.get("x")
        y = item.get("y")
        if (
            not isinstance(name, str)
            or not isinstance(x, str)
            or not isinstance(y, str)
        ):
            continue
        places[alias] = SavedPlace(
            alias=alias,
            name=name,
            x=x,
            y=y,
            address=str(item.get("address", "")),
            provider=str(item.get("provider", "tmap")),
            provider_id=str(item.get("provider_id", "")),
        )
    return places


def save_saved_places(places: dict[str, SavedPlace], path: Path | None = None) -> None:
    data_path = path or places_file()
    data_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "places": {alias: asdict(place) for alias, place in sorted(places.items())}
    }
    data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def point_place(name: str, point: Point) -> Place:
    return Place(
        provider="coordinate",
        id="",
        name=name,
        category="coordinate",
        phone="",
        address="",
        road_address="",
        x=point.x,
        y=point.y,
        url=build_tmap_search_url(name),
    )


def saved_to_place(saved: SavedPlace) -> Place:
    return Place(
        provider=saved.provider,
        id=saved.provider_id,
        name=saved.name,
        category="saved",
        phone="",
        address=saved.address,
        road_address=saved.address,
        x=saved.x,
        y=saved.y,
        url=build_tmap_search_url(saved.name),
    )


def resolve_place(
    client: TmapClient,
    value: str,
    *,
    saved_path: Path | None = None,
) -> Place:
    saved = load_saved_places(saved_path).get(value)
    if saved is not None:
        return saved_to_place(saved)
    point = parse_coordinate(value)
    if point is not None:
        return point_place(value, point)
    places = client.search_places(value, size=1)
    if places:
        return places[0]
    geocoded = client.geocode(value)
    if geocoded:
        return geocoded[0]
    raise ResolveError(f"Could not resolve location: {value}")


def _validate_limit(value: int) -> None:
    if not 1 <= value <= 20:
        raise ResolveError("limit must be between 1 and 20")


def _validate_transit_count(value: int) -> None:
    if not 1 <= value <= 10:
        raise ResolveError("count must be between 1 and 10")


def _validate_radius_km(value: int) -> None:
    if not 1 <= value <= 33:
        raise ResolveError("radius-km must be between 1 and 33")


def format_distance(meters: int | float) -> str:
    if meters < 1000:
        return f"{meters:.0f} m"
    return f"{meters / 1000:.1f} km"


def format_duration(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    hours, remainder = divmod(minutes, 60)
    if hours:
        return f"{hours} h {remainder} min"
    return f"{minutes} min"


def emit_places(places: list[Place], *, use_json: bool) -> None:
    if use_json:
        print(
            json.dumps(
                [asdict(place) for place in places], ensure_ascii=False, indent=2
            )
        )
        return
    if not places:
        print("No places found")
        return
    for index, place in enumerate(places, 1):
        _print_place(place, index=index if len(places) > 1 else None)


def _print_place(place: Place, index: int | None = None) -> None:
    prefix = f"{index}. " if index is not None else ""
    print(f"{prefix}{place.name}")
    if place.category:
        print(f"   Category: {place.category}")
    address = place.road_address or place.address
    if address:
        print(f"   Address: {address}")
    if place.phone:
        print(f"   Phone: {place.phone}")
    print(f"   Coordinates: {place.x},{place.y}")
    if place.distance is not None:
        print(f"   Distance: {format_distance(place.distance)}")
    if place.url:
        print(f"   TMAP: {place.url}")


def emit_transit_routes(routes: list[TransitRoute], *, use_json: bool) -> None:
    if use_json:
        print(
            json.dumps(
                [asdict(route) for route in routes], ensure_ascii=False, indent=2
            )
        )
        return
    if not routes:
        print("No transit routes found")
        return
    for index, route in enumerate(routes, 1):
        print(f"{index}. {format_duration(route.total_time_seconds)}")
        print(f"   Fare: {route.fare:,} KRW")
        print(f"   Transfers: {route.transfer_count}")
        print(f"   Distance: {format_distance(route.total_distance_meters)}")
        print(f"   Walk: {format_distance(route.total_walk_distance_meters)}")
        for leg in route.legs:
            route_label = f" {leg.route}" if leg.route else ""
            print(
                f"   - {leg.mode}{route_label}: {leg.start} -> {leg.end} "
                f"({format_duration(leg.duration_seconds)}, "
                f"{format_distance(leg.distance_meters)})"
            )
            if leg.stops:
                shown = " → ".join(leg.stops[:5])
                suffix = " ..." if len(leg.stops) > 5 else ""
                print(f"     Stops: {shown}{suffix}")


def client_from_args(args: argparse.Namespace) -> TmapClient:
    credentials = load_config(args.config)
    return TmapClient(credentials.tmap_app_key)


def cmd_setup(args: argparse.Namespace) -> int:
    setup(args.config, args.tmap_app_key_command)
    print(f"Config written: {args.config}")
    try:
        load_config(args.config)
    except ConfigError as error:
        print(f"Warning: {error}")
        return 0
    print("TMAP app key command works")
    return 0


def cmd_place(args: argparse.Namespace) -> int:
    if args.provider != "tmap":
        url = _search_url_for_provider(args.provider, args.query)
        if args.use_json:
            print(
                json.dumps(
                    {"provider": args.provider, "query": args.query, "url": url},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(url)
        if args.open:
            webbrowser.open(url)
        return 0
    _validate_limit(args.limit)
    client = client_from_args(args)
    places = client.search_places(args.query, size=args.limit)
    emit_places(places, use_json=args.use_json)
    return 0 if places else 1


def _search_url_for_provider(provider: str, query: str) -> str:
    if provider == "tmap":
        return build_tmap_search_url(query)
    if provider == "naver":
        return build_naver_search_url(query)
    if provider == "kakao":
        return build_kakao_search_url(query)
    raise ResolveError(f"unsupported provider: {provider}")


def cmd_nearby(args: argparse.Namespace) -> int:
    if args.provider != "tmap":
        query = f"{args.near} {args.query}"
        url = _search_url_for_provider(args.provider, query)
        if args.use_json:
            print(
                json.dumps(
                    {
                        "provider": args.provider,
                        "query": args.query,
                        "near": args.near,
                        "url": url,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(url)
        if args.open:
            webbrowser.open(url)
        return 0
    _validate_limit(args.limit)
    _validate_radius_km(args.radius_km)
    client = client_from_args(args)
    center_place = resolve_place(client, args.near, saved_path=args.places)
    center = Point(x=center_place.x, y=center_place.y)
    places = client.search_places(
        args.query,
        size=args.limit,
        center=center,
        radius_km=args.radius_km,
    )
    emit_places(places, use_json=args.use_json)
    return 0 if places else 1


def cmd_transit(args: argparse.Namespace) -> int:
    _validate_transit_count(args.count)
    client = client_from_args(args)
    locations = [args.origin, *args.via, args.destination]
    places = [
        resolve_place(client, location, saved_path=args.places)
        for location in locations
    ]
    segments: list[dict[str, object]] = []
    has_routes = False
    for origin, destination in zip(places, places[1:]):
        routes = client.transit_routes(
            Point(origin.x, origin.y),
            Point(destination.x, destination.y),
            count=args.count,
            search_dttm=args.at,
        )
        if routes:
            has_routes = True
        segments.append(
            {
                "origin": origin,
                "destination": destination,
                "routes": routes,
            }
        )
    if args.use_json:
        print(
            json.dumps(
                {
                    "origin": asdict(places[0]),
                    "destination": asdict(places[-1]),
                    "via": [asdict(place) for place in places[1:-1]],
                    "segments": [
                        {
                            "origin": asdict(cast("Place", segment["origin"])),
                            "destination": asdict(
                                cast("Place", segment["destination"])
                            ),
                            "routes": [
                                asdict(route)
                                for route in cast(
                                    "list[TransitRoute]", segment["routes"]
                                )
                            ],
                        }
                        for segment in segments
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for index, segment in enumerate(segments, 1):
            origin = cast("Place", segment["origin"])
            destination = cast("Place", segment["destination"])
            routes = cast("list[TransitRoute]", segment["routes"])
            print(f"Segment {index}: {origin.name} -> {destination.name}")
            print(f"Origin: {origin.name} ({origin.x},{origin.y})")
            print(f"Destination: {destination.name} ({destination.x},{destination.y})")
            emit_transit_routes(routes, use_json=False)
    return 0 if has_routes else 1


def cmd_geocode(args: argparse.Namespace) -> int:
    _validate_limit(args.limit)
    client = client_from_args(args)
    places = client.geocode(args.address)[: args.limit]
    emit_places(places, use_json=args.use_json)
    return 0 if places else 1


def cmd_reverse(args: argparse.Namespace) -> int:
    point = parse_coordinate(args.coords)
    if point is None:
        raise ResolveError("coords must be longitude,latitude")
    client = client_from_args(args)
    response = client.reverse(point, address_type=args.address_type)
    if args.use_json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0
    address_info = response.get("addressInfo")
    if isinstance(address_info, dict):
        full_address = address_info.get("fullAddress") or address_info.get("address")
        if full_address:
            print(full_address)
            return 0
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


def cmd_saved(args: argparse.Namespace) -> int:
    if args.saved_command == "list":
        saved = load_saved_places(args.places)
        if args.use_json:
            print(
                json.dumps(
                    [asdict(place) for place in saved.values()],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if not saved:
            print("No saved places")
            return 0
        for alias, saved_place in sorted(saved.items()):
            print(f"{alias}: {saved_place.name} ({saved_place.x},{saved_place.y})")
            if saved_place.address:
                print(f"   {saved_place.address}")
        return 0
    if args.saved_command == "remove":
        saved = load_saved_places(args.places)
        if args.alias not in saved:
            raise ResolveError(f"saved place not found: {args.alias}")
        del saved[args.alias]
        save_saved_places(saved, args.places)
        print(f"Removed saved place: {args.alias}")
        return 0
    if args.saved_command == "add":
        client = client_from_args(args)
        place = resolve_place(client, args.location, saved_path=args.places)
        saved = load_saved_places(args.places)
        saved[args.alias] = SavedPlace(
            alias=args.alias,
            name=place.name,
            x=place.x,
            y=place.y,
            address=place.road_address or place.address,
            provider=place.provider,
            provider_id=place.id,
        )
        save_saved_places(saved, args.places)
        print(f"Saved {args.alias}: {place.name} ({place.x},{place.y})")
        return 0
    raise ResolveError("unknown saved command")


def cmd_open(args: argparse.Namespace) -> int:
    url = _search_url_for_provider(args.provider, args.query)
    print(url)
    if args.open:
        webbrowser.open(url)
    return 0


def cmd_route_url(args: argparse.Namespace) -> int:
    client = client_from_args(args)
    origin = resolve_place(client, args.origin, saved_path=args.places)
    destination = resolve_place(client, args.destination, saved_path=args.places)
    url = build_route_url(args.provider, args.mode, origin, destination)
    if args.use_json:
        print(
            json.dumps(
                {
                    "provider": args.provider,
                    "mode": args.mode,
                    "origin": asdict(origin),
                    "destination": asdict(destination),
                    "url": url,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(url)
    if args.open:
        webbrowser.open(url)
    return 0


def add_json_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        dest="use_json",
        default=argparse.SUPPRESS,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Use TMAP APIs for Korean places and transit"
    )
    parser.add_argument("--config", type=Path, default=config_file())
    parser.add_argument("--places", type=Path, default=places_file())
    parser.add_argument("-j", "--json", action="store_true", dest="use_json")

    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser("setup", help="Write secret command config")
    setup_parser.add_argument("--tmap-app-key-command", required=True)

    place_parser = subparsers.add_parser(
        "place", help="Search places or map search URLs"
    )
    add_json_option(place_parser)
    place_parser.add_argument("query")
    place_parser.add_argument("-n", "--limit", type=int, default=10)
    place_parser.add_argument(
        "--provider", choices=["tmap", "naver", "kakao"], default="tmap"
    )
    place_parser.add_argument("--open", action="store_true")

    nearby_parser = subparsers.add_parser(
        "nearby", help="Search places near a location"
    )
    add_json_option(nearby_parser)
    nearby_parser.add_argument("query")
    nearby_parser.add_argument(
        "--near", required=True, help="Saved alias, lng,lat, or place query"
    )
    nearby_parser.add_argument("--radius-km", type=int, default=1)
    nearby_parser.add_argument("-n", "--limit", type=int, default=10)
    nearby_parser.add_argument(
        "--provider", choices=["tmap", "naver", "kakao"], default="tmap"
    )
    nearby_parser.add_argument("--open", action="store_true")

    transit_parser = subparsers.add_parser("transit", help="Get TMAP transit routes")
    add_json_option(transit_parser)
    transit_parser.add_argument("origin")
    transit_parser.add_argument("destination")
    transit_parser.add_argument(
        "--via",
        action="append",
        default=[],
        help="Waypoint to visit; repeat for multiple split-route segments",
    )
    transit_parser.add_argument("--count", type=int, default=3)
    transit_parser.add_argument("--at", help="Search time as yyyymmddhhmi")

    geocode_parser = subparsers.add_parser(
        "geocode", help="Convert address to coordinates"
    )
    add_json_option(geocode_parser)
    geocode_parser.add_argument("address")
    geocode_parser.add_argument("-n", "--limit", type=int, default=5)

    reverse_parser = subparsers.add_parser(
        "reverse", help="Convert coordinates to address"
    )
    add_json_option(reverse_parser)
    reverse_parser.add_argument("coords", help="Coordinates as longitude,latitude")
    reverse_parser.add_argument("--address-type", default="A10")

    saved_parser = subparsers.add_parser("saved", help="Manage saved places")
    add_json_option(saved_parser)
    saved_subparsers = saved_parser.add_subparsers(dest="saved_command", required=True)
    saved_add = saved_subparsers.add_parser("add", help="Save a place alias")
    saved_add.add_argument("alias")
    saved_add.add_argument("location")
    saved_subparsers.add_parser("list", help="List saved places")
    saved_remove = saved_subparsers.add_parser("remove", help="Remove a saved place")
    saved_remove.add_argument("alias")

    open_parser = subparsers.add_parser("open", help="Print or open map search URL")
    open_parser.add_argument("query")
    open_parser.add_argument(
        "--provider", choices=["tmap", "naver", "kakao"], default="tmap"
    )
    open_parser.add_argument("--open", action="store_true")

    route_url_parser = subparsers.add_parser(
        "route-url", help="Print or open NAVER/Kakao route URL"
    )
    add_json_option(route_url_parser)
    route_url_parser.add_argument("origin")
    route_url_parser.add_argument("destination")
    route_url_parser.add_argument(
        "--provider", choices=["naver", "kakao"], default="kakao"
    )
    route_url_parser.add_argument(
        "--mode",
        choices=["transit", "driving", "walking", "bicycle"],
        default="transit",
    )
    route_url_parser.add_argument("--open", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            return cmd_setup(args)
        if args.command == "place":
            return cmd_place(args)
        if args.command == "nearby":
            return cmd_nearby(args)
        if args.command == "transit":
            return cmd_transit(args)
        if args.command == "geocode":
            return cmd_geocode(args)
        if args.command == "reverse":
            return cmd_reverse(args)
        if args.command == "saved":
            return cmd_saved(args)
        if args.command == "open":
            return cmd_open(args)
        if args.command == "route-url":
            return cmd_route_url(args)
    except (ApiError, ConfigError, ResolveError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

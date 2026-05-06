#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

CONFIG_SUBDIR = "nmap-cli"
CONFIG_FILE_NAME = "config.json"
MAPS_BASE_URLS = {
    "geocoding": "https://maps.apigw.ntruss.com/map-geocode/v2",
    "reverse_geocoding": "https://maps.apigw.ntruss.com/map-reversegeocode/v2",
    "directions5": "https://maps.apigw.ntruss.com/map-direction/v1",
    "directions15": "https://maps.apigw.ntruss.com/map-direction-15/v1",
    "static": "https://maps.apigw.ntruss.com/map-static/v2",
}


@dataclass(frozen=True)
class Point:
    x: str
    y: str


@dataclass(frozen=True)
class Address:
    road_address: str
    jibun_address: str
    english_address: str
    x: str
    y: str
    distance: float | None = None


@dataclass(frozen=True)
class RouteResult:
    summary: dict[str, Any]
    guide: list[dict[str, Any]]


@dataclass(frozen=True)
class Credentials:
    key_id: str
    key: str


class ConfigError(RuntimeError):
    """Configuration could not be loaded."""


@dataclass(frozen=True)
class DirectionsRequest:
    start: Point
    goal: Point
    waypoints: list[Point]
    option: str
    lang: str
    use_directions15: bool


@dataclass(frozen=True)
class RouteCommand:
    origin: str
    destination: str
    option: str
    lang: str
    waypoints: list[str]
    use_directions15: bool
    config_path: Path | None


@dataclass(frozen=True)
class StaticMapCommand:
    center: str
    output: Path
    width: int
    height: int
    level: int
    maptype: str
    image_format: str
    scale: int
    lang: str
    markers: list[str]
    config_path: Path | None


class NcloudMapsClient:
    def __init__(self, credentials: Credentials) -> None:
        self.credentials = credentials

    def request_json(
        self,
        api: str,
        path: str,
        params: dict[str, str],
    ) -> dict[str, Any] | None:
        data = self.request_bytes(api, path, params, accept="application/json")
        if data is None:
            return None
        try:
            return cast("dict[str, Any]", json.loads(data.decode("utf-8")))
        except json.JSONDecodeError as error:
            print(f"Error decoding JSON response: {error}")
            return None

    def request_bytes(
        self,
        api: str,
        path: str,
        params: dict[str, str],
        *,
        accept: str = "*/*",
    ) -> bytes | None:
        base_url = MAPS_BASE_URLS[api]
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{base_url}{path}?{query}"
        headers = {
            "x-ncp-apigw-api-key-id": self.credentials.key_id,
            "x-ncp-apigw-api-key": self.credentials.key,
            "Accept": accept,
        }
        request = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
                return cast("bytes", response.read())
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            print(f"HTTP Error {error.code}: {error.reason}")
            if body:
                print(body)
        except urllib.error.URLError as error:
            print(f"Error: {error}")
        return None

    def geocode(
        self,
        query: str,
        *,
        coordinate: str | None = None,
        language: str = "kor",
        count: int = 10,
    ) -> dict[str, Any] | None:
        params = {
            "query": query,
            "language": language,
            "count": str(count),
        }
        if coordinate:
            params["coordinate"] = coordinate
        return self.request_json("geocoding", "/geocode", params)

    def reverse_geocode(
        self,
        coords: str,
        *,
        orders: str = "legalcode,admcode,addr,roadaddr",
    ) -> dict[str, Any] | None:
        return self.request_json(
            "reverse_geocoding",
            "/gc",
            {
                "coords": coords,
                "orders": orders,
                "output": "json",
                "sourcecrs": "EPSG:4326",
            },
        )

    def directions(self, request: DirectionsRequest) -> dict[str, Any] | None:
        api = (
            "directions15"
            if request.use_directions15 or len(request.waypoints) > 5
            else "directions5"
        )
        params = {
            "start": f"{request.start.x},{request.start.y}",
            "goal": f"{request.goal.x},{request.goal.y}",
            "option": request.option,
            "lang": request.lang,
        }
        if request.waypoints:
            params["waypoints"] = "|".join(
                f"{point.x},{point.y}" for point in request.waypoints
            )
        return self.request_json(api, "/driving", params)

    def static_map(
        self,
        params: dict[str, str],
    ) -> bytes | None:
        return self.request_bytes("static", "/raster", params)


def config_dir() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / CONFIG_SUBDIR
    return Path.home() / ".config" / CONFIG_SUBDIR


def config_file() -> Path:
    return config_dir() / CONFIG_FILE_NAME


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        msg = f"config must be a JSON object: {path}"
        raise ConfigError(msg)
    return data


def run_command(command: str) -> str:
    try:
        result = subprocess.run(
            shlex.split(command),
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        msg = f"failed to run credential command: {command}"
        raise ConfigError(msg) from error
    value = result.stdout.strip()
    if not value:
        msg = f"credential command returned no output: {command}"
        raise ConfigError(msg)
    return value


def _resolve_secret(
    env_key: str,
    env_command_key: str,
    data: dict[str, Any],
    config_key: str,
    config_command_key: str,
) -> str | None:
    value = os.environ.get(env_key)
    if value:
        return value

    command = os.environ.get(env_command_key)
    if command:
        return run_command(command)

    command_value = data.get(config_command_key)
    if isinstance(command_value, str) and command_value:
        return run_command(command_value)

    config_value = data.get(config_key)
    if isinstance(config_value, str) and config_value:
        return config_value

    return None


def save_config(path: Path, config: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(config, file, indent=2)
        file.write("\n")


def setup(
    path: Path | None,
    api_key_id_command: str,
    api_key_command: str,
) -> None:
    config_path = path or config_file()
    config = {
        "api_key_id_command": api_key_id_command,
        "api_key_command": api_key_command,
    }
    save_config(config_path, config)
    load_config(config_path)
    print(f"Wrote {config_path}")


def load_config(path: Path | None = None) -> Credentials:
    config_path = path or config_file()
    data = _load_json(config_path)
    key_id = _resolve_secret(
        "NCLOUD_MAPS_API_KEY_ID",
        "NCLOUD_MAPS_API_KEY_ID_COMMAND",
        data,
        "api_key_id",
        "api_key_id_command",
    )
    key = _resolve_secret(
        "NCLOUD_MAPS_API_KEY",
        "NCLOUD_MAPS_API_KEY_COMMAND",
        data,
        "api_key",
        "api_key_command",
    )
    if not key_id:
        msg = (
            "Ncloud Maps API key ID missing; set NCLOUD_MAPS_API_KEY_ID, "
            "NCLOUD_MAPS_API_KEY_ID_COMMAND, or config api_key_id/api_key_id_command"
        )
        raise ConfigError(msg)
    if not key:
        msg = (
            "Ncloud Maps API key missing; set NCLOUD_MAPS_API_KEY, "
            "NCLOUD_MAPS_API_KEY_COMMAND, or config api_key/api_key_command"
        )
        raise ConfigError(msg)
    return Credentials(key_id=key_id, key=key)


def client_from_config(config_path: Path | None = None) -> NcloudMapsClient | None:
    try:
        credentials = load_config(config_path)
    except ConfigError as error:
        print(error)
        return None
    return NcloudMapsClient(credentials)


def parse_coordinate(value: str) -> Point | None:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        return None
    try:
        float(parts[0])
        float(parts[1])
    except ValueError:
        return None
    return Point(x=parts[0], y=parts[1])


def first_address(response: dict[str, Any]) -> Address | None:
    addresses = response.get("addresses")
    if not isinstance(addresses, list) or not addresses:
        return None
    first = addresses[0]
    if not isinstance(first, dict):
        return None
    x = first.get("x")
    y = first.get("y")
    if not isinstance(x, str) or not isinstance(y, str):
        return None
    distance_value = first.get("distance")
    distance = (
        float(distance_value) if isinstance(distance_value, int | float) else None
    )
    return Address(
        road_address=str(first.get("roadAddress") or ""),
        jibun_address=str(first.get("jibunAddress") or ""),
        english_address=str(first.get("englishAddress") or ""),
        x=x,
        y=y,
        distance=distance,
    )


def first_route_list(route: dict[str, Any], option: str) -> list[Any] | None:
    for route_option in option.split(":"):
        value = route.get(route_option)
        if isinstance(value, list) and value:
            return value
    for value in route.values():
        if isinstance(value, list) and value:
            return value
    return None


def route_choice(response: dict[str, Any], option: str) -> RouteResult | None:
    route = response.get("route")
    if not isinstance(route, dict):
        return None
    selected_routes = first_route_list(cast("dict[str, Any]", route), option)
    if selected_routes is None or not isinstance(selected_routes[0], dict):
        return None

    summary = selected_routes[0].get("summary")
    guide = selected_routes[0].get("guide")
    if not isinstance(summary, dict):
        return None
    if not isinstance(guide, list):
        guide = []
    return RouteResult(
        summary=cast("dict[str, Any]", summary),
        guide=[item for item in guide if isinstance(item, dict)],
    )


def resolve_point(client: NcloudMapsClient, value: str) -> Point | None:
    coordinate = parse_coordinate(value)
    if coordinate is not None:
        return coordinate

    response = client.geocode(value, count=1)
    if response is None:
        return None
    address = first_address(response)
    if address is None:
        print(f"Could not geocode: {value}")
        return None
    return Point(x=address.x, y=address.y)


def format_distance(meters: int) -> str:
    if meters < 1000:
        return f"{meters} m"
    return f"{meters / 1000:.1f} km"


def format_duration(milliseconds: int) -> str:
    minutes = max(1, round(milliseconds / 60_000))
    hours, remainder = divmod(minutes, 60)
    if hours:
        return f"{hours} h {remainder} min"
    return f"{minutes} min"


def format_money(amount: int) -> str:
    return f"{amount:,} KRW"


def build_naver_maps_url(query: str, x: str | None = None, y: str | None = None) -> str:
    encoded_query = urllib.parse.quote(query)
    url = f"https://map.naver.com/p/search/{encoded_query}"
    if x and y:
        url += f"?c={x},{y},15,0,0,0,dh"
    return url


def print_address(address: Address, query: str, index: int | None = None) -> None:
    prefix = f"{index}. " if index is not None else ""
    title = address.road_address or address.jibun_address or address.english_address
    print(f"{prefix}{title}")
    if address.jibun_address and address.jibun_address != title:
        print(f"   Jibun: {address.jibun_address}")
    if address.english_address:
        print(f"   English: {address.english_address}")
    print(f"   Coordinates: {address.x}, {address.y}")
    if address.distance is not None:
        print(f"   Distance: {address.distance:.0f} m")
    print(f"   Naver Maps: {build_naver_maps_url(query, address.x, address.y)}")


def format_reverse_result(result: dict[str, Any]) -> str:
    region = result.get("region")
    if not isinstance(region, dict):
        return str(result.get("name", "unknown"))
    names: list[str] = []
    for key in ("area1", "area2", "area3", "area4"):
        area = region.get(key)
        if isinstance(area, dict) and area.get("name"):
            names.append(str(area["name"]))
    land = result.get("land")
    if isinstance(land, dict):
        road_name = land.get("name")
        number1 = land.get("number1")
        number2 = land.get("number2")
        if road_name:
            names.append(str(road_name))
        if number1:
            number = str(number1)
            if number2:
                number += f"-{number2}"
            names.append(number)
    return " ".join(names)


def geocode(
    query: str,
    limit: int,
    language: str,
    coordinate: str | None,
    config_path: Path | None,
) -> None:
    client = client_from_config(config_path)
    if client is None:
        return
    response = client.geocode(
        query,
        coordinate=coordinate,
        language=language,
        count=limit,
    )
    if response is None:
        return
    addresses = response.get("addresses")
    if not isinstance(addresses, list) or not addresses:
        print(f"No address results found for '{query}'")
        return
    for index, item in enumerate(addresses[:limit], 1):
        if not isinstance(item, dict):
            continue
        address = first_address({"addresses": [item]})
        if address is not None:
            print_address(address, query, index)


def reverse(coords: str, orders: str, config_path: Path | None) -> None:
    client = client_from_config(config_path)
    if client is None:
        return
    response = client.reverse_geocode(coords, orders=orders)
    if response is None:
        return
    results = response.get("results")
    if not isinstance(results, list) or not results:
        print(f"No reverse geocoding results found for '{coords}'")
        return
    for result in results:
        if isinstance(result, dict):
            name = result.get("name", "unknown")
            print(f"{name}: {format_reverse_result(result)}")


def route(command: RouteCommand) -> None:
    client = client_from_config(command.config_path)
    if client is None:
        return

    start = resolve_point(client, command.origin)
    goal = resolve_point(client, command.destination)
    if start is None or goal is None:
        return
    waypoint_points = []
    for waypoint in command.waypoints:
        point = resolve_point(client, waypoint)
        if point is None:
            return
        waypoint_points.append(point)

    response = client.directions(
        DirectionsRequest(
            start=start,
            goal=goal,
            waypoints=waypoint_points,
            option=command.option,
            lang=command.lang,
            use_directions15=command.use_directions15,
        )
    )
    if response is None:
        return
    selected = route_choice(response, command.option)
    if selected is None:
        print(f"No route found from '{command.origin}' to '{command.destination}'")
        return

    summary = selected.summary
    distance = int(summary.get("distance", 0))
    duration = int(summary.get("duration", 0))
    print(f"Route from {command.origin} to {command.destination}")
    print(f"Distance: {format_distance(distance)}")
    print(f"Duration: {format_duration(duration)}")
    print(f"Toll fare: {format_money(int(summary.get('tollFare', 0)))}")
    print(f"Taxi fare: {format_money(int(summary.get('taxiFare', 0)))}")
    print(f"Fuel price: {format_money(int(summary.get('fuelPrice', 0)))}")
    print(f"Naver Maps: {build_naver_maps_url(command.destination, goal.x, goal.y)}")

    if selected.guide:
        print("\nDirections:")
    for index, guide in enumerate(selected.guide[:20], 1):
        instruction = str(guide.get("instructions", ""))
        guide_distance = int(guide.get("distance", 0))
        guide_duration = int(guide.get("duration", 0))
        print(
            f"{index}. {instruction} ({format_distance(guide_distance)}, "
            f"{format_duration(guide_duration)})"
        )


def static_map(command: StaticMapCommand) -> None:
    client = client_from_config(command.config_path)
    if client is None:
        return
    point = resolve_point(client, command.center)
    if point is None:
        return

    params = {
        "center": f"{point.x},{point.y}",
        "w": str(command.width),
        "h": str(command.height),
        "level": str(command.level),
        "maptype": command.maptype,
        "format": command.image_format,
        "scale": str(command.scale),
        "lang": command.lang,
    }
    if command.markers:
        params["markers"] = command.markers[0]
    else:
        params["markers"] = f"type:d|size:mid|pos:{point.x} {point.y}"

    data = client.static_map(params)
    if data is None:
        return
    command.output.parent.mkdir(parents=True, exist_ok=True)
    command.output.write_bytes(data)
    print(f"Wrote {command.output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Use NAVER Cloud Maps APIs from the command line"
    )
    parser.add_argument("--config", type=Path, help="Config JSON path")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    setup_parser = subparsers.add_parser("setup", help="Setup credential commands")
    setup_parser.add_argument("--api-key-id-command", required=True)
    setup_parser.add_argument("--api-key-command", required=True)

    geocode_parser = subparsers.add_parser("geocode", help="Search addresses")
    geocode_parser.add_argument("query")
    geocode_parser.add_argument("-n", "--limit", type=int, default=5)
    geocode_parser.add_argument("--language", choices=["kor", "eng"], default="kor")
    geocode_parser.add_argument("--coordinate", help="Search center as lng,lat")

    reverse_parser = subparsers.add_parser(
        "reverse", help="Convert coordinates to address"
    )
    reverse_parser.add_argument("coords", help="Coordinates as lng,lat")
    reverse_parser.add_argument(
        "--orders",
        default="legalcode,admcode,addr,roadaddr",
        help="Comma-separated conversion types",
    )

    route_parser = subparsers.add_parser("route", help="Get driving directions")
    route_parser.add_argument("origin")
    route_parser.add_argument("destination")
    route_parser.add_argument(
        "--option",
        default="traoptimal",
        help="trafast, tracomfort, traoptimal, traavoidtoll, or traavoidcaronly",
    )
    route_parser.add_argument("--lang", choices=["ko", "en", "ja", "zh"], default="ko")
    route_parser.add_argument("--waypoint", action="append", default=[])
    route_parser.add_argument("--directions15", action="store_true")

    static_parser = subparsers.add_parser("static", help="Create static map image")
    static_parser.add_argument("center", help="Address or lng,lat")
    static_parser.add_argument("--output", type=Path, required=True)
    static_parser.add_argument("--width", type=int, default=600)
    static_parser.add_argument("--height", type=int, default=400)
    static_parser.add_argument("--level", type=int, default=16)
    static_parser.add_argument(
        "--maptype",
        choices=["basic", "traffic", "satellite", "satellite_base", "terrain"],
        default="basic",
    )
    static_parser.add_argument(
        "--format", choices=["jpg", "jpeg", "png8", "png"], default="png"
    )
    static_parser.add_argument("--scale", type=int, choices=[1, 2], default=1)
    static_parser.add_argument("--lang", choices=["ko", "en", "ja", "zh"], default="ko")
    static_parser.add_argument(
        "--marker",
        action="append",
        default=[],
        help="Raw marker option, e.g. 'type:d|size:mid|pos:127.1 37.3'",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "setup":
        try:
            setup(args.config, args.api_key_id_command, args.api_key_command)
        except ConfigError as error:
            print(error)
    elif args.command == "geocode":
        geocode(args.query, args.limit, args.language, args.coordinate, args.config)
    elif args.command == "reverse":
        reverse(args.coords, args.orders, args.config)
    elif args.command == "route":
        route(
            RouteCommand(
                origin=args.origin,
                destination=args.destination,
                option=args.option,
                lang=args.lang,
                waypoints=args.waypoint,
                use_directions15=args.directions15,
                config_path=args.config,
            )
        )
    elif args.command == "static":
        static_map(
            StaticMapCommand(
                center=args.center,
                output=args.output,
                width=args.width,
                height=args.height,
                level=args.level,
                maptype=args.maptype,
                image_format=args.format,
                scale=args.scale,
                lang=args.lang,
                markers=args.marker,
                config_path=args.config,
            )
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

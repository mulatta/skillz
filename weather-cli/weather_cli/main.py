from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from math import asin, atan2, cos, floor, log, pi, sin, tan
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from collections.abc import Iterable

KMA_API = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"
NOMINATIM_API = "https://nominatim.openstreetmap.org/search"
CONFIG_SUBDIR = "weather-cli"
CONFIG_FILE_NAME = "config.json"
SERVICE_KEY_COMMAND_FIELD = "service_key_command"
KST = ZoneInfo("Asia/Seoul")
USER_AGENT = "weather-cli/0.1 (https://github.com/mulatta/skillz)"

PTY = {
    "0": "강수 없음",
    "1": "비",
    "2": "비/눈",
    "3": "눈",
    "4": "소나기",
    "5": "빗방울",
    "6": "빗방울/눈날림",
    "7": "눈날림",
}
SKY = {
    "1": "맑음",
    "3": "구름많음",
    "4": "흐림",
}
ICONS = {
    "강수 없음": "☀️",
    "맑음": "☀️",
    "구름많음": "⛅",
    "흐림": "☁️",
    "비": "🌧️",
    "소나기": "🌦️",
    "빗방울": "🌦️",
    "비/눈": "🌨️",
    "빗방울/눈날림": "🌨️",
    "눈": "❄️",
    "눈날림": "❄️",
}


class Geocoder(StrEnum):
    AUTO = "auto"
    NMAP = "nmap"
    NOMINATIM = "nominatim"
    NONE = "none"


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    name: str


@dataclass(frozen=True)
class Grid:
    nx: int
    ny: int


@dataclass(frozen=True)
class CurrentWeather:
    timestamp: datetime
    values: dict[str, str]


@dataclass(frozen=True)
class ForecastSlot:
    timestamp: datetime
    values: dict[str, str]


def latlon_to_grid(lat: float, lon: float) -> Grid:
    """Convert WGS84 coordinates to KMA village forecast grid coordinates."""
    re = 6371.00877
    grid = 5.0
    slat1 = 30.0 * pi / 180.0
    slat2 = 60.0 * pi / 180.0
    olon = 126.0 * pi / 180.0
    olat = 38.0 * pi / 180.0
    xo = 43.0
    yo = 136.0

    re_grid = re / grid
    sn = tan(pi * 0.25 + slat2 * 0.5) / tan(pi * 0.25 + slat1 * 0.5)
    sn = log(cos(slat1) / cos(slat2)) / log(sn)
    sf = tan(pi * 0.25 + slat1 * 0.5)
    sf = (sf**sn) * cos(slat1) / sn
    ro = tan(pi * 0.25 + olat * 0.5)
    ro = re_grid * sf / (ro**sn)

    ra = tan(pi * 0.25 + lat * pi / 180.0 * 0.5)
    ra = re_grid * sf / (ra**sn)
    theta = lon * pi / 180.0 - olon
    if theta > pi:
        theta -= 2.0 * pi
    if theta < -pi:
        theta += 2.0 * pi
    theta *= sn

    nx = floor(ra * sin(theta) + xo + 0.5)
    ny = floor(ro - ra * cos(theta) + yo + 0.5)
    return Grid(nx=nx, ny=ny)


def grid_to_latlon(nx: int, ny: int) -> tuple[float, float]:
    """Convert KMA grid coordinates to WGS84 coordinates."""
    re = 6371.00877
    grid = 5.0
    slat1 = 30.0 * pi / 180.0
    slat2 = 60.0 * pi / 180.0
    olon = 126.0 * pi / 180.0
    olat = 38.0 * pi / 180.0
    xo = 43.0
    yo = 136.0

    re_grid = re / grid
    sn = tan(pi * 0.25 + slat2 * 0.5) / tan(pi * 0.25 + slat1 * 0.5)
    sn = log(cos(slat1) / cos(slat2)) / log(sn)
    sf = tan(pi * 0.25 + slat1 * 0.5)
    sf = (sf**sn) * cos(slat1) / sn
    ro = tan(pi * 0.25 + olat * 0.5)
    ro = re_grid * sf / (ro**sn)

    x = nx - xo
    y = ro - ny + yo
    ra = (x * x + y * y) ** 0.5
    if sn < 0.0:
        ra = -ra
    alat = (re_grid * sf / ra) ** (1.0 / sn)
    alat = 2.0 * asin(alat) - pi * 0.5
    theta = 0.0
    if abs(x) > 0.0:
        if abs(y) > 0.0:
            theta = atan2_compat(x, y)
        elif x < 0.0:
            theta = -pi * 0.5
        else:
            theta = pi * 0.5
    alon = theta / sn + olon
    return alat * 180.0 / pi, alon * 180.0 / pi


def atan2_compat(y: float, x: float) -> float:
    # Helper keeps inverse conversion aligned with original KMA reference formula.
    return atan2(y, x)


def latest_ultra_ncst_time(now: datetime | None = None) -> tuple[str, str]:
    kst_now = (now or datetime.now(tz=KST)).astimezone(KST)
    if kst_now.minute < 40:
        kst_now -= timedelta(hours=1)
    return kst_now.strftime("%Y%m%d"), kst_now.strftime("%H00")


def latest_vilage_fcst_time(now: datetime | None = None) -> tuple[str, str]:
    kst_now = (now or datetime.now(tz=KST)).astimezone(KST) - timedelta(minutes=20)
    base_hours = [2, 5, 8, 11, 14, 17, 20, 23]
    hour = max(
        (candidate for candidate in base_hours if candidate <= kst_now.hour), default=23
    )
    if hour == 23 and kst_now.hour < 2:
        kst_now -= timedelta(days=1)
    return kst_now.strftime("%Y%m%d"), f"{hour:02d}00"


def parse_latlon(value: str) -> Location | None:
    match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", value)
    if not match:
        return None
    first = float(match.group(1))
    second = float(match.group(2))
    if abs(first) <= 90 and abs(second) <= 180:
        return Location(lat=first, lon=second, name=f"{first:.5f},{second:.5f}")
    if abs(second) <= 90 and abs(first) <= 180:
        return Location(lat=second, lon=first, name=f"{second:.5f},{first:.5f}")
    return None


def geocode_location(query: str, geocoder: Geocoder) -> Location:
    parsed = parse_latlon(query)
    if parsed is not None:
        return parsed
    if geocoder is Geocoder.NONE:
        msg = "Location geocoding disabled; pass --lat/--lon or --nx/--ny"
        raise ValueError(msg)
    if geocoder in {Geocoder.AUTO, Geocoder.NMAP}:
        try:
            return geocode_with_nmap_cli(query)
        except (RuntimeError, ValueError) as error:
            if geocoder is Geocoder.NMAP:
                raise
            print(f"nmap-cli geocoder unavailable: {error}", file=sys.stderr)
    return geocode_with_nominatim(query)


def geocode_with_nmap_cli(query: str) -> Location:
    executable = shutil.which("nmap-cli")
    if executable is None:
        msg = "nmap-cli not found in PATH"
        raise RuntimeError(msg)
    result = subprocess.run(
        [executable, "geocode", query, "--limit", "1"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip() or "nmap-cli failed"
        raise RuntimeError(msg)
    return parse_nmap_geocode_output(result.stdout)


def parse_nmap_geocode_output(output: str) -> Location:
    name = ""
    lon: float | None = None
    lat: float | None = None
    for line in output.splitlines():
        stripped = line.strip()
        if not name and stripped:
            name = re.sub(r"^\d+\.\s*", "", stripped)
        match = re.search(
            r"Coordinates:\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)", stripped
        )
        if match:
            lon = float(match.group(1))
            lat = float(match.group(2))
            break
    if lat is None or lon is None:
        msg = "nmap-cli output did not include coordinates"
        raise ValueError(msg)
    return Location(lat=lat, lon=lon, name=name or f"{lat:.5f},{lon:.5f}")


def geocode_with_nominatim(query: str) -> Location:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": "1",
            "countrycodes": "kr",
        }
    )
    data = api_get_json(f"{NOMINATIM_API}?{params}", headers={"User-Agent": USER_AGENT})
    if not isinstance(data, list) or not data:
        msg = f"Location not found: {query}"
        raise ValueError(msg)
    first = cast("dict[str, Any]", data[0])
    return Location(
        lat=float(first["lat"]),
        lon=float(first["lon"]),
        name=str(first.get("display_name", query)),
    )


def api_get_json(url: str, headers: dict[str, str] | None = None) -> object:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        msg = f"HTTP {error.code} from {url}: {body or error.reason}"
        raise RuntimeError(msg) from error
    except urllib.error.URLError as error:
        msg = f"HTTP request failed for {url}: {error}"
        raise RuntimeError(msg) from error


def service_key_query_part(service_key: str) -> str:
    if "%" in service_key:
        return f"serviceKey={service_key}"
    return urllib.parse.urlencode({"serviceKey": service_key})


def kma_get(endpoint: str, service_key: str, params: dict[str, str]) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "pageNo": "1",
            "numOfRows": "1000",
            "dataType": "JSON",
            **params,
        }
    )
    url = f"{KMA_API}/{endpoint}?{service_key_query_part(service_key)}&{query}"
    data = api_get_json(url)
    if not isinstance(data, dict):
        msg = "Unexpected KMA response format"
        raise TypeError(msg)
    response = cast("dict[str, Any]", data.get("response", {}))
    header = cast("dict[str, Any]", response.get("header", {}))
    if str(header.get("resultCode")) != "00":
        message = str(header.get("resultMsg", "unknown error"))
        msg = f"KMA API error: {message}"
        raise RuntimeError(msg)
    return response


def extract_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    body = cast("dict[str, Any]", response.get("body", {}))
    items = cast("dict[str, Any]", body.get("items", {}))
    raw_items = items.get("item", [])
    if isinstance(raw_items, dict):
        return [raw_items]
    if isinstance(raw_items, list):
        return [item for item in raw_items if isinstance(item, dict)]
    return []


def get_current_weather(service_key: str, grid: Grid) -> CurrentWeather:
    base_date, base_time = latest_ultra_ncst_time()
    response = kma_get(
        "getUltraSrtNcst",
        service_key,
        {
            "base_date": base_date,
            "base_time": base_time,
            "nx": str(grid.nx),
            "ny": str(grid.ny),
        },
    )
    values: dict[str, str] = {}
    timestamp = parse_kma_datetime(base_date, base_time)
    for item in extract_items(response):
        category = str(item.get("category", ""))
        value = str(item.get("obsrValue", ""))
        if category:
            values[category] = value
            timestamp = parse_kma_datetime(
                str(item.get("baseDate", base_date)),
                str(item.get("baseTime", base_time)),
            )
    if not values:
        msg = "No current weather data available"
        raise RuntimeError(msg)
    return CurrentWeather(timestamp=timestamp, values=values)


def get_forecast(service_key: str, grid: Grid) -> list[ForecastSlot]:
    base_date, base_time = latest_vilage_fcst_time()
    response = kma_get(
        "getVilageFcst",
        service_key,
        {
            "base_date": base_date,
            "base_time": base_time,
            "nx": str(grid.nx),
            "ny": str(grid.ny),
        },
    )
    by_time: dict[datetime, dict[str, str]] = {}
    for item in extract_items(response):
        fcst_date = str(item.get("fcstDate", ""))
        fcst_time = str(item.get("fcstTime", ""))
        category = str(item.get("category", ""))
        value = str(item.get("fcstValue", ""))
        if not fcst_date or not fcst_time or not category:
            continue
        timestamp = parse_kma_datetime(fcst_date, fcst_time)
        by_time.setdefault(timestamp, {})[category] = value
    return [
        ForecastSlot(timestamp=timestamp, values=values)
        for timestamp, values in sorted(by_time.items())
    ]


def parse_kma_datetime(date_value: str, time_value: str) -> datetime:
    return datetime.strptime(f"{date_value}{time_value}", "%Y%m%d%H%M").replace(
        tzinfo=KST
    )


def fmt_float(value: str, suffix: str, digits: int = 1) -> str | None:
    try:
        number = float(value)
    except ValueError:
        return None
    return f"{number:.{digits}f}{suffix}"


def translate_condition(values: dict[str, str]) -> str:
    pty = values.get("PTY")
    if pty and pty != "0":
        return PTY.get(pty, f"강수형태 {pty}")
    sky = values.get("SKY")
    if sky:
        return SKY.get(sky, f"하늘상태 {sky}")
    if pty == "0":
        return PTY["0"]
    return "정보 없음"


def icon_for(condition: str) -> str:
    return ICONS.get(condition, "🌤️")


def format_current_weather(weather: CurrentWeather, location: str, grid: Grid) -> str:
    condition = translate_condition(weather.values)
    lines = [
        f"\n{icon_for(condition)} Weather for {location}",
        "=" * 50,
        f"Source: KMA ({grid.nx}, {grid.ny})",
        f"Time: {weather.timestamp.strftime('%Y-%m-%d %H:%M %Z')}",
        f"Condition: {condition}",
    ]
    details = [
        ("Temperature", fmt_float(weather.values.get("T1H", ""), "°C")),
        ("Humidity", fmt_float(weather.values.get("REH", ""), "%", digits=0)),
        ("Precipitation (1h)", format_precip(weather.values.get("RN1"))),
        ("Wind", format_wind(weather.values.get("WSD"), weather.values.get("VEC"))),
    ]
    for label, value in details:
        if value is not None:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def format_wind(speed: str | None, direction: str | None) -> str | None:
    if speed is None:
        return None
    speed_text = fmt_float(speed, " m/s")
    if speed_text is None:
        return None
    if direction is None:
        return speed_text
    try:
        degree = float(direction)
    except ValueError:
        return speed_text
    return f"{speed_text} from {degree:.0f}°"


def format_precip(value: str | None) -> str | None:
    if value is None:
        return None
    if value in {"0", "0.0", "강수없음"}:
        return "0 mm"
    return value if "mm" in value else f"{value} mm"


def format_forecast(
    slots: list[ForecastSlot], location: str, grid: Grid, days: int
) -> str:
    if not slots:
        return "No forecast data available"
    lines = [
        f"\n🔮 {days}-Day Forecast for {location}",
        "=" * 50,
        f"Source: KMA ({grid.nx}, {grid.ny})",
    ]
    by_day: dict[str, list[ForecastSlot]] = {}
    for slot in slots:
        by_day.setdefault(slot.timestamp.strftime("%Y-%m-%d"), []).append(slot)
    for day in sorted(by_day)[:days]:
        day_slots = by_day[day]
        temps = [
            float(slot.values["TMP"])
            for slot in day_slots
            if is_float(slot.values.get("TMP"))
        ]
        tmx = [
            float(slot.values["TMX"])
            for slot in day_slots
            if is_float(slot.values.get("TMX"))
        ]
        tmn = [
            float(slot.values["TMN"])
            for slot in day_slots
            if is_float(slot.values.get("TMN"))
        ]
        low = min(tmn or temps) if tmn or temps else None
        high = max(tmx or temps) if tmx or temps else None
        conditions = [translate_condition(slot.values) for slot in day_slots]
        condition = choose_day_condition(conditions)
        pop = max(
            (
                int(float(slot.values["POP"]))
                for slot in day_slots
                if is_float(slot.values.get("POP"))
            ),
            default=None,
        )
        precip = choose_precipitation(slot.values.get("PCP") for slot in day_slots)
        temp_text = (
            "n/a" if low is None or high is None else f"{low:.0f}°C - {high:.0f}°C"
        )
        parts = [f"{icon_for(condition)} {day}: {temp_text}", condition]
        if pop is not None:
            parts.append(f"강수확률 {pop}%")
        if precip is not None:
            parts.append(f"강수량 {precip}")
        lines.append(", ".join(parts))
    return "\n".join(lines)


def is_float(value: str | None) -> bool:
    if value is None:
        return False
    try:
        float(value)
    except ValueError:
        return False
    return True


def choose_day_condition(conditions: list[str]) -> str:
    rainy = [
        condition
        for condition in conditions
        if condition not in {"강수 없음", "맑음", "정보 없음"}
    ]
    if rainy:
        return max(set(rainy), key=rainy.count)
    usable = [condition for condition in conditions if condition != "정보 없음"]
    if not usable:
        return "정보 없음"
    return max(set(usable), key=usable.count)


def choose_precipitation(values: Iterable[str | None]) -> str | None:
    usable = [
        value
        for value in values
        if isinstance(value, str) and value not in {"강수없음", "0", "0.0"}
    ]
    if not usable:
        return None
    return max(usable, key=parse_precip_amount)


def parse_precip_amount(value: str) -> float:
    match = re.search(r"\d+(?:\.\d+)?", value)
    if match is None:
        return 0.0
    return float(match.group(0))


def config_dir() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / CONFIG_SUBDIR
    return Path.home() / ".config" / CONFIG_SUBDIR


def config_file() -> Path:
    return config_dir() / CONFIG_FILE_NAME


def load_config() -> dict[str, str]:
    path = config_file()
    if not path.exists():
        return {}
    with path.open() as file:
        data = json.load(file)
    if not isinstance(data, dict):
        msg = f"Invalid config format: {path}"
        raise TypeError(msg)
    return {str(key): str(value) for key, value in data.items()}


def save_config(config: dict[str, str]) -> None:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with config_file().open("w") as file:
        json.dump(config, file, indent=2)
        file.write("\n")


def run_command(command: str) -> str | None:
    try:
        result = subprocess.run(  # noqa: S602
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        print("Service key command timed out", file=sys.stderr)
        return None
    except (OSError, ValueError) as error:
        print(f"Error running service key command: {error}", file=sys.stderr)
        return None

    if result.returncode != 0:
        print(f"Service key command failed: {result.stderr.strip()}", file=sys.stderr)
        return None
    for line in result.stdout.splitlines():
        key = line.strip()
        if key:
            return key
    return None


def setup(service_key_command: str) -> None:
    config = load_config()
    config[SERVICE_KEY_COMMAND_FIELD] = service_key_command
    save_config(config)
    if run_command(service_key_command):
        print("Setup complete! Service key command works.")
    else:
        print("Warning: service key command did not return a usable key.")


def service_key_from_env() -> str | None:
    for name in ("KMA_SERVICE_KEY", "KMA_API_KEY", "DATA_GO_KR_SERVICE_KEY"):
        value = os.environ.get(name)
        if value:
            return value
    return None


def service_key_from_config() -> str | None:
    command = load_config().get(SERVICE_KEY_COMMAND_FIELD)
    if not command:
        return None
    return run_command(command)


def resolve_service_key(explicit_key: str | None) -> str:
    if explicit_key:
        return explicit_key
    env_key = service_key_from_env()
    if env_key:
        return env_key
    config_key = service_key_from_config()
    if config_key:
        return config_key
    msg = (
        "KMA service key required; run "
        "weather-cli setup --service-key-command 'pass show data-go-kr/kma' "
        "or set KMA_SERVICE_KEY"
    )
    raise RuntimeError(msg)


def resolve_location(args: argparse.Namespace) -> tuple[str, Grid]:
    if args.nx is not None or args.ny is not None:
        if args.nx is None or args.ny is None:
            msg = "--nx and --ny must be used together"
            raise ValueError(msg)
        return f"grid {args.nx},{args.ny}", Grid(nx=args.nx, ny=args.ny)
    if args.lat is not None or args.lon is not None:
        if args.lat is None or args.lon is None:
            msg = "--lat and --lon must be used together"
            raise ValueError(msg)
        location = Location(
            lat=args.lat, lon=args.lon, name=f"{args.lat:.5f},{args.lon:.5f}"
        )
    else:
        location = geocode_location(args.location, Geocoder(args.geocoder))
    return location.name, latlon_to_grid(location.lat, location.lon)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Weather CLI using Korea Meteorological Administration APIs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  weather-cli setup --service-key-command "pass show data-go-kr/kma"
  weather-cli 서울
  weather-cli "서울 강남구" --forecast
  weather-cli --lat 37.5665 --lon 126.9780
  weather-cli --nx 60 --ny 127 --forecast --days 3
""",
    )
    parser.add_argument(
        "location",
        nargs="?",
        default="서울",
        help="Korean address/place or lat,lon (default: 서울)",
    )
    parser.add_argument(
        "-f", "--forecast", action="store_true", help="Show KMA village forecast"
    )
    parser.add_argument(
        "-d", "--days", type=int, default=3, help="Forecast days (default: 3)"
    )
    parser.add_argument("--lat", type=float, help="Latitude, bypassing geocoding")
    parser.add_argument("--lon", type=float, help="Longitude, bypassing geocoding")
    parser.add_argument("--nx", type=int, help="KMA grid x, bypassing geocoding")
    parser.add_argument("--ny", type=int, help="KMA grid y, bypassing geocoding")
    parser.add_argument(
        "--geocoder",
        choices=[geocoder.value for geocoder in Geocoder],
        default=Geocoder.AUTO.value,
        help="Geocoder for location names (default: auto; tries nmap-cli then Nominatim)",
    )
    parser.add_argument(
        "--service-key",
        help="KMA/data.go.kr service key; overrides environment/config",
    )
    return parser


def build_setup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configure weather-cli")
    parser.add_argument("setup")
    parser.add_argument(
        "--service-key-command",
        required=True,
        help="Command that prints KMA/data.go.kr service key",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    raw_args = sys.argv[1:] if argv is None else argv
    if raw_args[:1] == ["setup"]:
        setup_args = build_setup_parser().parse_args(raw_args)
        setup(setup_args.service_key_command)
        return

    parser = build_parser()
    args = parser.parse_args(raw_args)
    try:
        service_key = resolve_service_key(args.service_key)
        location, grid = resolve_location(args)
        if args.forecast:
            slots = get_forecast(service_key, grid)
            print(format_forecast(slots, location, grid, args.days))
        else:
            weather = get_current_weather(service_key, grid)
            print(format_current_weather(weather, location, grid))
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()

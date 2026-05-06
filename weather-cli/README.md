# weather-cli

Command-line weather forecasts using Korea Meteorological Administration (KMA)
APIs from data.go.kr.

## Features

- Current weather via KMA ultra-short-term observations
- Multi-day forecasts via KMA village forecasts
- KMA latitude/longitude to `nx,ny` grid conversion
- Korean place geocoding via `nmap-cli` when available, with Nominatim fallback
- Pure Python stdlib, no runtime dependencies

## Setup

Get a service key for `VilageFcstInfoService_2.0` from data.go.kr, then store a
retrieval command:

```bash
weather-cli setup --service-key-command "pass show data-go-kr/kma"
```

Configuration is stored in `${XDG_CONFIG_HOME:-~/.config}/weather-cli/config.json`.
It stores the command, not the secret. `KMA_SERVICE_KEY`, `KMA_API_KEY`, and
`DATA_GO_KR_SERVICE_KEY` still work as environment overrides.

If `nmap-cli` is installed and configured, `weather-cli` uses it first for
Korean address geocoding. Otherwise it falls back to OpenStreetMap Nominatim.

## Usage

```bash
weather-cli 서울
weather-cli "서울 강남구" --forecast --days 3
weather-cli --lat 37.5665 --lon 126.9780
weather-cli --nx 60 --ny 127 --forecast
```

## License

MIT

---
name: weather-cli
description: Get current weather and forecasts for Korea from KMA. Use for Korean weather, Korean addresses, KMA grid coordinates, and coordinate-based weather lookups.
---

# weather-cli

Use `weather-cli` for weather in Korea. It uses data.go.kr KMA
`VilageFcstInfoService_2.0` by default.

Do not print API keys or secret-manager command output.

# Setup

Prefer storing a retrieval command, not the secret:

```bash
weather-cli setup --service-key-command "pass show data-go-kr/kma"
```

Config path:

```text
${XDG_CONFIG_HOME:-~/.config}/weather-cli/config.json
```

Temporary overrides also work:

```bash
KMA_SERVICE_KEY=... weather-cli 서울
weather-cli --service-key ... 서울
```

# Common usage

```bash
weather-cli                         # Current weather for Seoul
weather-cli 서울                    # Current weather
weather-cli "서울 강남구"            # Current weather for address/place
weather-cli 부산 -f                 # 3-day forecast
weather-cli 제주 -f -d 5             # 5-day forecast
weather-cli --lat 37.5665 --lon 126.9780
weather-cli --nx 60 --ny 127         # Bypass geocoding with KMA grid
```

# Location handling

`weather-cli` accepts:

- Korean place/address: `weather-cli "서울 강남구"`
- latitude/longitude: `weather-cli --lat 37.5665 --lon 126.9780`
- coordinate string: `weather-cli "37.5665,126.9780"`
- KMA grid: `weather-cli --nx 60 --ny 127`

For Korean address geocoding, `weather-cli` tries `nmap-cli geocode` first when
available, then falls back to Nominatim. To require NAVER Maps geocoding:

```bash
weather-cli "분당구 불정로 6" --geocoder nmap
```

If user asks for address/coordinate conversion rather than weather, use
`nmap-cli` directly:

```bash
nmap-cli geocode "분당구 불정로 6"
nmap-cli reverse "127.1054328,37.3595963"
```

If user gives `lng,lat` from `nmap-cli`, pass weather-cli as `--lat <lat> --lon <lng>` or directly as a coordinate string; weather-cli detects both `lat,lon`
and `lng,lat` when ranges are unambiguous.

# Troubleshooting

If KMA returns unauthorized:

1. Test without geocoding:

   ```bash
   weather-cli --nx 60 --ny 127
   ```

1. If that fails, check data.go.kr key and API application status for
   `기상청_단기예보 조회서비스` / `VilageFcstInfoService_2.0`.

1. If only address lookup fails, check `nmap-cli` setup or use `--geocoder nominatim` / `--lat --lon` / `--nx --ny`.

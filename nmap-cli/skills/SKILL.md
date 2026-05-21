---
name: nmap-cli
description: Use NAVER Cloud Maps APIs for Korean addresses, reverse geocoding, driving routes, and static map images. Use when user asks about NAVER Maps or Korea-focused map data.
---

# Use

Use `nmap-cli` for NAVER Cloud Maps data. It is not the `nmap` network scanner.

Configuration comes from `$XDG_CONFIG_HOME/nmap-cli/config.json` or environment variables. Do not print API keys, environment values, or secret-manager command output.

# Choose command

| User needs | Command | Notes |
| ------------------------------------------------------------ | ------------------- | ---------------------------------------------------------------------- |
| Address → coordinates | `geocode` | Address search, not rich POI/business search |
| Coordinates → address | `reverse` | Input must be `longitude,latitude` |
| Driving route | `route` | Inputs can be addresses or `longitude,latitude`; route is driving only |
| Map image file | `static` | Write images under `$HOME/.claude/outputs` unless user gives path |
| Transit/walking route, international POI, rich place details | Prefer another tool | NAVER Cloud Maps REST APIs here do not cover these well |

# Setup

If credentials are missing, ask user for secret-manager commands or tell them to configure the tool. Commands must print one secret value each.

```bash
nmap-cli setup \
  --api-key-id-command "rbw get ncloud-maps-api-key-id" \
  --api-key-command "rbw get ncloud-maps-api-key"
```

Environment alternatives:

- `NCLOUD_MAPS_API_KEY_ID`
- `NCLOUD_MAPS_API_KEY`
- `NCLOUD_MAPS_API_KEY_ID_COMMAND`
- `NCLOUD_MAPS_API_KEY_COMMAND`

Config fields:

- `api_key_id_command`
- `api_key_command`
- `api_key_id`
- `api_key`

# Examples

```bash
# Address search / geocoding
nmap-cli geocode "분당구 불정로 6"
nmap-cli geocode "Seoul Station" --language eng --limit 3

# Reverse geocoding
nmap-cli reverse "127.1054328,37.3595963"

# Driving routes
nmap-cli route "서울역" "강남역"
nmap-cli route "127.1054328,37.3595963" "129.075986,35.179470" --option trafast
nmap-cli route "서울역" "부산역" --waypoint "대전역" --directions15

# Static map image
nmap-cli static "분당구 불정로 6" --output "$HOME/.claude/outputs/naver-map.png" --level 16 --width 600 --height 400
```

# Agent rules

- Coordinates are always `longitude,latitude`.
- Use `geocode` before `route` only when you need to inspect or verify coordinates; `route` can geocode address inputs itself.
- Use `--directions15` only when route has more than 5 waypoints or user asks for Directions 15.
- If geocoding a place/business name fails, ask for road address or coordinates; do not assume POI support.
- Static Map uses ID-key authenticated `/raster`; Web service URL / referer setup is only needed for CORS image embedding.

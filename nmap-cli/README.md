# nmap-cli

Command-line helper for NAVER Cloud Maps APIs.

## Features

- Geocode addresses
- Reverse geocode coordinates
- Get driving routes with Directions 5/15
- Save static map images

## Configuration

Create a NAVER Cloud Platform Maps application and enable required Maps APIs.
Then provide credentials through environment variables or
`$XDG_CONFIG_HOME/nmap-cli/config.json`.

Environment variables:

- `NCLOUD_MAPS_API_KEY_ID`
- `NCLOUD_MAPS_API_KEY`
- `NCLOUD_MAPS_API_KEY_ID_COMMAND`
- `NCLOUD_MAPS_API_KEY_COMMAND`

Create config with setup:

```bash
nmap-cli setup \
  --api-key-id-command "rbw get ncloud-maps-api-key-id" \
  --api-key-command "rbw get ncloud-maps-api-key"
```

Or write config manually:

```json
{
  "api_key_id_command": "rbw get ncloud-maps-api-key-id",
  "api_key_command": "rbw get ncloud-maps-api-key"
}
```

Direct config values are also accepted as `api_key_id` and `api_key`. Priority:
environment direct values, environment command values, config command values,
then config direct values.

## Usage

```bash
nmap-cli geocode "분당구 불정로 6"
nmap-cli reverse "127.1054328,37.3595963"
nmap-cli route "서울역" "강남역" --option traoptimal
nmap-cli static "분당구 불정로 6" --output map.png --level 16
```

## API docs

- Overview: <https://api.ncloud-docs.com/docs/en/application-maps-overview>
- Geocoding: <https://api.ncloud-docs.com/docs/en/application-maps-geocoding>
- Reverse Geocoding: <https://api.ncloud-docs.com/docs/en/application-maps-reversegeocoding>
- Directions 5: <https://api.ncloud-docs.com/docs/en/application-maps-directions5>
- Directions 15: <https://api.ncloud-docs.com/docs/en/application-maps-directions15>
- Static Map: <https://api.ncloud-docs.com/docs/en/application-maps-static>

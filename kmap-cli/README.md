# kmap-cli

TMAP-first command-line helper for Korean places and public transit.

## Features

- Search places with TMAP POI
- Search nearby places with TMAP POI distance sorting
- Get public transit routes with TMAP Transit JSON
- Build NAVER/Kakao route URLs without NAVER/Kakao API keys
- Convert addresses to coordinates and coordinates to addresses
- Save local place aliases such as `home` and `work`
- Open TMAP/NAVER/Kakao map search URLs for human review

## Configuration

Create an SK Open API/TMAP app key, then configure a secret command:

```bash
kmap-cli setup --tmap-app-key-command "rbw get tmap-app-key"
```

Environment alternatives:

- `TMAP_APP_KEY`
- `TMAP_APP_KEY_COMMAND`

Config path follows XDG:

```text
$XDG_CONFIG_HOME/kmap-cli/config.json
```

Saved places are stored at:

```text
$XDG_DATA_HOME/kmap-cli/places.json
```

## Usage

```bash
kmap-cli place "정돈 강남점"
kmap-cli place "정돈 강남점" --provider kakao --open
kmap-cli nearby "돈까스" --near "강남역" --radius-km 1
kmap-cli nearby "돈까스" --near "강남역" --provider kakao --open

kmap-cli transit "서울역" "강남역"
kmap-cli transit "서울역" "강남역" --via "고속터미널"
kmap-cli transit "서울역" "강남역" --at 202605181830 --count 3
kmap-cli transit "서울역" "강남역" --json

kmap-cli geocode "서울 중구 세종대로 110"
kmap-cli reverse "126.9783882,37.5666103"

kmap-cli saved add home "우리집 주소"
kmap-cli saved add work "회사 주소"
kmap-cli saved list
kmap-cli transit home work

kmap-cli route-url "서울역" "강남역" --provider kakao --mode transit --open
kmap-cli route-url "서울역" "강남역" --provider naver --mode transit

kmap-cli open "정돈 강남점" --provider naver --open
kmap-cli open "정돈 강남점" --provider kakao --open
```

Coordinates are always `longitude,latitude` on input and output.

## Provider policy

Default workflow uses TMAP only: place resolve, nearby search, geocoding, reverse geocoding, and transit routing.

NAVER/Kakao are URL helpers for rich human review and route handoff. Their public APIs are not required for the core workflow. `place --provider kakao|naver` and `nearby --provider kakao|naver` print/open map search URLs rather than API search results.

ODsay is intentionally not included.

## TMAP transit notes

`transit` calls:

```text
POST https://apis.openapi.sk.com/transit/routes
```

TMAP transit responses may include route summaries, fares, transfers, walking distance/time, legs, stop lists, and route geometry. `kmap-cli` currently prints the route summary and boarding legs.

`--via` is implemented as split route calls (`A -> via`, `via -> B`) because TMAP transit routing does not expose a native waypoint parameter. This is not globally optimized across all stops.

TMAP transit API terms restrict storing returned data for more than 24 hours, so `kmap-cli` does not cache route responses.

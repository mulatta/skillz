---
name: kmap-cli
description: Use kmap-cli whenever the user asks for Korea-focused 장소찾기/POI lookup, 주변검색, 맛집 후보 찾기, 대중교통 길찾기, 경유지 transit routing, address geocoding, reverse geocoding, saved home/work aliases, or NAVER/Kakao/TMAP map app handoff. Default to TMAP API for machine-readable place/transit data; use NAVER/Kakao only as URL handoff helpers without NAVER/Kakao API keys. Do not use ODsay.
---

# Use

Use `kmap-cli` for Korean places and public transit. Default provider is TMAP.

Do not print API keys, environment values, or secret-manager command output.

# Provider choice

- Use `transit` when user wants machine-readable public transit route data: time, fare, transfers, legs, stops.
- Use `route-url` when user wants NAVER/Kakao app/web handoff, sharing a route link, or opening route UI.
- Use `place`/`nearby` without `--provider` for TMAP API result data.
- Use `place --provider naver|kakao` or `nearby --provider naver|kakao` only for map search URLs. These do not call NAVER/Kakao APIs and do not return review/menu JSON.
- Use `open` for a plain map search URL when no structured place data is needed.

# Configuration

```bash
kmap-cli setup --tmap-app-key-command "rbw get tmap-app-key"
```

Environment alternatives:

- `TMAP_APP_KEY`
- `TMAP_APP_KEY_COMMAND`

# Commands

| User needs | Command | Notes |
| --------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------ | ------------ | ------------------------------------------------------ | -------------------- |
| Place search | `place QUERY` | TMAP POI search with API result data |
| NAVER place URL | `place QUERY --provider naver --open` | URL only; no NAVER API result JSON |
| Kakao place URL | `place QUERY --provider kakao --open` | URL only; no Kakao API result JSON |
| Nearby search | `nearby QUERY --near LOCATION --radius-km N` | TMAP distance search; `LOCATION` can be saved alias, `lng,lat`, or query |
| NAVER nearby URL | `nearby QUERY --near LOCATION --provider naver --open` | Builds `LOCATION QUERY` map search URL |
| Kakao nearby URL | `nearby QUERY --near LOCATION --provider kakao --open` | Builds `LOCATION QUERY` map search URL |
| Public transit route JSON | `transit ORIGIN DEST` | TMAP `/transit/routes`; requires TMAP key |
| Transit alternatives | `transit ORIGIN DEST --count N` | `N` is alternatives per segment, 1-10 |
| Transit via waypoints | `transit ORIGIN DEST --via VIA` | Split calls; fixed waypoint order; not globally optimized |
| Time-specific transit route | `transit ORIGIN DEST --at yyyymmddhhmi` | TMAP `searchDttm` |
| NAVER route handoff | `route-url ORIGIN DEST --provider naver` | URL only; uses TMAP to resolve coordinates |
| Kakao route handoff | `route-url ORIGIN DEST --provider kakao` | URL only; uses TMAP to resolve coordinates |
| Route mode handoff | `route-url ORIGIN DEST --mode transit                  | driving                                                                  | walking      | bicycle` | Default is `transit` |
| Address to coordinate | `geocode ADDRESS` | TMAP geocoding |
| Coordinate to address | `reverse LNG,LAT` | TMAP reverse geocoding |
| Save aliases | `saved add ALIAS LOCATION` | Stored under XDG data home |
| Use saved aliases | `transit home work` | Resolves local saved places first |
| Open human review page | `open QUERY --provider naver                           | kakao                                                                    | tmap --open` | Opens map search URL; does not fetch reviews/menu JSON |

# Examples

```bash
kmap-cli place "정돈 강남점"
kmap-cli place "정돈 강남점" --provider kakao --open
kmap-cli nearby "돈까스" --near "강남역" --radius-km 1
kmap-cli nearby "돈까스" --near "강남역" --provider kakao --open
kmap-cli transit "서울역" "강남역" --count 3
kmap-cli transit "서울역" "강남역" --via "고속터미널"
kmap-cli transit "서울역" "강남역" --at 202605181830 --json
kmap-cli saved add home "우리집 주소"
kmap-cli saved add work "회사 주소"
kmap-cli transit home work
kmap-cli route-url "서울역" "강남역" --provider kakao --mode transit --open
kmap-cli route-url "서울역" "강남역" --provider naver --mode transit
kmap-cli open "정돈 강남점" --provider naver --open
```

# Important behavior

- Coordinates are always `longitude,latitude` for CLI input/output.
- `--via` performs one TMAP transit API call per segment. One waypoint means two calls; two waypoints means three calls.
- `--via` keeps user-provided waypoint order and does not optimize waypoint order.
- `--count` applies per segment. With `--via`, each segment can return up to `--count` alternatives.
- TMAP transit route responses must not be cached longer than 24 hours.

# Boundaries

- Do not use ODsay; this tool intentionally excludes it.
- Do not claim NAVER/Kakao APIs are being called by this skill. NAVER/Kakao support is URL generation only.
- Do not claim official NAVER/Kakao APIs return review/menu JSON. Use URL handoff for human review in browser/app.
- Mobile app opening depends on OS/browser/app-link handling. If app links fail, URLs open in web.

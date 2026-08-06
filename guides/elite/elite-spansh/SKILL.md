---
name: elite-spansh
description: >-
  Query spansh.co.uk, the Elite Dangerous galaxy database and route planner,
  for systems, bodies, stations, markets, and routes. Use this whenever the
  user wants to find anything in the Elite Dangerous galaxy, including a
  planet with organisms or biological signals, a station selling a commodity
  or module, a neutron route, an exobiology or Road-to-Riches tour,
  ammonia/Earth-like worlds, fleet carrier jumps, trade loops, colonisation
  targets, name-to-id64 resolution, or any filtered Spansh search.
---

# Spansh API

Spansh is the most complete queryable index of the Elite Dangerous galaxy — ~200M bodies, daily-rebuilt from EDDN. The API is public, unauthenticated, and undocumented. Everything here was verified live against the site.

Base URL: `https://spansh.co.uk/api`

## Read this first — three things that fail silently

These cost real debugging time because none of them produce an error.

**1. Numeric filters need `comparison`, not `min`/`max`.** The `{min,max}` shape returns HTTP 200 and is ignored, so you get unfiltered results that look plausible.

```
"gravity":{"min":0,"max":0.05}                 -> 429 results (filter ignored)
"gravity":{"comparison":"<=>","value":[0,0.05]} -> 21 results (correct)
```

The sole exception is the special `distance` field (distance from your reference system), which genuinely uses `{"min":0,"max":40}`.

**2. Transport is endpoint-specific.** Route planners are normal form posts. Search endpoints expect a raw JSON string, but the current web client sends it with `Content-Type: application/x-www-form-urlencoded; charset=UTF-8`. On 2026-08-05, `requests.post(..., json=payload)` returned HTTP 400 while `requests.post(..., data=json.dumps(payload), headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})` returned the expected results. Do not “clean up” this compatibility quirk without a live probe.

**3. Wrong field names fail two different ways.** An unknown *top-level* filter key is silently ignored; an unknown *sub-key* inside a struct filter yields zero results. Neither errors. Confirm names against `searchable_fields` before trusting a count.

Common traps: the field is `atmosphere` (not `atmosphere_type`), `subtype` (not `body_type`), `volcanism_type` (not `volcanism`). `atmosphere_type`, `body_type`, `ring_type`, `material`, and `signal_name` all return HTTP 500 — they aren't real fields.

## Choosing an endpoint

| Goal | Use |
|---|---|
| Find bodies matching criteria | `POST /api/bodies/search` |
| Find systems matching criteria | `POST /api/systems/search` |
| Find stations / markets / outfitting | `POST /api/stations/search` |
| An ordered *tour* of many targets | a `/route` planner |
| Name → id64 | `GET /api/search/systems?q=` |
| Full record by id | `GET /api/system/<id64>`, `/api/body/<id64>`, `/api/station/<marketId>` |
| What values does field X accept? | `GET /api/<entity>/field_values/<field>` |
| What fields exist? | `GET /api/<entity>/searchable_fields` |
| Bulk / offline analysis | the dumps — see `references/dumps.md` |

Search honors the requested sort but does not optimize a multi-system jump route. Routers solve a travelling-salesman tour and return an ordered, jump-aware itinerary. Exception: a legacy First Logged exobiology run must generate candidate bodies with Bodies Search first, group every candidate by system, and only then route those system clusters. Sending the original search through Exomastery would switch to public known-organism/base-value mode.

## Search request shape

```bash
curl -s -m 60 -X POST https://spansh.co.uk/api/bodies/search \
  -H 'Content-Type: application/x-www-form-urlencoded; charset=UTF-8' --data-binary '{
  "filters": {
    "is_landable": {"value": true},
    "subtype": {"value": ["High metal content world"]},
    "distance": {"min": 0, "max": 500},
    "gravity": {"comparison": "<=>", "value": [0, 1.0]},
    "landmark_value": {"comparison": "<=>", "value": [19000000, 999999999]}
  },
  "sort": [{"landmark_value": {"direction": "desc"}}],
  "size": 10, "page": 0, "reference_system": "Sol"}'
```

`size` maxes at 500 — larger values silently fall back to 25. `count` caps at 10000, so exactly 10000 means "10000 or more"; narrow the filter before concluding anything about volume. Instead of `reference_system` you may pass `reference_coords: {x,y,z}` or `reference_route: {source,destination}`.

Filter serialization by field type is in `references/search-api.md`. Read it before composing a non-trivial query — guessing the shape is exactly how you hit failure mode #1.

## Biological filtering — the thing Spansh does that nothing else does

Spansh indexes organisms on bodies two ways, and the distinction matters:

- **`genuses`** — genera inferred from a submitted Odyssey DSS signal. A `group` filter; 21 values (`Bacterial`, `Stratum`, `Tussocks`, …). It identifies a mapped candidate but does **not** prove the organism is unlogged or that the First Logged bonus remains available.
- **`landmarks`** — *confirmed, surveyed* organisms, down to species and colour variant, with latitude/longitude per instance. A `combined` filter with subfields `type` (genus, e.g. `Stratum`), `subtype` (species, e.g. `Stratum Tectonicas`), `variant` (colour only, e.g. `Emerald`), and `value`. Use when you want a guaranteed payout and don't care about being first.

`landmark_value` is the summed credit value of all organisms recorded on a body — the single best sort key for exobiology.

Filtering on `genuses` finds where genera were predicted after DSS; filtering on `landmarks` finds submitted surveyed organisms. `landmark_value = 0` means Spansh has no submitted organism value, not that the body is virgin. Multiple `landmarks` entries AND together, so you can demand a body hosting two specific species.

For **pre-Odyssey exact-body exobiology candidates**, do not add `is_landable`, `genuses`, `signals`, or `landmark_value`. The legacy thin-atmosphere rows were legitimately stored as non-landable before Odyssey; `is_landable=true` deletes the intended cohort. Filter by old `updated_at`, HMC subtype, compatible atmospheres and arrival distance, then validate the named body from the live journal. The complete recipe is in `elite-exobiology/references/targeting.md`.

Enumerate the vocabularies with `GET /api/bodies/field_values/{genuses,landmark_type,landmark_subtype,landmark_variant}`.

For the full exobiology workflow — which filters to combine, value thresholds, first-footfall targeting — see the `elite-exobiology` skill, which drives this API.

## Route planners

All planners are async and form-encoded: POST returns `{"job":"<GUID>","status":"queued"}`, then poll `GET /api/results/<job>` until `state` is `completed`. Jobs typically finish in under 5 seconds.

```bash
JOB=$(curl -s -X POST https://spansh.co.uk/api/exobiology/route \
  -d 'from=Sol&range=55&radius=50&max_results=3&min_value=15000000&loop=0' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['job'])")
curl -s "https://spansh.co.uk/api/results/$JOB"
```

| Planner | Endpoint | Purpose |
|---|---|---|
| Expressway to Exomastery | `POST /api/exobiology/route` | Exobiology tour by landmark value |
| Neutron Router | `POST /api/route` | Long-haul via neutron supercharging |
| Exact plotter | `POST /api/generic/route` | Fuel-aware, per-jump accurate |
| Road to Riches | `POST /api/riches/route` | Scan/map value tour |
| Ammonia / Earth-like / Rocky-Metal | `POST /api/riches/route` | Same endpoint + `body_types` preset |
| Fleet Carrier | `POST /api/fleetcarrier/route` | Tritium-aware; takes **id64s**, not names |
| Tourist | `POST /api/tourist/route` | Visit a set of systems |
| Trade | `POST /api/trade/route` | Multi-hop commodity loop |
| Colonisation | `POST /api/colonisation/route` | Colonisation hauling |
| Engineer | `POST /api/engineer/route` | **JSON, not form-encoded** — the one exception |

Full parameter lists per planner are in `references/routers.md`.

## Etiquette

No rate limiting is enforced and `robots.txt` permits everything, but Spansh is one person funded by [Patreon](https://www.patreon.com/spansh). Self-throttle to roughly 1 request/second, send a descriptive `User-Agent`, and use the dumps rather than the API for anything bulk. If a task needs thousands of queries, that's a signal to download a dump instead.

## Verified-unknown

Honest gaps, so you don't present guesses as fact:

- Job retention/TTL for `/api/results/<job>` is untested.
- Deep pagination past roughly page 20 is untested and likely limited by the Elasticsearch backend.
- `/api/user/*` needs Frontier/Patreon session cookies and is out of scope here.
- `POST /api/systems/search` accepted a `landmarks` filter correctly but returned an empty `landmarks` array in the response. Filter on it; don't rely on it echoing back.

## Reference files

- `references/search-api.md` — filter serialization by type, full field lists, saved searches, worked exobiology query with verified result counts
- `references/routers.md` — every planner's parameters and response shape
- `references/dumps.md` — the daily bulk data files

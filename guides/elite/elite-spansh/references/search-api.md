# Spansh Search API — filter reference

Applies to `POST /api/bodies/search`, `/api/systems/search`, `/api/stations/search`.
All shapes and request transport re-verified live 2026-08-05 against site build `0.1.888`.

## Contents

- [Envelope](#envelope)
- [Filter serialization by field type](#filter-serialization-by-field-type)
- [Discovering fields and values](#discovering-fields-and-values)
- [Body fields that matter](#body-fields-that-matter)
- [Biological data on bodies](#biological-data-on-bodies)
- [Legacy exact-body exobiology query](#legacy-exact-body-exobiology-query)
- [Worked exobiology query](#worked-exobiology-query)
- [Verified result counts](#verified-result-counts)
- [Saved searches](#saved-searches)
- [Detail and name lookups](#detail-and-name-lookups)

## Envelope

The body is a raw JSON string, but the live web client labels it as form-encoded. This is intentional compatibility behavior:

```python
headers = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=60)
```

`requests.post(url, json=payload)` returned HTTP 400 during the 2026-08-05 validation.

```json
{
  "filters": { },
  "sort": [ {"<field>": {"direction": "asc|desc"}} ],
  "size": 10,
  "page": 0,
  "reference_system": "Sol"
}
```

`size` maxes at 500; larger silently becomes 25. `page` is 0-indexed. `count` in the response caps at 10000, so exactly 10000 means "at least 10000".

Reference point alternatives — pick one:

```json
"reference_system": "Sol"
"reference_coords": {"x": 0, "y": 0, "z": 0}
"reference_route": {"source": "Sol", "destination": "Colonia"}
```

## Filter serialization by field type

Field types come from `searchable_fields`. Using the wrong shape is the primary failure mode and does not raise an error.

| Type | Shape |
|---|---|
| `string` | `{"value": "text"}` |
| `group`, `autocomplete` | `{"value": ["A","B"], "logic": "or"}` |
| `numeric` (real/integer) | `{"comparison": "<=>", "value": [min, max]}` |
| `boolean` | `{"value": true}` — `{}` means "any" |
| `timestamp` | `{"comparison": "<=>", "value": ["2015-01-01","2021-05-17"]}` |
| `distance` **(special)** | `{"min": 0, "max": 40}` |
| `value_struct` | `[{"comparison":"<=>","<subField>":"Name","<valueField>":[min,max]}]` |
| `combined` | `[{"<groupSub>":["A"], "<numSub>":{"comparison":"<=>","value":[min,max]}}]` |
| `ring` / `belt` | `[{"type":["Icy"],"inner_radius":{...},"outer_radius":{...}}]` |

`distance` is the only field using `{min,max}`. Everything else numeric needs `comparison`.

In a `value_struct`, the sub-field is a **scalar string**, not an array — `"name": "Biological"`, not `"name": ["Biological"]`.

### Group logic

`logic` applies to `group` and `autocomplete` filters:

- `"or"` (default) — any listed value matches
- `"and"` — all listed values must be present
- `"not"` — exclude the listed values

Verified on `genuses` over a fixed base set: `Bacterial` 382, `Stratum` 27, `or` 386, `and` 0, `not` 168.

## Discovering fields and values

```bash
curl -s https://spansh.co.uk/api/bodies/searchable_fields     # 61 fields
curl -s https://spansh.co.uk/api/systems/searchable_fields    # 44 fields
curl -s https://spansh.co.uk/api/stations/searchable_fields   # 57 fields
curl -s https://spansh.co.uk/api/bodies/sortable_fields

curl -s https://spansh.co.uk/api/bodies/field_values/subtype
curl -s "https://spansh.co.uk/api/bodies/field_values/atmosphere?q=thin"
```

`searchable_fields` returns `{"fields": [ ... ]}` — a wrapper object, not a bare array. Each entry carries the field's `type`, which is what tells you which filter shape from the table above to use.

`field_values` returns `{"min_max": {...}, "values": [...]}`. The `min_max` map doubles as a galaxy-wide histogram — useful for sanity-checking how rare a target is before you plan around it.

## Body fields that matter

Correct names, since guessing produces silent failures:

| Field | Type | Notes |
|---|---|---|
| `subtype` | group | Body type — `High metal content world`, `Rocky body`, `Icy body`, … **Not** `body_type` |
| `atmosphere` | group | `Thin Carbon dioxide`, `Thin Sulphur dioxide`, … **Not** `atmosphere_type` |
| `is_landable` | boolean | |
| `gravity` | numeric | In g |
| `surface_temperature` | numeric | Kelvin |
| `surface_pressure` | numeric | |
| `distance_to_arrival` | numeric | Ls from system entry |
| `distance` | **distance** | Ly from your reference point — uses `{min,max}` |
| `volcanism_type` | group | Includes `No volcanism` |
| `terraforming_state` | group | |
| `landmark_value` | numeric | Total credit value of organisms on the body |
| `genuses` | group | Predicted genera |
| `landmarks` | combined | Confirmed organisms |
| `signals` | value_struct | Subfields `name`, `count` |
| `signal_count` | numeric | |
| `parent_type`, `parent_subtype` | group | Parent star class — for species keyed to star type |
| `system_region` | group | Galactic region |
| `materials`, `solid_composition`, `atmosphere_composition` | value_struct | |
| `updated_at` | timestamp | Legacy-record heuristic for probable First Logged availability; not a First Footfall mechanism |

These return HTTP 500 — they are not real fields: `atmosphere_type`, `body_type`, `ring_type`, `material`, `signal_name`.

## Biological data on bodies

Two independent indexes, with different meanings:

**`genuses`** — group filter, genera inferred from a submitted DSS biological signal. 21 values:

```
Aleoids, Amphora Plants, Anemones, Bacterial, Bark Mounds, Brain Trees,
Cactoids, Clypeus, Conchas, Crystalline Shards, Electricae, Fonticulus,
Fumerolas, Fungoids, Osseus, Recepta, Shrubs, Stratum, Tubers, Tubus, Tussocks
```

Note these are the plural UI names, not the Latin genus names used in `landmarks`.

**`landmarks`** — combined filter, *confirmed surveyed* organisms with per-instance latitude/longitude. Subfields:

- `type` — genus in-game name (`Bacterium`, `Frutexa`, `Stratum`)
- `subtype` — species (`Bacterium Aurasus`, `Stratum Tectonicas`)
- `variant` — colour **only** (`Emerald`, `Lime`) — 24 values, not the full `"Species - Colour"` string
- `value` — numeric credit value

Multiple entries in the `landmarks` array AND together, so this finds bodies hosting both species:

```json
"landmarks": [{"subtype": ["Bacterium Aurasus"]}, {"subtype": ["Frutexa Flabellum"]}]
```

Enumerate vocabularies:

```bash
curl -s https://spansh.co.uk/api/bodies/field_values/genuses
curl -s https://spansh.co.uk/api/bodies/field_values/landmark_type
curl -s https://spansh.co.uk/api/bodies/field_values/landmark_subtype
curl -s https://spansh.co.uk/api/bodies/field_values/landmark_variant
```

**Choosing between them.** `genuses` identifies a body whose Odyssey DSS event predicted genera. It does not prove nobody sampled or sold them. `landmarks` identifies submitted surveyed organisms and therefore gives a confirmed base-value target. Neither index can prove a First Logged bonus is free because journal upload is optional.

## Legacy exact-body exobiology query

For pre-Odyssey Stratum candidate mining, the absence of modern Odyssey fields is the signal. Do **not** combine this query with `is_landable=true`, `genuses`, `signals`, or `landmark_value=0`. Old thin-atmosphere rows commonly store `is_landable=false` because they predate Odyssey; requiring the current value destroys the candidate cohort.

```python
payload = {
    "filters": {
        "subtype": {"value": ["High metal content world"]},
        "atmosphere": {"value": [
            "Hot thin Carbon dioxide", "Hot thin Sulphur dioxide",
            "Thin Carbon dioxide", "Thin Carbon dioxide-rich",
            "Thin Sulphur dioxide", "Thin Water", "Thin Water-rich",
            "Thin Oxygen", "Thin Ammonia", "Thin Ammonia and Oxygen",
            "Thin Ammonia-rich", "Thin Argon", "Thin Argon-rich",
        ]},
        "gravity": {"comparison": "<=>", "value": [0.035, 0.62]},
        "surface_temperature": {"comparison": "<=>", "value": [0, 450]},
        "distance": {"min": 0, "max": 500},
        "distance_to_arrival": {"comparison": "<=>", "value": [0, 1700]},
        "updated_at": {"comparison": "<=>", "value": [
            "2014-12-16T00:00:00Z", "2021-05-18T23:59:59Z"
        ]},
    },
    "sort": [
        {"distance": {"direction": "asc"}},
        {"distance_to_arrival": {"direction": "asc"}},
    ],
    "size": 100,
    "page": 0,
    "reference_coords": {"x": current_x, "y": current_y, "z": current_z},
}

headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
response = requests.post(
    "https://spansh.co.uk/api/bodies/search",
    data=json.dumps(payload),
    headers=headers,
    timeout=60,
)
```

The returned `name`, `system_name`, and `distance_to_arrival` are the operational target. Group all candidate bodies from the same system; do not deduplicate them. This is a stale-database heuristic, not a guarantee of present landability, First Footfall, or First Logged availability. See `elite-exobiology/references/targeting.md` for the exact atmosphere-specific post-filter and route ranking.

## Worked exobiology query

The query below is a **modern known-data search**. It finds submitted biological records and is appropriate for deterministic base-value targets, not legacy First Logged hunting.

```bash
curl -s -m 60 -X POST https://spansh.co.uk/api/bodies/search \
  -H 'Content-Type: application/x-www-form-urlencoded; charset=UTF-8' --data-binary '{
  "filters": {
    "is_landable": {"value": true},
    "subtype": {"value": ["High metal content world"]},
    "distance": {"min": 0, "max": 500},
    "distance_to_arrival": {"comparison": "<=>", "value": [0, 2000]},
    "surface_temperature": {"comparison": "<=>", "value": [165, 450]},
    "atmosphere": {"value": ["Thin Carbon dioxide", "Thin Sulphur dioxide"]},
    "genuses": {"value": ["Stratum"]},
    "signals": [{"comparison": "<=>", "name": "Biological", "count": [4, 20]}],
    "landmark_value": {"comparison": "<=>", "value": [19000000, 999999999]}
  },
  "sort": [{"landmark_value": {"direction": "desc"}}, {"distance": {"direction": "asc"}}],
  "size": 20, "page": 0, "reference_system": "Sol"}'
```

Response bodies carry `genuses`, `landmarks` (with lat/long per instance), `signals`, `signal_count`, `landmark_value`, `estimated_scan_value`, `estimated_mapping_value`, and `distance` from the reference point.

## Verified result counts

Measured 2026-08-04 against a base of `is_landable + Rocky body + distance 0–40 Ly of Sol` = **429 bodies**. Use these to confirm a filter is actually biting rather than being ignored:

| Added filter | Count |
|---|---|
| *(none — base)* | 429 |
| `gravity {"min":0,"max":0.05}` (wrong shape) | 429 ← ignored |
| `gravity {"comparison":"<=>","value":[0,0.05]}` | 21 |
| `distance_to_arrival` ≤ 500 Ls | 87 |
| `surface_temperature` ≤ 200 K | 286 |
| `signals` Biological 5–20 | 13 |
| `signals` Biological 1–20 | 43 |
| `landmarks` Bacterium value ≥ 1M | 42 |

If a filter you just added leaves the count unchanged, you almost certainly used the wrong shape or an unknown top-level key.

## Saved searches

```bash
# Save
curl -s -X POST https://spansh.co.uk/api/bodies/search/save \
  -H 'Content-Type: application/x-www-form-urlencoded; charset=UTF-8' \
  --data-binary '{"filters":{...},"sort":[...]}'
# -> {"search_reference": "<GUID>", ...}

# Recall
curl -s https://spansh.co.uk/api/bodies/search/recall/<GUID>
```

A saved body/system search can also seed the Tourist router: `POST /api/search/tourist/route/<GUID>`.

## Detail and name lookups

```bash
curl -s https://spansh.co.uk/api/system/10477373803        # by id64
curl -s https://spansh.co.uk/api/body/1981583949022889140  # by id64
curl -s https://spansh.co.uk/api/station/3707582976        # by marketId
curl -s https://spansh.co.uk/api/dump/10477373803          # full system dump record

curl -s "https://spansh.co.uk/api/search/systems?q=Colonia" # light: id64/name/xyz only
curl -s "https://spansh.co.uk/api/search?q=Colonia"         # heavy: full records
curl -s "https://spansh.co.uk/api/nearest?x=0&y=0&z=0"
```

All detail endpoints return `{"record": {...}}`. Body records include full `genuses` and `landmarks` with coordinates — so once you have an id64 you can get exact surface positions to fly to.

Prefer `/api/search/systems` over `/api/search` for name→id64 resolution; it returns far less data.

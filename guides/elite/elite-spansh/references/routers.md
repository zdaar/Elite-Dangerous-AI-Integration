# Spansh route planners

Every planner follows the same async pattern, and every one except the Engineer plotter is **form-encoded**.

## The pattern

```bash
# 1. Submit -> job GUID
JOB=$(curl -s -X POST https://spansh.co.uk/api/<planner>/route \
  -d 'param=value&param2=value2' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['job'])")

# 2. Poll until state == completed
curl -s "https://spansh.co.uk/api/results/$JOB"
```

Submit returns `{"job":"<GUID>","status":"queued"}`. Polling returns `status: "queued"` while running, then `status: "ok"` with `state: "completed"`. Jobs generally finish in under 5 seconds; poll every 2s and give up after ~60s.

**Do not send `Content-Type: application/json` to a route endpoint.** It returns `{"error":"from, range, radius and max_results are required"}` regardless of what you sent. Use plain `-d 'k=v&k2=v2'`.

Job retention/TTL is untested — treat results as ephemeral and re-run rather than caching a GUID for later.

---

## Expressway to Exomastery — `POST /api/exobiology/route`

Highest-value biological bodies inside a sphere, ordered into a minimal-jump tour. Value comes from precomputed `landmark_value` — organisms actually recorded on the body, not estimates. This means it only routes to bodies someone has already surveyed.

| Param | Required | Default | Notes |
|---|---|---|---|
| `from` | yes | — | Origin system name |
| `to` | no | — | End system; omit for open-ended |
| `range` | yes | — | Jump range in Ly |
| `radius` | yes | 25 | Search sphere in Ly (UI caps at 100) |
| `max_results` | yes | 100 | Number of systems in the tour |
| `max_distance` | no | 50000 | Max body distance-to-arrival in Ls |
| `min_value` | no | 10000000 | Minimum `landmark_value` per body |
| `avoid_thargoids` | no | 0 | `0` / `1` |
| `loop` | no | 1 | `1` returns to origin (origin appears twice) |

```bash
curl -s -X POST https://spansh.co.uk/api/exobiology/route \
  -d 'from=Sol&range=55&radius=50&max_results=4&min_value=15000000&loop=0'
```

Result is an array of systems, each with `bodies[]`:

```json
{"id64":"112979870900","name":"HIP 28774","jumps":2,"x":1.84,"y":6.97,"z":-82.94,
 "bodies":[{"name":"HIP 28774 AB 10 f","subtype":"Rocky body",
   "distance_to_arrival":2890.5,"landmark_value":22622800,
   "landmarks":[{"type":"Frutexa","subtype":"Frutexa Acus","count":17,"value":7774700},
                {"type":"Osseus","subtype":"Osseus Fractus","count":25,"value":4027800}]}]}
```

`landmarks[].value` is the total for that species on that body; `count` is the number of surface instances. Raw results may repeat a `subtype` — de-duplicate before summing, as the web UI does.

---

## Neutron Router — `POST /api/route`

| Param | Notes |
|---|---|
| `from`, `to` | System names |
| `range` | Jump range in Ly |
| `efficiency` | Default 60. Lower = more detours for neutron boosts |
| `via` | Repeatable waypoint |
| `supercharge_multiplier` | Usually 4 |

Returns an **object**, not an array:

```json
{"source_system":"Sol","destination_system":"Colonia","distance":22000.47,
 "total_jumps":130,
 "system_jumps":[{"system":"...","id64":...,"x":..,"y":..,"z":..,
                  "jumps":4,"distance_jumped":..,"distance_left":..,"neutron_star":true}]}
```

Verified: Sol→Colonia at 50 Ly / 60% efficiency = 130 jumps, 131 waypoints.

---

## Road to Riches — `POST /api/riches/route`

Same parameters as the exobiology router, plus:

- `use_mapping_value` — `0`/`1`, include DSS mapping value
- `body_types` — repeatable

Bodies carry `is_terraformable`. `landmark_value` may be `null` here.

The Ammonia, Earth-Like and Rocky/Metal pages are this endpoint with a preset:

```bash
# Ammonia worlds
-d 'from=Sol&range=50&radius=100&max_results=20&min_value=1&body_types=Ammonia world'
# Earth-likes
-d '...&body_types=Earth-like world'
# Rocky/metal
-d '...&body_types=Rocky body&body_types=High metal content world'
```

---

## Fleet Carrier — `POST /api/fleetcarrier/route`

Takes **id64s, not system names** — resolve first via `GET /api/search/systems?q=`.

| Param | Notes |
|---|---|
| `source` | id64 |
| `destinations` | Repeatable id64 |
| `capacity` | Tritium capacity |
| `mass` | Carrier mass |
| `capacity_used` | |
| `calculate_starting_fuel` | `0`/`1` |
| `fuel_loaded`, `tritium_stored` | |
| `refuel_destinations` | |

---

## Tourist — `POST /api/tourist/route`

`source`, `destination` (repeatable), `range`, `loop`. Solves the visiting order.

From a saved search: `POST /api/search/tourist/route/<GUID>`.

---

## Trade — `POST /api/trade/route`

`system`, `station`, `max_hops`, `max_hop_distance`, `starting_capital`, `max_cargo`, `max_system_distance`, `max_price_age`.

`0`/`1` flags: `requires_large_pad`, `allow_prohibited`, `allow_planetary`, `allow_player_owned`, `allow_restricted_access`, `unique`, `permit`.

---

## Colonisation — `POST /api/colonisation/route`

`source_system`, `destination_system`. Hauling routes for the colonisation system.

---

## Exact plotter — `POST /api/generic/route`

Fuel-aware, per-jump accurate routing. Slower than the neutron router but respects actual fuel usage and scoopable stars.

---

## Engineer plotter — `POST /api/engineer/route`

**JSON, not form-encoded** — the sole exception among planners. Plots a tour of engineer bases.

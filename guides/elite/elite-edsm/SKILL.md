---
name: elite-edsm
description: Query EDSM (Elite Dangerous Star Map) for system data, bodies, stations, markets, minor-faction/BGS state, traffic, and game server status. Use whenever the user asks about a specific Elite Dangerous system by name — its coordinates, what bodies or stations it has, who controls it, what a station's market is selling, how busy it is, or whether the game servers are up. Also use for sphere/cube searches around a system, resolving a system name to an id64, and checking BGS faction influence and states. Trigger on mentions of EDSM, "what's in system X", "who controls X", "what's the market at station Y", faction influence, BGS, or Elite server status.
---

# EDSM API

EDSM is the long-running community star map. Broad, stable, and free of auth for everything except your own commander data.

Base: `https://www.edsm.net` — no API key needed for system/body/station/faction data.

Verified live 2026-08-04: server self-reports `{"message":"Good","status":1}`, and ship breakdowns include 2026 hulls (Mandalay, Python Mk II, Corsair, Caspian Explorer), confirming ingest is current rather than a frozen snapshot.

## Two things that will bite you

**EDSM returns HTTP 200 on logical errors.** Branch on the `msgnum` field in the body, never the status code. `msgnum` 100 = OK, 203 = auth failure. A bad API key gets you a 200 with `{"msgnum":203,"msg":"Commander name/API Key not found"}`.

**No rate-limit headers are emitted.** The documented policy is soft — roughly 360 requests/hour, with some endpoints hard-capped server-side. Because there's no header feedback to react to, throttle yourself to about 1 request/second. There's no way to discover you're being limited except by results degrading.

## Endpoints

### Systems

```bash
# Single system
curl -s "https://www.edsm.net/api-v1/system?systemName=Sol&showId=1&showCoordinates=1&showInformation=1&showPrimaryStar=1"

# Batch — repeat systemName[], up to ~50
curl -s "https://www.edsm.net/api-v1/systems?systemName[]=Sol&systemName[]=Achenar&showCoordinates=1"

# Sphere around a system (radius max 100 Ly)
curl -s "https://www.edsm.net/api-v1/sphere-systems?systemName=Sol&radius=10"

# Cube (size = edge length in Ly)
curl -s "https://www.edsm.net/api-v1/cube-systems?systemName=Sol&size=20"
```

Useful flags: `showId`, `showCoordinates`, `showPermit`, `showInformation` (population, economy, security, controlling faction), `showPrimaryStar` (type + `isScoopable`).

`showPrimaryStar` is the cheap way to check scoopability when planning a long route.

### Bodies and stations

```bash
curl -s "https://www.edsm.net/api-system-v1/bodies?systemName=Sol"
curl -s "https://www.edsm.net/api-system-v1/stations?systemName=Sol"
curl -s "https://www.edsm.net/api-system-v1/stations/market?systemName=Sol&stationName=Abraham%20Lincoln"
```

`bodies` gives full orbital and atmospheric detail per body. `stations` includes `marketId` and the service list — that `marketId` is what Spansh's `/api/station/<marketId>` wants, so the two services compose.

`stations/market` returns commodities with `buyPrice`, `sellPrice`, `stock`, and `demand`.

### BGS / factions

```bash
curl -s "https://www.edsm.net/api-system-v1/factions?systemName=Sol"
```

Returns every minor faction with `influence`, `activeStates`, `pendingStates`, `recoveringStates`, plus `controllingFaction`. Verified: Sol returns 14 factions controlled by Mother Gaia.

**This is the BGS endpoint to use.** The dedicated BGS service at elitebgs.app is down — its MongoDB refuses connections and the API returns HTTP 500 while the frontend still serves 200, so it looks healthy and isn't. EDSM covers the same ground.

### Traffic, deaths, status

```bash
curl -s "https://www.edsm.net/api-system-v1/traffic?systemName=Sol"
curl -s "https://www.edsm.net/api-system-v1/deaths?systemName=Sol"
curl -s "https://www.edsm.net/api-status-v1/elite-server"
```

`traffic` gives visitor counts (total/week/day) and a per-ship breakdown. Low traffic is a decent proxy for "unexplored", which matters for first-discovery hunting — though EDAstro's traffic heatmaps are better for that at region scale.

### Commander endpoints (API key required)

```bash
curl -s "https://www.edsm.net/api-commander-v1/get-ranks?commanderName=NAME&apiKey=KEY"
curl -s "https://www.edsm.net/api-commander-v1/get-credits?commanderName=NAME&apiKey=KEY"
curl -s "https://www.edsm.net/api-commander-v1/get-position?commanderName=NAME&apiKey=KEY"
curl -s "https://www.edsm.net/api-commander-v1/get-materials?commanderName=NAME&apiKey=KEY"
curl -s "https://www.edsm.net/api-logs-v1/get-logs?commanderName=NAME&apiKey=KEY"
```

Auth is query params, not headers. Generate the key in EDSM account settings.

**Setup:** store the key outside the repo and read it from the environment — `EDSM_COMMANDER` and `EDSM_API_KEY`. Never inline a key into a skill file or a command you echo back. If the key isn't set, say so and fall back to the unauthenticated endpoints rather than prompting for it inline.

### Does not exist

`/api-v1/estimated-value` returns 404 despite appearing in older tutorials. For body scan/mapping value use Spansh's `estimated_scan_value` / `estimated_mapping_value` fields instead.

## How EDSM fits with the others

EDSM is the generalist. Reach for a sibling when the question is narrower:

- **Filtered search across the galaxy** ("find me bodies matching X") → `elite-spansh`. EDSM has no filter query language.
- **Which organism species are on a body** → `elite-edastro`. EDSM does not carry species-level bio data.
- **Whether a body has bio/geo signals at all** → `elite-canonn`.
- **Route planning** → `elite-spansh`.

EDSM's strengths are per-system detail, station markets, and BGS faction state.

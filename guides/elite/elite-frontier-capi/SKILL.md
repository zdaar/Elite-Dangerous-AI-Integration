---
name: elite-frontier-capi
description: Access Frontier's official Companion API (cAPI) for YOUR OWN live commander state — ranks, credits, current ship and modules, last-docked market and shipyard, fleet carrier status, server-side journals, and community goal contributions. Use when the user asks about their own current in-game state, their ship loadout, their carrier's fuel or cargo, or wants to pull their own journal data programmatically. Trigger on Companion API, cAPI, "my commander", "my ship", "my carrier", "my credits", or Frontier API. Requires OAuth2 — prefer shelling out to EDMC rather than implementing the flow.
---

# Frontier Companion API (cAPI)

Frontier's official API. It returns **your own commander's live state** and nothing else — it is not a galaxy database. For anything about the wider galaxy use `elite-spansh`, `elite-edsm`, or `elite-edastro`.

## Hosts

```
https://companion.orerve.net          # Live galaxy
https://legacy-companion.orerve.net   # Legacy galaxy
```

`api.orerve.net` is **not** the cAPI host. That mistake is widespread in old tutorials.

## Strongly prefer EDMC over implementing OAuth2

Auth is OAuth2 Authorization Code + PKCE against Frontier's auth service, with token refresh. Implementing it is the most expensive integration in this whole skill set, and it means handling Frontier account credentials.

**EDMC already holds a valid cAPI session**, and ships a headless CLI that dumps cAPI data as JSON to stdout:

```bash
# From the EDMC install directory
python EDMC.py -j          # journal-ish dump
python EDMC.py -m          # market data
python EDMC.py -o          # outfitting
python EDMC.py -s          # shipyard
```

Shell out to that. It's less code, it stays current with Frontier's auth changes, and no credential handling lands in a skill.

**If OAuth2 is genuinely required, the user should complete the Frontier login themselves, interactively.** Don't drive a login flow, don't accept a password, and don't handle the authorization code on their behalf — point them at the setup and use the resulting token from the environment (`FDEV_ACCESS_TOKEN`).

## Endpoints

Header: `Authorization: Bearer <access_token>`

| Endpoint | Returns |
|---|---|
| `GET /profile` | Commander name, ranks, credits, current ship + modules + engineering, all owned ships |
| `GET /market` | Last-docked station market: commodities, prices, stock/demand, prohibited list, economies, services |
| `GET /shipyard` | Ships and modules for sale with prices and stock |
| `GET /fleetcarrier` | Carrier state, fuel, balance, cargo, buy/sell orders, crew, itinerary — **204 No Content** if you own none |
| `GET /journal` or `/journal/{year}/{month}/{day}` | Server-side journal entries |
| `GET /communitygoals` | Active CGs plus your own contribution |
| `GET /visitedstars` | `VisitedStarsCache.dat` as a zip |

## Rate limits

Frontier states throttling engages above **2 requests/second**. Community convention is far more conservative — **at most 1 query per minute**. cAPI data is slow-moving (it updates on docking and similar events), so frequent polling gains nothing and risks your access.

## Caveats

- `/fleetcarrier` returning 204 means "no carrier", not an error.
- cAPI reflects *server* state, which can lag your local session — it typically refreshes on docking, not continuously.
- The Operations update (July 2026) had an incident where visited-star data reset; v4.4.0.3 added a "Resync Local Data" button under Help and Info. If `/visitedstars` looks wrong, that's the fix.

## References

- [Athanasius/fd-api](https://github.com/Athanasius/fd-api) — the community reference documentation
- [EDCD/FDevIDs](https://github.com/EDCD/FDevIDs) — endpoint list and ID mappings, last commit 2026-05-13
- `companion.py` in EDMarketConnector — the reference implementation of the auth flow

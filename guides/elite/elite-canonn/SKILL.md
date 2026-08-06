---
name: elite-canonn
description: Query Canonn Research for per-system points of interest — biological and geological surface signals, ring signals, Thargoid and Guardian sites — and for the current location of the Gnosis megaship. Use whenever the user asks whether a system or body has bio/geo signals, wants to find Thargoid structures, barnacles, spires, crash sites, Guardian ruins or beacons, is chasing xenology or Ram Tah unlocks, or asks about Canonn or the Gnosis. Trigger on Canonn, Thargoid site, Guardian ruins, barnacle, non-human signal source, surface POI, SAA signals, or "does this system have geology/biology".
---

# Canonn Research API

Canonn is the community science organisation that catalogues anomalies — Thargoid sites, Guardian ruins, surface signal sources. Its data is fed by the EDMC-Canonn plugin (actively maintained, last release 2026-07-26).

## The old hosts are gone — use the new one

`api.canonn.tech` and `capi.canonn.tech` **no longer resolve** (verified: connection failure, not a 404). Every tutorial referencing them is obsolete.

The live API is on Google Cloud Functions:

```
https://us-central1-canonn-api-236217.cloudfunctions.net/query
```

No API key.

## Endpoints

### System POIs — the main one

```bash
C="https://us-central1-canonn-api-236217.cloudfunctions.net/query"
curl -s "$C/getSystemPoi?system=Sol&odyssey=Y"
```

```json
{"SAAsignals": [
  {"body": "Galle",      "count": 1, "english_name": "Opal",    "hud_category": "Ring"},
  {"body": "Europa",     "count": 2, "english_name": "Geology", "hud_category": "Geology"},
  {"body": "Persephone", "count": 2, "english_name": "Geology", "hud_category": "Geology"}]}
```

`hud_category` is the grouping key: `Ring`, `Geology`, `Biology`, `Guardian`, `Thargoid`, `Unknown`.

**Handle `"Unknown"` — it is common, not exceptional.** A live Sol query returns several bodies with `english_name: "Unknown"` and `hud_category: "Unknown"`. That means the signal was detected but not resolved to a type, not that the API failed. Don't report "no signals" when the answer is "unidentified signals".

The `odyssey=Y` parameter matters: Odyssey and Horizons surface signals differ.

### Gnosis megaship

```bash
curl -s "$C/gnosis"
# {"coords":[365.78125,-291.75,-188.65625],
#  "system":"Synuefe PR-L b40-1",
#  "desc":"Visit the protolagrange clouds on the Gnosis (Subject to availability)"}
```

The Gnosis is Canonn's roaming science vessel; it relocates periodically, so query rather than assume.

### Endpoints that exist but need parameters

`/codex`, `/getBioStats`, `/getRingPoi`, and `/cs` return HTTP 400 when called bare. They're live — they need arguments this survey didn't determine. If you need one, probe its parameters rather than assuming it's broken.

## Xenology in 2026 — read this before planning AX content

**The Thargoid war concluded in 2024.** Verified live against DCoH: all eight Titans (Indra, Leigong, Taranis, Cocijo, Oya, Raijin, Thor, Hadad) report state `Completed` / `Destroyed` with zero hearts remaining, and there are **zero systems** in alert, invasion, Thargoid-controlled, or recovery states.

What this means practically:

- There is no live AX war to fight, no maelstrom rotation, no system-defence content.
- The *static* Thargoid content remains: surface structures, barnacles, spires, crash sites, and the Thargoid organic samples that still sell at Vista Genomics (Coral Root, Coral Tree, Mega Barnacles, Spires — see `elite-exobiology/references/species-values.md`).
- Guardian sites are unaffected and remain the route to Guardian module unlocks.
- **dcoh.watch is now an archive.** Don't build live tracking on it.

So Canonn is still the right tool for xenology, but the goal is exploration and codex completion rather than war participation.

### A trap that will fool your error handling

DCoH — and some other Elite SPAs — return **HTTP 200 with `text/html`** for any unmatched path, because the Angular app serves its shell as a fallback. A status-code check alone will report success on a nonexistent endpoint.

```bash
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" "https://dcoh.watch/api/v1/overwatch"
# 200 text/html          <- SPA fallback, not the API
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" "https://dcoh.watch/api/v1/overwatch/systems"
# 200 application/json   <- real
```

Always assert `content_type` contains `application/json` before parsing. The same pattern appears on Raven Colonial.

## Related

- `elite-edastro` — GEC category 16 is "Mystery and Xenology"; complements Canonn for named POIs
- `elite-spansh` — the exobiology router takes `avoid_thargoids=1` if you want to route around Thargoid space
- `elite-exobiology` — values for the Thargoid organic samples

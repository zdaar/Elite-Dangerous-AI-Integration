---
name: elite-edastro
description: Query EDAstro for confirmed organism species per planet, galactic exploration POIs (the GEC catalog), and system/body records. Use this whenever the user wants to know WHICH biological species are actually on a specific planet or in a system — the only public API that reports confirmed species-per-body rather than predictions. Also use for finding named points of interest, nebulae, notable stellar phenomena, organic POIs, and xenological sites by location or category. Trigger on EDAstro, "what bio is on this planet", "what species are in system X", confirmed organics, Galactic Exploration Catalog, GEC, exploration POIs, or nearest-POI-to-coordinates questions.
---

# EDAstro API

EDAstro (CMDR Orvidius) indexes ~199.8M systems and ~472M planets from EDDN. Its distinguishing feature is **confirmed species-level organism data per body** — no other public API in this ecosystem has it.

Base: `https://edastro.com` — no API key.

## Rate limit is real and enforced

**100 requests per 15 minutes**, reported in headers — unusual and useful:

```bash
curl -s -D- "https://edastro.com/api/starsystem?q=Sol" -o /dev/null | grep -i ratelimit
# RateLimit-Limit: 100
# RateLimit-Remaining: 99
# RateLimit-Reset: 620
```

Read `RateLimit-Remaining` and back off before you exhaust it. Because the budget is small, prefer the batch form and cache aggressively — especially `/gec/json/all`, which should be fetched once and reused, never per-query.

## The exobiology payload

```bash
curl -s "https://edastro.com/api/starsystem?q=Nervi"
```

Each planet carries an `organic` array with species-level entries:

```json
{"name": "Nervi 2 e", "organic": [
  {"genus_local": "Bacterium", "species_local": "Bacterium Alcyoneum",
   "genus": "$Codex_Ent_Bacterial_Genus_Name;", "species": "$Codex_Ent_Bacterial_06_Name;",
   "firstReported": "2022-09-05T22:49:29", "lastSeen": "2023-08-13T00:10:54"}]}
```

Verified live: Nervi 2 d returns eight distinct species including Cactoida Lapis, Osseus Spiralis, Fungoida Stabitis, and Frutexa Flabellum.

Use `genus_local` / `species_local` for display; the `$Codex_...;` forms are the raw journal tokens, useful for matching against journal data or BioScan's tables.

**What this is good for.** Cross-reference the species list against the value table in `elite-exobiology/references/species-values.md` to compute exactly what a body is worth before you fly there. `firstReported` also tells you the body has already been logged — so expect base value, not the 5× first-discovery bonus.

### Batch lookup

```bash
# Max 10 systems, names or id64s, comma-separated
curl -s "https://edastro.com/api/starsystem?q=Sol,Achenar,Colonia"
```

Ten systems for one request against a 100/15min budget is a large efficiency win. Batch by default.

### Record shape

System keys: `id64, name, coordinates, coord_x/y/z, region, sol_dist, mainStarType, bodyCount, numELW, numWW, numAW, numTerra, stars, planets, barycenters, stations, carriers, codex, FSSprogress, FSSdate, edsm_id`.

Planet keys include: `organic, materials, rings, atmoComposition, isLandable, gravity, subType, distanceToArrivalLS`.

`codex[]` carries category/subcategory plus localised names, including xenological entries.

## Galactic Exploration Catalog (GEC)

A curated POI database returned in EDSM's GMP-JSON format.

```bash
curl -s "https://edastro.com/gec/json/all"          # ~2.17 MB, every POI — cache this
curl -s "https://edastro.com/gec/json/categories"
curl -s "https://edastro.com/gec/json/rare"
curl -s "https://edastro.com/gec/json/combined"     # GEC + GMP merged
curl -s "https://edastro.com/gec/json/single/{POI-ID}"
curl -s "https://edastro.com/gec/json/id64/{id64}"
curl -s "https://edastro.com/gec/json/nearest/{x}/{y}/{z}"
curl -s "https://edastro.com/gec/json/nearest/{x}/{y}/{z}/{minrating}"
```

POI fields: `id, type, categoryId, name, region, galMapSearch, galMapUrl, coordinates[x,y,z], summary, descriptionMardown`.

Two gotchas: `descriptionMardown` is misspelled *in the API* — match it exactly. And in `/combined`, `id` is **not unique**; pair it with `source` to key records.

Categories worth knowing: **15 = Organic**, **16 = Mystery and Xenology**.

`galMapSearch` gives you a string you can paste straight into the in-game galaxy map search box — the fastest way to hand a player a destination.

### Broken sub-endpoints

`/gec/json/stats` returns HTTP 500; `/gec/json/summary` and `/poi/json` return empty `{}`. Everything else listed above works. `/api/` root is 403 by design, not an outage.

## Attribution

Community-data project by CMDR Orvidius, Patreon-funded, explicitly welcoming API use. Attribution is expected — credit EDAstro when presenting its data.

## How EDAstro fits with the others

The three bio-data services answer different questions, and using the wrong one wastes a trip:

| Question | Service |
|---|---|
| Which species are *confirmed* on this body? | **EDAstro** `organic[]` |
| Which genera *might* be here (predicted)? | Spansh `genuses` |
| Does this body have bio/geo signals at all? | Canonn `getSystemPoi` |
| Find bodies matching filter criteria galaxy-wide | Spansh `bodies/search` |

Typical flow: Spansh finds candidates by filter → EDAstro confirms what's actually there → value it against the species table.

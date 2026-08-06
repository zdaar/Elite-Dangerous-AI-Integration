# Spawn conditions and targeting matrix

Ground truth is **EDMC-BioScan's rulesets** (`src/bio_scan/bio_data/rulesets/*.py`, repo pushed 2026-07-11), cross-checked against Canonn's per-genus codex pages. Where they differ, BioScan encodes the *reliable* band and Canonn publishes *observed* min/max including outliers — filter with BioScan's numbers for fewer false positives, and reach for Canonn's when explaining an unexpected find.

Gravity in g. Pressure in atm (BioScan stores journal Pa ÷ 101231.65625).

## Contents

- [The two hard gates](#the-two-hard-gates)
- [Star class gate by genus](#star-class-gate-by-genus)
- [Stratum Tectonicas — exact rulesets](#stratum-tectonicas--exact-rulesets)
- [Top-value species conditions](#top-value-species-conditions)
- [Special-location gates](#special-location-gates)
- [Stacking profiles](#stacking-profiles)
- [Stratum-sniping search recipe](#stratum-sniping-search-recipe)
- [Queue, route, and distance semantics](#queue-route-and-distance-semantics)
- [Spansh filter recipes](#spansh-filter-recipes)
- [Known source disagreements](#known-source-disagreements)

## The two hard gates

**Gravity ≤ 0.276 g.** The hard ceiling for twelve genera: Aleoida, Cactoida, Clypeus, Concha, Fonticulua, Frutexa, Fumerola, Fungoida, Osseus, Recepta, Tubus, Tussock. Above 0.28 g only Stratum and Bacterium remain. Single highest-leverage filter available.

**Surface pressure < 0.0987 atm.** Every ruleset in the dataset caps below this — it is the game's thin-atmosphere ceiling. "Thin" in the atmosphere name is doing real work.

## Star class gate by genus

A species cannot spawn if no star in the body's parent chain belongs to a permitted class. BioScan implements this as hard elimination. Fifteen classes participate: O, B, A, F, G, K, M, L, T, TTS (T Tauri), Ae (Herbig Ae/Be), Y, W (Wolf-Rayet), D (white dwarf), N (neutron).

| Genus | Permitted | Excluded |
|---|---|---|
| **Stratum** (except Araneamus) | F K M L T TTS Ae Y W D | **O B A G N** |
| Stratum Araneamus | B A N F | — |
| **Osseus** (star-keyed spp.) | O A F G K T TTS Y | B M L Ae W D N |
| **Concha** (Aureolas, Labiata) | B A F G K L Y W D N | O M T TTS Ae |
| **Clypeus** (all) | B A F G K M L Y D N | O T TTS Ae W |
| **Frutexa** (all) | O B F G M L TTS W D N | A K T Y Ae |
| **Cactoida** (all) | O A F G M L T TTS Y W D N | B K Ae |
| **Tussock** (all) | F G K M L T Y W D N | O B A TTS Ae |
| **Aleoida** (all) | B A F K M L T TTS Y W D N | O G Ae |
| **Tubus** (all) | O B A F G K M L T TTS W D N | Y Ae |
| **Recepta Umbrux** | O B A F G K M L T TTS Ae Y D N | W |
| **Bacterium** Aurasus/Alcyoneum/Cerbrus | all 15 | — |
| **Fonticulua** (all) | all 15 | — |

**F-class appears in every one of these tables — it is the only class that does.** K misses Cactoida and Frutexa; M misses Concha and Osseus; G misses Aleoida and Stratum.

This is why the popular "route through A/F/G/K stars" advice underperforms: **A and G host no Stratum at all.** For Tectonicas volume filter F/K/M; for maximum stacking filter F.

The gate evaluates the body's own parent star chain plus stars at the arrival point (0 Ls) and stars parented to a black hole. A distant companion of the right class does not count — filter on *primary star class*.

Genera with **no** star gate (material-determined instead): Electricae, Fumerola, Fungoida, most Bacterium, Concha Renibus/Biconcavis, Osseus Discus/Pumice, Recepta Conditivus/Deltahedronix.

### Explicit star requirements

| Organism | Requirement |
|---|---|
| Electricae Pluma | Parent star A, Neutron, or White Dwarf (BioScan also allows black hole, Herbig Ae/Be) |
| Amphora Plant | An A-class star in system |
| Crystalline Shards | An A, F, G, K, MS or S star in system |
| Anemone | Star class **and luminosity**: B I/II/III → Roseum + Roseum Biolum; B IV/V → Luteolum + Blatteum Biolum; B VI or A III → Croceum + Rubeum Biolum; O → Puniceum + Prasinum Biolum |
| Radicoida Unica | System HIP 87621 only |

## Stratum Tectonicas — exact rulesets

**High metal content body only. Never Rocky.** The single most discriminating filter. Extracted directly from `stratum.py`:

| Atmosphere | Gravity | Temp K | Volcanism |
|---|---|---|---|
| Carbon dioxide | 0.045–0.61 | 165–430 | any |
| Carbon dioxide-rich | 0.035–0.61 | 165–260 | any |
| Sulphur dioxide | 0.29–0.62 | 165–450 | any |
| Ammonia | 0.045–0.38 | 165–177 | any |
| Oxygen | 0.40–0.52 | 165–246 | any |
| Argon / Argon-rich | 0.485–0.54 | 167–199 | **none** |
| Water | 0.045–0.063 | — | **none** |

**165 K is the universal floor** across every ruleset. **0.62 g is the absolute ceiling.** No region restriction — works galaxy-wide, which is why it's the farming target. Canonn records it as 37.5% of all Stratum.

Note this refutes the "no gravity preference" claim circulating in some video guides. Gravity is bounded; the bound is just looser than the old `<1G` rule of thumb.

## Top-value species conditions

| Value | Species | Body | Atmosphere | Temp K | Gravity | Notes |
|---|---|---|---|---|---|---|
| 20,000,000 | Fonticulua Fluctus | Icy | Oxygen | 143–200 | 0.235–0.276 | ≥0.012 atm. **0.42% of Fonticulua** — a lottery ticket, not routable |
| 19,010,800 | Stratum Tectonicas | **HMC only** | see above | ≥165 | ≤0.62 | No region gate. The workhorse |
| 19,010,800 | Fonticulua Segmentatus | Icy | Neon / Neon-rich | 50–75 | 0.25–0.276 | <0.006 atm, no volcanism |
| 19,010,800 | Tussock Stigmasis | Rocky / HMC | SO₂ | 132–180 | 0.04–0.276 | <0.01 atm. Often stacks with Recepta |
| 19,010,800 | Concha Biconcavis | Rocky / HMC | Nitrogen | **42–52** | 0.053–0.275 | <0.0047 atm, no volcanism. Very cold, very narrow |
| 16,202,800 | Cactoida Vermis | Rocky / HMC | Water, or SO₂ 160–210 K | — | 0.04–0.276 | volcanism none or water |
| 16,202,800 | Clypeus Speculumi | **Rocky** | CO₂ 190–197 K, or Water | — | 0.04–0.276 | **Body ≥2000 Ls from star** (some sources say 2500 — use 2500 to be safe) |
| 16,202,800 | Fumerola Extremus | Rocky / RI / HMC | CH₄ 77–109 (83%), NH₃, Ar, SO₂, CO₂ ≥500 | — | 0.025–0.276 | **Requires silicate/metallic/rocky magma volcanism** |
| 16,202,800 | Recepta Deltahedronix | any | SO₂ 132–272, CO₂ 150–195 | — | 0.04–0.276 | Atmosphere must be **≥1.05% SO₂** |
| 16,202,800 | Stratum Cucumisis | **Rocky** | CO₂ 191–371, SO₂ 191–373, O₂ 200–250 | — | 0.04–0.60 | **Sagittarius-Carina only** |
| 14,313,700 | Recepta Conditivus | Icy/Rocky/HMC | SO₂ 132–275, CO₂ 150–195 | — | 0.04–0.276 | ≥1.05% SO₂ |
| 14,313,700 | Tussock Virgam | Rocky / HMC | **Water** | 390–450 | **0.04–0.065** | Key member of the water stack |
| 12,934,900 | Aleoida Gravis | Rocky / HMC | CO₂ | **190–197** | 0.04–0.276 | **≥0.054 atm** |
| 12,934,900 | Osseus Discus | Rocky/RI/HMC | Water ≤0.055 g, NH₃, Ar, CH₄, CO₂ ≥500 K | — | ≤0.276 | |
| 12,934,900 | Recepta Umbrux | any | SO₂ 132–273, CO₂ 151–200 | — | 0.04–0.276 | ≥1.05% SO₂ |
| 11,873,200 | Clypeus Margaritus | **HMC only** | CO₂ 190–197, or Water | — | 0.04–0.276 | CO₂ needs ≥0.054 atm |
| 11,873,200 | Tubus Cavas | Rocky | CO₂ | 160–197 | **0.04–0.152** | ≥0.003 atm. **Scutum-Centaurus only** |
| 10,326,000 | Frutexa Flammasis | Rocky | Ammonia | 152–177 | 0.04–0.276 | <0.0135 atm. **Scutum-Centaurus only** |
| 9,739,000 | Osseus Pellebantus | Rocky / HMC | CO₂ | ≥191 | 0.0405–0.276 | **≥0.057 atm**. NOT Perseus |
| 7,774,700 | Tussock Triticum | Rocky / HMC | CO₂ | 191–197 | 0.04–0.276 | **≥0.058 atm**. Sag-Car / Perseus / Orion-Cygnus cores |
| 7,774,700 | Frutexa Acus | Rocky | CO₂ | 146–197 | 0.04–0.237 | ≥0.0029 atm. **Orion-Cygnus only** |
| 7,774,700 | Tubus Compagibus | Rocky | CO₂ | 160–197 | 0.04–0.153 | ≥0.003 atm. **Sagittarius-Carina only** |
| 6,284,600 | Electricae Pluma | Icy | Ar/Ar-rich 50–150, Ne 20–70 | — | 0.025–0.276 | **A / White Dwarf / Neutron primary.** 1000 m colony range |
| 6,284,600 | Electricae Radialem | Icy | same | — | same | **Within 150 Ly of a nebula** (100 Ly of a planetary nebula) |

## Special-location gates

Pre-filter on these or you'll waste trips:

- **Brain Trees** — inside a Guardian zone: within 750 Ly of Hen 2-333 or Gamma Velorum, or within 100 Ly of Skaudai AA-A h71, Blaa Hypai AA-A h68, Eorl Auwsy AA-A h72, Prai Hypoo AA-A h60, Eta Carina Nebula, or NGC 3199.
- **Bark Mounds** — within 150 Ly of a large nebula. Excluded from Galactic Centre, Empyrean Straits, Ryker's Hope.
- **Electricae Radialem** — within 150 Ly of a nebula.
- **Crystalline Shards** — body ≥12,000 Ls out; system needs an A/F/G/K/MS/S star plus an ELW, Ammonia world, Water world, water-life or ammonia-life gas giant, or water giant; exterior regions only.
- **Amphora Plant** — metal-rich body, no atmosphere, 1000–1750 K, magma volcanism; A-class star in system plus an ELW / water-life gas giant / water giant. Norma Expanse, Hawking's Gap, Dryman's Point, Sagittarius-Carina Arm, Mare Somnia only.
- **Sinuous Tubers** — only inside 22 named tuber zones (Galactic Centre, Odin A/B, Ryker A/B, Norma Arm A/B, Inner Sag-Car A–D, Hawking A/B, Izanami, Trojan Belt, Arcadian Stream, Empyrean Straits, Inner Orion Spur, Inner Orion-Perseus Conflux, Norma Expanse A/B).

## Stacking profiles

One species per genus per body — so the biological signal count equals the number of distinct genera. The exceptions are Brain Trees and Sinuous Tubers, which can place several colour variants on one body.

**Maximum observed is 12 genera**, on three bodies galaxy-wide. 144 bodies reach 11. Nothing exceeds 12. Treat 8 as a strong planning ceiling and 5+ as a good body.

Bodies reporting 17–40 signals are no-atmosphere Horizons-era bodies counting *instances* of Bark Mounds/Brain Trees/Shards, not genera. Exclude them by requiring an atmosphere.

### Ceiling by atmosphere

| Atmosphere | Max genera | Bodies at ≥11 |
|---|---|---|
| Thin Carbon dioxide | **12** | 136 |
| Thin Ammonia | 11 | 8 |
| Thin Water | 10 | 0 |
| Thin Sulphur dioxide | 7 | – |
| Thin Argon | 7 | – |
| Thin Methane | 6 | – |
| Thin Nitrogen | 5 | – |
| Thin Neon / Thin Oxygen | ≤4 | – |

CO₂ ≫ Ammonia > Water ≫ everything else. Icy-world atmospheres are structurally capped low.

### The three 12-genus bodies

| Body | Atmosphere | Type | g | K | Ly from Sol | Ls |
|---|---|---|---|---|---|---|
| Drojau BG-W d2-1 A 3 b | Thin CO₂ | Rocky | 0.063 | 192 | 5,641 | 3,241 |
| Blo Thaa FQ-Y d4 7 a | Thin CO₂ | Rocky | 0.051 | 193 | 7,527 | 2,338 |
| Leamue HQ-O d6-4723 B 8 c | Thin CO₂ | Rocky | 0.061 | 191 | 21,108 | 100,083 |

All three share the same profile, which is what makes it a recipe rather than a coincidence.

## Stratum-sniping search recipe

Use this recipe for the default maximum-credits workflow. It mines exact HMC body names from stale pre-Odyssey Spansh records, then lets the live journal plus BioInsights decide whether the body is worth visiting. It is a candidate generator, not proof of First Logged availability.

### Required server-side filters

```json
{
  "filters": {
    "subtype": {"value": ["High metal content world"]},
    "atmosphere": {"value": [
      "Hot thin Carbon dioxide",
      "Hot thin Sulphur dioxide",
      "Thin Carbon dioxide",
      "Thin Carbon dioxide-rich",
      "Thin Sulphur dioxide",
      "Thin Water",
      "Thin Water-rich",
      "Thin Oxygen",
      "Thin Ammonia",
      "Thin Ammonia and Oxygen",
      "Thin Ammonia-rich",
      "Thin Argon",
      "Thin Argon-rich"
    ]},
    "gravity": {"comparison": "<=>", "value": [0.035, 0.62]},
    "surface_temperature": {"comparison": "<=>", "value": [0, 450]},
    "distance": {"min": 0, "max": 500},
    "distance_to_arrival": {"comparison": "<=>", "value": [0, 1700]},
    "updated_at": {"comparison": "<=>", "value": [
      "2014-12-16T00:00:00Z",
      "2021-05-18T23:59:59Z"
    ]}
  },
  "sort": [
    {"distance": {"direction": "asc"}},
    {"distance_to_arrival": {"direction": "asc"}}
  ],
  "size": 100,
  "page": 0,
  "reference_coords": {"x": 0, "y": 0, "z": 0}
}
```

Replace the sample coordinates with the live `Location.StarPos`. Use `reference_system` only when Spansh already knows the current system name. A newly visited system can be absent from Spansh while its coordinates still work.

The strict cutoff is the day before Odyssey's 2021-05-19 PC release. The March 2026 MOXCIE preset used the narrower proven window `2016-11-06T15:17:20Z` through `2021-04-02T04:22:19.310Z`, 11 atmospheres, and a 0.45 g ceiling. The current planner broadens that preset to the full verified Tectonicas envelope by adding Argon/Argon-rich and accepting up to 0.62 g, then post-filters each atmosphere exactly.

### Never add these fields

- **No `is_landable`.** Pre-Odyssey thin-atmosphere rows commonly store `false`, because they were not landable at the time. Requiring `true` deletes the intended legacy cohort.
- **No `genuses`, `landmarks`, or biological `signals`.** They require submitted Odyssey-era biological data and turn this into a known-body search.
- **No `landmark_value=0`.** Zero means “no value submitted to Spansh,” not “unclaimed in game.” It is neither necessary nor sufficient for this method.

The live 2026 recall of MOXCIE's saved search `46419108-1996-11F1-BFB0-F526C43836DB` returned 884 candidates and its first page contained `is_landable=false` records. The broadened 13-atmosphere request was also accepted during the live planner test. The earlier zero-result conclusion came from adding `is_landable=true`, not from Spansh having removed old records.

### Post-filter with the exact Tectonicas envelope

The server filter is deliberately broad. Normalize `Hot thin …`, `Thin …`, and `…-rich` labels, then enforce the table in [Stratum Tectonicas — exact rulesets](#stratum-tectonicas--exact-rulesets):

- CO₂: 0.045–0.61 g, 165–430 K.
- CO₂-rich: 0.035–0.61 g, 165–260 K.
- SO₂: 0.29–0.62 g, 165–450 K.
- Ammonia: 0.045–0.38 g, 165–177 K.
- Oxygen: 0.40–0.52 g, 165–246 K.
- Argon/Argon-rich: 0.485–0.54 g, 167–199 K, no volcanism.
- Water: 0.045–0.063 g, no volcanism.

The automated maximum-credits queue rejects rows missing gravity or temperature because it cannot verify or rank their Tectonicas eligibility. Keep missing-data rows only as an explicit exploratory fallback. Missing landability or biology is expected and must not trigger a full-system FSS.

### Rank the trip, not only the body

Group surviving bodies by system. Rank primarily by number of candidates in the same system, then route distance and total arrival distance. Preserve every exact body designation; do not deduplicate a five-body system down to one body.

For best First Logged odds, build the queue at least 3,000 ly from inhabited space and away from obvious tourist corridors. A closer queue is still usable but should be labelled lower confidence. Use a 500 ly search radius, fetch at least 100 rows, prefer ≤1,000 ls arrival when supply is abundant, and accept up to 1,700 ls by default.

Spansh results are radially sorted around the reference, not automatically an efficient tour. Route system clusters by nearest neighbour or the Tourist router, and re-anchor when necessary.

Search requests use a raw JSON string with the current site's form content type; `requests.post(..., json=payload)` returned HTTP 400 during the 2026-08-05 verification. See `elite-spansh/references/search-api.md`.

## Queue, route, and distance semantics

The persisted expedition queue is exact-body planning data, not live navigation state.

- Queue positions exposed to the commander are **1-based**. `set index 4` means the fourth target; never translate it to a zero-based number in conversation.
- `status` reads without mutation. `start` replots/resumes the selected entry. `next` and `previous` mutate by one. `set` selects an explicit position. `reset` is destructive to progress and requires an explicit request.
- A target's stored `distance_ly` is the distance from the coordinates used when the queue was planned. It does not shrink as the ship moves and must be labelled `distance_from_planning_source_ly` in explanations.
- In live COVAS `NavInfo`, the first `NavRoute` entry is the next hop and the last is the final route destination. The list length is the remaining jump count.
- An `FSDTarget`/`NextJumpTarget` by itself does not prove the final destination. Verify the final `NavRoute` entry against the exact requested system, including its procedural numeric suffix.
- Keep queue mutation and plot verification separate. A correctly selected queue entry can still have a failed or mismatched plot; report both facts rather than collapsing them into “success.”
- Route failure does not prove the destination is outside single-jump range or that the surrounding region lacks stars. State only the returned error unless a source provides a specific cause.

## Spansh filter recipes for known-data searches

These profiles use modern submitted body data. They are useful for deterministic base-value routes and condition research, not for the default legacy-record First Logged hunt. Remember numeric filters need `{"comparison":"<=>","value":[min,max]}` — see `elite-spansh`.

### Profile A — known jackpot stack (11 species, ~90.3M base verified)

```json
{"is_landable": {"value": true},
 "subtype": {"value": ["Rocky body"]},
 "atmosphere": {"value": ["Thin Carbon dioxide"]},
 "gravity": {"comparison": "<=>", "value": [0.04, 0.07]},
 "surface_temperature": {"comparison": "<=>", "value": [190, 196]}}
```

### Profile B — known water stack (9 species, ~85.8M base verified)

```json
{"is_landable": {"value": true},
 "subtype": {"value": ["High metal content world"]},
 "atmosphere": {"value": ["Thin Water", "Water"]},
 "gravity": {"comparison": "<=>", "value": [0.04, 0.065]}}
```

### Profile C — known Tectonicas volume

```json
{"is_landable": {"value": true},
 "subtype": {"value": ["High metal content world"]},
 "atmosphere": {"value": ["Thin Carbon dioxide", "Thin Sulphur dioxide"]},
 "surface_temperature": {"comparison": "<=>", "value": [165, 450]},
 "gravity": {"comparison": "<=>", "value": [0, 0.62]}}
```

For a confirmed-organism route, prefer Spansh Expressway to Exomastery over manually assembling these rows. Public submitted organisms normally have poor First Logged odds; their advantage is certainty and low scanning effort.

## Known source disagreements

Flagged so you don't "fix" correct data against a wrong source:

1. **Concha Biconcavis** — BioScan stores `16777215` (0xFFFFFF, a sentinel). Canonn, ed-dsn and Fandom's Concha page say **19,010,800**. Use 19,010,800.
2. **Fandom's "Exobiology Sample Values and Details" summary page** is wrong on eight values — see `species-values.md`. Its per-genus pages are fine; the summary page isn't.
3. **Clypeus Speculumi distance** — BioScan says ≥2000 Ls, Fandom and DSN say >2500. Filter at 2500.
4. **Crystalline Shards stars** — BioScan `A F G K MS S` (no plain M); Fandom includes M. Unresolved; A/F/G/K/S is safe.
5. **Electricae Pluma** — Canonn says A/WD/Neutron; DSN adds luminosity V or brighter for the A case; BioScan also allows black holes and Herbig Ae/Be.
6. **Recepta Umbrux around O stars** — Canonn records an O→Indigo variant; BioScan's table omits O and would wrongly eliminate it there. A genuine BioScan gap.
7. **Temperature bands** — BioScan encodes reliable bands, Canonn observed extremes (e.g. Stratum Tectonicas: BioScan floor 165 K, Canonn observed 61.5 K).
8. Several BioScan rulesets carry in-source low-confidence notes: Bacterium Nebulus rocky-ice ("only one sample, likely inaccurate"), Fungoida Stabitis argon-rich icy and Gelata argon ("only one sample"), Frutexa Metallicum methane ("only two samples"), Fumerola Carbosis ammonia/argon-rich/CO₂-rich ("probably incomplete").

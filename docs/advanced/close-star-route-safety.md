# Close-star route safety

Nova can deterministically avoid some dangerous close-star arrivals, but only when intra-system star geometry is available. The feature never infers geometry from a system name and never asks an LLM to classify a system.

## Feasibility result

Elite exposes a plotted route before the first jump. `NavRoute.json` and the `NavRoute` journal event contain each hop's system name, id64 address, galactic `StarPos`, and arrival `StarClass`. `FSDTarget` then identifies the authoritative immediate hop. These fields are documented in Frontier's [Player Journal manual](https://hosting.zaonce.net/community/journal/v37/Journal_Manual_v37.pdf) and the community-maintained [travel-event reference](https://elite-journal.readthedocs.io/en/latest/Travel.html).

`StarPos` is the star system's position in the galaxy, in light-years. It is not a position for a star inside that system. Close-binary detection therefore requires body records from a prior journal `Scan`, the local system cache, EDSM, or Spansh. The journal's `Scan` and `ScanBaryCentre` events can contain stellar radius, distance from arrival, parents, semi-major axis, eccentricity, and orbital period; see the [exploration-event reference](https://elite-journal.readthedocs.io/en/latest/Exploration.html).

| Candidate | Available before jump | Result |
|---|---|---|
| Previously scanned and cached | Journal/EDSM-shaped body geometry may be present | Deterministic when required fields are complete |
| Community-known but unvisited locally | Exact id64 body records may be available from Spansh/EDSM | Deterministic when required fields are complete |
| Plotted but absent from community catalogues | Name, id64, galactic coordinates, and arrival class only | Geometry is `unknown` |
| Truly undiscovered deep-space system | Game route metadata, but normally no community body geometry | Geometry is `unknown` |

EDSM describes itself as a community database for system coordinates and celestial bodies, and its sphere API returns only systems known to that database. Spansh likewise depends on community-submitted exploration data. Catalogue absence is not evidence that a system is single-star or safe.

## Objective danger rule

The classifier identifies the arrival star and each companion. For a shared barycentre with complete orbital data it calculates the minimum centre separation at periapsis:

`minimum separation = (arrival semi-major axis + companion semi-major axis) × (1 − eccentricity)`

It then calculates:

`empty surface gap = minimum separation − arrival radius − companion radius`

A pair is dangerous when:

`empty surface gap ≤ (arrival radius + companion radius) × configured gap ratio`

The default gap ratio is `1.0`. In plain language, the pair is excluded when the minimum empty gap is no larger than the two stellar radii combined.

If a catalogue supplies only a recorded separation, a close recorded phase can prove that the stars reach the danger envelope. A far recorded phase cannot prove safety because the unavailable periapsis may be closer. Compact objects are `unknown`: their gameplay exclusion zones are not represented by photospheric radius.

This is a conservative geometry rule, not a ship-specific heat simulator. Frontier does not publish an exact journal field for arrival exclusion-zone radius, heat rate, arrival orientation, or damage threshold. Ship heat efficiency, throttle, orbital phase, and arrival orientation can change the outcome. Binary positions change over time, but the orbital periapsis used by the rule is invariant until the underlying game data changes.

## Route-supervisor sequence

1. When Elite writes `NavRoute`, Nova batches exact id64 star lookups for all exposed hops.
2. Nova announces either a verified-safe route or the exact number of hops whose companion geometry is unknown.
3. If a hop is proven dangerous, Nova preserves the original destination and replots only to the last safe hop before it.
4. On arrival at that boundary, Nova searches EDSM within the live jump range for a coordinate-locked system with a scoopable primary star.
5. Candidate waypoints are ranked by forward progress, lateral displacement, and clearance from the dangerous system. Spansh geometry is then checked locally with the same classifier.
6. A proven-safe KGBFOAM waypoint is preferred. If none is available, Nova may use a scoopable waypoint with unknown companion geometry and explicitly warns the commander.
7. After the intermediate jump, Nova replots the preserved original destination and validates the new `NavRoute` again.
8. The loop records rejected id64 systems and stops after five failed bypass attempts instead of cycling indefinitely.

Nova replots routes but never initiates the jumps in this workflow. If the immediate `FSDTarget` is proven dangerous and hyperspace charging begins, Nova presses the dedicated `Hyperspace` binding once to cancel the charge, then asks for a route around the system. Supercruise charging is never cancelled. After every system entry, Nova also warns if the next remaining hop has unmapped close-star geometry.

Elite's own Galaxy Map pathfinder has no blacklist input. Nova therefore cannot make Elite exclude a system internally; the safe-prefix and intermediate-waypoint loop is the deterministic wrapper around that limitation.

## Settings

The Quality of Life panel stores these settings through the normal versioned configuration path:

- `Avoid known dangerous close-star destinations`: enables classification, exobiology destination filtering, route validation, and supervision.
- `Cancel jumps into proven dangerous systems`: enables the last-resort charge guard.
- `Unknown star geometry`: `Allow` is the default so deep-space routing remains usable; `Exclude` can leave exobiology planning with no destination.
- `Close-star surface-gap ratio`: controls the dimensionless geometry envelope; default `1.0`, allowed range `0–5`.

Configuration migration preserves characters, providers, TTS/STT, voice effects, Terra/OpenAI settings, autostart, plugin settings, and active exobiology expedition data.

## Diagnostics and limitations

Exobiology plan results include a `route_safety` object with evaluated, excluded, and unknown-allowed systems, provider errors, the active rule, and coverage. Each target and persisted expedition entry carries its own assessment.

The safety classifier is pure and has no network, LLM, filesystem, or game-control dependency. Data acquisition is separate. Route lookups are prefetched in background threads so the charge-time decision never blocks on a web request.

False negatives remain possible when community records are absent, incomplete, stale, or incorrect. False positives are possible because the default rule considers the closest orbital geometry rather than predicting the ship's precise arrival orientation and thermal response. A `safe` result means the supplied catalogue's complete star records are outside the configured envelope; it is not a guarantee against every Elite Dangerous arrival hazard.

## Data references

- [Frontier Player Journal manual](https://hosting.zaonce.net/community/journal/v37/Journal_Manual_v37.pdf)
- [Elite Journal travel events](https://elite-journal.readthedocs.io/en/latest/Travel.html)
- [Elite Journal exploration events](https://elite-journal.readthedocs.io/en/latest/Exploration.html)
- [EDSM system and celestial-body API](https://www.edsm.net/en_GB/api-system-v1)
- [Spansh body search](https://spansh.co.uk/bodies)
- [EDSM sphere-system request flags](https://kayahr.github.io/edsm/interfaces/SystemRequestFlags.html)

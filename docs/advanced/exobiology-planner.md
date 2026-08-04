# Profit-optimized exobiology planner

COVAS exposes `find_exobiology_targets` as a first-class action. It is the preferred tool for every exobiology money-making request; the generic web agent and `body_finder` are not used first.

Typical action sequence:

1. The assistant calls `find_exobiology_targets` with `strategy: auto`.
2. The planner reads the current system and live ship jump range from projections.
3. It obtains viable targets from Spansh, ranks them by estimated credits per hour, and returns `navigation_instruction` containing the selected system and body.
4. The assistant immediately calls `plotToTarget` with that instruction unless the commander asked for information only.

This removes a nested LLM search round trip and prevents invented or malformed Spansh filters.

## Strategies

### Confirmed throughput (default)

`auto` resolves to `confirmed_throughput`. It uses Spansh's Expressway to Exomastery route endpoint with a minimum organism value of 16 million credits. Results contain recorded organisms and therefore provide a reliable base payout.

The planner does not blindly accept route order. Each body is scored using:

- recorded organism value;
- direct jump estimate from the commander's current system and jump range;
- supercruise distance, with a strong penalty for extreme arrival distances;
- approximate landing and three-sample collection time.

This is the normal credits-per-hour mode. A 19-million-credit body at 50 ls can outrank a nominally richer body millions of light-seconds from arrival.

### First-discovery hunting

Use `strategy: first_discovery` only when the commander explicitly asks for virgin targets, a deep expedition, or maximum payout per body. It searches three profiles:

- Rocky body, thin CO2, 0.04–0.07 g, 190–196 K: theoretical base ceiling 90,323,900 credits.
- High-metal-content body, thin water, 0.04–0.065 g, no volcanism: theoretical base ceiling 85,819,600 credits.
- High-metal-content body, thin CO2/SO2, at least 165 K and at most 0.62 g: Tectonicas volume profile.

Candidates must have predicted biological genera and `landmark_value = 0`, meaning Spansh has no recorded organism payout for the body. This is useful evidence that the target is unconfirmed, but it is **not proof** that the first-logged 5× total remains available.

An earlier design used `updated_at < 2021-05-17` as a guarantee. Live API validation on 2026-08-04 showed that the cutoff returns no usable nearby candidates and does not reliably encode first-logged state. The production planner therefore does not make that guarantee.

## Current biological rules encoded in the planner

- First logged payout totals 5× base value (base plus a 4× bonus).
- Stratum Tectonicas is restricted to high-metal-content worlds; never Rocky bodies.
- Tectonicas target envelope: thin CO2/SO2, at least 165 K, gravity no higher than 0.62 g.
- Low gravity is the main stacking gate. Many genera cap at approximately 0.276 g.
- Signal count is not a value metric. Confirmed throughput uses organism value instead.
- The high-value route threshold is 16 million credits.
- All three samples of one species must be completed before another species is started.
- Unsold biodata is lost on death.
- First Footfall is not the first-logged organism credit bonus.

The assistant should prioritize the high-value organisms listed in the result and skip low-value samples when collecting them reduces credits per hour.

## Spansh protocol requirements

- Search endpoints use JSON.
- Route endpoints use form encoding.
- Route jobs are asynchronous and are polled through `/api/results/<job>`.
- Numeric filters use `{"comparison":"<=>","value":[min,max]}`.
- Only the special distance-from-reference filter uses `{"min":min,"max":max}`.
- Correct biological fields include `atmosphere`, `subtype`, `volcanism_type`, `genuses`, `signals`, `landmark_value`, `surface_temperature`, and `gravity`.
- Requests identify COVAS with a dedicated user agent and use bounded timeouts.

## Deliberate limits

- The credits-per-hour estimate is a ranking heuristic, not a promise. Actual terrain, organism distribution, ship handling, and player technique vary.
- Spansh only knows data submitted to the network. An unconfirmed target can already have been visited or logged without the database knowing.
- The planner does not block on an Artemis-suit check. That state may be stale while the commander is in the ship, and the check adds friction to the normal route-selection path.
- Personal scan-history exclusion is not used unless COVAS has authoritative history in its own state. Remote galaxy data is never treated as personal history.

## Maintenance references

The consolidated rules originated from the local `elite-exobiology`, `elite-spansh`, `elite-local-data`, and `elite-frontier-capi` research skills. When updating the planner, verify filter behavior against the live Spansh API and keep deterministic search/ranking logic in `src/lib/actions/ExobiologyPlanner.py`; do not move it into a personality prompt.

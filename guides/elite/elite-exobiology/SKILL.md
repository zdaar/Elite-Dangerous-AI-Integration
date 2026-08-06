---
name: elite-exobiology
description: Plan and execute maximum-credit Elite Dangerous exobiology runs. Use for Stratum Tectonicas sniping, First Logged hunting, controller-friendly routes that avoid full FSS scans, Spansh candidate searches, Observatory/BioInsights triage, Expressway to Exomastery, organism conditions and values, DSS/Artemis sampling, Vista Genomics sales, First Footfall questions, or any request to make credits from biodata.
---

# Exobiology — maximum credits per hour

Use the operating procedure below for money runs. Read the reference files only when their detail is needed.

## Non-negotiable operating rules

1. For “find money targets now”, run `find_exobiology_targets` immediately. When the commander asks Nova to persist and plot targets one by one, run `plan_tectonicas_expedition` instead, then use `control_exobiology_expedition` for each “next target.” Do not perform a preliminary guide lookup or generic web search.
2. Default to **pre-Odyssey Stratum sniping**. It gives an exact system and body candidate while preserving a strong chance of the 5× First Logged payout.
3. Never require a full-system FSS for a money run. Try the named body directly; otherwise resolve only enough HMC signals to identify it, then exit FSS.
4. Rank whole **systems**, not isolated bodies. Prefer several candidates in one system, short jumps, and low arrival distances.
5. Never describe a Spansh candidate as guaranteed. Community uploads are optional and First Logged belongs to the first commander who sells.
6. Keep responses operational and short: target, body, arrival distance, expected payout, next control action. Do not initiate roleplay, but comply immediately when the commander explicitly asks for humour, roleplay, or another tone.
7. Treat live state, journal events, and successful tool results as authoritative for current state. Do not precede a direct action or live-status request with a guide lookup, generic search, or memory search.
8. Never use conversation memory to establish the current target, route, queue index, scan completion, or distance. If the commander corrects one of these, read live state or call the exact status action.

## Expedition control contract

Use `control_exobiology_expedition` as a state machine; do not substitute natural-language guesses:

| Request | Call | Mutation |
|---|---|---|
| “Where are we in the queue?” | `status` | none |
| “Resume/replot this target” | `start` | none |
| “Next target” after the current body is done/skipped | `next` | +1 |
| “Previous target” | `previous` | -1, clamped |
| “Set target/index N” | `set`, `index: N` | select the **1-based** queue position |
| “Reset the expedition” | `reset` | index 1 |

Pass `plot: false` when the commander asks only to inspect or change queue state without navigation. Never treat “guide me here,” “what now?”, or a question about the current body as permission to advance.

After any mutating control call, report these fields separately: queue position, exact target body, requested target system, verified live route destination, and next hop. A successful queue update is not a successful route plot. If the returned route destination differs from the requested system, state the mismatch and do not tell the commander to jump.

Route and distance semantics:

- `NavInfo.NavRoute[0]` is the next hop; `NavInfo.NavRoute[-1]` is the final destination; `len(NavRoute)` is the remaining jump count.
- `NextJumpTarget`/`FSDTarget` alone identifies the next targeted system, not the final destination.
- A persisted candidate `distance_ly` is measured from the expedition's original planning source. Label it **distance from planning source**, never current distance.
- State a current distance only when live coordinates or a tool result explicitly calculated it from the current location.
- A plot failure proves only that plotting failed. Do not infer insufficient single-jump range, an empty region, filters, or any other cause unless Elite or the tool explicitly returned that cause.

## Choose one strategy

| Strategy | Use when | FSS burden | Expected payout |
|---|---|---:|---:|
| **Stratum sniping — default** | Maximise credits/hour and First Logged probability | None or named-body-only | 95,054,000 Cr per first-logged Tectonicas; base 19,010,800 |
| **Confirmed throughput** | The commander wants deterministic targets and zero discovery work | Usually none | Recorded base value only; use Spansh Expressway to Exomastery |
| **Virgin exploration** | The commander wants exploration/name discoveries, not the least friction | Partial HMC-band FSS | High variance; 5× possible, target unknown in advance |

Do not blend these modes. A public confirmed-organism route is convenient precisely because another commander submitted it; it should not be sold as a First Logged route.

## Default: pre-Odyssey Stratum sniping

### Why it works

Odyssey added landings and biology to suitable thin-atmosphere worlds. Spansh still contains older HMC records whose last community update predates Odyssey. Their physical properties and exact body designations are known, but their Odyssey biology often is not.

This is the crucial database invariant:

- Filter `updated_at` to before Odyssey release.
- **Do not add `is_landable=true`.** Those old thin-atmosphere records commonly say `is_landable=false`; that was correct when submitted. Requiring `true` deletes the candidate set.
- Do not require `genuses`, `signals`, or `landmark_value=0`. Those are Odyssey-era submitted data and are not the legacy signal.

The date proves only that Spansh has no newer submitted record. It does not prove nobody visited without an uploader. Current community reports put success above 80% in suitable remote regions; one 2026 tool author measured about 4% unreported misses against personal sales. Treat both as field reports, not guarantees.

### Positioning

- Prefer at least **3,000 ly from inhabited space** and away from major tourist highways for the highest hit rate.
- If closer, either accept lower confidence or continue outward before building the queue.
- Use the live `Location.StarPos` coordinates as the Spansh reference when possible. A newly visited system name may not exist in Spansh yet; `reference_coords` avoids that failure.

### Candidate filter and route

Read `references/targeting.md` → **Stratum-sniping search recipe** before constructing the request.

Use these defaults unless the commander overrides them:

- Radius: 500 ly around the operating center.
- Maximum arrival: **1,700 ls**; use 1,000 ls for an even tighter run.
- Results: fetch at least 100 nearest candidates, then post-filter the atmosphere-specific Tectonicas envelope.
- Sort/rank: candidate bodies per system first, then travel time and arrival distance.
- Preserve the exact system and body names. One system containing five eligible bodies is usually better than five single-body systems.

When `count` is exactly 10,000, the Spansh result is capped. Narrow or partition the search before drawing population conclusions.

### Per-target loop

1. Plot the returned system and retain the exact body designation. Verify that the live route's final entry exactly matches the requested system before calling it successful.
2. Report the first live route entry as the next hop and the last as the destination. Jump and honk. The initial route may target only the system because a stale, unresolved body cannot always be selected in the galaxy map; retain every supplied body name.
3. If the system map/nav panel exposes the named body, select it directly. Otherwise enter FSS, tune straight to the HMC band, resolve only until the named body appears, then exit.
4. Read Observatory + BioInsights after the relevant scan event. Reject the body immediately if it predicts no high-value Stratum.
5. Check the in-game First Footfall marker. `WasFootfalled: true` confirms a marker is already recorded; `false` says only that none is recorded in the live data received. Neither state proves whether First Logged remains available. In a conservative high-hit-rate run, an already claimed marker is a reason to deprioritize or skip; otherwise continue when the base payout or remaining First Logged chance justifies it.
6. DSS only the candidate. If the DSS biology filters do not include `Stratum`, leave immediately.
7. Select the Stratum overlay, descend into open flat highlighted terrain, and fly low and slow.
8. Collect three Tectonicas samples consecutively, at least 500 m apart. Reposition a small ship between samples; do not walk or drive long distances.
9. Move to the next named candidate body in the same system before taking another jump. Once a body has been resolved, target that exact body rather than advancing to another system.
10. Advance the saved queue only after the commander explicitly confirms completion/skip or asks for the next target. Do not finish the rest of the FSS for completeness.

BioInsights predicts after sufficient FSS/body data and validates after DSS. It is the go/skip layer, not the route finder.

## Confirmed-throughput mode

Use Spansh **Expressway to Exomastery** for already catalogued organisms. Set a high minimum biological value and a tight arrival cap. This is the lowest-friction training/base-money route but normally pays base value only.

Do not replace this purpose-built router with a generic `landmark_value=0` query. Zero recorded value means “not submitted to Spansh”, not “unclaimed in game”.

## Virgin-exploration fallback

Use this only when legacy candidates are exhausted or the commander wants genuine exploration.

1. Move to a dark/low-traffic ED Astrometrics region, normally 1,500–3,000+ ly out.
2. Use economical routing through likely stars. For Tectonicas eligibility prefer F/K/M; do not assume the common A/F/G/K video heuristic is a hard rule.
3. Honk each system.
4. Enter FSS and tune directly to the HMC band.
5. No HMC signal: jump immediately.
6. Resolve HMC bodies only. Let BioInsights reject bodies without valuable predictions.
7. Exit as soon as the HMC band is flat. Never scan to 100% for an exobiology credits/hour objective.

A single biological signal is not proof of low-value Bacterium. Let BioInsights override that older heuristic.

## Surface execution

- Required: Artemis suit and Detailed Surface Scanner.
- Prefer a small, easy-to-land ship with fuel scoop and an SCO-capable FSD. An SRV is optional and usually slower for flat Tectonicas.
- The DSS overlay marks compatible terrain, not organism density.
- Tectonicas prefers broad, flat terrain and has a 500 m colony range.
- Complete all three samples of one species before touching another; switching species discards incomplete progress.
- Skip low-value organisms unless already co-located with the profitable target.
- Unsold biodata is lost on death.

Read `references/field-guide.md` for visual identification, terrain, approach, and other genera. Read `references/species-values.md` for all fixed values and sample distances.

## Payout terminology and selling

- **First Footfall** records the first on-foot landing. It pays no Vista Genomics multiplier and is only a strong availability clue.
- **First Logged** is awarded to the first commander who sells that species from that body.
- First Logged adds 4× base to the normal base payment: **5× total**.
- Stratum Tectonicas: 19,010,800 base; **95,054,000 First Logged total**.
- Sell at Vista Genomics. Carrier Vista currently banks the full normal/First Logged amount without a fixed Vista cut, reducing deep-space risk, but current tests say it does **not** receive Antal's bonus.
- A current Pranav Antal +30% organic-data bonus, when the commander meets the active Powerplay requirements and sells at a normal eligible Vista port, raises a first-logged Tectonicas to about **123.6M**. Verify current rank and territory before planning the return trip.

Never say landing reserves the 5× payout. Another commander can sell first.

## Evidence and confidence rules

- Use live journal state, direct tool output, and this skill before model memory.
- Separate confirmed facts from community field measurements and video claims.
- If a target tool returns an exact body, act on it; do not run a generic explanatory lookup first.
- Never convert a planning-source distance into a claim about current distance.
- Never convert a selected next hop into a claim about final destination, or vice versa.
- Never report a First Logged total as earned before a sale event confirms it; label it as potential until then.
- If the local evidence is insufficient, say so and make one sourced lookup rather than improvising a game mechanic.

## References

- `references/targeting.md` — exact Tectonicas envelope, pre-Odyssey Spansh payload, star/gravity gates, and stacking profiles
- `references/field-guide.md` — DSS/FSS triage, terrain, organism identification, and surface technique
- `references/species-values.md` — all Vista Genomics values and colony distances
- `elite-spansh` — request transport, field shapes, saved searches, and route APIs

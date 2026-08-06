# Profit-optimized exobiology planner

COVAS:NEXT exposes deterministic exobiology actions so the assistant can execute a money run without a preliminary web search, memory lookup, or full-system FSS.

Close-star destination filtering and live route supervision are documented in [Close-star route safety](close-star-route-safety.md).

## Choose the action from the commander's intent

| Intent | Action | Important rule |
|---|---|---|
| Find or replace profitable targets now | `find_exobiology_targets` | One planning call; do not use `body_finder` first |
| Create a persistent Tectonicas queue | `plan_tectonicas_expedition` | Builds a new queue and selects its first exact body |
| Inspect the saved queue | `control_exobiology_expedition`, `operation: status` | Read-only |
| Replot/resume the selected target | `operation: start` | Does not advance |
| Advance after a completed or skipped body | `operation: next` | Requires explicit intent to advance |
| Go back one body | `operation: previous` | Does not rebuild the queue |
| Select queue position N | `operation: set`, `index: N` | Index is **1-based** |
| Return to the first body | `operation: reset` | Use only when explicitly requested |
| Explain how to find a known genus on the current body | `get_exobiology_field_guide` | Never searches for another planet |
| Explain an Elite mechanic | `lookup_elite_guide` | Do not call before a direct action or live-status read |

`control_exobiology_expedition` also accepts `plot`. Set it to `false` when the commander wants to inspect or select a queue entry without changing the live navigation route.

“Guide me here,” “what do I do now?”, or a question about the current body does not mean “next.” The assistant must not advance the queue unless the commander explicitly asks to advance or confirms that the current target is complete/skipped.

## Default strategy: exact pre-Odyssey HMC leads

`auto`, `stratum_sniping`, and the compatibility alias `first_discovery` use old Spansh high-metal-content body records as Tectonicas leads. The planner:

1. Reads the live location coordinates and jump range.
2. Searches exact HMC body records last updated before Odyssey.
3. Applies the atmosphere-specific Tectonicas gravity and temperature envelope.
4. Groups every surviving exact body by system.
5. Ranks systems by candidate count, route cost, and arrival distance.
6. Applies the configured close-star safety policy to exact system id64 records and selects a safe alternate when available.
7. Persists every exact body designation and route-safety assessment instead of collapsing a system to one body.

Do not add `is_landable`, biological signals, genera, or `landmark_value=0` to this legacy search. Those fields require later community data and remove the intended candidate cohort.

The result is a lead, not proof. An old community timestamp guarantees neither Stratum, First Footfall, nor First Logged availability.

## Confirmed-throughput strategy

`throughput` uses Spansh Expressway to Exomastery and public organism records. It trades First Logged probability for deterministic base-value targets and low scanning work.

Do not describe a public confirmed-organism route as a virgin-discovery route. The public record is the reason the species and base value are known.

## Controller-friendly per-target loop

1. Keep the returned exact system and body names.
2. Plot the system, then verify the live route destination exactly.
3. Jump and honk.
4. Select the named body directly if exposed.
5. Otherwise enter FSS, tune only to the HMC band, resolve only the bodies listed in `targeted_fss_bodies`, and exit immediately when they are resolved.
6. Let BioInsights predict after the relevant body scan. Reject low-value results before flying out.
7. DSS only a passing body. Require a `Stratum` filter for the Tectonicas lane.
8. Collect three valid samples of one species before switching species.
9. Advance the queue only after the current body has been completed or deliberately skipped.

Never require 100% FSS for this workflow. If the system is already fully scanned, use the data already present; do not ask the commander to repeat it.

## Route truth contract

The queue target and the Galaxy Map route are separate states and can disagree.

- In `NavInfo.NavRoute`, entry `0` is the next hop and the last entry is the final destination.
- The number of entries is the remaining jump count.
- `NextJumpTarget` or an `FSDTarget` event alone proves only the next targeted system, not the final route destination.
- A plot is verified only when the final live route entry exactly equals the requested target system, including the procedural suffix.
- A queue update can succeed while plotting fails. Report `queue_updated`, plot success, requested system, route destination, and mismatch separately.
- A failed plot does not establish insufficient single-jump range, an empty region, or a filter problem unless the tool or Elite explicitly returns that cause.

Never describe the next hop as the final target. Never describe a selected marker as a verified multi-jump route.

## Distance truth contract

Candidate `distance_ly` is calculated when the expedition is planned and remains measured from that original source. It is historical planning metadata, not a live distance counter.

- Label it `distance from planning source`.
- State current distance only from live coordinates or a tool field explicitly calculated from the current location.
- Do not derive current jumps remaining from the candidate estimate. Use the live route length.

## First Footfall and First Logged

- `WasFootfalled: true` confirms that a First Footfall marker is already recorded.
- `WasFootfalled: false` means only that no marker is recorded in the live data received.
- First Footfall pays no Vista Genomics multiplier.
- First Logged belongs to the first commander who sells that species from that body.
- The First Logged payment is 5× base total, but it remains potential until a sale event confirms it.

For Stratum Tectonicas, the verified base value is 19,010,800 credits and the potential First Logged total is 95,054,000 credits. Do not tell the commander that the 5× amount is earned immediately after sampling.

## Assistant response contract

For normal operation, return one or two short sentences containing only:

1. verified target or result;
2. relevant value/distance with its source semantics;
3. immediate next action.

Do not initiate roleplay or commentary from game events. An explicit request for a joke, roleplay, or another tone is a valid commander override and must not be refused because of operational mode.

## Deterministic expedition callouts

An active managed expedition adds two operational callouts without asking the LLM to interpret the journal:

- `FSDJump` or `Location` matching the current system-level queue target announces that the destination was reached and reads the exact `targeted_fss_bodies` checklist in arrival-distance order.
- `FSSBodySignals` caches the biological signal count for a listed candidate. The following `Scan` event reports that count and the journal's `WasFootfalled` value. A listed body with no biological signal is an immediate skip; a body with biology is sent to BioInsights, with DSS reserved for a Stratum prediction.

Each arrival and candidate result is announced once. Unlisted bodies, transit systems, historic journal replay, and completed queues remain silent. `WasFootfalled` is only a First Footfall marker and is never presented as proof that First Logged is unavailable.

## Maintenance references

The authoritative local workflow is tracked under `guides/elite`. The packaged app
deploys that tree to `managed-guides/elite` in Electron user data, so
`lookup_elite_guide` does not depend on a separate Claude project checkout. The
`COVAS_ELITE_GUIDE_PATH` environment variable can override the deployed tree; legacy
personal locations remain fallbacks.

The exobiology workflow lives in `elite-exobiology` and its `targeting.md`,
`field-guide.md`, and `species-values.md` references. Keep deterministic filters and
ranking in `src/lib/actions/ExobiologyPlanner.py`; keep queue control and output
verification in the plugin; keep personality and brevity in the Nova profile.

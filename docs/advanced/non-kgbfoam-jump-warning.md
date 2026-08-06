# Non-KGBFOAM jump warning

The **Warn before non-KGBFOAM jumps** option gives a calm, deterministic
orientation message for the immediate hyperspace destination. It is enabled by
default in this fork. The feature is informational: it never changes a target,
route, expedition index, control, or action permission.

## Inputs and timing

The selected immediate target comes from the Elite journal `FSDTarget` event:
`Name`, `SystemAddress`, and `StarClass`. The class is accepted only for that
same destination. If the current `Status.json` destination does not match the
cached target, the cached class is treated as unknown rather than copied to a
different system.

The preferred trigger is the rising edge of `Status.Flags.FsdCharging`, gated
by `Status.Flags2.FsdHyperdriveCharging`. This prevents a supercruise charge
from warning about a selected interstellar route. If the hyperdrive flag or
early class is unavailable, `StartJump` is the deterministic fallback, using
its own `JumpType`, `StarSystem`, `SystemAddress`, and `StarClass`. That fallback
is later and should be treated as orientation rather than a guaranteed
cancellation window.

Plotting or clearing `NavRoute` never triggers speech. In the normal route
projection, `NavInfo.NavRoute[0]` is the immediate hop and the last entry is the
final destination, but warning classification does not need to infer either
from a system name or from an LLM.

## Charge-cycle state

Each transition into charging creates one cycle. A known non-KGBFOAM class can
produce at most one warning in that cycle. Repeated status frames, the derived
`FsdCharging` status event, and `StartJump` cannot repeat it. Charging off ends
the active charge; a later rising edge is a retry and receives a new cycle.
`FSDJump` completes the old cycle without discarding an already-received
`FSDTarget` for the following hop. Target changes replace the cached target,
and `LoadGame` or `Shutdown` clears runtime warning state.

Unknown and malformed classes are silent by default. The separate **Warn when
the next star class is unknown** option enables a short statement that the
classification is unknown and will not be inferred.

## Local class mapping

KGBFOAM is defined as the seven complete journal codes `K`, `G`, `B`, `F`, `O`,
`A`, and `M`. All other documented codes use the checked-in mapping in
`src/lib/NonKgbfoamJumpWarning.py`. The table stores the canonical and
normalized code, family, actual fuel scoopability, expected appearance,
class-level arrival hazard, jet-cone supercharging capability, and one short
recommended action.

| Family | Journal codes | Fuel scoop | Jet-cone boost | Operational distinction |
| --- | --- | --- | --- | --- |
| Brown dwarfs | `L T Y` | No | No | Faint or dark arrival; normal exclusion-zone mechanics, plus a real fuel-stranding risk |
| Protostars | `TTS AeBe` | No | No | T Tauri can resemble a scoopable K/M star; the main danger is trusting that appearance for fuel |
| Wolf-Rayet | `W WN WNC WC WO` | No | No | Very luminous and unfamiliar, but normally routine outside the exclusion zone; fuel reserve still matters |
| Carbon and late-type stars | `CS C CN CJ CH CHd MS S` | No | No | Deep red/ruby appearance; no special arrival mechanic beyond the exclusion zone; fuel reserve still matters |
| White dwarfs | `D DA DAB DAO DAZ DAV DB DBZ DBV DO DOV DQ DC DCV DX` | No | Yes | Broad exclusion zone can sit close to short jets; cone use and emergency drops there are genuine hazards |
| Neutron stars | `N` | No | Yes | Clear arrival is routine; cone flight disturbs control, wears the FSD, and is dangerous after an emergency drop |
| Black holes | `H` | No | No | Visually dark/lensed but normal arrival is routine; avoid excessive close approach and preserve fuel |
| Supermassive black hole | `SupermassiveBlackHole` | No | No | Lensing-dominated appearance; close approach can cause rapid heat build-up |
| Giants and supergiants | `A_BlueWhiteSuperGiant B_BlueWhiteSuperGiant F_WhiteSuperGiant M_RedSuperGiant M_RedGiant K_OrangeGiant` | Yes | No | Outside the seven exact codes but scoopable; large apparent scale calls for ordinary exclusion-zone and heat awareness |
| Documented exotic/placeholders | `X RoguePlanet Nebula StellarRemnantNebula` | Not documented | Not documented | The warning states that class-level mechanics are not documented; it does not invent them |

For every non-scoopable class, the message distinguishes an uneventful arrival
from the strategic danger of becoming stranded: if no scoopable star remains
within the ship's fuel range, a single non-scoopable hop can be critical.

## Sources and limitation

Class codes and event fields come from Frontier's journal documentation:

- [Frontier-hosted Journal Manual v34](https://hosting.zaonce.net/community/journal/v34/Journal_Manual_v34.pdf)
- [Elite Journal travel events](https://elite-journal.readthedocs.io/en/latest/Travel.html)
- [Elite Journal star descriptions](https://elite-journal.readthedocs.io/en/latest/Appendix.html#star-descriptions)

Fuel-scoopability and family presentation are cross-checked against the
[established Elite Dangerous star catalogue](https://elite-dangerous.fandom.com/wiki/Stars).
Jet-cone and exclusion-zone guidance is cross-checked against the
[INARA travel and exploration guide](https://inara.cz/elite/squadron-document/7746/2927/).

A journal class cannot prove an individual generated body's exact exclusion
zone, whether a white dwarf's jets are visible at that moment, or the ship's
arrival clearance. Messages therefore state class-level mechanics and never
claim that an individual arrival is dangerous solely because its class is
unfamiliar.

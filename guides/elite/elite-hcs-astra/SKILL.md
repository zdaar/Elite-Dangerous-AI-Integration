---
name: elite-hcs-astra
description: Look up and explain exact HCS VoicePacks Singularity/Astra voice commands for Elite Dangerous. Use whenever the user asks what to say to Astra or another installed HCS crew voice, forgets a spoken command, wants to operate ship, SRV, fighter, panels, docking, navigation, combat, crew roster, macros, modes, educational content, or troubleshooting through HCS Singularity, or mentions HCS, Astra, Singularity, VoiceAttack, crew commands, or voice-command phrasing.
---

# HCS Singularity / Astra commands

Use the bundled command reference as the sole authority. Do not reconstruct commands from model memory or general Elite Dangerous controls.

## Lookup workflow

1. Search `references/commands.md` for the requested action and close synonyms.
2. Return the shortest exact phrase shown in backticks under **Say**.
3. Add a prerequisite or follow-up only when the matching **Does** text explicitly requires one.
4. Distinguish a sequence with arrows from alternative phrases separated by dots or slashes.
5. State when a command belongs to an unavailable add-on or requires fitted equipment.
6. If no matching phrase exists, say that the cheat sheet does not document it. Do not invent a plausible command.

For crew-station questions, distinguish a **station name** from a command performed by that station. Exploration/scanning duties map to `science officer`; `away missions` is the Odyssey on-foot suit station and `SRV` is the rover station. If the user asks only “what is the station called?”, answer only with the station name and do not expand into a roster tutorial.

## Response format

Respond in the user's language, but preserve the spoken HCS command exactly in English:

`<exact phrase>` — <one-sentence effect or required sequence>.

For a multi-step interaction, list only the ordered phrases the user must say. Keep roleplay at zero.

`references/commands.md` is a bundled snapshot of the source HCS cheat sheet. It
has no runtime dependency on the original HTML file.

Elite Dangerous · VoiceAttack · HCS VoicePacks

# Singularity Voice Command Cheat Sheet

Everything installed on this ship, what it can do, and the features the manual buries. Compiled from the local HCS v9.0 command manual, HCS's own command lists, companion-pack docs, and the official store.

## 00How to read commands

Some doc spellings are deliberately phonetic (`twenny`, `bacon` for beacon, `shroad inga's cat` for Schrödinger's cat) — that's recognition tuning, not a typo. Commands only fire if the underlying action has a keyboard key bound in Elite; the plugin reads your binds file automatically and warns in red when a bind is missing.

## 01Your crew — who's installed

Singularity runs up to six/seven packs at once and assigns each a bridge station. There is no "change voice to X" command — the crew roster is the mechanism.

#### Verity

The official in-game COVAS voice of Elite Dangerous — full Astra-level functionality. The seamless pick if you want the ship computer to sound like… the ship computer.

#### Celeste

Character background officially "CLASSIFIED" on the HCS store.

#### Doris

Sarcastic AI robot from Russell's Elite novel Mostly Harmless. Also one half of the playable "I Spy" game (with Jazz cameos).

#### Alix

Sold under the performer's own name — no in-universe backstory.

#### Delta

A robot-interface voice in the GLaDOS style, built from a heavily processed Alix Martin recording. Officially "performed by CLASSIFIED".

#### Z ("Ze" folder)

Experimental AI nanobot, last of its kind, that vocalises through surrounding surfaces. The install folder is "Ze" so the roster recognises the spoken name.

#### The Ship's Cat

100+ meows. Does absolutely nothing until you feed it — see section 08.

### Crew roster — assigning voices

| Say | Does |
|---|---|
| `crew command roster` | Enters allocation mode (bosun's whistle plays). Required before any role changes. 2-minute timeout. |
| `crewman <name>` → `<station>` | Assign that voice to a station: `first officer`/`number one`, `helm control`, `engineering`, `tactical`, `operations`, `science officer`, `SRV`, `away missions` (Odyssey suit). |
| `crewman <name>` → `take all stations` | One voice handles everything — the de-facto "switch voice to X". |
| `that is all` | Closes the roster. |
| `organise a crew` | Auto-allocates a crew for you (say `number one` first to hail the first officer). |
| `rotate the watch` | Randomises the whole crew. |
| `crewman <name>` → `you're relieved of duty` | Removes a crew member. |
| `crewman <name>` → `you're with me` / `transfer to the SRV` | Moves that voice to your suit / the SRV. |
| `assign all stations to crew favourite <number>` | Applies a whole saved crew in one phrase (save favourites in the customiser). |
| `refer to me as captain` / `…commander` | Changes how the crew addresses you. |
| `mute engineering` / `unmute engineering` | Silences a station (confirm with `yes`). |
| `all stations to non verbose mode` | Terser responses; also per-station, and `profane mode` exists if you want a sweary helm. |
| `enable chit chat` / `disable chit chat` | Toggles ambient crew banter. |
| `enable crew rotation mode` | Crew voices change periodically on their own. |
Ship Assigned Crew (in the customiser) auto-swaps your whole crew when you board a different ship — a different bridge crew per ship, hands-free. Station duties matter too: First Officer handles nav/maps/panels, Engineering handles power/gear/scoop, Helm handles thrust, Tactical handles targeting/weapons, Science handles scanning.

Terminology shortcut: if the commander calls this the “exploration station,” the documented station name is `science officer`. Do not redirect that request to `away missions`; that station is specifically for the Odyssey suit/on-foot role.

## 02Essentials — the daily loop

The 20 commands that cover 90% of a session.

| Say | Does |
|---|---|
| `launch` · `departure handover` | Launch; departure handover also rises 30 m, retracts gear and syncs panel tabs (runs launch first if still on the pad). |
| `request docking` | Docking request via the contacts panel — works within 7.5 km. |
| `refuel and repair when we land` | Deferred maintenance macro — runs the moment you dock. Variants: `arrival checks`, `perform routine maintenance`. |
| `engage supercruise` | Supercruise. Exit with `disengage` (also cancels a charging FSD jump) or `emergency stop`. |
| `engage jump drive` | Supercruise, or hyperspace jump if a system is targeted. |
| `engage system jump` · `safety jump` | Jump to the next system with throttle zeroed during the jump — no face-full of star. |
| `explorer jump please` | Jump + automatic discovery-scanner honk on arrival. |
| `full impulse` · `half impulse` · `seventy five percent` | Throttle presets; any 10% step plus 25/75 works. `stop engines` zeroes it. `warp factor one`–`ten` scales supercruise speed. |
| `boost engines` · `afterburners` | Boost. `engage speed brake` to shed velocity. |
| `power to engines` / `weapons` / `systems` | Max pips. `power to engines and systems` = 4/2 split; `balance power between X and Y` = 3/3; `increase power to X` = +1 pip; `balance power` resets. |
| `deploy hardpoints` / `retract hardpoints` | Weapons out/away. |
| `gear down` / `gear up` · `cargo scoop down` / `up` | Landing gear and scoop. `lights on` / `off` too. |
| `lock target` · `next hostile` · `target highest threat` | Targeting basics. Subsystems: `target the powerplant`, `target the drives`, `next subsystem`. |
| `launch chaff` · `heatsink` · `shield cell` | Countermeasures. |
| `flight assist off` / `on` · `silent running on` / `off` | Flight toggles. Silent running also answers to `rig for silent running`. |
| `scan the system` | Discovery scanner honk. `enter system scan` / `exit system scan` opens/closes the FSS. |
| `open galaxy map` · `open system map` · `close the map` | Cartography. |
| `take her in nice and slow` | Engages the docking computer (needs one fitted). `number 1 take us out` for auto-launch (advanced DC). |
| `prepare for docking` | 10% throttle, gear, 4-2 pips. `prepare for landing` auto-stages pips <2.5 km and gear <1.5 km on planets. |
| `run diagnostics` | The panel-desync fix. If commands open wrong tabs because you clicked panels with the mouse: put panels at default, say this, tracking resets. |

## 03Flight, engines & docking — full set

### Throttle & thrust

| Say | Does |
|---|---|
| `[quarter;half;three quarter;full;maximum] impulse` | Velocity presets (quarter = 25%). |
| `[engines;] <XX> percent` | Any 10% increment + 25/75, e.g. `main drives twenty percent`. |
| `[stop;cut;kill] [all;] engines` | Throttle to zero. |
| `reverse thrusters [25;50;75;100] percent` · `full reverse` | Reverse thrust. |
| `boost brake` | Boost then immediate brake. |
| `clear the mass lock` | Throttles up until mass lock clears. |
| `observation speed` · `slow down for a look` | Slow cruise for sightseeing. |
| `clearance velocity` | Speed-limit-safe pace inside the no-fire zone. |

### Jumps & supercruise

| Say | Does |
|---|---|
| `[engage;initiate] [jump drive;warp drive;FSD;hyperspace;frame shift]` | The big macro — dozens of accepted phrasings. |
| `cancel jump` | Aborts a charging jump. |
| `clear the area and prepare for system jump` | Boost away from the station, then jump. Also `clearance velocity and jump`. |
| `next system in route` | Targets the next hop on your plotted route. |
| `maximum warp` | Full supercruise throttle. |
| `prepare for orbit` | 50% throttle + max shields for planetary approach. |

### Docking & stations

| Say | Does |
|---|---|
| `request docking [on my mark;]` · `cancel docking request` | Panel-driven docking request. |
| `docking speed` · `safety dock` | Slow approach pace. |
| `open starport services` / `close starport services` | Station services screen. `enter hangar`, `return to surface`. |
| `take me to the [commodity market;mission board;outfitting;shipyard;advanced maintenance;livery;holo me;universal cartographics]` | Direct navigation inside station services. |
| `pre launch checks` · `launch when ready` | Launch variants; `clear the pad` / `take off` also work. |

## 04Combat, wings & fighters

### Weapons & defence

| Say | Does |
|---|---|
| `red alert` · `battle stations` | Combat macro: hardpoints, pips, (optionally auto-deploys fighter — customiser). `yellow alert` for the defensive version; `stand down red alert` to cancel. |
| `attack protocol [alpha;beta;charlie]` | Preset offensive configurations. `defence protocol [alpha;beta]` for defensive ones. |
| `fire group alpha` … `golf` | Direct fire-group selection; `next fire group` / `previous fire group` to cycle. |
| `burst ECM` · `charge the ECM` · `triple ECM` | ECM control. |
| `cycle turret mode` | Turret behaviour. |
| `start mining` / `cancel mining` | Mining laser fire control. |
| `friend or foe` | Reports whether target is wanted or clean (Alpha-grade packs). |
| `reboot and repair` | Module reboot sequence. |

### Wings

| Say | Does |
|---|---|
| `wingman [one;two;three]` | Select wing member. |
| `lock wing target` · `wingman ones target` | Wing target selection. |
| `wingman nav lock` · `follow wingman` | Nav lock; also per-member. |
| `deploy the wing beacon` | Wing beacon (recogniser also accepts "bacon" — intentional). |

### Ship-launched fighters

| Say | Does |
|---|---|
| `deploy fighter one` / `two` · `recall the fighter` | Launch and recover. `launch me in fighter one` puts you in it. |
| `attack my target` · `hold position` · `follow me` · `cease fire` | NPC pilot orders. |
| `aggressive posture` / `defensive posture` | Engagement stance. |
| `switch to fighter` / `switch to mothership` | Seat swap. Note: nav/inventory panel commands don't work from the fighter. |

## 05Panels, HUD & camera

### Cockpit panels

| Say | Does |
|---|---|
| `open [left;right;comms;role] panel` | Left = nav/target, right = systems, top = comms, bottom = role. `exit the panel` / `look ahead` to close. |
| `navigation` · `contacts` · `cargo hold` · `modules` · `fire groups` · `status` · `transactions` … | Jump straight to a tab by name — say the tab, the AI opens the right panel and tab. |
| `take me to [Galnet news;the engineers;the codex;the refinery;materials;synthesis;reputation;finance;statistics;…]` | ~20 deep-link destinations inside panels. |
| `next tab` / `previous tab` | Manual tab stepping. |
| `accept` / `confirm` · `cancel` / `dismiss` | Dialog responses. |

### HUD & scanners

| Say | Does |
|---|---|
| `switch to analysis mode` / `combat mode` | HUD mode switch (also `switch hud mode`). |
| `activate detailed surface scanner` · `launch probe` | DSS mapping (auto fire-group switch — set in customiser). |
| `increase sensor range` / `decrease sensor range` · `zoom out max` | Radar zoom. |
| `lock and scan` · `scan celestial body` | Exploration scans. |

### Camera suite

| Say | Does |
|---|---|
| `external camera` · `return camera to ship` | Enter/exit vanity cam. |
| `camera [one…nine]` · `next camera` | Preset positions (cockpit front/back, commander, co-pilot, low…). |
| `free camera on` · `camera hud off` | Free cam and clean-shot HUD toggle. |
| `take a photo` · `take a high rez photo` | Screenshots — also flavour triggers like `delightful view`. |

## 06Planets, SRV & surface ops

| Say | Does |
|---|---|
| `prepare for touchdown` | Staged landing: pips and gear applied automatically by altitude. |
| `deploy the SRV` · `deploy buggy two` | SRV deployment; `deploy the SRV when we land` queues it. |
| `recover the SRV` · `open the pod bay doors` · `bring me aboard` | Board the ship from the SRV. |
| `dismiss the ship` / `recall the ship` | Send the ship to orbit / call it back (`come and get me`). |
| `go for launch` · `launch to orbit` | Semi-assisted surface departure — boosts once you pitch vertical. |
| `prepare for immediate dustoff` | The full macro: lands, drops the SRV, ship leaves. Say it again to recall the ship and auto-launch to orbit. |
| `SRV recovery and launch now` · `emergency extraction and launch` | Fast pickup + departure. |
| `drive assist [on;off]` · `handbrake` · `enable eco mode` | SRV systems; eco mode powers down modules to stretch fuel. |
| `refuel the buggy` · `emergency SRV repair` · `transfer cargo` | SRV maintenance via synthesis. |
| `deploy the turret` / `leave the turret` | Turret mode. |
If you add the Gravity DLC: `weapons hot`, `selecting arc cutter`, `scanning profile`, `hack the terminal`, `patching myself up`, emotes (`07 commander` salutes), the Insight hub (`insight recall ship`, `what am I carrying?`) — and you can talk to NPC service desks by name (`Apex Interstellar`, `Vista Genomics`, `bar tender`) then read their on-screen dialogue lines aloud. On-foot binds must be single keypresses with HOLD options set to TOGGLE.

## 07Advanced & hidden features

The stuff you're paying for and probably never used.

| Say | Does |
|---|---|
| `<almost anything> on my mark` → `punch it` | Arm nearly any jump/dock/mining/SRV command, trigger when ready with `mark`/`engage`/`execute`/`now`/`punch it`. 15 s timeout, configurable, optional warning beeps. |
| `commence smuggling run` | Full smuggler's approach: heatsinks, boost, silent running inside the no-fire zone, docking request, cuts silent running when docked. You steer and drop gear. Fit heatsinks; disable auto-dock. Works with `on my mark`. |
| `explore mode on` | Auto-fires the discovery scanner after every jump. Fire-group configurable. |
| `deploy [collector;prospector;hatch breaker;repair;recon;research;decontamination;fuel transfer] limpet` | Auto-switches to the right fire group per limpet type (map groups in customiser → Limpet Control). |
| `fill my hold with limpets` · `buy 300 limpets` → `confirm purchase` | Voice limpet restock; `dump all limpets` / `dump 25 limpets` to jettison. |
| `set course for Felicity Farseer` | Route-plots to any of the 15 engineers by name; also POIs (`set course for the alien scout ship`, ancient ruins…). Reply `destination confirmed thank you`. |
| `plot a course to my clipboard` | Plots to whatever system name is in your Windows clipboard — the EDSM/Inara power move. |
| `plot a course to my mission` · `locate my mission target` | Odyssey mission navigation. |
| `initiate self destruct` → `<your passcode>` | Self-destruct guarded by a custom override phrase you set in the customiser (e.g. "Destruct Alpha Zero Zero"); wrong phrase or 5 s silence cancels. |
| `protocol override take me to [game controls;graphics;audio;social menu;help menu;arx store]` | Menu navigation from the Continue screen. `protocol override exit to desktop` too. |
| `invoke mode on` | The AI proactively asks ("deploy landing gear?"); answer `yes please`, `in a moment`, or `no thank you`. Per-question frequency in the customiser. |
| `send standard [greeting;reply;target;wing] [one…ten]` | Sends your pre-written chat macros to players (write them in customiser → Comms Messages). |
| `enable stars and planets` · `enable Galaxapedia` · `enable quantum theory` · `enable constellations` | Ambient educational content toggles — see section 10. |
| `is this system dangerous` | Threat assessment of the current system. |
| `tell me about the Orion Nebula Expedition` | Guided nebula tour: prepare, `set navigation for the Orion Nebula Expedition`, per-stop lore (`tell me more about the ___ nebula`), `resume the nebula tour` if lost. |

## 08Ad-Astra ship's assistant Add-on — not detected in your install

These commands need the Ad-Astra add-on pack (the "ship's assistant"). Listed so you know what you'd get — it's the deepest feature set HCS sells and the source of most "wait, it can do that?" moments.

| Say | Does |
|---|---|
| `plot a course to my nearest [material trader;interstellar factor;black market;tech broker;…]` | Nearest-facility routing filtered by your ship size; also economy types and allegiances. `how far is my nearest …` to just ask. |
| `access blueprint database` | Interactive engineering lookup: module → mod → grade → which engineer, materials needed vs what you own. |
| `notify me when I have all those materials` | Watched shopping list — announces at next dock when you've gathered everything for a blueprint. |
| `tell me about <anything>` · `how much Vanadium do I have?` | Knowledgebase + live stock checks; `show me an exploration build for the Anaconda` opens coriolis.io. |
| `load the Colonia Bridge expedition` · `plot a course to my next waypoint` | Expedition system with waypoint tracking; build custom expeditions from a pasted system list. |
| `what did I discover in this system` · `are we there yet` · `where is my landing pad` | Status queries: bodies left to map, credits, bounties, rebuys, jumps remaining, pad location. |
| Journal auto-responses | Reacts to the game journal: valuable-planet callouts, "someone mapped it first", prospector yield analysis (Void Opals!), under-attack warnings, mission-will-fail alerts, docking-denied reasons, and Launch Checks (warns if leaving with no limpets, low fuel, or an empty fighter bay). |

## 09The Ship's Cat

The cat is silent until you feed it once: say `feed the cat` to enable it, then `letting the cat in` to start ambient cockpit meowing. `letting the cat out` silences it.

| Say | Does |
|---|---|
| `here kitty kitty` · `where's the cat` · `ships cat` | Calling it. |
| `are you hungry` · `I better feed you` · `no breakfast for you` | Feeding time (lunch/dinner/supper variants too). |
| `check the cargo hold for vermin` | Putting it to work. |
| `do you want to go out` · `you're not coming in` · `come back kitty` | Door negotiations. |
| `flea spray the cat` · `time for your flea treatment` | Grooming (it has opinions). |
| `naughty cat` · `get in your bed` · `you need a name kitty` · `do you like Dave the dog` | General cat business. |

## 10Chit-chat, games & the galactic encyclopedia

### Universal chit-chat (all voices)

| Say | Does |
|---|---|
| `introduce yourself` · `all stations say hello to the stream` | Introductions — great for streams. |
| `hi crewman <name>` · `thank you crewman <name>` | Greetings and thanks. |
| `target destroyed` · `he went boom` | Kill confirmations with attitude. |
| `what's your name` · `who made you` | Identity questions. |

### Your crew's party tricks

- Doris — playable "I Spy": `something beginning with A` (any letter A–Z), `try B again` — a full 78-command letter game. Also Hitchhiker's flavour: `quote Douglas Adams`, `tell me a joke Doris`.
- Verity: `what is the foxtrot romeo protocol`, `tell me about the Thargoids`, `it's my birthday`, `merry Christmas`.
- Scripted lore dialogues exist for voices you don't own (Midnight, Eden, Vega, Orion's obelisk storyline…) — cameo content sometimes plays through installed packs.

### Educational databases

| Say | Does |
|---|---|
| `tell me about <topic>` · `what is a black hole` | GalaXapediA: ~228 astronomy topics A–Z (accretion, blazars, dark energy…). `give me a random galactic fact`. |
| `tell me about constellation Orion` | All 88 constellations, with phonetic aliases built in. `random constellation fact`. |
| `what is entanglement` · `shroad inga's cat` | Quantum Theory: 45 topics — superposition, many-worlds, Hawking radiation, Alice & Bob. `random quantum theory fact`. |
| `enable [Galaxapedia;quantum theory;constellations;stars and planets]` | Ambient mode — facts get woven into flight. Packs missing content borrow cameo voices. |

## 11Customisation & maintenance

| Thing | How |
| `protocol override customise my settings` | Opens the HCS Customiser (or LeftCtrl+LeftAlt+LeftShift+Enter). All voice commands pause while it's open. |
| Voice Trigger Editor | In the customiser: edit the spoken phrase of any command using the [a;b] syntax. Saved to a "Custom" template — originals never overwritten, per-line reset. The search box doubles as the best "what can I say?" browser: it also shows which flight modes each command works in. |
| Adding your own commands | Never edit the Singularity profile directly — updates wipe it. Put custom commands in a separate VoiceAttack profile, then Singularity profile → Profile Options → General → "Include commands from other profiles". Re-select after profile updates. |
| Keybind Creator | Customiser tool that generates a complete HCS-prefixed binds file, filling every missing bind (game must be closed). The Missing KeyBind Report lists exactly what's unbound and where to set it. |
| Panel Tracking (keys/joystick) | Off by default. Import `Run Singularity Commands by Keypress example.vap` from HCS TOOLS\Profiles\…\Extra helper profiles, set your six panel keys in its PANEL TRACKING commands, include it into Singularity, and enable the keyboard icon on VoiceAttack's main window. Without it, manual panel presses desync tracking (mouse never tracks — use `run diagnostics` to resync). |
| Timing & behaviour toggles | Customiser: key-press duration, panel pause, auto-heatsink on heat warning, retract-modules-before-jump, auto-fighter on red alert, disable boost while docking, clearance height (30 m default), stand-by timeout, hyperspace chatter off, Archer's singing off, always-refuel-when-docked, VR command-ignored beeps. |
| Backup / restore | Customiser Backup & Restore preserves custom voice triggers across reinstalls (your backups live in %APPDATA%\VoiceAttack\HCS VoicePacks). |
| HCS HUB (2025) | New official launcher replacing the HCS Tools workflow: syncs purchases, installs/updates packs and Singularity, delta "Smart Updates", file verification. Download · setup video. |

## 12Gotchas — why commands "don't work"

- Wrong profile: Live Odyssey/Horizons needs `HCS - SINGULARITY (ELITE ODYSSEY)`; the plain `HCS - SINGULARITY (Elite)` profile is for Legacy Horizons. Switching between them can silently change which binds file is selected — recheck after switching.
- Keyboard binds only: a HOTAS-only binding is invisible to the pack. Every voice-controlled action needs a keyboard key bound in-game; Odyssey users must select the same bindings profile in all four control sections.
- Panel desync: clicked a panel with the mouse? Commands now open wrong tabs. Panels to default position, say `run diagnostics`.
- Pinned blueprints shift menus (Horizons remote workshop): untick "No pinned Blueprints" in the customiser if you pin any, or engineering navigation misfires.
- UI panel keys vs galaxy map: panel keys that clash with galaxy-map panning binds break map commands.
- Updates overwrite the profile: customisations survive only via the Voice Trigger Editor (custom template) and included profiles — both are re-linked, not lost, but direct profile edits are gone.
- Crew roster errors: "You must issue crew command roster before changing roles" — say `crew command roster` first; the `crewman` prefix before names is mandatory.
- Ship's Cat silent: it must be fed once (`feed the cat`) and let in (`letting the cat in`).
- Slow PCs: if a menu won't open, increase key-hold times in customiser → Keyboard Control.

## 13Resources

- Local docs on this PC — `C:\Program Files\VoiceAttack\Sounds\HCS TOOLS\Documentation\` (the 76-page Singularity manual v9.0 lives in `Launcher\Singularity manual.pdf`) and printable quick lists in `HCS TOOLS\.Voice command lists\Elite Dangerous Voice Commands\`.
- HCS Elite Dangerous manual page · store catalogue
- HCS support forum (crew-command docs, update guides) · Discord via the store footer
- HCS YouTube channel — install and setup playlists
- VoiceAttack (you're on 2.1.8)

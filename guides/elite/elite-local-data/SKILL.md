---
name: elite-local-data
description: Read the local Elite Dangerous data that the user's own tools have already collected — EDMC-BioScan's exobiology SQLite database, SrvSurvey's per-body JSON, EDDiscovery's commander database, and the raw Frontier journal files. Use whenever the user asks about THEIR OWN history — which species they have already scanned, which codex entries they are missing, where they have been, what they earned, or which bodies they have partially sampled. Trigger on "what have I scanned", "my exobiology history", "codex gaps", "have I been here", BioScan, SrvSurvey, EDDiscovery, journal files, or any question about personal progress rather than galaxy data.
---

# Local Elite Dangerous data

The remote APIs know about the galaxy. Only local data knows about **you** — what you've scanned, where you've been, what you're missing. For personal-history questions this is the right source, and it needs no network at all.

## Windows path warning — read before trusting any read

Several of these tools ship as MSIX/Store packages. Under MSIX, `%APPDATA%` writes are redirected into a per-package sandbox, so a path that looks right can return stale or empty data while the real file lives elsewhere.

SrvSurvey's Store install redirects to:

```
%LOCALAPPDATA%\Packages\35333NosmohtSoftware...\LocalCache\Roaming\SrvSurvey\
```

**Verify which path actually holds current data before drawing conclusions** — check modification times on both candidate locations, and prefer verifying through WSL where the virtualization layer doesn't apply. Reporting "you have no scans" because you read a shadow copy is a bad failure, and a silent one.

## EDMC-BioScan — the best local exobiology source

Repo: https://github.com/Silarn/EDMC-BioScan (last commit 2026-07-11) — the most actively maintained exobiology tool in the ecosystem.

Database (via its ExploData component):

```
%LOCALAPPDATA%\EDMarketConnector\explodata.db
```

SQLite, per-commander, with a bulk importer for historical journals — so it can be backfilled with your entire play history rather than only data since install.

```bash
sqlite3 "$LOCALAPPDATA/EDMarketConnector/explodata.db" ".tables"
sqlite3 "$LOCALAPPDATA/EDMarketConnector/explodata.db" ".schema"
```

**Open it read-only.** Use `file:...?mode=ro` or copy the file first. BioScan may be running and holding it, and a write from an outside process risks corrupting the user's scan history.

```bash
sqlite3 "file:$LOCALAPPDATA/EDMarketConnector/explodata.db?mode=ro" "SELECT ..."
```

What it holds: per-body flora with scan progress (the `FloraScans.count` field runs 0–3), waypoints with coordinates, per-commander scan state, and codex-found marks.

That `count` field is also the ground truth on the sampling rule — BioScan zeroes every other incomplete species' count when you start a new one, mirroring the in-game discard. See `elite-exobiology`.

**Its source files are a reference dataset in their own right.** `src/bio_scan/bio_data/rulesets/*.py` carries per-species values and spawn conditions; `EDMC-ExploData`'s `src/ExploData/explo_data/bio_data/genus.py` carries per-genus sample distances. These are more current and more machine-readable than any wiki — though see the known `Concha Biconcavis` sentinel bug documented in `elite-exobiology/references/species-values.md`.

## SrvSurvey — easiest format to read

Repo: https://github.com/njthomson/SrvSurvey (last commit 2026-07-31) — fastest-moving tool in the ecosystem.

Plain JSON, one file per system/body:

```
%APPDATA%\SrvSurvey\SrvSurvey\1.1.0.0\
```

(Store install redirects — see the MSIX warning above.)

No database driver, no schema archaeology — just read the JSON. It tracks predicted species per body, every sample taken with exact remaining distance, exobiology rewards, Guardian ruins survey data, and Ram Tah progress.

## EDDiscovery — richest history, heaviest schema

Repo: https://github.com/EDDiscovery/EDDiscovery (last commit 2026-07-01, release 19.1.9)

```
%LOCALAPPDATA%\EDDiscovery\EDDUser.sqlite     # commander history
%LOCALAPPDATA%\EDDiscovery\EDDSystem.sqlite   # system data cache
```

The most complete historical ledger available locally, but the schema is large and changes between major versions. Inspect it rather than assuming a layout, and open read-only. It records organic scans but does not predict species.

## Raw journal files

```
%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous\
```

Newline-delimited JSON, one file per session, plus `Status.json` for live state. This is the source everything else is built from — reach for it when a tool's database doesn't have what you need, or to verify a tool is reporting correctly.

Events relevant to exobiology:

| Event | Meaning |
|---|---|
| `ScanOrganic` | A sample. `ScanType` is `Log` (1/3), `Sample` (2/3), `Analyse` (3/3). Carries `Genus`, `Species`, `Body` |
| `SellOrganicData` | Vista Genomics turn-in with credit values |
| `SAASignalsFound` | DSS results — biological signal counts per body |
| `FSSBodySignals` | Signal counts from the FSS |
| `CodexEntry` | Codex discovery, with lat/long |
| `Touchdown` / `Disembark` | First footfall context |

Frontier added `WasFootfalled` and `WasLogged` fields around December 2025. **`WasLogged` is buggy** — it only updates after the first bio scan *and* opening the system map ([issue 81891](https://issues.frontierstore.net/issue-detail/81891)). Don't treat it as authoritative for "has anyone logged this". Also note that populated systems don't record first-footfall data at all, so the field is meaningless in the Bubble.

## Other tools worth knowing

**EDMC** (https://github.com/EDCD/EDMarketConnector, 2026-07-26) — the hub. Holds the cAPI session and relays to every service. `EDMC.py` is a headless JSON-to-stdout CLI, the cleanest programmatic entry point for commander data. See `elite-frontier-capi`.

**Elite Observatory + Botanist** (https://github.com/Xjph/ObservatoryCore, 2026-05-20) — Botanist tracks 3-sample progress and required distances in-game. A tracker, not a predictor; BioInsights is the third-party plugin that adds prediction.

**EDCoPilot** (v1.11.741, 2026-08-02) — voice companion with real exobiology support: Canonn integration, orbital guidance to the nearest sample, first-footfall detection, and spoken "far enough for the next sample" cues. No public API or export — it's a good *sink* for generated chatter files, a poor *source* of data.

**EDMC-Canonn** (2026-07-26) — the ingest side of the Canonn API. See `elite-canonn`.

**BGS-Tally** (https://github.com/aussig/BGS-Tally, 2026-07-26) — personal BGS/Colonisation/Powerplay activity tracking.

### Abandoned — don't build on these

- **SpanshRouter** — last commit 2021-03-09. Replacement: EDOCSpanshPlotter (Observatory plugin, 2026-05-16).
- **EDEngineer** — last commit 2024-03-22. It exposes a tempting local HTTP JSON API on `localhost:44405`, but its blueprint and material data predates everything Frontier shipped since early 2024. Verify anything it tells you.

## Privacy

This is the user's personal play history. Read it to answer their questions; don't upload it anywhere, and don't include commander identifiers in anything sent to an external service.

---
name: elite-inara
description: Query the Inara API for commander profiles and recent community goals, and understand its write-event surface. Use when the user asks about an Elite Dangerous commander's public Inara profile, wants current community goals, or is building an integration that reports commander state to Inara. Trigger on Inara, "commander profile", "community goals", "CG", or questions about syncing commander data to Inara. Note the API is mostly write-oriented and needs a registered key.
---

# Inara API

Inara is the community commander/squadron/market hub. Its API is live, but the read surface is far smaller than the website suggests — plan around that.

Endpoint: `https://inara.cz/inapi/v1/` — **POST only, one URL, batched events.**

## Auth setup

Generate a key in your Inara account under **Settings → API**, then export it:

```bash
export INARA_API_KEY="..."
export INARA_COMMANDER_NAME="..."
```

Read from the environment; never inline the key into a file or a command echoed back to the user.

A key alone may not be sufficient. A bogus key returns:

```json
{"header":{"eventStatus":400,"eventStatusText":"This application has no access allowed."}}
```

That wording — *application* has no access — suggests app registration/approval is a separate step from key generation. If you see it with a key you believe is valid, the app likely needs registering rather than the key being wrong.

## Request envelope

```json
{"header": {"appName": "MyApp", "appVersion": "1.0",
            "isBeingDeveloped": true,
            "APIkey": "...", "commanderName": "...", "commanderFrontierID": "F123456"},
 "events": [{"eventName": "getCommanderProfile",
             "eventTimestamp": "2026-08-04T12:00:00Z",
             "eventData": {"searchName": "Braben"}}]}
```

Set `isBeingDeveloped: true` while testing — it suppresses global events so your experiments don't pollute community-visible data. Turn it off only when the integration is real.

Event timestamps must be **less than 30 days old** or the event is rejected.

## Status codes

Responses come back in the order sent, one per event:

| Code | Meaning |
|---|---|
| 200 | OK |
| 202 | Warning — multiple matches found |
| 204 | Soft error — no results |
| 400 | Error or auth failure |

## The read/write asymmetry

Roughly 60 events exist and **almost all are writes** — `setCommanderCredits`, `setCommanderShipLoadout`, `addCommanderTravelFSDJump`, `setCommanderRankPilot`, inventory/mission/combat setters, and so on.

Only two are usefully readable with a generic key:

```bash
# Commander profile
{"eventName": "getCommanderProfile", "eventData": {"searchName": "CMDR NAME"}}

# Recent community goals
{"eventName": "getCommunityGoalsRecent", "eventData": {}}
```

**Do not build write integrations here.** That is EDMC's job, it already does it correctly, and pushing malformed data to a live public commander profile is a real and visible harm that's tedious to undo. If the user wants their commander synced to Inara, the answer is "configure EDMC", not "let me write an uploader".

For anything Inara *displays* on its website — market data, engineer info, rankings, station listings — there is no read API. Use `elite-edsm`, `elite-edastro`, or `elite-spansh` instead.

## Rate limits

None published. Inara's guidance is qualitative: set reasonable timeouts, don't retry-spam every second, and send periodic data (like credits) hourly or on session events rather than continuously. Treat ~1 request/second as a ceiling.

## Honest assessment

This is a **marginal** skill. It's here for completeness and for the two read events, but for nearly every question a user actually asks — where to buy something, what's in a system, where the bio is — one of the other Elite skills answers it better and without auth. Reach for Inara when the question is specifically about a commander's public profile or current CGs.

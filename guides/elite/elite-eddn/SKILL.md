---
name: elite-eddn
description: Consume EDDN, the Elite Dangerous Data Network live firehose of player-uploaded journal, market, outfitting, and exploration events. Use when the user wants real-time galaxy data, wants to build a collector or local database of live game events, asks how market/system data propagates between tools, or wants to watch for specific events like codex entries or body signals as they happen. Trigger on EDDN, data network, live game data, firehose, real-time market data, or building a data collector.
---

# EDDN — Elite Dangerous Data Network

The community firehose. Every major tool (EDMC, EDDiscovery, EDDI) uploads player journal events here, and EDSM, Spansh, EDAstro and Canonn all ingest from it. When you wonder how a tool knows something, the answer is usually EDDN.

- Relay: `tcp://eddn.edcd.io:9500` (ZeroMQ SUB)
- Upload: `https://eddn.edcd.io:4430/upload/`
- Monitor: `https://eddn.edcd.io/`
- Repo/schemas: https://github.com/EDCD/EDDN (last commit 2026-07-12)

Verified live: 388 messages in 25 seconds, roughly **15.5 messages/second**.

## This is a daemon, not a request/response API

A skill is request/response; EDDN is an unbounded stream. Wrapping the socket directly in a skill does not work — there's no "answer" to return, and a single connect-and-read gives you an arbitrary 20-second slice of the galaxy.

**The right architecture:** run a long-lived collector that subscribes, filters for what you care about, and writes to SQLite. Then a skill queries that SQLite. That gives you real answers ("which bodies with Stratum signals were reported this week") instead of a random sample.

Only tap the socket directly to confirm the relay is alive or to sample what's flowing.

## Working consumer

Requires `pyzmq`.

```python
import zlib, json, zmq

ctx = zmq.Context()
sub = ctx.socket(zmq.SUB)
sub.setsockopt(zmq.SUBSCRIBE, b"")
sub.setsockopt(zmq.RCVTIMEO, 20000)   # ms; raises zmq.Again on timeout
sub.connect("tcp://eddn.edcd.io:9500")

while True:
    msg = json.loads(zlib.decompress(sub.recv()))   # every frame is zlib-compressed JSON
    schema = msg["$schemaRef"]
    event  = msg["message"].get("event")
    print(schema, event)
```

Always set a receive timeout. Without one, a relay hiccup hangs the process forever with no diagnostic.

## Wire format

Each frame decompresses to:

- `$schemaRef` — which schema this message conforms to
- `message` — the payload
- `header` — `softwareName`, `softwareVersion`, `uploaderID` (SHA256-anonymised), `gameversion`, `gamebuild`, `gatewayTimestamp`

`uploaderID` is anonymised by design. Don't attempt to de-anonymise it or correlate uploaders across messages to identify players.

## Live traffic mix

Measured over 25 seconds:

| Count | Schema |
|---|---|
| 224 | `journal/1` |
| 30 | `fsssignaldiscovered/1` |
| 26 | `commodity/3` |
| 20 | `navroute/1` |
| 19 | `fssdiscoveryscan/1` |
| 16 | `scanbarycentre/1` |
| 13 | `outfitting/2` |
| 12 | `dockinggranted/1` |
| 8 | `shipyard/2`, `fssbodysignals/1` |
| 7 | `fssallbodiesfound/1` |
| 2 | `navbeaconscan/1` |
| 1 | `codexentry/1`, `approachsettlement/1`, `dockingdenied/1` |

Also defined: `blackmarket/1`, `fcmaterials_capi/1`, `fcmaterials_journal/1`.

Full schemas: https://github.com/EDCD/EDDN/tree/main/schemas

**For exobiology**, the streams that matter are `fssbodysignals/1` (biological signal counts per body) and `codexentry/1` (confirmed organism discoveries). Note the rates — roughly 8 and 1 per 25 seconds. These are *sparse*. A collector needs to run for days to accumulate anything useful; a short sample will look empty and mislead you into thinking the stream is broken.

## Who feeds the network

From the same sample — useful for judging which tools matter:

| Messages | Uploader |
|---|---|
| 203 | EDMC (Windows) |
| 84 | EDDiscovery |
| 74 | EDO Materials Helper |
| 15 | EDDLite |
| 6 | EDDI |
| 4 | EDRobot |

EDMC dominates by a wide margin, which is why it's the hub of the ecosystem.

## Uploading

Only upload data your own game client actually produced, through the documented schemas. Don't relay, synthesise, or replay data — EDDN feeds every downstream service in this skill set, and bad data propagates everywhere and is hard to retract. In practice, if the user wants to contribute, the answer is "run EDMC", not "let me write an uploader".

## Related

- `elite-edsm`, `elite-edastro`, `elite-spansh`, `elite-canonn` — all downstream consumers; query them instead of reimplementing their ingest
- `elite-local-data` — for reading what your own tools have already collected locally

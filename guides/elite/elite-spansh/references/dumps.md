# Spansh bulk data dumps

Host: `https://downloads.spansh.co.uk/<filename>`

Rebuilt daily, roughly 05:00–07:00 UTC (`galaxy_stations` around 11:50 UTC). The directory listing returns 403 — you must request an exact filename. All files are gzip; older documentation referencing `.json.bz2` is stale.

## Files

| File | Approx size | Contents |
|---|---|---|
| `galaxy.json.gz` | 115 GB | Everything — every system, body, station |
| `galaxy_1month.json.gz` | 6.4 GB | Systems updated in the last month |
| `galaxy_7days.json.gz` | 3.0 GB | Last 7 days |
| `galaxy_1day.json.gz` | 980 MB | Last 24 hours |
| `galaxy_populated.json.gz` | 4.3 GB | Populated systems only |
| `galaxy_stations.json.gz` | 4.2 GB | Systems with stations |
| `systems.json.gz` | 6.2 GB | System-level only, no bodies |
| `systems_6months.json.gz` | 717 MB | |
| `systems_neutron.json.gz` | 177 MB | Neutron stars only |
| `systems_1month.json.gz` | 124 MB | |
| `systems_2weeks.json.gz` | 58 MB | |
| `systems_1week.json.gz` | 35 MB | |
| `systems_1day.json.gz` | 3.3 MB | |
| `factions.json.gz` | 16 MB | Minor factions |

Sizes verified 2026-08-04.

## When to use a dump instead of the API

The API is the right tool for interactive questions. Reach for a dump when the work is bulk or repeated — anything that would otherwise mean thousands of requests. Concretely:

- Building your own filtered index (e.g. every body with Stratum Tectonicas)
- Statistical questions ("what fraction of HMC worlds in this region have 4+ bio signals")
- Offline work, or anything you'll query many times

`systems_1week.json.gz` at 35 MB is small enough to pull and process casually; `galaxy.json.gz` at 115 GB is not something to download without deliberate intent — check with the user first.

## Format

Newline-delimited JSON inside the gzip, one record per line. Stream it rather than loading it:

```bash
curl -s https://downloads.spansh.co.uk/systems_1week.json.gz \
  | gunzip -c | head -1 | python3 -m json.tool
```

Schemas: https://github.com/spansh/elite_dangerous_schemas
(`schema.json` at the download root 404s — the GitHub repo is the source.)

## Checking freshness without downloading

```bash
curl -sI https://downloads.spansh.co.uk/systems_1day.json.gz | grep -i 'last-modified\|content-length'
```

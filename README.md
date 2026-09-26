# gtnh-eu-dash — EU-only wireless dashboard

OpenComputers (in game) → HTTPS POST → this service (Dokploy) → charts on your phone.
EU only: current total, EU/t over 5m/1h/24h, trend charts 5m→30d. No AE2, no items.

## How it flows

```
LSC controller --Adapter--> OC computer --Internet Card--> https://energy.<domain>/ingest
                                                              |
                                                     SQLite (exact digit strings,
                                                     Python ints = no 2^53 / Influx limits)
                                                              |
                                                     https://energy.<domain>/  (this UI)
```

## Deploy (Dokploy)

1. New app/service from this repo (compose). Set env: `TOKEN=<long random>` (generate: `python3 -c "import secrets;print(secrets.token_hex(32))"`), `RAW_DAYS=90`.
2. Attach domain `energy.<your-domain>` in Dokploy (Traefik handles TLS). Data persists in the `eu-data` volume.
3. Open the URL on your phone — you'll see "waiting for first sample" until step 5 runs.

Local test: `TOKEN=x PORT=8099 python3 server/app.py`, then
`curl -X POST localhost:8099/ingest -H "Authorization: Bearer x" -d '{"wireless_eu":"91820123456"}'`.

## In-game (OC computer you already have)

1. Second Adapter face on the LSC controller (keeps NIDAS's reader untouched), cabled to the same OC network — or reuse the same machine if its only `gt_*` neighbour is the LSC.
2. Copy `lua/eu_poster.lua` onto the computer, set `URL` (your `https://…/ingest`) and `TOKEN` (same as server).
3. Run `eu_poster`. It posts raw digit strings every 10s. If it prints `no digits at sensorInformation[23]`, dump indices (`for i,v in ipairs(lsc.getSensorInformation()) do print(i,v) end`) and adjust the index.

## API

- `POST /ingest` — `{"wireless_eu":"<digits>"}` + `Authorization: Bearer <TOKEN>` → `200 {"ok":true}`. Rejects non-digits (400), bad token (401), posts faster than 3s (429).
- `GET /api/current` — `{ts, eu, eut_5m, eut_1h, eut_24h}` (EU/t from exact int diffs).
- `GET /api/series?window=5m|1h|24h|7d|30d&points=N` — bucketed floats for charts.

## Notes

- EU numbers travel and store as **strings** end-to-end (Lua doubles and Influx ints both lose precision past 2^53 / get finicky — this sidesteps both).
- Gaps (MC offline, net down) render as gaps, never fake zeros. The header badge flips to **STALE · Xm ago** after 90s without a sample; the DB persists in the volume across restarts.
- Retention: raw 10s samples kept `RAW_DAYS` (default 90d, ~8.6k rows/day — SQLite doesn't care), hourly cleanup, no downsampling needed (chart buckets on read).

# Reviewer brief: open-rec v0.1.2

> **Status update:** a second-AI review of this brief led to further fixes, merged in PR #1 (bridge lease and fail-safe, single Home Assistant controller, strict forecast/baseload completeness, publication lock, exact event ownership, overlap-based metering, randomization test). All three CI jobs passed on that PR: unit + live VTN, Home Assistant 2026.2 runtime, and the compose smoke test with live data. For the current state and the **next** audit checklist, read [`review-fixes-handoff.md`](review-fixes-handoff.md); this brief describes the pre-review baseline.

You are reviewing **https://github.com/icarusrex/open-rec** (branch `main`). Be adversarial: find bugs, unsafe behaviour, wrong assumptions, and anything more complex than needed. Skip style nits. For each finding give the file and line, what's wrong, why it matters (critical / major / minor), and a concrete fix. Also state which claims below you checked and found true.

## Context

The owner is starting a small Portuguese collective self-consumption group (ACC, *autoconsumo coletivo*): his 2.7 kWp rooftop PV (inverter capped at 3 kW) shared with a few neighbours. He wants to steer flexible loads (first a 3 kW water heater) into solar-surplus windows using **OpenADR 3**, with a community-run VTN ([openleadr-rs](https://github.com/OpenLEADR/openleadr-rs) v0.2.7) instead of a utility's.

The constraints are: as simple as possible; home device logic stays in Home Assistant; open source, because it will later be donated to an energy-community operator. Neighbours join only after DGEG certification, so v0.1 runs on one home.

## What it does

1. **Service** (`open-rec run`) stores Home Assistant kWh counters every 15 min. Each afternoon (14:30 Lisbon) it builds the next market day's event:
    - **PV forecast:** Open-Meteo 15-min global tilted irradiance → kW, capped at the inverter limit.
    - **Baseload:** the 14-day median house load per quarter-hour, minus the steered load's own meter if configured.
    - **Window rule:** `SIMPLE=1` where forecast surplus ≥ threshold, dropping windows shorter than 2 quarters.
    - **Prices:** OMIE Portuguese day-ahead prices, carried as `PRICE` (informational).
    - It publishes one OpenADR event per market day (92/96/100 intervals of 15 min from 00:00 CET), replaces it if republished, and deletes open-rec events older than 7 days.
2. **VEN bridge** (`open-rec ven`) polls the VTN and switches one Home Assistant helper, `input_boolean.open_rec_surplus_window`. A Home Assistant package (`examples/homeassistant/open_rec.yaml`) turns it into water-heater boost logic.
3. **Experiment:** from `TEST_PLAN_START`, days are paired and one day per pair is randomly a steer day, the other a control day (all `SIMPLE=0`). `open-rec report` gives each market day's self-consumption ratio, the mean steer-minus-control difference over pairs, an exact two-sided sign test, and a PV-yield-band breakdown.

## Acceptance criteria and evidence

| # | Criterion | Evidence |
| --- | --- | --- |
| 1 | Runs via Docker Compose; one bootstrap command creates VTN credentials | CI job `compose-smoke` passed: builds the image, starts Postgres + VTN from `docker-compose.yml`, runs `open-rec bootstrap --apply` |
| 2 | Live data sources work | Same CI job runs `open-rec publish` for today's market day against **live OMIE and Open-Meteo** and asserts 92/96/100 prices and a complete forecast. Passed |
| 3 | End to end through OpenADR | `tests/test_integration_vtn.py` against a real VTN covers: publish → replace (one event left) → VEN self-registers → bridge switches Home Assistant (mocked) correctly across a window; control day all zero; pruning; bootstrap rerun updates scopes; bad secret rejected |
| 4 | Fails safe | No event or interval → flag 0 (`logic.current_flag`); missing forecast → zero windows, and the day isn't marked done so it retries (`tests/test_service.py`); VTN unreachable 3 polls → off (`tests/test_ven.py`); no direct device switching by default |
| 5 | Honest measurement | Paired design (`testplan.py`); report recovers a planted +10 pp effect on top of a seasonal drift (`tests/test_report.py`); sign test checked against exact binomial values |
| 6 | Simple | One Python package, 5 runtime dependencies (`httpx`, `pyomie`, `aiohttp`, `psycopg`, `argon2-cffi`), configuration only via environment variables |
| 7 | Tested and clean | 40 tests (35 unit + 5 live-VTN) pass locally and in CI; `ruff check` clean; the Home Assistant package passes `hass --script check_config` on HA 2026.2 |

## How to reproduce

```bash
pip install -e ".[dev]" ruff
ruff check src tests && pytest            # live tests skip without the env vars below
# live: run openleadr-rs v0.2.7 (internal OAuth) on :3000 with Postgres, then
export OPENREC_TEST_VTN_URL=http://localhost:3000
export OPENREC_TEST_VTN_DATABASE_URL=postgresql://openadr:openadr@localhost:5432/openadr
export OPENREC_TEST_DATABASE_URL=postgresql://openadr:openadr@localhost:5432/openrec_test
pytest
```

`.github/workflows/ci.yml` shows both setups exactly.

## Where to look

| File | What to scrutinise |
| --- | --- |
| `src/openrec/logic.py` | DST handling (`quarter_starts`); Lisbon slots vs Madrid market day; window rule; ISO-8601 durations; `current_flag` with overlapping events |
| `src/openrec/service.py` | `publish_day` degrade/retry rules; `due_days` across the 23:00 Lisbon / 00:00 CET rollover; baseload subtraction |
| `src/openrec/ven.py` | Fail-safe and reassert behaviour; anything that could leave the flag **on** wrongly |
| `src/openrec/report.py` | `interval_energy` (gaps, resets, same-quarter snapshots); market-day grouping; paired comparison; sign test |
| `src/openrec/vtn.py` | Token caching; pagination (openleadr-rs max `limit` 50); replace-by-name upsert; prune by name prefix |
| `src/openrec/bootstrap.py` | SQL seeding of VTN clients (argon2 hashes, least-privilege scopes); injection safety |
| `examples/homeassistant/open_rec.yaml` | Boost start/stop, hysteresis, sensor loss, HA restart, interplay with an existing thermostat automation |
| `docker-compose.yml`, `Dockerfile`, `.env.example` | Secrets handling, exposed ports, defaults |

## Design decisions (challenge these)

1. One event per market day, `SIMPLE` 0/1 plus `PRICE`: the simplest shape any VEN understands, versus per-device setpoints.
2. The bridge sets an `input_boolean`, never the device; safety and overrides stay in Home Assistant.
3. Missing data can only *remove* windows, never add them.
4. Paired randomised days instead of a baseline period, to cancel the seasonal trend.
5. The first VTN clients are created by SQL, because openleadr-rs's user API needs an existing `write_users` client. Scopes are least-privilege: service `read_all, write_programs, write_events`; VEN `read_targets, read_ven_objects, write_vens_ven`.
6. Events are identified by name prefix `open-rec YYYY-MM-DD` within the open-rec program. Republishing PUTs the existing event; events older than 7 days are deleted.
7. Negative-price windows are off by default: on the owner's fixed bi-horário tariff, grid power at negative wholesale prices isn't free.
8. Apache-2.0 licence, matching openleadr-rs.

## Fixed during self-review (verify the fixes)

- **List calls stopped at 50 items:** they now paginate (openleadr-rs caps `limit` at 50).
- **Publish timing at the market-day rollover:** the next market day was due after 23:00 Lisbon, before OMIE had cleared it. It now becomes due at the publish time on the current market day's date.
- **A day without a forecast was marked published:** that turned a steer day into a de facto control day and biased the experiment. It's now an all-zero placeholder, retried every 15 min.
- **Report grouped by Lisbon day while events use the CET market day:** both now use the market day.
- **Two meter snapshots in one quarter lost energy:** that energy now counts.
- **Over-broad VTN scopes:** cut to least privilege, and a bootstrap rerun now updates scopes.

## Known limitations (accepted; flag if you think any is worse than stated)

- **E-Redes data import is not built.** E-Redes sends daily `sgl_v2` files over sFTP. The EGAC document lists the record types (`00`, `01`, `04`, `20`, `99`) but not the delimiter, byte layout or service-code meanings, so the parser waits for a real file.
- **Home Assistant package runtime is untested.** It passes `check_config`, but boost start/stop hasn't run in a live Home Assistant. Entity names are placeholders.
- **Load size vs surplus:** a 3 kW on/off element on a ~3 kW-capped array will often import some grid energy during a window. This is measured honestly, not optimised; a proportional diverter would fit better.
- **The VEN polls** every 30 s. It doesn't use MQTT or subscriptions, and it sends no OpenADR reports; measurement comes from Home Assistant counters.
- **Without `HA_STEERED_ENERGY_ENTITY`,** past steering can inflate the midday baseload and shrink future windows.
- **Single community and single program,** with no multi-tenant support, statements or sharing-coefficient engine yet.
- **Open-Meteo radiation is assumed to be a mean over the preceding 15 min.** If it is instantaneous, windows shift by up to 15 min.

## Specific questions

1. Is there any path where a failure or race turns a window **on**, or leaves it on?
2. Is `due_days` correct on DST-change days and across the 23:00–24:00 Lisbon hour?
3. Can `upsert_event` or `prune_events` delete or overwrite the wrong event?
4. Is the sign test plus mean paired difference sound for 20–40 pairs, or is a bootstrap CI or permutation test needed?
5. Is anything here more complex than the "as simple as possible" brief justifies?

# Audit notes for a second reviewer

These notes let a reviewer check open-rec v0.1 without the conversation that produced it. Please verify the claims below, rerun the commands, and challenge the design decisions and limitations. Report anything that is wrong, unsafe, or more complex than it needs to be.

## What this is for

The software side of a one-home pilot for a Portuguese collective self-consumption group (ACC). It runs a community OpenADR 3 VTN (openleadr-rs) that steers home loads into solar-surplus windows, and it measures the effect honestly. Constraints from the owner: keep it as simple as possible, keep home energy management in Home Assistant, and keep it open source, because it will later be donated to an operator.

## Acceptance criteria (defined before building)

| # | Criterion | Evidence to check |
| --- | --- | --- |
| 1 | Runs: Postgres + VTN + service via compose; one bootstrap command creates credentials | `docker-compose.yml`, `open-rec bootstrap`; compose validated with `docker compose config`; VTN tested from a source build of openleadr-rs **v0.2.7** (commit f586cc3), the tag the compose file pins |
| 2 | End to end: OMIE + PV forecast → one OpenADR event of 15-min intervals (PRICE + SIMPLE) → VTN → VEN bridge → Home Assistant | `tests/test_integration_vtn.py::test_publish_then_ven_follows` (live VTN and Postgres, Home Assistant mocked) |
| 3 | Measures honestly: paired steer/control days; report compares within pairs and by PV-yield band | `testplan.py`, `report.py`, `tests/test_testplan.py`, `tests/test_report.py::test_compare_recovers_known_effect_despite_seasonal_trend` |
| 4 | Simple: one Python package, 5 runtime dependencies, no ERP, config in `.env`, device logic in Home Assistant | `pyproject.toml`, `config.py`, `ven.py` docstring |
| 5 | Fails safe: no event, no forecast, or VTN down means the window is off; no secrets committed; no direct device switching by default | `logic.current_flag`, `logic.surplus_flags`, `tests/test_ven.py::test_bridge_holds_through_brief_outage_then_fails_safe`, `.gitignore`, `bootstrap.py` |
| 6 | Tested: unit and live-integration tests pass; lint clean | 34 tests pass (31 unit + 3 live); `ruff check` clean; CI (`.github/workflows/ci.yml`) runs all of them against the pinned VTN image on every push |
| 7 | Documented in the format of the reference repo (openleadr-rs: what it is, how it works, getting started, configuration, testing, roadmap, licence; `.env` + compose pattern) | `README.md`, `.env.example` |

## How to reproduce

```bash
pip install -e ".[dev]"
pytest                      # unit tests; live tests skip without the env vars below
ruff check src tests

# Live VTN tests: run openleadr-rs v0.2.7 with internal OAuth against Postgres, then
export OPENREC_TEST_VTN_URL=http://localhost:3000
export OPENREC_TEST_VTN_DATABASE_URL=postgresql://openadr@localhost:5432/openadr
export OPENREC_TEST_DATABASE_URL=postgresql://openadr@localhost:5432/openrec_test
pytest tests/test_integration_vtn.py
```

## File map

| File | Role |
| --- | --- |
| `src/openrec/logic.py` | Pure logic: market-day quarters (DST-aware), baseload profile, surplus flags, event body, reading the current flag |
| `src/openrec/testplan.py` | Paired steer/control day assignment (deterministic from a seed) |
| `src/openrec/report.py` | 15-min energy from counters, daily self-consumption, paired comparison |
| `src/openrec/service.py` | Publishes a day's event; collects readings; the run loop |
| `src/openrec/ven.py` | VEN bridge: VTN → one Home Assistant helper, with fail-safe |
| `src/openrec/vtn.py` | Minimal OpenADR 3 client (token, programs, events upsert, VEN self-registration) |
| `src/openrec/bootstrap.py` | SQL that creates the business-logic and VEN clients in the VTN database (argon2 hashes) |
| `src/openrec/sources/` | OMIE (via pyomie), Open-Meteo PV forecast, Home Assistant REST |
| `src/openrec/db.py` | open-rec's own tables, in a database separate from the VTN's |
| `examples/homeassistant/open_rec.yaml` | Home Assistant package: the window helper and water-heater boost automations |
| `.github/workflows/ci.yml` | CI: lint, unit tests, live VTN tests (openleadr-rs v0.2.7 container) |

## Design decisions to challenge

1. **One event per market day, 15-min intervals, SIMPLE 0/1 plus PRICE.** This is the simplest OpenADR shape a generic VEN understands. The alternative, DISPATCH_SETPOINT per device, is more precise but needs per-device modelling.
2. **The bridge sets an `input_boolean`, not the device.** This keeps safety (thermostat, cut-out) and household overrides in Home Assistant. The cost is that the owner must write one Home Assistant automation.
3. **Surplus = min(forecast PV, inverter cap) − 14-day median house load per quarter-hour ≥ threshold.** It's simple and explainable. Missing forecast counts as zero surplus, so failure never opens a window.
4. **Paired randomised test days, not a baseline period.** This cancels the seasonal trend that a Feb-baseline / Mar–Apr-steering design would confound. The test plants a known effect on top of a drifting trend and recovers it within 0.5 pp.
5. **The first VTN client is created with SQL.** openleadr-rs's user API needs an existing client with `write_users`, so there is no way to create the first one through the API.
6. **Event replace-by-day.** The name prefix `open-rec YYYY-MM-DD` identifies a day, and republishing PUTs the existing event. This was verified live: one event remains after two publishes.

## Known limitations and unverified items

- **Live OMIE and Open-Meteo were not reachable from the build sandbox** (egress blocked). Parsing and mapping are tested with fixtures only. On the first real run, verify that:
    - `pyomie` returns 92/96/100 Portuguese quarter prices for the market day; `map_quarters` raises otherwise.
    - Open-Meteo `minutely_15=global_tilted_irradiance` with `tilt`/`azimuth` (0 = south) works for this location. The code assumes values are means over the *preceding* 15 minutes.
- **Docker images were not built or pulled here** (registry blocked). The VTN binary was compiled from the v0.2.7 source and run directly. The `Dockerfile` and the compose `service` have not been built.
- **Baseload and the steered load (fixed in v0.1.1).** Setting `HA_STEERED_ENERGY_ENTITY` subtracts the steered load's own meter from house load before taking the median (`tests/test_service.py`). Without that sensor, the old behaviour remains: past steering can inflate the midday baseload.
- **Load size vs surplus.** The 2.7 kWp array, capped at 3 kW, rarely produces more than the 3 kW element draws, so a window can still import some grid energy. The report measures this honestly, since the ratio uses actual 15-minute flows. A proportional (PWM) diverter would match load to surplus better.
- **The VEN polls** every 30 s. It doesn't use subscriptions or MQTT, and it sends no OpenADR reports back; measurement comes from Home Assistant counters instead.
- **No E-Redes import, statements, or coefficient engine yet.** E-Redes delivers daily `sgl_v2` files over sFTP. Its EGAC document lists the record types (`00`, `01`, `04`, `20`, `99`) and fields, but not the delimiter, byte layout or service-code meanings. The parser is deliberately deferred until a real file exists, rather than guessed.
- **Home Assistant package:** it passes `hass --script check_config` on Home Assistant 2026.2, and an injected typo is rejected, so the check is meaningful. Its runtime behaviour (boost start, stop, hysteresis, restart) has not been exercised in a running Home Assistant.
- **CI workflow is unverified until its first run** on GitHub (it pulls `ghcr.io/openleadr/openleadr-rs:v0.2.7`, which this sandbox couldn't).
- **Licence is Apache-2.0** to match openleadr-rs. The owner may prefer AGPL-3 if he later builds on the Som Comunitats Odoo modules.

## Questions for the reviewer

1. Is any interval-alignment bug possible around DST changes (market day in CET vs Lisbon local slots)?
2. Does `current_flag` choose correctly when an old and a replaced event overlap?
3. The report now adds an exact two-sided sign test over pairs (`report.sign_test_p`, tested against known binomial values). Is that enough for ~20–40 pairs, or is a bootstrap CI on the mean difference also needed?
4. Is there any path where a failure turns a window *on*?
5. Is anything here more complex than the owner's "as simple as possible" constraint justifies?

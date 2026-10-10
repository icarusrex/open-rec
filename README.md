# open-rec

[![CI](https://github.com/icarusrex/open-rec/actions/workflows/ci.yml/badge.svg)](https://github.com/icarusrex/open-rec/actions/workflows/ci.yml)

Open-source tools to run a small Portuguese energy community (*autoconsumo coletivo*) and steer its homes with an **OpenADR 3** VTN.

open-rec turns tomorrow's solar surplus forecast and OMIE day-ahead prices into one OpenADR event of 15-minute intervals, publishes it to an [openleadr-rs](https://github.com/OpenLEADR/openleadr-rs) VTN, and lets each home follow it through Home Assistant. It also estimates the change in quarter-hour PV/load matching using paired steer/control days.

Status: **v0.1, prototype.** It runs on one home first. Neighbours join once the community is certified by DGEG.

## How it works

```
OMIE prices ─┐
Open-Meteo PV forecast ─┼─► open-rec service ──OpenADR 3──► openleadr-rs VTN ◄──OpenADR 3── VEN bridge ──► Home Assistant
HA energy counters ─┘      (business logic)                                             (per home)      input_boolean
```

- **Service** (`open-rec run`): every 15 minutes it stores the PV and house energy counters from Home Assistant. Each afternoon it publishes tomorrow's event.
- **Event**: 92–100 intervals of 15 minutes, aligned to the OMIE market day (00:00 CET, which is 23:00 in Lisbon). Tomorrow's event is published after the local publish time on the current market day, once OMIE has cleared it. Events older than 7 days are pruned from the VTN. Each interval carries `PRICE` (EUR/kWh, informational) and `SIMPLE` (1 = surplus window, 0 = normal).
- **Surplus window**: forecast PV (capped at the inverter limit) minus the median house load for that quarter-hour over the last 14 days is at least `SURPLUS_THRESHOLD_KW`. Optionally (`NEGATIVE_PRICE_WINDOWS`, off by default) any quarter with a price at or below zero also counts; that's only useful on a wholesale-indexed tariff. Windows shorter than `MIN_WINDOW_QUARTERS` are dropped.
- **VEN bridge** (`open-rec ven`): polls the VTN, switches `input_boolean.open_rec_surplus_window`, and renews the two-minute `timer.open_rec_bridge_lease` while permission is valid. Your Home Assistant automations decide what each device does with it, so thermostats, safety cut-outs and manual overrides stay in Home Assistant.
- **Fail safe**: no event or three consecutive failed polls turn permission off. HA also stops an owned boost when the bridge lease expires, including after the bridge exits. Missing or invalid forecast quarters and unobserved configured baseload slots cannot open windows; cached forecasts are never used as a freshness fallback. Incomplete forecast/baseload publications are retried every 15 minutes, including after an earlier complete publication. Selecting no house meter explicitly uses the configured constant baseload.

### Measuring the effect

Comparing a winter baseline with spring steering would mostly measure the season. Instead, from `TEST_PLAN_START` days are grouped in consecutive pairs, and one day of each pair is randomly (and reproducibly) a **steer** day while the other is a **control** day. On control days the event is still published, with every `SIMPLE` value at 0.

`open-rec report` prints each completed market day's PV, consumption, matched energy, ratio and observation coverage. Matched energy is the sum of `min(PV, consumption)` per quarter; it is an estimate and can exceed physical self-consumption within a quarter. Counter deltas are allocated by elapsed overlap assuming uniform power; gaps longer than 16 minutes, resets and invalid readings are excluded. Coverage uses the actual 92/96/100-quarter market day.

The paired report includes the mean steer-minus-control difference, an exact two-sided sign test (how often steering wins), a sign-flip randomization test for the mean, and PV-yield bands. The mean test enumerates up to 16 pairs and uses 20,000 reproducible draws beyond that. Random assignment reduces systematic seasonal confounding; it does not eliminate weather noise or a heated tank's carryover into the following control day. Freeze `TEST_PLAN_START` and `TEST_PLAN_SEED` before collecting results.

## Getting started

Requirements: Docker with Compose, and Home Assistant with long-lived token access.

```bash
cp .env.example .env
# set PG_PASSWORD, OAUTH_BASE64_SECRET (openssl rand -base64 32), site and HA values
docker compose up -d db vtn

# create the VTN clients for the service and the VEN bridge (prints generated secrets)
docker compose run --rm service open-rec bootstrap --apply \
  --vtn-database-url postgresql://openadr:<PG_PASSWORD>@db:5432/openadr
# copy the printed VTN_BL_CLIENT_SECRET and VEN_CLIENT_SECRET into .env

docker compose up -d service
docker compose run --rm service open-rec publish   # publish tomorrow now instead of waiting
docker compose --profile ven up -d ven
```

### Home Assistant

Copy [`examples/homeassistant/open_rec.yaml`](examples/homeassistant/open_rec.yaml) into your Home Assistant `packages/` folder and replace the two placeholder entities (`switch.water_heater`, `sensor.water_heater_temperature`). The package creates the surplus helper, an ownership helper, a two-minute bridge lease and one queued controller:

- **Window on with a live lease:** heat the tank up to a boost limit (default 65 °C, adjustable), with 2 °C hysteresis. Manual OFF during an owned boost stays off.
- **Window off, lease expired, tank at the limit, sensor unavailable, or HA restart:** switch off only what open-rec owns. Keep ownership until the relay confirms OFF and retry failed OFF commands every 30 seconds.

Your normal water-heater automation should skip while `input_boolean.open_rec_heater_boost` is on, and should also trigger when it turns off, so it takes over again straight away. The element's own thermostat and cut-out stay the hardware limit. CI runs the controller against HA 2026.2 with mocked actuator services. Real relay behavior and interaction with your existing thermostat still need a live audit. When upgrading, replace the old package and reload automations/helpers or restart HA; the bridge and package must be deployed together.

### Commands

| Command | What it does |
| --- | --- |
| `open-rec bootstrap [--apply]` | Create the VTN clients (prints SQL unless `--apply`) |
| `open-rec publish [--day YYYY-MM-DD]` | Build and publish one day's event (default: tomorrow) |
| `open-rec collect` | Store one snapshot of the Home Assistant energy counters |
| `open-rec plan [--days N]` | Show which days are steer or control |
| `open-rec report` | Steer vs control self-consumption report |
| `open-rec run` | Run the service loop |
| `open-rec ven` | Run the VEN bridge for one home |

## Configuration

All settings come from environment variables. See [`.env.example`](.env.example) for the full list with defaults. The ones that matter most:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PV_KWP`, `PV_TILT`, `PV_AZIMUTH` | 2.7, 30, 0 | Array size and orientation (azimuth 0 = south) |
| `PV_MAX_KW` | 3.0 | Inverter output cap |
| `SURPLUS_THRESHOLD_KW` | 1.0 | Minimum forecast surplus to open a window |
| `HA_PV_ENERGY_ENTITY`, `HA_HOUSE_ENERGY_ENTITY` | – | Cumulative kWh sensors for PV and whole-house consumption |
| `HA_STEERED_ENERGY_ENTITY` | – | Optional kWh sensor of the steered load, subtracted from the baseload so steering doesn't shrink future windows |
| `HA_LEASE_ENTITY` | `timer.open_rec_bridge_lease` | HA timer renewed by successful ON polls; required by the supplied heater package |
| `TEST_PLAN_START` | empty | First day of the steer/control plan (empty = always steer) |

## Testing

```bash
pip install -e ".[dev]"
pytest
```

The integration test in `tests/test_integration_vtn.py` runs against a live VTN. Set `OPENREC_TEST_VTN_URL`, `OPENREC_TEST_VTN_DATABASE_URL` and `OPENREC_TEST_DATABASE_URL` to enable it; it is skipped otherwise. Concurrent publishers must share the same open-rec database and program name for the PostgreSQL advisory lock to serialize refreshes.

The HA runtime tests in `tests/ha` require Python 3.14, `homeassistant==2026.2.0`, `pytest` and `pytest-asyncio`. See [the developer handoff](docs/review-fixes-handoff.md) for changes and the next audit checklist.

## Roadmap

- [x] v0.1: one-home prototype: prices, forecast, readings, events, VEN bridge, paired test plan and report
- [ ] E-Redes data import: daily `sgl_v2` files over sFTP (one per installation, plus energy-for-sharing). The record types are documented (`00` header, `01` description, `04` service list, `20` detail per 15 min, `99` totals), but the byte layout and service codes need a real file, which arrives after certification
- [ ] Monthly per-member statements (donation model first)
- [ ] Sharing-coefficient engine with export in the E-Redes format
- [ ] Onboarding and paperwork assistant (internal regulation, member agreements, DGEG filing pack)
- [ ] Multi-community operation

## Built on

[openleadr-rs](https://github.com/OpenLEADR/openleadr-rs) (LF Energy), [pyomie](https://github.com/luuuis/pyomie), [Open-Meteo](https://open-meteo.com/) and [Home Assistant](https://www.home-assistant.io/).

## License

Apache License 2.0. See [LICENSE](LICENSE).

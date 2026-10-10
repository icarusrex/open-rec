# Developer handoff: review fixes

These changes repair the reviewed main commit `a62740938e4483b637b14e4e5d1da1192024d234`. Please perform a fresh adversarial audit of the resulting branch before deployment; previous CI evidence does not validate this diff.

## What changed

| Area | Repair | Regression evidence |
| --- | --- | --- |
| VEN failures | Count parse/evaluation failures before resetting the failure counter; clear permission before attempting registration and retry registration inside the loop. | `tests/test_ven.py` |
| Bridge death | Successful ON polls renew a two-minute HA lease; failed polls do not. HA refuses boost without an active lease. | VEN tests and actual HA timer expiry test |
| Heater race/stop failure | One queued controller owns start/stop. Acquire ownership before ON, recheck permission, restore ownership on restart, and retain it until OFF is confirmed. Retry OFF every 30 seconds; manual OFF is preserved. | Eight runtime tests in `tests/ha/test_controller.py`, actuator services mocked |
| Forecast freshness | Require every market-day forecast quarter for completion; omit null/nonfinite radiation, fetch the preceding UTC date, and never use archived forecasts to open windows. Missing quarters stay OFF. | Source/service/logic tests |
| Baseload loss | A configured but unobserved slot suppresses permission instead of guessing a small load. Only fully observed house quarters enter the profile; subtract a steered meter only where its quarter is fully observed. | Service tests |
| Retry state | Incomplete forecast or relevant baseload clears an earlier published marker and retries after 15 minutes. Control-day counts reflect the actual zero flags. | Complete-to-incomplete and baseload recovery tests |
| Publication races | Serialize the whole fetch/build/VTN replace cycle with a PostgreSQL advisory transaction lock keyed by program name. Update the retained event before removing duplicates. | New concurrent publish test against the live VTN, plus ordering unit test |
| Event ownership/pruning | Match only exact `open-rec YYYY-MM-DD steer/control` names with valid dates. Prune relative to the current market day, even when publishing a future day. | Source/service tests |
| Meter allocation | Split deltas by elapsed overlap across quarter boundaries, retain same-quarter energy, reject resets/invalid values and gaps over 16 minutes. Partial quarters cannot manufacture observed coverage. | Report tests |
| Report validity | Use actual DST quarter counts, exclude unfinished market days, require common observed quarters, and print daily metrics/coverage. Label the metric as quarter-hour matching. | Report/CLI tests |
| Statistical inference | Retain the exact sign test for win frequency; add a mean sign-flip randomization test (exact through 16 pairs, 20,000 fixed-seed draws beyond). | Mean-versus-sign regression |
| Continuous verification | Add HA 2026.2 runtime CI. Compose live-source smoke explicitly selects the constant baseload because it has no HA house meter. | `.github/workflows/ci.yml` |

## Upgrade and operating assumptions

Deploy the Python bridge and updated HA package together. Replace the two former heater automations with the new controller; reload configuration or restart HA. Keep the default timer entity or configure `HA_LEASE_ENTITY` to match it. The lease is two minutes; a poll period at or beyond that duration will cause intermittent permission expiry. Do not extend the lease without reassessing the loss-of-bridge shutdown time.

No database schema migration is required. Publishers must use the same open-rec database and program name; standalone `VtnClient` calls or publishers with different databases are not protected by this lock. The SQL transaction encloses external calls: if archival SQL fails, the transaction rolls back and publication retries rather than degrading. PostgreSQL and VTN cannot commit atomically; subsequent refresh reconciles an interrupted publish.

With a configured house meter, collect usable history for every potentially eligible daylight slot before expecting complete publication. If the meter is deliberately absent, the configured constant baseload is used. Missing steered-meter observations skip subtraction, conservatively increasing the baseline.

The report assumes uniform power between snapshots and reports quarter-hour PV/load matching, not physical exported/imported energy. Thermal carryover between adjacent paired days remains an experimental limitation. Freeze the plan seed/start date; select a carryover policy or a different randomization unit before making causal claims. A confidence interval may be useful, but an ordinary bootstrap does not repair carryover or missing-data selection.

## Please run a new audit

1. Run all three CI jobs on this branch. In particular, confirm the real openleadr-rs v0.2.7 concurrent-publish test and Compose bootstrap/live OMIE/Open-Meteo smoke; neither can run locally without Docker/PostgreSQL.
2. Challenge bridge startup with VTN down, malformed events for three consecutive polls, HA unavailable, process termination while ON, and recovery after lease expiry. Verify the heater stops even if the surplus helper remains ON.
3. In real HA with the actual relay, test failed/delayed OFF, permission revoked during ON, sensor loss, restart during boost, manual OFF, and normal-thermostat ownership handover. Runtime regressions mock the actuator, so they cannot establish hardware behavior.
4. Test two overlapping publishers, interruptions between VTN PUT and database commit, malformed/similar foreign event names, and publishing a far-future date. Verify current events survive and only strictly owned old events are pruned.
5. Check `due_days` and event/report quarter boundaries across both DST changes and Lisbon 23:00–24:00. No rollover rewrite was required; retain an adversarial check of this unchanged logic.
6. Simulate partial/stale forecasts, missing house and steered meters, long gaps, resets, and DST days. Confirm no unknown input creates a positive window and no gap manufactures report coverage.
7. Review the mean randomization test against independent exact values and assess selective missing days and thermal carryover before interpreting 20–40 pairs. Document that sign-test significance concerns win frequency, not mean effect size.

Local validation at handoff: 54 unit tests passed; six real-VTN tests and the optional HA module skipped in that environment. Separately, eight HA 2026.2 runtime tests passed on Python 3.14. Ruff passed. The next audit must add live VTN, live-source CI, and real hardware evidence.

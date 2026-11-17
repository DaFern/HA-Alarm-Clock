# HA-AlarmClock

A Home Assistant alarm-clock integration for satellite speakers and Echo devices.

The integration source is in `custom_components/household_alarms/`. See its
[README](custom_components/household_alarms/README.md) for setup, behavior, and
acceptance-testing notes.

Offline tests are in `tests/`:

```text
python3 -B tests/test_alarms.py
python3 -B tests/run_browser.py
node --check custom_components/household_alarms/frontend/household-alarms-card.js
```

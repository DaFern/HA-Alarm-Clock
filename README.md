# HA-AlarmClock

A Home Assistant alarm-clock integration for satellite speakers and Echo devices.

The integration source is in `custom_components/household_alarms/`. See its
[README](custom_components/household_alarms/README.md) for setup, behavior, and
acceptance-testing notes.

## Current candidate: 0.7.0b2

### Deployed follow-up: 0.7.0b2

The working tree now contains clearer song selection/search feedback and optional
Companion phone controls. These changes were **deployed and verified loaded**
on 2026-11-18. Phone controls remain off by default and separate from help-needed
messages. See the [integration README](custom_components/household_alarms/README.md)
for behavior, permissions and acceptance requirements. No MA patch update is
needed for this follow-up; it still uses protocol 2.

The project contains opt-in scheduled Music Assistant songs, per-alarm library
search/selection, separate background gain, and a 0–120-second voice delay.
The briefing is attempted once; Snooze restarts the same song without speech.
Existing schedules and speakers remain unchanged, with music off by default.

**This is not a published stable release.** The deployed 0.7.0b2 candidate now
also permits same-day rescheduling: after a run ends, saving a different future
time clears that completed run and its stale error. Unchanged saves and enable
toggles do not re-arm it; active alarms and unconfirmed music stops stay protected.
The user confirmed a successful Kitchen scheduled alarm with music and Jarvis
voice-over, notification Snooze with music-only resume, and Dismiss with notification
cleanup even when dismissed elsewhere. Music requires the pinned protocol-2 MA
companion; stock MA and the older DEV
protocol-1 patch are not compatible with the scheduled-music API.

- [Morning deployment handoff](docs/DEPLOYMENT_HANDOFF.md)
- [Pinned MA build, installation gates and rollback](packaging/music_assistant/README.md)
- [Upstream feature proposal](https://github.com/music-assistant/support/discussions/998#discussioncomment-19695063)

The separate MA image still needs building. DEV is now pinned to
`DaFern/server@7aab695417cea5d0fdf926620724cfd873ef1c22`. Song search and one
scheduled audible alarm cycle have passed user testing, not long-term reliability
acceptance. Screen wake/lock-screen visibility, Sleep in, deadline escalation,
takeover and restart recovery still need live checks. Earlier connection resets
remain unexplained; the rescheduling fix does not repair that separate failure.
Leave DEV and its data installed until the replacement is verified. The intermittent
Echo song/chapter restart remains unreproduced and unfixed; the timed music-volume
ramp and clearer sound labels remain deferred in issue #3.

Offline tests are in `tests/`:

```text
python3 -B -m unittest discover -s tests -p 'test_*.py' -q
python3 -B tests/run_browser.py
node --check custom_components/household_alarms/frontend/household-alarms-card.js
```

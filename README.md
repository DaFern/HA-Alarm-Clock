# HA-AlarmClock

A Home Assistant alarm-clock integration for satellite speakers and Echo devices.

The integration source is in `custom_components/household_alarms/`. See its
[README](custom_components/household_alarms/README.md) for setup, behavior, and
acceptance-testing notes.

## Current candidate: 0.7.0b1

The project contains opt-in scheduled Music Assistant songs, per-alarm library
search/selection, separate background gain, and a 0–120-second voice delay.
The briefing is attempted once; Snooze restarts the same song without speech.
Existing schedules and speakers remain unchanged, with music off by default.

**This is not a published stable release.** The 0.7.0b1 candidate was deployed
for verification on 2026-11-18, retaining DEV. The integration loaded and its
card rendered at phone/desktop widths; no saved alarms were enabled or changed
and no audio was played. Music
requires the pinned protocol-2 MA companion; stock MA and the older DEV
protocol-1 patch are not compatible with the scheduled-music API.

- [Morning deployment handoff](docs/DEPLOYMENT_HANDOFF.md)
- [Pinned MA build, installation gates and rollback](packaging/music_assistant/README.md)
- [Upstream feature proposal](https://github.com/music-assistant/support/discussions/998#discussioncomment-19695063)

The separate MA image still needs building. DEV is now pinned to
`DaFern/server@7aab695417cea5d0fdf926620724cfd873ef1c22`; card-driven protocol-2
song search and audible/scheduled acceptance remain pending. Leave DEV and
its data installed until the replacement is verified. The intermittent Echo
song/chapter restart remains unreproduced and unfixed.

Offline tests are in `tests/`:

```text
python3 -B -m unittest discover -s tests -p 'test_*.py' -q
python3 -B tests/run_browser.py
node --check custom_components/household_alarms/frontend/household-alarms-card.js
```

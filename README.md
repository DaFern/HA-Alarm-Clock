# HA-AlarmClock

A Home Assistant alarm-clock integration for satellite speakers and Echo devices.

The integration source is in `custom_components/household_alarms/`. See its
[README](custom_components/household_alarms/README.md) for setup, behavior, and
acceptance-testing notes.

## Music Assistant compatibility

Standard tone and spoken alarms use Home Assistant and can run without Music Assistant. If you use Music Assistant to expose a speaker to Home Assistant, that speaker still needs to be available as a compatible media player.

The current scheduled-song mode, including music-only alarms and voice over music, requires the project's patched Music Assistant server with protocol 2. Keep the Music option off on stock Music Assistant while upstream support is pending. The patched server is optional for users who want to test scheduled music now.

## Current candidate: 0.7.0b6 (source only)

### Issue #4 follow-up: next dates and preserved music queues

The card uses Home Assistant's timezone for **Next: Today / Tomorrow / dd/mm/yy**
labels and refreshes them across local midnight. Disabled alarms show
**Next: Not scheduled**.

Scheduled music and confirmed saved-alarm Tests now require companion protocol 2
with `restore_playback` (in addition to `preserve_queue`). The latest project-only
follow-up also requires `queue_mode_lease`. Each alarm segment
captures the currently playing queue item and position, then adds/starts its own
unique alarm item. Snooze and Dismiss remove only that alarm item and resume the
interrupted music if its item still exists. Stopped/paused queues stay stopped.
Every snooze wake-up captures current playback afresh, rather than restoring the
first ring's stale track later. User queue edits and same-song copies survive.
Playback takeover prevents stale stop/restore; a protected item currently being
used by the user is not deleted. A missing/deleted interrupted item is not recreated.

**Repeat morning message after snooze** defaults off, appears under Snooze only
for spoken modes, and applies to scheduled alarms and confirmed saved-alarm
Tests. When enabled, it regenerates the configured message once per intentional
snooze wake-up. Ordinary song loops and same-ring retries/restarts never repeat
speech. Restored music is user-owned: changing the sleep entity does not stop it.
The existing optional turn-sleep-switch-off-on-dismissal behavior is unchanged.
Scheduled alarms now lease the queue's Repeat and Autoplay settings: they are
temporarily suspended while the alarm owns playback and restored afterward if
they have not changed. This requires the new `queue_mode_lease` companion
capability; grouped speakers and ambient overlays remain unsupported.

**Deployment gate:** the `queue_mode_lease` follow-up is not yet built, published,
or deployed. The currently installed companion does not advertise it, so enabled
Repeat/Autoplay will continue to block alarm playback until the updated companion
and matching integration are deployed. Physical queue-state acceptance remains
separate from offline tests.

### Project-only follow-up: timed music-volume ramp (issue #3)

The working tree adds an opt-in ramp with separate percentage-point and elapsed
interval settings, capped at Maximum volume. It changes speaker volume without
restarting the song or replaying speech. Snooze resets the ramp; manual volume
changes pause it for that ring. Tone repeat timing is labelled separately and
existing alarms retain their behaviour unless the ramp is enabled.

**Not deployed or physically verified.** This needs the updated companion's
`volume_ramp` capability and ownership-checked volume command; the current pinned
DEV commit below does not provide it. HA and companion updates require separate
approval. Offline checks passed 282 Python tests and 100 browser checks at each
width (390 and 1280); the ramp controls were visually reviewed in the offline
fixture. These checks do not prove Echo volume reporting or audible ramp timing.

### Deployed follow-up: 0.7.0b2

The working tree now contains clearer song selection/search feedback and optional
Companion phone controls. These changes were **deployed and verified loaded**
on 2026-11-18. Phone controls remain off by default and separate from help-needed
messages. See the [integration README](custom_components/household_alarms/README.md)
for behavior, permissions and acceptance requirements. No MA patch update is
needed for this follow-up; it still uses protocol 2.

The project contains opt-in scheduled Music Assistant songs, per-alarm library
search/selection, separate background gain, and a 0–120-second voice delay.
By default the briefing is attempted once; the optional snooze-repeat setting
allows one new message on each snooze wake-up.
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
`DaFern/music-assistant-alarm-clock-server@7aab695417cea5d0fdf926620724cfd873ef1c22`. Song search and one
scheduled audible alarm cycle have passed user testing, not long-term reliability
acceptance. Screen wake/lock-screen visibility, Sleep in, deadline escalation,
takeover and restart recovery still need live checks. Earlier connection resets
remain unexplained; the rescheduling fix does not repair that separate failure.
Leave DEV and its data installed until the replacement is verified. The intermittent
Echo song/chapter restart remains unreproduced and unfixed. Issue #3's timed
music-volume ramp is prepared in the project only, as described above.

Offline tests are in `tests/`:

```text
python3 -B -m unittest discover -s tests -p 'test_*.py' -q
python3 -B tests/run_browser.py
node --check custom_components/household_alarms/frontend/household-alarms-card.js
```

# HA-AlarmClock 0.7.0b6 — source-only candidate

## Issue #4: next occurrence and queue behavior

Next occurrence dates use HA's configured timezone and local calendar dates,
including DST and year boundaries: **Next:** Today at 10:53, Tomorrow at 9:00,
or 23/11/26 at 9:00. Disabled alarms show Not scheduled.

Music alarms and the confirmed saved-alarm Test require companion protocol 2
with `preserve_queue` and `restore_playback`. Each ring segment captures the
currently playing queue-item ID and playback position, then starts its own
unique alarm item immediately. Snooze and Dismiss remove only that alarm item,
preserve the current user-edited queue and resume the interrupted item at its
saved position if still present. With no prior playing music, playback stays
stopped (including queues that were paused). No old queue snapshot is restored.
Every snooze wake-up is a fresh segment: its next Snooze/Dismiss restores the
music playing at that wake-up, not the first ring's music. User-added copies of
the same song are never identified or removed by URI.

A playback takeover invalidates stop/restore authority. Only a safe, noncurrent,
nonbuffered stale alarm item can be removed; an item reused by the user's active
playback is left alone. Repeated stop requests cannot stop already restored music,
and an uncertain restore is not retried blindly. No new playback is started after
MA loses its runtime ownership state.

**Repeat morning message after snooze** defaults off and is shown under Snooze
only while snooze and a spoken mode are enabled. It regenerates the configured
message once on each intentional snooze wake-up when enabled; ordinary loops,
same-ring retries and HA reload/restart do not rearm it. The same setting applies
to confirmed saved-alarm Tests and nonmusic spoken alarms.
Restored music is not controlled by the sleep entity. Optional turn-sleep-switch-
off-on-dismissal behavior is retained; users can add their own music automations.
Repeat, Autoplay, grouping and ambient overlays still block playback.
Failures appear beside the alarm under **Playback failed — details**.

The previous deployed companion does not implement `restore_playback`. Upgrade
the companion first; the integration rejects old companions rather than silently
using incompatible queue behavior. Physical queue-state acceptance remains pending.
The sections below include older deployed/test history.

## Song picker and optional lock-screen controls (phone acceptance pending)

This follow-up was deployed and verified loaded on 2026-11-18 after the approved
Core restart and a 65-second wait. All 20 runtime files matched the candidate;
configuration validation passed and the dashboard rendered at phone/desktop
widths. Saved settings remained unchanged, with zero enabled/active alarms.
No audio or notification-feature phone/screen-wake test was sent. Lock-screen
acceptance remains pending; the older 0.7.0b1 notes below record prior stages.

Search now shows loading, failures and empty results directly **above its search
box**, not only at the top of the card. Choosing a song shows a highlighted
selected-song summary and collapses the results. **Change song** reopens search
without discarding the existing selection until another song is chosen. Speaker
choices include entity IDs to distinguish native Alexa and MA entities sharing
the same friendly name. Enter in search searches rather than saving the form.

### Alarm controls on your phone

The optional per-alarm setting is **off by default**, independent of **Let someone
know**. Choose one `notify.mobile_app_*` Companion app recipient, not a notification
group. Normal saved-alarm sound/music tests do not create real-run phone controls.

When a scheduled alarm rings, the integration submits a high-priority,
lock-screen-visible notification with **Dismiss** and, when permitted, **Snooze**.
Snooze uses the saved minutes, maximum count and get-up deadline; it is absent
while already snoozing or at escalation/deadline. Snoozing updates the same tagged
notification; ending, sleeping in, missing or dismissing the alarm requests its
removal. Retried tone delivery does not repeatedly push or wake the screen.

The separately optional **Wake the phone screen** requests Android's documented
`command_screen_on`. It does not unlock the phone or change brightness, timeout,
DND, volume or security settings. The target must be identifiable as Android from
registered Companion metadata; an iOS/unknown target still gets controls but is
never sent an Android command. Renamed/ambiguous registrations may require a
manual check if automatic platform identification is unavailable.

**Permissions and limits:** allow Companion notifications and lock-screen
content for the dedicated **HA-AlarmClock controls** notification channel.
Android's channel importance/content settings override application requests;
enable Companion notification commands for screen wake. Screen wake and visibility
must be checked on the actual locked phone and cannot be guaranteed from a push
service response. Delivery and button actions need connectivity to Home Assistant;
high-priority/TTL-zero delivery is not a guaranteed offline alarm. Notification
sound/DND behavior remains controlled by the phone/channel settings.

Buttons intentionally do not require unlocking: **anyone holding the selected
phone can dismiss or snooze that alarm**. The notification exposes only the alarm
name/status, not the assistant briefing or calendar contents. Run/phase-scoped
random action capabilities are persisted before posting, rotated on state
transitions/republication, hidden from card snapshots, and checked atomically
with the normal alarm action. Stale, duplicate, wrong-occurrence and disallowed
snooze actions cannot affect a later run. These safeguards are not a substitute
for protecting the phone and HA event/API access.

Push/clear failure produces a bounded, sanitized warning and background retry;
it does not block speaker delivery or silently dismiss an alarm. Screen-wake
failure leaves submitted controls available without assuming the phone woke.
Clearing is best-effort; an old displayed notification may remain on an offline
phone, but stale actions are rejected after the run changes. A Core reload can
republish an active occurrence with fresh controls; it cannot receive actions
while offline.

Deployment/restart were approved and completed. On 2026-11-18 the user confirmed
notification Snooze, music-only resume, Dismiss, and removal of the notification
after dismissal through another route during a scheduled Kitchen alarm. This does
not establish locked-screen wake/visibility. Remaining physical-phone acceptance
includes two phones/occurrences where possible, locked-screen wake/visibility,
Snooze limits/deadline, stale buttons, offline delivery and restart behavior.
Automated tests use fakes, not a real phone or push gateway.

## Scheduled selected-song alarms (deployed candidate; acceptance pending)

### Timed volume increases (project-only follow-up; issue #3)

Under **More settings → Volume and repeats**, music alarms can opt into
**Gradually increase music volume**. **Increase by (percentage points)** is
1–25, **Increase every (seconds)** is 30–300, and the shared **Maximum volume (%)**
caps increases. For example, starting at 20%, adding 5 points every 30 seconds
with a 50% maximum requests 25%, 30%, 35% and so on, without restarting media or
replaying the message. Background music gain remains a separate mixing setting.

The ramp defaults off; existing alarm settings and legacy per-ring increases stay
unchanged. Tone alarms retain their repeat behaviour with explicit tone-specific
labels. With the ramp on, every resumed ring starts at Starting volume; Snooze
stops its timer; its wake-up starts a fresh timer and ring, with speech only if
the snooze-repeat option is enabled. Natural song loops
retain the current level. Deadline escalation still takes precedence at Maximum
volume. Dismiss, Sleep in and takeover cancel future increases through the normal
playback lifecycle. A manual volume change detected by MA suspends increases for
the ring, is preserved across natural song loops, and disables old-volume restoration
over that choice. Unavailable volume or uncertain writes also suspend increases;
the ramp does not restart media or blindly retry an uncertain volume write.

Timing uses a monotonic clock and the existing two-second playback poll: increases
may be late, never applied in a catch-up burst. A reattached run starts a fresh
interval at its current level; a persisted suspension stays suspended. An MA restart
that loses ownership does not create a replacement alarm. Manual-change detection
depends on the provider's reported volume and cannot detect changes it does not
report, or changes away and back between observations. Physical Echo testing is
still required; optimistic MA state is not proof of audible output or exact timing.

The saved-alarm Test uses the same ramp helper and explicitly confirms its settings,
without changing the saved schedule. The optional capability `volume_ramp` and
`player_queues/alarm_volume` endpoint are added to the project companion templates.
The currently deployed fork `7aab695...` lacks them: enabling the new ramp against
that fork fails before briefing generation/playback, rather than using unsafe generic
volume services. Ramp-off alarms remain compatible with the existing fork.
**Neither this follow-up nor the companion extension has been deployed/published.**
Offline validation passed 282 Python tests, 100 Chromium checks at both 390/1280px,
and targeted generated-companion Ruff/mypy checks; offline screenshots were reviewed.

Each alarm now has an opt-in **Music** section: select its MA speaker, search
that server's song library, choose a song, and save its background gain (1–30%)
and voice delay (0–120 seconds). Changing speaker clears the song selection:
library identifiers are bound to the HA MA connection and cannot be assumed to
match a different server, even if it reuses the same speaker entity id. Existing
alarms keep their schedules/speakers and default to music **off**.

Music replaces the tone. It plays under the selected named HA assistant's exact
voice/language, on the first ring and optionally on snooze wake-ups, and continues afterwards. Delay is music
playback time, not a sleep before starting the song. Message/TTS preparation
happens before playback. A short song can end before delayed speech finishes.
Missing assistant voices warn and leave music playing; tone-only legacy alarms
retain their existing fallback behavior.

Snooze removes only the alarm item, resumes interrupted music when available, and
uses the saved snooze minutes/deadline/limit. At wake-up a new alarm segment
captures current music and starts the selected alarm song from the beginning;
speech is controlled by the snooze-repeat option. Dismiss and Sleep in release
only the owned alarm segment and restore interrupted music. Their normal
sleep-switch behavior remains intact.
Music repeats at song end (two-second polling, not gapless), rather than at the
tone repeat interval. Hardware volume is selected at the start of each ring;
the deadline can interrupt and escalate it. The background gain stays separate.

Each permitted speech attempt (initial ring or opted-in snooze ordinal) and each music dispatch id are saved before generation
or playback. After an unclean restart, HA may reattach only to that exact owned
session, never blindly start a replacement. Uncertain starts/stops and external
takeover block further automatic playback for that run and surface an error.
An explicit dismissal can retry a guarded stop; otherwise check the speaker
manually. Successful clean shutdown releases the owned alarm segment and restores
interrupted music. It does not authorize replay of an already attempted message.

The old **Experimental music test** panel is removed. The normal saved alarm
**Test** button confirms speaker, song, volume, gain and delay, then offers
Snooze/Dismiss/Sleep in controls in a bounded 30-minute test. Tests never edit
saved schedules, run records or sleep switches. The saved alarm's snooze minutes
are used, not accelerated experimental seconds. Legacy protocol-1 test endpoints
remain for compatibility but are not the scheduled alarm API.

### Changing the time after today's alarm (deployed 2026-11-18)

After dismissing or finishing today's run, saving a **different time still in
the future today** permits another scheduled run. The save clears the previous
run and its stale error together; it does not start playback immediately.
Unchanged saves, enable/disable toggles, Snooze and Dismiss do not re-arm an alarm.
Moving the time into the past does not replay it. Active alarms must be dismissed
first, and pending cleanup or an unconfirmed music stop prevents re-arming until
the previous playback has been safely stopped. A failed save keeps the old run.

The user confirmed same-day rescheduling and a successful scheduled Kitchen run
with music and Jarvis voice-over, notification Snooze resuming music without a
second briefing, and Dismiss stopping playback and clearing the notification.
The rescheduling change does not fix the separately observed connection resets;
their cause and long-term playback reliability remain unresolved.

### Required companion and release boundary

Stock MA and the previously published protocol-1 fork are **not sufficient**.
Scheduled playback requires a protocol-2 companion. The temporary DEV route is
now pinned to `DaFern/music-assistant-alarm-clock-server@7aab695417cea5d0fdf926620724cfd873ef1c22`.
The separate local-app recipe is prepared under
[`packaging/music_assistant`](../../packaging/music_assistant/README.md).
It has a separate app identity/data directory and an exact upstream image digest,
with hash-guarded source patching at build time and no startup Git installation.
Disable Supervisor automatic updates when installing it; this cannot be enforced
by its manifest. The older deployment rejected busy/nonempty queues; current
scheduled-alarm templates preserve them as described above. Grouped queues,
Repeat, Autoplay and ambient overlay are still rejected rather than changed.

The user confirmed a full-song playthrough, simultaneous briefing, Dismiss and
Snooze on the earlier DEV prototype. **The intermittent Echo song/chapter restart
is not reproduced or fixed.** The 0.7.0b1 HA candidate was deployed and verified
loaded/rendering on 2026-11-18, retaining DEV and leaving saved alarms unchanged
and off. No audio was played. Card-driven protocol-2 song search and audible/
scheduled acceptance remain pending. The local-app image is unbuilt/uninstalled
and no stable release was published; see the repository's
[`morning handoff`](../../docs/DEPLOYMENT_HANDOFF.md) for the outstanding work.
Keep an independent alarm for essential wake-ups.

Upstream implementation evidence was submitted to the existing feature request:
https://github.com/music-assistant/support/discussions/998#discussioncomment-19695063

Checks: `python3 -B -m unittest discover -s tests -p 'test_*.py' -q` and
`python3 -B tests/run_browser.py`. Opt-in native FFmpeg tests are documented in
`prototypes/ma_one_shot/README.md`. These do not boot an authenticated MA server.

## Historical 0.6.0 prototype notes

The sections below record earlier development stages; their pending/deployed
labels describe those stages, not the 0.7.0b1 candidate above.

## Experimental MA music test — HA panel deployed, MA source setup pending

The card now has a collapsed **Experimental music test** panel, disabled until
explicitly enabled on this dashboard device. It is separate from alarm settings:
no music fields, schedules, persisted runs or sleep switches are changed. Choose
a saved alarm for its assistant/message settings and explicitly select the
development MA speaker. Check readiness without playing audio, then separately
confirm Start music test, naming the speaker and volume.

This requires the companion **patched MA 2.10.12 development build**, not the
ordinary MA app. The new `ma_audio.py` adapter resolves the speaker through HA's
entity registry and reuses the MA integration's already-authenticated client.
It never reads/copies tokens or accesses internal configuration files. The MA
capability check must explicitly match protocol 1; an unsupported build fails
before song selection, speech generation or queue changes.

The selected named HA assistant still supplies the conversation engine. Its TTS
entity is matched to exactly one registered MA engine on the local Supervisor HA
connection, with its exact language and optional voice passed through. Missing,
ambiguous, legacy non-entity or remote-HA voices are rejected, not replaced with
Piper or another default. Provider support for the chosen voice needs an audible
test. MA's existing HA TTS renderer/cache/URL handling is used; this does not add
a public personal-audio endpoint or change preview's separate cache-disabled API.

The initial test randomly selects one library song from the **development
server's own library**. Its library IDs need not match the stable server. Start
requires one ungrouped idle player, an empty queue, Repeat and Autoplay off, and
the ambient overlay off. Existing queues are never replaced. These settings
are checked rather than silently changed. The test enqueues just its own song
without autostart and binds the briefing to its new session before dispatch.

Speaker volume is separately selectable from 1–40%; background music gain is
0–30%, with speech gain 0.7. Gains are linear mix multipliers, not device volume.
Music stays at its background gain after speech. Snooze is deliberately a
**test-only 5–300 seconds**, default 10 seconds, not the saved alarm's snooze.
It stops music and restarts the same queued song from zero with no new briefing
generation or speech. The MA control endpoint checks the run, session, source,
group and exact one-item queue under its playback lock before every control.

Music-only repetitions are requested after the song goes idle, polled every two
seconds; this is **not gapless looping**. Dismiss and Sleep in both stop only the
test. A 30-minute HA-side watchdog also stops it. On successful owned completion,
the test clears its own one-item queue and restores speaker volume only if the
reported volume still equals the level it set. A takeover releases control
without stopping/restoring someone else's playback. If MA does not confirm a
stop, the UI reports uncertainty and keeps the reservation; Dismiss can retry a
guarded stop, never a start. There is no blind playback retry or experimental
tone fallback after uncertain dispatch.

A real alarm delivery takes priority and first requests the test's guarded stop;
if that cannot be confirmed, normal delivery reports/retries the conflict rather
than overlapping audio. Shutdown/unload makes a bounded stop attempt. Test state
is runtime-only: it is not resumed after HA/MA restart. If shutdown or connectivity
prevents confirmation, check/stop the speaker manually. The server retains no
automatic repeat setting, so HA loss does not create an endless server-side loop.

### Validation and deployment boundary

- Offline tests cover capability/voice matching, bounds, admin-only commands,
  independent test state, cancel-before/after dispatch, uncertain-stop retry,
  source takeover, same-song Snooze, watchdog and real-alarm priority.
- The real custom card is exercised with fake HA transport in Chromium at 390
  and 1280 pixels. Native audio tests use real MA helpers/FFmpeg with synthetic
  tones, not actual TTS, an authenticated MA server or a physical speaker.
- HA-AlarmClock 0.6.0 was deployed and verified loaded/rendering after an approved
  Core restart on 2026-11-17. Saved alarm settings were not changed. The companion
  fork is published at `DaFern/music-assistant-alarm-clock-server@d66459f7f7eab48a18e7fb5d6c0768a17da2ef52`.
  MA DEV source selection/full-server verification remain pending. Its inspected
  logs reported a port 8097 conflict; stable and DEV must not share default ports.
  No speaker test has run. The HA project changes remain uncommitted/unpushed.
- Use the official Music Assistant DEV SERVER app's supported `server_repo`
  mechanism with a reviewed fork commit pinned exactly. Do not patch the stable
  app's container. Stop stable MA for the test window to avoid default-port
  conflicts; keep its data untouched and configure the DEV app independently.
  HA registry identifiers are not necessarily namespaced by MA server: verify
  which config entry owns the chosen entity rather than assuming a second server
  creates a second Kitchen entity. Do not delete/reassign production entities.
- Before deploying, back up the current runtime integration as well as the full
  system. HA custom-component deployment requires a separately approved Core
  restart. Version/cache-busting should be bumped at deployment. Rollback stops
  DEV MA and starts stable MA, plus restores the prior integration/restarts HA
  if that code was deployed. No installation, fork publishing or restart is
  automated by the test panel.

Offline commands: `python3 -B tests/test_ma_audio.py`,
`python3 -B tests/test_ma_test_commands.py`, and `python3 -B tests/run_browser.py`.
See `../../prototypes/ma_one_shot/README.md` for the server patch and native tests.

## Issue #1: Assist voices and spoken preview — project changes, not deployed

**Choose an assistant** lists the named assistants from Home Assistant's
Settings → Voice assistants. Each alarm stores the selected pipeline ID, not a
separate conversation engine, TTS service, language or voice. Generation and
speech resolve the assistant's current configuration through HA's pipeline API.
**Play on** still chooses the alarm's output speaker.

Older schedules and output speakers are preserved. Their old manual playback
settings are retired on load and omitted from subsequent saves. No assistant is
guessed from those settings. Choose an assistant again for spoken messages; a
missing/deleted assistant or one without configured TTS is explained in the card
and falls back to a tone. Sound-only alarms do not need an assistant.

**Preview message** uses the current unsaved draft, including its instructions,
weather and selected/filtered calendars. No alarm speaker is required. A popup
shows loading, the generated text and local playback controls. Its audio uses the
selected assistant's configured TTS engine, language and voice (or the engine's
default voice if the pipeline does not specify one). Preview plays on the device
viewing the dashboard, never the alarm speaker. Blocked autoplay offers a Play
button; errors identify conversation or voice settings to check. Closing/Escape
or disconnecting the card stops local audio, revokes its Blob URL and ignores late
responses. Closing does not undo an already-submitted provider request.

The administrator-only preview WebSocket returns bounded audio bytes (up to 8 MiB)
and text; no personal-audio endpoint or public preview URL is added. The HA TTS API
is called with disk caching disabled. Preview does not save an alarm, schedule or
sleep switch. The voice provider receives the spoken text. The conversation
assistant retains its usual permissions during preview as well as real alarms;
the prompt's request not to take actions is not a security boundary.

By default the briefing is attempted only on the first ring. The optional
snooze-repeat setting permits one new attempt per snooze ordinal. Each attempt
is persisted before generation/playback so an interruption or restart within
the same ring cannot repeat it. Other rings use the chosen tone, or Chime for a voice-only alarm.
If voice-only speech fails, Chime is attempted immediately and a warning is shown.

These changes were checked offline against the HA 2026.11.1 pipeline/TTS API
source. Actual HA loading, the configured voice on a physical speaker, dashboard
audio on real devices, and Echo dismissal still require separately approved live
verification. The GitHub issue must remain open until that work is verified.

## Issue #1: scheduling and dismissal — project changes, not deployed

The sleep switch remains optional. When a linked switch is off at the scheduled
time, that occurrence is recorded as missed; turning it back on during the
five-minute catch-up window does not replay it, including after a restart.
Future occurrences stay enabled.

With a linked switch, **Turn off the sleep switch when I dismiss the alarm** is
opt-in per alarm and defaults off for existing alarms. Explicit dismissal of a
ringing or snoozed run saves the dismissal and cancels delivery before trying to
turn off the switch. A switch failure shows a warning without restoring the
alarm. Snooze and Sleep in do not change the switch. Dashboard and service-based
dismissals share this path; this does not establish a verified Echo command.

For either selected-weekday calendar rule, an unavailable or failed calendar
check rings on an otherwise eligible day, with a visible warning. A successful
read with no matching events remains distinct: it permits the Skip rule but
does not permit the Only ring rule. Calendar results are cached for five minutes.

## 0.4 automation lookup, longer messages and calendar filters — pending activation

`household_alarms.get_active` is a read-only, admin-service action with a required
response. Its optional `person` and `speaker` fields narrow the results (combined
with AND). It returns `count` and an `alarms` list containing IDs, names, people,
output speakers, speaker group members, ringing/snoozed status and timing fields.
The status sensor's `active_alarms` attribute exposes the same structured list.
No instructions, calendar events or voice-provider settings are included.

Your automation must decide which alarm to control. Zero matches means no action;
multiple matches require an explicit choice. The integration never guesses a
speaker from Alexa history and adds no household-specific voice routing. It retains
the existing explicit-ID snooze/dismiss actions and all snooze/deadline safeguards.

For example, an automation can call `get_active` with a speaker and save its response
using `response_variable`. Only when `count == 1` should it pass
`alarms[0].id` to `household_alarms.snooze` or `household_alarms.dismiss`, unless it
has its own explicit selection rule. These are API examples, not installed automations.

The instructions box now accepts 10,000 characters. Per-alarm Message length offers
Short (up to 100 words), Medium (200), or Long (300). Existing alarms default to
Short: the prior 90-word prompt and 100-word output guard remain for that choice.
Longer choices allow 45 seconds for generation and 60 seconds for speech submission.
Speaker ownership waits for a conservative speech-duration estimate (at most 210
seconds) before allowing another repeat. It is not an audio-completion acknowledgement;
actual voice speed and provider limits still require physical testing. A get-up
deadline can still interrupt the delivery task and escalate the alarm.

Optional calendar filters have one literal word or phrase per line. Inclusion
matches ANY listed phrase; blank means no inclusion restriction. Exclusions always
win. Matching is case-insensitive Unicode text matching, not regular expressions,
and checks the full event title before truncating/sending the title to the assistant.
Descriptions are not read or matched. Both fields default blank for existing alarms.
Only the filtered schedule reaches the assistant, though the calendar provider must
first return events to HA for local filtering. Shared-calendar attendance is not inferred.

Local scheduling for independently configured speaker alarms. Built for Home
Assistant **2026.10.1**. It does not create alarms in Samsung Clock or Amazon's
native alarm scheduler. Home Assistant, the speech provider and the playback path
must be available. Keep an independent alarm for essential wake-ups until physical
acceptance testing is complete.

## Activation — pending

The integration files are saved but are not loaded merely by saving them.

1. Validate Home Assistant configuration and obtain approval for a Core restart.
2. After restarting, wait at least 60 seconds before checking recovery.
3. Add **HA-AlarmClock** in Settings → Devices & services → Add integration.
   Setup creates an empty manager. It does not modify any existing alarm.
4. Add `custom:household-alarms-card` to the existing Settings → Alarm section,
   preserving the old controls during testing. The integration serves and registers
   its own JavaScript module through HA's dashboard-resource collection API. Only
   this integration's relative resource URL is created or updated. Other resources
   are preserved. No internal files are edited directly. YAML-owned resources are
   left alone and use the extra-module fallback; manual module registration is
   recommended for that mode. Refresh an already-open app after activation.
5. Create disabled test alarms. Confirm real speaker and selected assistant-voice
   playback with the user present before enabling schedules.
6. Migrate old alarms only after separate approval. Do not run duplicate schedules.

## Settings and operation

Each alarm has a name, person, enabled flag, local time, repeat days or one date,
optional school holiday calendar, output speaker/group, generated ringing sound,
starting/maximum volume, volume step, repeat interval and optional named assistant.
Three simple eight-second tones are generated in memory;
no film audio or downloaded sound library is included.

Choose the weekdays when the alarm should ring, or choose one date. You can also
select a calendar and choose whether matching event titles skip those weekdays
or are the only days the alarm can ring. Write one word or phrase per line; the
alarm stays at its set time. The calendar phrases for alarm days are separate
from the optional event filters used in a morning message.

An optional latest wake-up time ends snoozing and raises the alarm to its loudest
volume. If alerts are enabled, one message is sent until the alarm is stopped.
The alarm does not claim that anyone is physically awake. Dismissal changes a
linked sleep switch only when the per-alarm option is explicitly enabled.

Use a notification destination such as the existing `notify.adults` service for
phone alerts. If none is selected, alerts are persistent notifications **inside
Home Assistant only**, not phone pushes. Delivery failures are reported once per
run; unavailable speakers are retried rather than silently dismissing the alarm.

Each run, snooze count, snooze expiry, deadline state and dismissal are persisted
through HA's Store API. A restart resumes a same-day active run without resetting
its snoozes. A first scheduled trigger missed by less than five minutes can catch
up; longer missed starts do not suddenly ring later in the day. Stale runs from a
previous date are not replayed. A repeated autumn DST minute fires at most once;
nonexistent spring-forward times are skipped. Snooze durations use elapsed time.

Only one alarm/test owns a speaker or its group members at a time. A conflicting
alarm retries and reports the conflict. The repeat interval is a minimum: a long
briefing is not overlapped by another repeat. The original volume is restored only
when the current reported volume still matches the alarm's last setting, to avoid
undoing a manual change. Already-sent audio may finish after dismissal; no further
repeats are sent. Acceptance of a playback service call is **not** proof of sound.

## Assist voices

The named assistant supplies the conversation engine and configured TTS provider,
language and voice; the selected media player plays alarm audio. The integration
does not change the assistant's configuration or choose a different voice itself.
`tts.speak` uses HA's announcement media-source path, including the generated-audio
bridge in the installed Alexa Media Player integration. Echo playback still needs
that bridge's externally reachable URL and cloud connection. No Alexa integration
configuration or public URL is changed by HA-AlarmClock.

An optional briefing receives only the configured person/name instructions,
current local time and bounded current-weather facts. It uses a fresh conversation
ID, a 25-second timeout, and a bounded spoken response. It requests plain speech
without actions. **This prompt is not a security boundary:** the chosen conversation
agent retains its existing permissions and provider behavior. Use a briefing-only
agent with tool access disabled if hard separation from device control is required.
No existing JARVIS, F.R.I.D.A.Y. or other agent configuration is changed.

The initial ringing sound is sent independently of briefing generation. If AI
generation fails, the standard wake-up greeting is used. The initial ring and
opted-in snooze wake-ups attempt speech; ordinary repeats use tones. A failure in both speaker playback and notification
delivery cannot be made reliable by software; maintain a separate critical alarm.

The card's spoken preview may contact the selected assistant and voice provider
and plays locally when Preview message is selected. A saved-alarm speaker test
requires an explicit confirmation naming the speaker and volume.
Tests do not create an active alarm, change bedtime, or enable a schedule.

Generic Alexa actionable-notification `ResponseYes` events are intentionally **not**
accepted as snoozes or proof of identity. This first version exposes explicit
alarm-ID actions and dashboard buttons, not unrestricted voice creation/deletion.

## Future bedtime automation migration

The integration does not modify Charlotte's current bedroom → landing → dining
automation or its morning/evening conditions. After testing and approval, that
automation can call:

```yaml
action: household_alarms.dismiss_person
data:
  person: "Charlotte"
```

This dismisses only Charlotte's active alarms/pending snoozes; Dan's and Meg's
alarms are untouched. Alternatively, link an alarm to Charlotte's bedtime boolean:
an `off` state prevents or dismisses that alarm on the next scheduler tick.
Dismissal changes the bedtime boolean only when the per-alarm option is enabled. The existing early-wake
warning and motion corroboration remain the automation's responsibility.

## API and access

All alarm list/subscription, create/update/delete, preview, test and action
WebSocket handlers require an authenticated administrator. Settings saves/deletes
use a persisted revision precondition; stale editors must reload, not blindly retry.
Active alarms must be dismissed before editing/deleting. Services `snooze`,
`dismiss`, `sleep_in` and `dismiss_person` use HA's admin-service wrapper, permitting
trusted automation contexts. Only non-personal generated tone WAVs and the static
frontend code are publicly served; alarm settings and briefing text are not.

## 0.2 usability update

- One large On/Off switch, with no duplicate enable checkbox. Existing switches
  save immediately; saving other edits preserves their latest state. New alarms
  remain off by default. Unsaved edits and revision conflict protection are retained.
- A short main form and collapsed More settings, larger text and touch targets,
  generic wording, and no preset household names, assistant, weather entity or
  Piper provider ID. Existing saved selections are preserved. Sound-only alarms
  work without a TTS provider; spoken messages still require one.
- “Let someone know” explains the three notification reasons and shows readable
  destination names. Home Assistant-only notifications are distinguished from phones.
- Calendar-free weekday/weekend rules are explained. Optional calendar selection
  links to HA's Local Calendar setup and calendar page, and explains holiday titles.
  No calendar is created or existing calendar changed automatically.
- Versioned dashboard resource registration replaces reliance on page-wide module
  injection for storage-mode dashboards. This is the proposed app-loading fix;
  actual Companion app verification is still required after an approved restart.

## 0.2.1 mobile buttons and complete test — pending activation

Edit and Test share one equal-width row, with Delete on a full-width row below.
Test plays one cycle using the saved speaker, starting volume, sound and morning
message (when configured), including the chosen assistant and voice. It uses the
normal delivery path without enabling the alarm, modifying its persisted run or
bedtime flag, or sending alerts. Confirmation is still required before playback.
Older clients' message-only test request remains accepted for compatibility.

## 0.3 selected-calendar morning schedule — pending activation

Morning message includes an optional “Include today's schedule” switch and
calendar picker. Existing alarms default to off with no calendars selected. The
user must explicitly choose calendars for each alarm. Shared calendars may contain
other people's events; selection does not establish attendance or silently filter
by the person's name. A personal calendar is the clearest way to limit relevance.

Only selected calendars are queried, read-only, from local midnight to the next
midnight. Event titles, start/end times, all-day status and calendar names are
supplied to the assistant; descriptions, locations and attendee details are not.
Unavailable calendars are distinguished from an empty day. Reads have an eight-
second timeout per calendar and run concurrently; context is limited to twenty
deduplicated events with explicit truncation status. Calendar text is treated as
untrusted data in the prompt; the existing warning about agent permissions applies.
Ringing starts independently of this work. No calendar, schedule or bedtime flag
is modified. No real personal events were fetched during offline tests.

The status sensor has only active alarm IDs/names and enabled counts, not private
briefing instructions. No native LLM administration tools are automatically exposed.

## Validation

Offline tests and browser fixtures live in the project's `tests/` directory. They exercise the rules and
adapter calls using in-memory HA fakes, and the actual frontend in isolated Chromium
at mobile/desktop widths. They do **not** replace HA integration tests or real
speaker acceptance tests. This container has no Home Assistant Python environment.

```text
python3 -B tests/test_alarms.py
python3 -B tests/run_browser.py
node --check custom_components/household_alarms/frontend/household-alarms-card.js
```

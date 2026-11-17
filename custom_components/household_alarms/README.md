# HA-AlarmClock 0.4.1

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
5. Create disabled test alarms. Confirm real speaker and selected Piper-voice
   playback with the user present before enabling schedules.
6. Migrate old alarms only after separate approval. Do not run duplicate schedules.

## Settings and operation

Each alarm has a name, person, enabled flag, local time, repeat days or one date,
optional school holiday calendar, output speaker/group, generated ringing sound,
starting/maximum volume, volume step, repeat interval, speech provider, language
and installed voice. Three simple eight-second tones are generated in memory;
no film audio or downloaded sound library is included.

Choose the weekdays when the alarm should ring, or choose one date. You can also
select a calendar and choose whether matching event titles skip those weekdays
or are the only days the alarm can ring. Write one word or phrase per line; the
alarm stays at its set time. The calendar phrases for alarm days are separate
from the optional event filters used in a morning message.

An optional latest wake-up time ends snoozing and raises the alarm to its loudest
volume. If alerts are enabled, one message is sent until the alarm is stopped.
The alarm does not claim that anyone is physically awake or change a sleep switch.

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

## Piper and Assist

The Assist agent generates wording; the separately selected TTS provider and voice
generate audio; the selected media player plays it. These are independent choices.
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
generation fails, the standard wake-up greeting is used. Deadline escalation does
not start another AI briefing. A failure in both speaker playback and notification
delivery cannot be made reliable by software; maintain a separate critical alarm.

The card's text preview may contact the selected AI provider but never plays audio.
Every audio test requires an explicit confirmation naming the speaker and volume.
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
Dismissal does not itself change the bedtime boolean. The existing early-wake
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

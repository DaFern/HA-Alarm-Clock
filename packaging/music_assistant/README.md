# Pinned Music Assistant companion — release candidate

This is a **project-only build recipe**, not an installed or validated app image.
The integration's music path requires companion protocol **2**, not the old DEV
test API. Ordinary tone/voice alarms do not require this package.

### Issue #4 queue-preservation extension

Current templates advertise protocol 2 plus `preserve_queue` and `restore_playback`. Scheduled alarms
and confirmed saved-alarm Tests can append/start an alarm item on a nonempty or
playing queue, without discarding existing tracks. Only the alarm item is removed
after an owned Snooze/Dismiss, and the interrupted playing item is resumed at its
saved position if still present. Every snooze wake-up captures current playback
and creates a fresh unique alarm segment. The live queue is filtered by the alarm
item ID; user additions, removals, order changes and copies of the same song are
preserved. A later user playback/session is never stopped or overwritten by stale
alarm controls. Lost stop responses do not stop restored music a second time.
Enqueue attempts are consumed before preparation/dispatch so an uncertain response
cannot duplicate the alarm song. Message repetition is opt-in per snooze wake-up;
natural song loops never rearm speech.

The older protocol-1 experimental random-song test remains idle/empty-only;
it is not the saved-alarm Test. Grouping, Repeat, Autoplay and ambient overlays
remain unsupported. The old `7aab695...` deployment lacks this capability.
Publish/install a regenerated companion before deploying integration 0.7.0b6.
Empty, stopped-nonempty and active queues still require live speaker acceptance;
offline command tests are not an audible result.

See the [morning deployment handoff](../../docs/DEPLOYMENT_HANDOFF.md) for the
current stop point and step-by-step transfer/build/verification sequence. Do not
uninstall DEV before the replacement is tested and its data backed up.

### Project-only ramp extension (not in the current DEV pin)

Issue #3 adds optional `volume_ramp` capability and an ownership-checked
`player_queues/alarm_volume` command to the project templates. Regenerating this
recipe includes the extension; old generated contexts do not. The published
`7aab695...` DEV fork below does **not** include it. Existing ramp-off alarms
remain compatible; ramp-enabled alarms reject a server missing that capability
before generating speech or dispatching playback. Publishing an updated fork or
building/updating the packaged companion needs separate approval. Offline checks
do not constitute authenticated API startup or a physical ramp test.

### Temporary compatible DEV route

The earlier protocol-2 source (without the ramp extension) was published in the MA fork at
`DaFern/music-assistant-alarm-clock-server@7aab695417cea5d0fdf926620724cfd873ef1c22`.
The user approved retaining DEV temporarily, avoiding the local-package transfer
until a convenient migration window. Back up HA+DEV before changing DEV's
`server_repo`, verify that exact build and its protocol before deploying the HA
candidate, and preserve all existing app options and data. The older
`d66459f...` protocol-1 build is not compatible with scheduled music.

## Reproducible local build context

From the project root, create a **new** directory on a development machine:

```sh
python3 packaging/music_assistant/prepare.py /path/to/new/music_assistant_alarmclock
docker build -t music-assistant-alarmclock:2.10.12-alarmclock.1 /path/to/new/music_assistant_alarmclock
```

The generated directory is also a standalone Supervisor local-app source. Place
it in the host's local-app folder through an approved host-access route and use
Supervisor to build it. This agent environment has neither Docker nor app-folder
access, so no image build, install or migration has been performed here.

The Dockerfile extends MA's exact 2.10.12 image index:
`sha256:7eb272e2e13da9a5d61dcbc4e1fcfc734776222b23f2825a9b5690d4427cfafb`.
Its published revision is `6ab5bfa63f02d0daa237d342097a42feae5c5aae`.
Build-time code checks eleven pristine source hashes, parses all candidates,
then installs four modified files. Any source mismatch aborts the build.
There are **no startup source downloads or dependency installations**. The
generated context and installed sources have separate SHA-256 manifests.

## Installation and update policy (separate approval required)

1. Back up HA and the working MA instance using Supervisor. Confirm restore works.
2. Build and inspect the candidate image; test both startup and actual MA APIs.
3. **Disable automatic updates** for this companion in Supervisor. This is an
   installation setting, not something a manifest can enforce. Do not update the
   upstream MA app or replace this image until compatible upstream support is
   released and tested. Review upstream security advisories nevertheless; pinning
   is not a reason to ignore a critical security fix.
4. Stop DEV/stable before starting this package: all use host-network ports
   8094/8095/8097. Never run two on the same ports.
5. This app has a **different slug and private `/data`**. Start with fresh data;
   configure providers through MA's UI. Do not copy DEV databases/cookies or try
   to downgrade a newer schema. The prior schema 74 → 58 migration failed.
6. Connect HA to this new instance using its supported integration flow, preserve
   the original integration for rollback, and reselect each music alarm's MA
   speaker **and song**. Library URIs are local to each server. No existing alarm
   is silently redirected or enabled.
7. With separate deployment/restart consent, deploy the integration candidate;
   test song selection, delayed assistant voice, full playback, Snooze, Dismiss,
   Sleep in, once-per-snooze message opt-in/off, current-track/position restoration,
   user queue edits/copies, active/stopped queues, lost responses and takeover.

Retain the previous app, its data and previous integration files for rollback.
Stop the companion before restoring the prior MA app and HA connection. A
rollback involving different database versions requires that app's matching
backup, not opening its newer database with an older binary.

## Release gates and limitations

- The image has **not been built here** and an authenticated MA server has not
  been exercised with protocol 2. Passing fake-controller tests and real FFmpeg
  helper tests does not prove server startup, Supervisor install or audibility.
- Music alarms require an idle, empty, ungrouped queue with Repeat, Autoplay and
  ambient overlay off. Existing listening is never replaced automatically.
- Voice delay is 0–120 seconds of music, after message/TTS preparation. The song
  is the primary stream: a short song can end before delayed speech completes.
- Track repeats are polled, not gapless. Snooze begins the song again and never
  repeats speech. HA saves the first-speech attempt and every dispatch identity.
  An uncertain start/stop blocks further automatic playback for that run.
- The mixer retains up to 65,536 runtime replay ids and fails closed at its
  bound rather than evicting protection. A clean app restart resets this runtime
  state; HA's persisted first-briefing attempts still prevent speech replay.
- The intermittent Echo song/chapter restart remains **unreproduced and unfixed**.
  A user-confirmed full-song playthrough is not proof this fault is gone.
- No stable release should be published until the above live checks pass.

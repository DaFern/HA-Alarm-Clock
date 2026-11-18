# Pinned Music Assistant companion — release candidate

This is a **project-only build recipe**, not an installed or validated app image.
The integration's music path requires companion protocol **2**, not the old DEV
test API. Ordinary tone/voice alarms do not require this package.

See the [morning deployment handoff](../../docs/DEPLOYMENT_HANDOFF.md) for the
current stop point and step-by-step transfer/build/verification sequence. Do not
uninstall DEV before the replacement is tested and its data backed up.

### Temporary compatible DEV route

The same protocol-2 source is now published in the MA fork at
`DaFern/server@7aab695417cea5d0fdf926620724cfd873ef1c22`.
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
   Sleep in, restart without speech replay, busy queue rejection and takeover.

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

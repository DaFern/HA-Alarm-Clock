# Morning handoff — 2026-11-18

## Deployed follow-up: song-picker feedback and phone controls

The user confirmed search worked after selecting the correct MA speaker, but
reported off-screen error feedback and unclear song-selection state. The
approved follow-up adds inline loading/errors, a highlighted selected-song
summary with Change song, unambiguous speaker entity IDs, and optional per-alarm
lock-screen Dismiss/Snooze controls with an Android screen-wake option.

The user approved deployment. Live is now **0.7.0b2** on the same protocol-2 DEV
fork. Eight runtime files changed; all 20 files matched the candidate. No YAML
changed. Previous runtime files and a deployment hash receipt were saved at
`/data/v2/cache/opencode/household_alarms-before-0.7.0b2-20261118T021342Z`.
Configuration validation passed without errors/warnings. Core was restarted once
(its disconnect returned 502, not retried); after a 65-second wait the integration
was loaded, zero alarms were enabled/active, Kitchen was idle, and the dashboard
rendered at 390 and 1280 pixels. No saved settings, phone commands, audio or MA
updates were performed. Phone controls stay off by default. Physical-phone
acceptance remains pending; see the integration README for permissions and
lock-screen privacy/connectivity limits. Source publication is tracked separately
in the Git history and issue #2; deployment/publication is not a stable release
or completion of physical-phone acceptance.

## Current status: 0.7.0b1 deployed; live acceptance pending

This supersedes the older stop-point statements below. The user updated and
restarted DEV on fork `7aab695417cea5d0fdf926620724cfd873ef1c22`, then explicitly
approved HA-AlarmClock deployment and Core restart. DEV startup logged that
exact commit; its HA library query succeeded and Kitchen was idle with an empty
queue. Stable MA remained untouched.

Nine integration source/documentation files were deployed, including the new
`music.py`; all 19 installed files matched the project. No YAML changed. The
previous runtime was backed up with verified hashes at:

```text
/data/v2/cache/opencode/household_alarms-before-0.7.0b1-20261118T012905Z
```

The backup contains `runtime/` and `deployment.json`. The separate Supervisor
HA+DEV backup `a4c89d7b` also remains available. Configuration validation passed
without errors or warnings. The approved Core restart call returned 502 as the
connection went away; it was not retried. After waiting 65 seconds, the
integration reported **loaded**, the alarm sensor showed zero enabled/active
alarms, and Kitchen was idle. The live card rendered at both 390 and 1280 pixels
without the experimental test panel.

No saved settings, speaker selections or sleep switches were changed, no alarm
was enabled, and no audio was played. This is a deployed **beta candidate**, not
a published or fully accepted stable release. The local-app image remains
unbuilt/uninstalled and the intermittent song/chapter restart remains unfixed.

### Next: non-playing protocol-2 check

The exposed tools cannot directly invoke custom HA WebSocket commands or click
the card editor, so runtime protocol-2 capabilities/song search remain pending.

1. Open **Jarvis Alarm → Edit**, leaving the saved alarm **off**.
2. Enable Music in the unsaved draft and search for a song using the DEV MA
   speaker. **Search songs** checks protocol 2 before reading library metadata;
   it does not play audio or save anything.
3. Report song results or the exact error; cancel the draft if not continuing.
   An ordinary MA library service query is not this protocol-2 check.
4. With explicit consent, save song/gain/delay while leaving the alarm off, then
   use **Test**. Verify exact assistant voice, delay, full song, music-only Snooze,
   Dismiss and Sleep in. Scheduled firing, deadline escalation, takeover and
   restart recovery still need acceptance testing.

Keep issue #2 open and keep an independent alarm for essential wake-ups.

## Approved follow-up: temporarily keep MA DEV

After the original handoff, the user disabled **Start on boot** for stable MA
and approved retaining DEV while moving it to the compatible protocol-2 patch.
The separately packaged app remains an eventual migration route, not a
prerequisite for trying this candidate on the existing DEV connection.

The updated MA patch was committed and successfully pushed to the fork:
`7aab695417cea5d0fdf926620724cfd873ef1c22`, branch `ha-alarmclock-2.10.12`.
DEV must use this exact `server_repo` value:

```text
DaFern/server@7aab695417cea5d0fdf926620724cfd873ef1c22
```

The published helper and seven relevant queue methods match the tested project
templates by AST. All 225 Python tests passed again; targeted mypy and Ruff
checks passed on the two changed MA files. This is not live-server verification.

The exposed MCP tools can back up and restart DEV, but cannot edit its app
options. After confirming the HA+DEV backup has completed, use DEV's supported
**Configuration** tab to change only `server_repo`; preserve every other option.
Saving may prompt for an app restart. Restarting DEV interrupts MA playback;
obtain confirmation before doing so. Leave stable MA stopped and DEV installed.

The pre-change HA+DEV partial backup completed successfully: slug `a4c89d7b`,
created at `2026-11-18T01:18:59.686112+00:00`. Supervisor reported HA and one app
included. It is not password-protected; retain it on trusted backup storage and
do not publish or copy its contents into the project. The earlier protected full
backup `60787622` also remains available.

Then verify DEV startup, HA connection, the Kitchen speaker and protocol-2
capabilities without playing audio. Do not deploy the integration candidate
until this succeeds. Integration deployment still needs a runtime-file backup,
configuration validation, explicit Core-restart approval and post-restart
verification after at least 60 seconds. No saved alarm should be silently
enabled or switched to music, and no audio test should start without consent.

Tracking: https://github.com/DaFern/HA-Alarm-Clock/issues/2

The original stop-point and local-package instructions below remain useful
historical context; this temporary DEV route supersedes their installation order.

## Where we stopped

HA-AlarmClock **0.7.0b1** was prepared as a source release candidate. It includes
the per-alarm song picker, saved MA-connection identity, music gain, voice delay,
scheduled music delivery and the normal saved-alarm Test controls. The pinned
MA companion source/build recipe lives in `packaging/music_assistant/`.

The PC was switched off and deployment was deferred until the morning. No more
work on the running system is needed overnight.

## Live setup — left unchanged

- The deployed HA integration remained **0.6.0**, not this candidate.
- The working MA DEV instance was not stopped, removed or changed by this work.
- The original stable MA app/integration and their data were left intact.
- No candidate MA image was built, installed or started. No Core restart or
  stable GitHub release was performed for this candidate.
- The user previously verified simultaneous music/briefing, Dismiss, music-only
  Snooze and a complete song on the earlier DEV prototype. Sleep in and the new
  scheduled protocol-2 flow still need live acceptance tests.
- The intermittent song/chapter restart remains **unreproduced and unfixed**.
  Charlotte's audiobook setup was not changed.

## Why installation is pending

This agent environment has no Docker/Podman builder or enabled local-app folder
access. Editing the official app's container would be temporary and can be lost
when Supervisor recreates it, even with automatic updates off. Rebuilding the
official app alone would not include these project patches.

The prepared package is a **separate local app**, not an edit to the existing
official app. Supervisor can build it once its self-contained source directory
has been transferred to the host's local-app folder.

## Next session: smallest safe sequence

1. Read this handoff and the package README. Confirm which transfer tool is
   available: Terminal & SSH, Studio Code Server, or Samba share. Verify that
   tool's actual local-app mount before providing copy commands; current HA docs
   call it `local_apps`, while older installations/tools use `addons`.
2. Recreate the self-contained package from the repository on an accessible
   machine or approved host environment:

   ```sh
   python3 packaging/music_assistant/prepare.py /path/to/new/music_assistant_alarmclock
   ```

   The destination must not already exist. Transfer the **whole generated
   directory**, including `config.json`, `Dockerfile`, `patches/` and its hash
   manifest. Copying only `packaging/music_assistant/` is not sufficient: its
   preparer collects the reviewed patch templates from `prototypes/ma_one_shot/`.
   Obtain approval before exporting/copying into any live host directory.
3. In HA's App store, use **Check for updates**, refresh if needed, then find
   **Music Assistant — HA-AlarmClock pinned** under **Local apps**. With approval,
   install/build it. Do **not** start it yet. A separate Docker CLI is unnecessary
   when Supervisor performs the build. Read build errors rather than bypassing
   source/hash checks.
4. Back up HA and the working MA apps. Agree on the migration/test window. Disable
   the companion's Supervisor automatic updates; the manifest cannot enforce it.
5. With approval, stop DEV/stable before starting the companion: they share
   default ports. The companion has private data and needs provider setup;
   do not copy cookies or incompatible databases, or attempt a schema downgrade.
6. Connect HA through the supported MA integration flow. Preserve rollback
   entries. Reselect the intended MA speaker **and song**: selections are bound
   to the exact HA MA config entry, and library IDs are server-local.
7. Separately approve integration-file deployment and Core restart. Back up the
   installed files, validate, restart, wait **at least 60 seconds**, then verify
   loading and the actual dashboard at phone/desktop widths.
8. Verify scheduled firing, selected song, exact assistant voice, voice delay,
   complete playback, Snooze, Dismiss, Sleep in, deadline escalation, busy-queue
   refusal, takeover and restart without speech replay. Keep an independent
   alarm for essential wake-ups.
9. Only after verification and separate approval, disable/remove DEV. Its removal
   can delete data; do not uninstall it merely to free a port. Retain rollback
   backups and do not publish a stable release until acceptance tests pass.

## Evidence and reproducibility

- **225 Python tests passed** using the isolated Python 3.14.10 MA helper
  environment, including **five real MA-helper/FFmpeg synthetic-audio tests**.
- **80 Chromium checks passed at each width**, 390 and 1280 pixels. The new music
  panel was also visually reviewed in an offline phone-width fixture.
- The build-time installer was tested against all eleven pristine MA source
  hashes; generated candidates parsed under Python 3.14, matching the base image.
- These are not an authenticated MA-server boot, Docker build, Supervisor
  installation, physical-speaker test, or production deployment.
- System Python 3.13 passes the ordinary offline suite, with the five native
  audio tests and Python-3.14-only full-source installer test explicitly skipped.
- A verified generated context also existed at
  `/data/v2/cache/opencode/ma-alarmclock-package-0.7.0b1`, but that cache is not
  the durable source of truth. Regenerate from the repository if unavailable.

Native test invocation used in this environment:

```sh
MA_NATIVE_SOURCE=/data/v2/cache/opencode/ma-native-runtime/server PATH=/data/v2/cache/opencode/ma-native-runtime:$PATH /data/v2/cache/opencode/ma-native-runtime/venv/bin/python -B -m unittest discover -s tests -p 'test_*.py' -q
python3 -B tests/run_browser.py
```

The upstream implementation evidence was posted on the existing feature request:
https://github.com/music-assistant/support/discussions/998#discussioncomment-19695063

GitHub issue #1 remains relevant to assistant voice/preview/dismissal work.
The deployment follow-up issue should remain open until the checks above pass.

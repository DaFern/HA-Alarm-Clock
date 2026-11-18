# Morning handoff — 2026-11-18

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

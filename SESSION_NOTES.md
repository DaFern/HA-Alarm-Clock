# Session notes

## 2026-11-18
- Prepared the 0.7.0b1 candidate with saved song selection, MA-connection guards, voice delay, scheduled music and normal Test controls.
- Prepared a digest-pinned MA local-app recipe and verified its generated build context. Ran 225 Python tests, including five real FFmpeg tests, and 80 Chromium checks at each of two widths.
- Posted implementation evidence to upstream discussion 998 and documented the morning deployment handoff in `docs/DEPLOYMENT_HANDOFF.md`.
- Left the deployed 0.6.0 integration, stable MA, DEV and their data unchanged. No image build, installation, deployment, new backup, restart or stable release occurred. Left live acceptance, DEV retirement and the unreproduced restart bug pending.

## 2026-11-18 — protocol-2 DEV follow-up
- The user disabled stable MA Start on boot and approved keeping DEV temporarily. Published and pushed the compatible MA fork commit `7aab695417cea5d0fdf926620724cfd873ef1c22` and updated issue #2.
- Verified the published helper/queue methods against the project AST; 225 Python tests, targeted mypy and Ruff checks passed.
- Created and verified HA+DEV partial backup `a4c89d7b` (not password-protected); the service timed out initially, but the Supervisor job completed successfully without a retry. DEV still needed a supported UI edit of `server_repo`; no explicit DEV/Core restart or HA candidate deployment occurred.

## 2026-11-18 — approved candidate deployment
- The user updated/restarted DEV on fork `7aab695417cea5d0fdf926620724cfd873ef1c22`; verified its HA library response and idle, empty Kitchen queue.
- Backed up runtime files at `/data/v2/cache/opencode/household_alarms-before-0.7.0b1-20261118T012905Z`, deployed 0.7.0b1, verified 19 source hashes and passed configuration validation.
- Performed the approved Core restart without retrying its 502, waited 65 seconds and verified the integration loaded, zero enabled/active alarms, idle Kitchen speaker, and live card rendering at phone/desktop widths.
- Left saved settings and speakers unchanged and played no audio. Left card-driven protocol-2 song search, audible/scheduled acceptance, packaged-app migration and stable release pending; retained DEV and the known restart limitation.

## 2026-11-18 — project-only UI and phone controls
- The user confirmed song search worked with the correct MA entity and approved clearer selection/inline feedback plus optional lock-screen controls.
- Prepared 0.7.0b2 with highlighted song selection/Change song, inline search loading/errors, speaker entity IDs, and opt-in phone Dismiss/Snooze with guarded state-scoped actions and an Android screen-wake option.
- Passed 250 Python tests (including five real MA-helper/FFmpeg tests) and 92 Chromium checks at each width; visually reviewed the offline music/phone panels. Updated behavior, privacy, permissions and acceptance documentation.
- Left this follow-up uncommitted, unpushed and undeployed. Live remained 0.7.0b1; no feature-test phone commands, audio, MA changes or restart occurred. Physical lock-screen behavior and deployment required separate approval.

## 2026-11-18 — approved 0.7.0b2 deployment
- Backed up 0.7.0b1 runtime files at `/data/v2/cache/opencode/household_alarms-before-0.7.0b2-20261118T021342Z`, deployed eight changed files and verified all 20 candidate files matched. No YAML changed; configuration validation passed.
- Performed the approved Core restart without retrying its 502 disconnect, waited 65 seconds, and verified the integration loaded, zero enabled/active alarms, idle DEV Kitchen speaker, and live dashboard rendering at both widths.
- Left saved settings and MA unchanged, left phone controls off by default, and sent no audio or notification-feature test. Retained physical lock-screen acceptance as pending. The b2 source remained uncommitted/unpushed; no stable release was published.

## 2026-11-18 — 0.7.0b2 publication review
- Reviewed the deployed phone-control and song-picker follow-up for the requested commit/push and refreshed its publication handoff. Excluded the unrelated `archive/services.yaml.bak` and runtime/cache artifacts.
- Kept physical lock-screen/audio acceptance and the known Echo restart issue pending. No live changes, restart or stable release accompanied this publication task.

## 2026-11-18 — same-day scheduling fix and Kitchen acceptance
- Diagnosed same-day rescheduling suppression after a dismissed run; added explicit future-time re-arming with atomic rollback and cleanup/uncertain-stop protection. All 258 Python tests passed, including eight new scheduler regressions and five real MA-helper/FFmpeg tests.
- Deployed only the tested `manager.py`, without a new backup at the user's request. Configuration validation passed; completed the approved Core restart, waited 65 seconds and verified integration loading with no active alarms.
- The user confirmed the saved-alarm Test with Cenotaph/Jarvis, then successful scheduled Kitchen playback, notification Snooze with music-only resume, Dismiss and notification cleanup after dismissal elsewhere.
- Updated project/deployment documentation for publication. Left earlier connection resets unexplained, lock-screen/screen-wake and broader reliability checks pending, MA migration unstarted, the Echo restart unfixed and issue #3 deferred. Left the unrelated archive file excluded.

## 2026-11-18 — project-only timed music-volume ramp
- Implemented the approved opt-in step/interval/cap ramp with distinct tone-repeat labels, shared scheduled/Test logic, Snooze reset, manual override, persisted suspension and no downtime catch-up bursts. Added ownership-checked companion volume controls; the current published DEV pin did not include them.
- Passed 282 Python tests (including five real MA-helper/FFmpeg tests), 100 Chromium checks at each width and targeted generated-companion Ruff/mypy checks. Visually reviewed offline mobile/desktop ramp controls and updated behaviour/deployment/package documentation.
- Left these changes uncommitted, unpushed and undeployed; made no live settings changes, playback attempt, backup, restart or MA publication/migration. Left physical ramp acceptance and issue #3 open, and the unrelated archive file untouched.

## 2026-11-19 — issue #4 follow-up and fork preparation
- Published timezone-aware Next labels and queue-preserving companion changes in project `79ac934` and existing server fork `46b4183`. Passed 291 Python tests including native FFmpeg tests, browser checks at four widths, Ruff and targeted companion mypy.
- Created HA+DEV backup `ffa20773`, updated DEV's exact source pin and deployed matching HA 0.7.0b5 after the active test alarm cleared. Verified deployed hashes, configuration validation, recovery and live phone/desktop card rendering; played no new test audio.
- Created and verified `DaFern/home-assistant-addon`; verified `DaFern/server` was already an upstream fork. Left app installation/migration and physical queue acceptance pending; retained earlier Plex/playback errors for follow-up.

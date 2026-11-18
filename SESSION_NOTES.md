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

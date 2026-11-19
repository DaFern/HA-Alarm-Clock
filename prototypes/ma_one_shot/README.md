# MA-native one-shot briefing companion source

The protocol-1 prototype was audibly tested in MA DEV. The current templates
also generate the **protocol-2 scheduled-alarm candidate**, not yet installed or
live-verified. Its packaged build and deployment gates are documented in
[`packaging/music_assistant/README.md`](../../packaging/music_assistant/README.md).
Do not confuse the earlier tested fork with these newer local source changes.

This adapts the **same MA mixing machinery** that successfully played queued
Piper speech with the enabled pink-noise overlay on the Kitchen Echo. The earlier
test of ordinary TTS announcements paused and resumed music; the later queue test
was audibly simultaneous, as confirmed by the user.

Here the selected **song stays the main MA stream**. A finite briefing is the
second input. The song remains in MA's normal provider/queue pipeline; no full-song
export, preview-clip substitution, external downloader or streaming-service
circumvention is required by the mixer.

## Files

- `adapter.py`: a development-only module intended for the **MA server**, not HA.
- `build_patch.py`: builds a review-only unified diff against pinned MA source;
  never patches its input tree or changes the installed app.
- `start_command.py.txt`: MA command template inserted by the patch builder;
  this is not an executable HA command or an installed API.
- `test_commands.py.txt`: read-only capability check, guarded manual-test start
  and run/session/source-specific control commands, also review-only templates.
- `alarm_commands.py.txt`: versioned selected-song/speech-delay/music-only start
  and guarded control APIs used by the scheduled-alarm release candidate.
- `upstream.json`: SHA-256 guards for the exact MA **2.10.12** source reviewed.
- `../../tests/test_ma_one_shot.py`: offline lifecycle and native graph-contract
  tests (from the repository root, run `python3 -B tests/test_ma_one_shot.py`).
- `../../tests/test_ma_one_shot_native.py`: opt-in real MA-helper/FFmpeg tests
  using generated tones, with no server, provider, credentials or speaker.

## Mixer behaviour

The adapter uses MA's own `ComplexFilterInput`, `ComplexFilter` and
`get_ffmpeg_stream`:

- Input zero is the already-decoded song stream supplied by MA.
- The second input is a **trusted, MA-resolved** local clip or HTTP(S) audio URL.
  It must not be an unvalidated path/URL from a client request.
- The briefing explicitly uses `-stream_loop 0`, not `-1`. It is capped at 240
  seconds and has no HTTP reconnect options that could restart its words.
- The mix uses `amix=inputs=2:duration=first:dropout_transition=0:normalize=0`.
  There is no `-shortest`; finishing the briefing does not finish the song.
- Default linear gains are song `0.25`, speech `0.7`, independent of device volume.
  Both are bounded and their sum cannot exceed one. The song stays at its quiet
  mix gain afterwards; this proof does **not** dynamically duck/restore it.
- The candidate supports a validated 0–120-second speech delay inside the audio
  graph; music starts immediately once preparation completes. Delayed speech
  cannot extend a short song.
- Output PCM follows MA's supplied format. Mono/stereo little-endian integer
  PCM and F32 are supported; normal player encoding/DSP remains downstream.

MA still owns provider playback and output encoding. The mixer does not choose
songs or call `play_announcement`. The protocol-2 scheduled-alarm and saved Test
commands advertise `preserve_queue` and `restore_playback`: capture the currently
playing item and position and append/start a unique alarm item. Owned Snooze and
Dismiss remove only that item and resume the captured playing item if still present.
Snooze wake-ups use new segment IDs and capture current music afresh. The live
queue is never replaced by an old snapshot. Same-song copies survive; takeover
prevents stale stop/restoration. HA optionally generates one new morning message
on each snooze wake-up, with separate replay protection per segment. Enqueue attempts are
tombstoned independently of speech claims, and controls reject a later user's
current item or session. The protocol-1 experimental manual-test commands load
one explicitly selected library track into an **empty** queue and set a bounded
test volume. They refuse existing playback, Repeat, Autoplay or ambient overlays
rather than replacing queues or changing those settings. HA selects the random
development-library song and requests music-only repetitions on natural idle.

## Scope and replay protection

An internal MA caller must arm a request with an alarm run ID and the **exact
queue/session ID**, after session creation but **before stream dispatch**. The
request is claimed before opening the mixer, with no intervening await. Duplicate
GETs, reconnects, another queue/session and later repeats cannot claim it again.

The proposed hook diff covers HTTP single/flow streams and direct-PCM single/flow
streams. Existing ambient overlay code/configuration is not changed. Existing
queue permission checks are preserved; public stop/pause handlers cancel this
queue's pending/active briefing. Per-run cancellation also refuses to cancel a
different alarm's run. Closing a consumer closes the mixer and song generators.

All requests are runtime-only. Clip sources are omitted from representations,
erased on completion/cancellation or lazy expiry, and never serialized or logged.
The candidate retains up to 65,536 run keys per process and then refuses new arming
rather than evicting replay protection. It is deliberately **single-consumer**:
group/fan-out playback is not supported or tested by this proof. A consumer that
already received buffered audio may still finish some of it after cancellation.

A failure before reading any song bytes can pass through the untouched song. A
failure after consuming bytes aborts that stream with a generic error, so an
eventual caller can restart **music only**. It does not silently replay or skip
already-consumed music, retry voice, or claim guaranteed seamless failure recovery.

## Review-only diff

Given an unmodified source checkout/snapshot of MA 2.10.12 containing all eleven
files listed in `upstream.json`:

```text
python3 -B prototypes/ma_one_shot/build_patch.py --checkout /path/to/ma-2.10.12 --output /data/v2/cache/opencode/ma-one-shot-review.patch
git -C /path/to/ma-2.10.12 apply --check /data/v2/cache/opencode/ma-one-shot-review.patch
```

These commands produce/check a diff only. Existing output artifacts are not
overwritten. Hash/anchor mismatches stop the build rather than adapting blindly.
No credentials or installed app directories are needed. Tests use public-source
snapshots under `/data/v2/cache/opencode/ma-one-shot-upstream-2.10.12`; when absent,
source-contract tests are explicitly skipped rather than reported as tested.

The diff adds `music_assistant/helpers/one_shot_briefing.py`, stream/stop hooks,
and the proposed `player_queues/play_index_with_briefing` command. It requires
`Scope.QUEUES_CONTROL`, preserves `_check_player_permission(queue_id)`, and uses
MA's existing re-entrant group/player playback lock via `@handle_play_action`.

The command accepts an **existing queued track's ID**, alarm run ID, bounded
message, registered TTS-engine UID, language, optional voice and the two gains.
It does not accept audio URLs, filesystem paths, arbitrary TTS options, or a
separate remote arming operation. Groups/synced players and non-track items are
rejected. The engine is explicitly resolved; missing engines do not fall back.
The voice is passed as the engine's `voice` option; actual support depends on the
selected provider. The companion HA test adapter now maps the selected pipeline's
exact TTS entity, language and voice; this still needs provider/audible validation.

Speech preparation is bounded to 30 seconds, with a 25-second query deadline,
4096 text characters and 240 seconds of audio. Paths come only from MA's existing
TTS resolver and undergo the mixer's source validation. Renderer errors are
replaced with a generic error, not personal text or a clip location. Rendered
files remain owned by the TTS provider; this module never deletes provider files.

The prepared clip is a private argument of `_play_index`, never queue metadata,
cache state or a shared "next playback" slot. At MA's session creation boundary,
the old briefing is cancelled, the new session ID is created and the clip is armed
**without an intervening await**, before item loading or player dispatch. The
arming TTL is 120 seconds; a slower start degrades to music-only, not late speech.
Cancellation/failure revokes that run, and the temporary prepared source is erased.
Repeated run IDs are rejected before TTS. Replay keys remain process-local; HA's
persisted first-attempt guard is still required across restarts.

### Companion manual-test protocol

Project follow-up for issue #3: protocol 2 optionally advertises `volume_ramp`.
`alarm_volume(queue_id, run_id, volume_level=None)` reads/checks the exact owned
session under the playback lock and optionally changes only its volume. Manual
changes/unknown levels suspend writes and prevent restoring an older level over
the user's choice; natural restarts preserve the manual level. An explicit stopped
`alarm_control(..., action="restart", volume_level=...)` resets a snoozed test's
ring volume and suspension without rearming speech. The HA ramp handles interval,
step, cap and persisted suspension; it never catches up missed intervals. All new
API calls require queue-control scope and player permission. The templates are
project-only: the published `7aab695...` fork does not have this extension.

All three `player_queues/briefing_test_*` commands require `QUEUES_CONTROL`, a
player permission check, and the existing re-entrant playback lock:

- `briefing_test_capabilities(queue_id)`: returns protocol 1, readiness reasons
  and registered HA engine identities, not text, tokens or audio locations. Only
  the local Supervisor HA provider (`http://supervisor/core/api`) is included;
  another HA server with the same entity IDs must not be substituted.
- `briefing_test_start(...)`: requires an idle, ungrouped, empty development
  queue, Repeat/Autoplay/overlay off, a `library://track/<digits>` URI, the exact
  local HA engine UID and 1–40% speaker volume. Speech is rendered before loading
  the song with ADD (no autostart). Its clip, ownership and mix gains are bound
  before player dispatch. No arbitrary audio URL/path is accepted.
- `briefing_test_control(queue_id, run_id, action)`: status, snooze, restart or
  stop. Every action checks the run/session, source, grouping and exact one-item
  queue. Snooze retains a private stopped owner; restart binds a new session with
  the same song/gain, not another clip. Stop cancels only the owned test, clears
  its one-item queue and conditionally restores the original device volume. A
  stopped run is tombstoned even before a delayed start acquires the lock.

The owning HA test adapter polls idle every two seconds and requests music-only
repetitions; this may leave a gap and is not gapless looping. It uses a 30-minute
HA-side watchdog, runtime-only sessions and explicit stop-uncertainty reporting.
Losing HA stops its future repeats, not necessarily the finite song already
playing. This does not implement production scheduled music alarms or durable
post-restart ownership recovery. See the integration README for the manual panel,
shutdown limitations and separate deployment/publication approvals.

## Validation and remaining work

Offline tests exercise single-use/session ownership, expiry, source cleanup,
stop/pause cancellation, fallback boundaries, and gain/format bounds. Contract
tests verify hashes, render the graph with **MA's actual pinned graph-builder
function**, and run `git apply --check` against disposable source copies.

The offline suite uses a test-double runner. Separately, **four real FFmpeg
tests passed** using Python 3.14.10, FFmpeg 9.0.2 and the actual pinned MA audio
helpers: simultaneous frequency components, finite secondary input, complete
music tail, non-replay, music-only background gain, short-song duration and early consumer closure. These use
synthetic tones, not a provider song or actual TTS, and do not emit device audio.

The isolated environment is under `/data/v2/cache/opencode/ma-native-runtime`.
The complete dependency install failed because `aiolibdatachannel` needs C/C++
compilers unavailable here. Installing the remaining dependencies allowed real
audio-helper execution, **not a full supported server environment**. Importing
the queue controller additionally hit an absent `hass_client` dependency.
No missing modules were stubbed to claim a server startup. No server was started.

To repeat the native audio tests with an equivalent prepared environment:

```text
MA_NATIVE_SOURCE=/path/to/pristine/ma-2.10.12 PATH=/path/to/ffmpeg-directory:$PATH /path/to/ma-python/bin/python -B tests/test_ma_one_shot_native.py
```

The test checks all eleven pinned source hashes before importing actual MA audio
helpers. Without the explicit environment/FFmpeg, it reports skips. The Git tag
was also cloned and verified at commit `6ab5bfa63f02d0daa237d342097a42feae5c5aae`.
This is **not** a claim that a patched MA server booted or that a selected library
song played underneath a real voice briefing on the Echo.

Before deployment or another live test:

1. Test the new command/permissions/locking inside a complete supported MA build.
   Offline command/contract tests are not an authenticated end-to-end API test.
2. Validate the selected HA assistant mapping and provider voice support on the
   actual development build, without substituting a different voice silently.
3. After manual testing, separately design persistent scheduled music-alarm
   ownership and complete all MA stop/source-switch/shutdown paths. The included
   hooks are not a complete audit of every internal MA lifecycle path.
4. Run MA's native tests, real FFmpeg tests and a controlled single-Echo playback
   test in a supported development build. Audit the new module's import/style
   requirements against that build. No installed add-on patching is automated.
5. Obtain separate installation and playback approval. Your working HA-AlarmClock
   integration and installed Music Assistant remain untouched by this prototype.

# Isolated speech-over-music proof

For the subsequent **MA-native** song-main/one-shot-voice prototype, see
[`ma_one_shot/README.md`](ma_one_shot/README.md). That route keeps full-song
playback within MA instead of trying to export songs into this WAV proof.

This prototype is **not installed or called by HA-AlarmClock**. It does not use
Home Assistant credentials, contact a provider, modify a queue, create a public
audio endpoint, or play anything. The working integration is unchanged.

## What it proves

`mixed_audio.py` writes one bounded WAV containing both inputs at the same time:

- The song starts from its beginning, at a separately adjustable gain.
- Speech starts after a short lead-in and plays **once**, not once per music loop.
- The song loops through the remainder of the requested duration.
- `--music-only` renders the song from the beginning with no speech, modelling the
  desired restart after Snooze. It does not itself implement a live Snooze action.
- An output is never overwritten, and inputs and render duration are bounded.
- Mono/stereo speech and different sample rates are handled. The simple linear
  resampler is for this proof, not a claim of production mastering quality.
- Defaults leave headroom. The report counts any clipped samples if higher gains
  are chosen. These gains are **not** an Echo volume setting or loudness guarantee.

Use local, uncompressed **16-bit PCM WAV** files. No bundled song or copied film
audio is included. The coding container does not have FFmpeg; compressed audio
decoding/encoding and delivery on an actual Echo are not tested here.

```text
python3 -B prototypes/mixed_audio.py --music song.wav --speech briefing.wav --output /data/v2/cache/opencode/first-ring.wav --seconds 30
python3 -B prototypes/mixed_audio.py --music song.wav --music-only --output /data/v2/cache/opencode/snooze-restart.wav --seconds 30
python3 -B tests/test_mixed_audio.py
```

The tests generate synthetic sample fixtures in the approved cache directory,
check their actual mixed samples, and never play audio. Synthetic tones are test
fixtures, **not** a replacement for the requested Music Assistant song.

## Music Assistant source boundary — unresolved

Source review used Music Assistant server **2.10.12**, HA **2026.11.1**, and the
HA-pinned Music Assistant Python client **v1.6.0**:

- [`player_queues/overlay`](https://github.com/music-assistant/server/blob/2.10.12/music_assistant/controllers/player_queues/controller.py)
  requires a `sound_effect` media item and loops it. It is not a general one-shot
  TTS input over a selected library song.
- The client's
  [`get_track_preview_url` / `track_preview`](https://github.com/music-assistant/client/blob/v1.6.0/music_assistant_client/music.py)
  expose **short previews**, not a full-song audio export. The server's
  [`get_preview_stream`](https://github.com/music-assistant/server/blob/2.10.12/music_assistant/controllers/streams/controller.py)
  describes a 30-second clip. Do not silently substitute that for a full song.
- Full queue streams validate an active session, queue, item and player. This
  prototype does not invent those IDs, scrape tokens, or start a hidden playback
  session to obtain audio. The normal HA Music Assistant library service returns
  library metadata/URIs, not decoded song bytes.
- The user-observed Kitchen Echo test of normal TTS on the Music Assistant entity
  paused and resumed music. It did not prove simultaneous audio.

A supported full-track input/mixing adapter on the Music Assistant side (or an
explicitly supplied local song file for a limited proof) is still needed before
the requested library-song feature can be considered implemented. A native MA
server/provider extension would be a separate scope decision, not something this
prototype installs. Streaming-service restrictions must be respected.

## Still pending

- Full-song MA acquisition and actual assistant audio generation for this proof.
- A production mixed stream/encoding path that the Kitchen Echo can consume.
- Persistent ownership, stop/dismissal, Snooze and restart recovery for that stream.
- The eventual library picker and per-alarm settings, once the audio route is viable.
- Separate approval for any deployment, restart, source download or playback test.

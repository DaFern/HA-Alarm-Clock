# One-shot server-side speech over music for players without native announcements

> Archived submission text, posted at
> https://github.com/music-assistant/support/discussions/998#discussioncomment-19695063.
> References to uncommitted work below describe the state when it was posted;
> consult the project history and deployment handoff for subsequent publication.

Adding implementation evidence to the existing request rather than opening a
duplicate. I understand native announcements / Sendspin already cover some
players. This proposal targets server-side queue/flow mixing for other playback
paths, tested here with an Echo through MA's Alexa provider.

## Use case

A Home Assistant alarm starts a complete provider song, speaks the selected HA
assistant's finite morning briefing over it once, then leaves the song playing.
Snooze stops playback and restarts that same song from zero **without** repeating
speech. No provider song export or preview-clip substitution is involved.

## Proof of concept

- Base: MA 2.10.12, upstream commit
  `6ab5bfa63f02d0daa237d342097a42feae5c5aae`.
- Published, user-tested companion patch:
  https://github.com/DaFern/music-assistant-alarm-clock-server/commit/d66459f7f7eab48a18e7fb5d6c0768a17da2ef52
- HA consumer project: https://github.com/DaFern/HA-Alarm-Clock
- The song remains the main PCM input. A registered MA TTS engine renders a
  finite second input using the named HA assistant's language and voice.
- FFmpeg mixes with `amix=inputs=2:duration=first:dropout_transition=0:normalize=0`;
  gains leave headroom. The voice is not looped or reconnected and cannot extend
  the song. A draft successor adds a bounded voice lead-in delay.
- The clip is armed against the new queue session **before** stream dispatch,
  and consumed before opening the mixer. Duplicate stream GETs/reconnects do
  not rearm speech. Queue control permission and scope checks remain in MA.
- Private run/session/item ownership guards stop/restart and avoids stopping
  audio that another user has taken over. The published test is deliberately
  restricted to one idle, empty, ungrouped queue, Repeat/Autoplay/overlay off.

## What was and was not verified

The user audibly verified simultaneous music and the assistant briefing,
Dismiss, Snooze restarting the same song without repeated speech, and a full
song playthrough on the Echo. Synthetic real-MA-helper/FFmpeg tests cover the
finite voice, uninterrupted song tail, cancellation and music-only restart.

The successor's selected-song scheduled-alarm API and speech-delay option are
**local, uncommitted release-candidate work**, not included in the linked fork
commit or live-verified. Its tests use fake HA/MA transports and real audio
helpers, not an authenticated production server.

An intermittent Echo restart-to-beginning also occurred, and a similar audiobook
chapter symptom was reported outside this mixing test. There is no proper
reproduction or proven cause. This patch **does not claim to fix reconnect/resume**.

## Upstream design question

Would a small, session-scoped, finite server-side announcement/overlay API be
welcome for players that cannot natively mix announcements? We would prefer an
upstream-supported abstraction over maintaining alarm-specific endpoints.
Dynamic ducking, multi-room synchronization, arbitrary live injection and a
general-purpose public audio-URL API are outside this proof of concept.

Happy to adapt the implementation to the maintainers' preferred queue/stream
abstraction before proposing a PR. This is a feature proposal, not a claim that
the prototype is ready to merge.

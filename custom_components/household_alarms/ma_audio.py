"""Opt-in, runtime-only MA development tests. Never called by the scheduler."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import math
from time import monotonic
import uuid

from .assistants import resolve_assistant
from .model import AlarmError

PROTOCOL = 1
TERMINAL = {"dismissed", "sleeping_in", "finished", "failed", "interrupted"}


def resolve_client(hass, speaker):
    """Use HA's registered MA entity/client; never read or copy its credentials."""
    from homeassistant.helpers import entity_registry
    from homeassistant.components.music_assistant.helpers import get_music_assistant_client

    registered = entity_registry.async_get(hass).async_get(speaker)
    entry = hass.config_entries.async_get_entry(registered.config_entry_id) if registered else None
    if entry is None or entry.domain != "music_assistant":
        raise AlarmError("Choose the Music Assistant development server's speaker entity")
    client = get_music_assistant_client(hass, entry.entry_id)
    player_id = registered.unique_id
    # Resolve by the actual registered identifier, never by a friendly-name match.
    if client.players.get(player_id) is None:
        raise AlarmError("The selected Music Assistant player is unavailable")
    return client, player_id


def resolve_server_id(hass, speaker):
    """Bind library URIs to the exact HA connection, not a reusable entity id."""
    from homeassistant.helpers import entity_registry

    registered = entity_registry.async_get(hass).async_get(speaker)
    if registered is None or not registered.config_entry_id:
        raise AlarmError("The selected Music Assistant speaker has no registered connection")
    return registered.config_entry_id


class MusicTests:
    """One explicitly confirmed test, separate from saved alarms and their runs."""

    def __init__(self, manager, *, resolver=resolve_client, clock=monotonic):
        self.manager = manager
        self.resolver = resolver
        self.clock = clock
        self.task = None
        self.session = None
        self.members = set()
        self.client = None
        self.queue_id = None
        self.event = asyncio.Event()
        self.desired = "playing"
        self.submitted = False
        self.selected = None
        self.protocol = PROTOCOL

    @property
    def active(self):
        return self.session is not None and (
            self.session["status"] not in TERMINAL or self.task is not None and not self.task.done())

    def snapshot(self):
        return deepcopy(self.session)

    async def _send(self, command, *, timeout=90, **kwargs):
        if self.selected is not None:
            command = command.replace("briefing_test_", "alarm_")
        try:
            async with asyncio.timeout(timeout):
                return await self.client.send_command(command, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not expose upstream errors containing personal text or audio URLs.
            raise AlarmError("Music Assistant did not confirm the command. Check its connection and development build; do not retry playback blindly.") from None

    async def async_check(self, speaker, assistant_id):
        pipeline = resolve_assistant(self.manager.hass, assistant_id, voice=True)
        client, queue_id = self.resolver(self.manager.hass, speaker)
        try:
            async with asyncio.timeout(15):
                result = await client.send_command("player_queues/briefing_test_capabilities", queue_id=queue_id)
        except Exception:
            raise AlarmError("This speaker needs the patched MA development build. The normal Music Assistant app is not changed or supported by this test.") from None
        if not isinstance(result, dict) or result.get("protocol") != PROTOCOL:
            raise AlarmError("The MA development test protocol is incompatible")
        matches = [engine for engine in result.get("engines", [])
                   if engine.get("entity_id") == pipeline.tts_engine]
        if len(matches) != 1:
            raise AlarmError("The assistant's exact HA voice must be available through one MA Home Assistant provider. Missing or ambiguous voices are not substituted.")
        reasons = result.get("reasons", [])
        return {"ready": result.get("ready") is True, "reasons": reasons}, client, queue_id, pipeline, matches[0]["uid"]

    async def async_start(self, alarm_id, speaker, confirmation, enabled, music_gain,
                          volume_level, snooze_seconds, *, selected=None):
        if confirmation != "PLAY MUSIC" or enabled is not True:
            raise AlarmError("Enable the experimental test and confirm speaker playback first")
        if self.manager.closed or self.active:
            raise AlarmError("Stop the existing music test before starting another")
        if alarm_id not in self.manager.alarms:
            raise AlarmError("Save an alarm with a selected assistant before testing")
        if any(run.get("status") in ("ringing", "snoozed") for run in self.manager.runs.values()):
            raise AlarmError("Dismiss active alarms before running a music test")
        if (type(music_gain) not in (int, float) or not math.isfinite(music_gain)
                or not 0 <= music_gain <= 0.3):
            raise AlarmError("Background music gain must be between 0 and 30 percent")
        if type(volume_level) is not int or not 1 <= volume_level <= (100 if selected else 40):
            raise AlarmError("Test speaker volume must be between 1 and 40 percent")
        if type(snooze_seconds) is not int or not 5 <= snooze_seconds <= (1800 if selected else 300):
            raise AlarmError("Test snooze must be between 5 and 300 seconds")
        if not isinstance(speaker, str) or not speaker.startswith("media_player."):
            raise AlarmError("Choose a Music Assistant speaker")
        alarm = deepcopy(self.manager.alarms[alarm_id])
        self.selected = deepcopy(selected)
        self.protocol = 2 if selected else PROTOCOL
        run_id = str(uuid.uuid4())
        # Reserve synchronously before any network operation can interleave.
        self.members = self.manager._reserve(speaker, run_id)
        self.session = {"id": run_id, "alarm_id": alarm_id, "speaker": speaker,
                        "status": "preparing", "track": "", "message": "Checking the development server…",
                        "volume_level": volume_level, "music_gain": music_gain,
                        "snooze_seconds": snooze_seconds, "max_minutes": 30}
        self.event = asyncio.Event()
        self.desired = "playing"
        self.submitted = False
        self.client = None
        self.queue_id = None
        self.task = self.manager.hass.async_create_background_task(
            self._run(alarm), "household_alarms_music_test")
        self.manager.changed()
        return self.snapshot()

    async def async_start_selected(self, alarm):
        """Explicit saved-alarm test; never starts automatically or changes schedules."""
        return await self.async_start(alarm["id"], alarm["speaker"], "PLAY MUSIC", True,
            alarm["music_gain"] / 100, alarm["start_volume"], alarm["snooze_minutes"] * 60,
            selected=alarm)

    async def async_action(self, session_id, action):
        if not self.active or self.session["id"] != session_id:
            raise AlarmError("This music-test session is no longer active")
        if action not in ("snooze", "dismiss", "sleep_in"):
            raise AlarmError("Unknown music-test action")
        if action == "snooze" and self.session["status"] != "playing":
            raise AlarmError("Wait for the music test to start before snoozing")
        self.desired = "snoozed" if action == "snooze" else "dismissed" if action == "dismiss" else "sleeping_in"
        self.session["message"] = "Stopping the test…" if action != "snooze" else "Stopping music for the test snooze…"
        self.event.set()
        if self.task is None or self.task.done():
            # Explicit retry may only issue a guarded stop, never another start.
            self.task = self.manager.hass.async_create_background_task(self._finish(), "household_alarms_music_test_stop")
        self.manager.changed()
        return self.snapshot()

    async def _control(self, action):
        result = await self._send("player_queues/briefing_test_control", queue_id=self.queue_id,
                                  run_id=self.session["id"], action=action)
        if not isinstance(result, dict) or result.get("protocol") != self.protocol:
            raise AlarmError("MA returned an incompatible test-control response")
        return result

    async def _run(self, alarm):
        try:
            if self.selected is None:
                check, self.client, self.queue_id, pipeline, engine_uid = await self.async_check(
                    self.session["speaker"], alarm["assistant_id"])
            else:
                from .music import capabilities
                self.client, self.queue_id = self.resolver(self.manager.hass, self.session["speaker"])
                if resolve_server_id(self.manager.hass, self.session["speaker"]) != alarm["music_server"]:
                    raise AlarmError("The Music Assistant connection changed. Reselect this alarm's song before testing")
                check = await capabilities(self.client, self.queue_id)
                pipeline, engine_uid = None, ""
                if alarm["assistant_id"] or alarm["briefing_enabled"]:
                    pipeline = resolve_assistant(self.manager.hass, alarm["assistant_id"], voice=True)
                    engines = [item for item in check.get("engines", []) if item.get("entity_id") == pipeline.tts_engine]
                    if len(engines) != 1:
                        raise AlarmError("The assistant's exact HA voice is unavailable or ambiguous in Music Assistant")
                    engine_uid = engines[0]["uid"]
            if not check["ready"]:
                raise AlarmError("; ".join(check["reasons"]))
            tracks = ([{"uri": alarm["music_track"], "name": alarm["music_track_name"]}]
                      if self.selected else await self._send("music/tracks/library_items", limit=1, offset=0, order_by="random"))
            if isinstance(tracks, dict):
                tracks = tracks.get("items", [])
            if not isinstance(tracks, list) or not tracks:
                raise AlarmError("The development server needs at least one library song")
            track = tracks[0]
            uri = track.get("uri", "")
            if not isinstance(uri, str) or not uri.startswith("library://track/"):
                raise AlarmError("MA did not return a playable library song")
            self.session["track"] = str(track.get("name", "Library song"))[:200]
            self.session["message"] = "Preparing the selected assistant's morning message…"
            self.manager.changed()
            text = ""
            if pipeline is not None:
                try:
                    text = await self.manager.async_briefing(alarm, pipeline)
                except Exception:
                    text = f"Good morning, {alarm['person'] or alarm['name']}. It is time to get up."
            if self.desired != "playing":
                return
            # Mark before sending: a lost response is an uncertain attempt, never a retry.
            self.submitted = True
            extra = {"speech_delay": alarm["speech_delay"]} if self.selected else {"speech_gain": 0.7}
            result = await self._send("player_queues/briefing_test_start", queue_id=self.queue_id,
                run_id=self.session["id"], track_uri=uri, message=text, tts_engine=engine_uid,
                language=pipeline.tts_language if pipeline else None, voice=pipeline.tts_voice if pipeline else None,
                music_gain=self.session["music_gain"], **extra,
                volume_level=self.session["volume_level"])
            if not isinstance(result, dict) or result.get("protocol") != self.protocol:
                raise AlarmError("MA did not confirm a compatible music-test start")
            self.session.update(status="playing", message="Listen for music under the message. Acceptance does not prove it was audible.")
            self.manager.changed()
            expires = self.clock() + 1800
            snooze_until = 0
            while self.desired not in ("dismissed", "sleeping_in") and self.clock() < expires:
                self.event.clear()
                status = await self._control("status")
                if self.desired in ("dismissed", "sleeping_in"):
                    break
                if not status.get("owned"):
                    self.session.update(status="interrupted", message="Playback changed elsewhere. The test released control without stopping other audio.")
                    return
                if self.desired == "snoozed" and self.session["status"] == "playing":
                    stopped = await self._control("snooze")
                    if not stopped.get("owned"):
                        raise AlarmError("The test no longer owns this playback")
                    snooze_until = self.clock() + self.session["snooze_seconds"]
                    self.session.update(status="snoozed", message="Test snooze: the same song will restart from the beginning, without the message.")
                    self.manager.changed()
                elif self.session["status"] == "snoozed" and self.clock() >= snooze_until:
                    self.desired = "playing"
                    restarted = await self._control("restart")
                    if not restarted.get("owned"):
                        raise AlarmError("The test no longer owns this playback")
                    self.session.update(status="playing", message="Music only. The morning message will not repeat.")
                    self.manager.changed()
                elif self.session["status"] == "playing" and status.get("state") == "idle":
                    restarted = await self._control("restart")
                    if not restarted.get("owned"):
                        raise AlarmError("The test no longer owns this playback")
                try:
                    await asyncio.wait_for(self.event.wait(), timeout=2)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            self.desired = "dismissed"
            raise
        except Exception as err:
            self.session.update(status="failed", message=str(err) if isinstance(err, AlarmError) else "The development music test failed. Check MA and the chosen assistant.")
        finally:
            await self._finish()

    async def _finish(self):
        interrupted = self.session["status"] == "interrupted"
        try:
            if self.submitted and not interrupted:
                result = await self._control("stop")
                if not result.get("owned"):
                    self.session.update(status="interrupted", message="The test no longer owns this session. Other playback was left alone.")
            if self.session["status"] not in TERMINAL:
                self.session.update(status=self.desired if self.desired in TERMINAL else "finished",
                                    message="Music test stopped. Saved alarms and sleep switches were not changed.")
        except Exception:
            self.session.update(status="uncertain", message="MA could not confirm the stop. Check the speaker, then press Dismiss to retry a guarded stop. No playback will be retried.")
        finally:
            if self.session["status"] != "uncertain":
                for member in self.members:
                    if self.manager.owners.get(member) == self.session["id"]:
                        self.manager.owners.pop(member)
                self.members.clear()
            self.manager.changed()

    async def async_shutdown(self):
        if not self.active:
            return
        await self.async_action(self.session["id"], "dismiss")
        try:
            async with asyncio.timeout(15):
                await asyncio.shield(self.task)
        except TimeoutError:
            # HA may be stopping; a pending command cannot be assumed cancelled remotely.
            self.session.update(status="uncertain", message="Shutdown could not confirm the music-test stop. Check the speaker manually.")

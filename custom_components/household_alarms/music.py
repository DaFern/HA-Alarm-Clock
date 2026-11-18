"""Selected-song alarms using a versioned, ownership-checked MA companion API."""

from __future__ import annotations

import asyncio
import re
import uuid

from .assistants import resolve_assistant
from .ma_audio import resolve_client, resolve_server_id
from .model import AlarmError, volume

PROTOCOL = 2
FEATURES = {"selected_track", "speech_delay", "music_only"}


async def command(client, name, *, timeout=90, **data):
    """Never expose upstream exceptions containing credentials or private speech."""
    try:
        async with asyncio.timeout(timeout):
            return await client.send_command(name, **data)
    except asyncio.CancelledError:
        raise
    except Exception:
        raise AlarmError("Music Assistant did not confirm the operation. Check the pinned HA-AlarmClock companion build and speaker; playback is not retried blindly.") from None


async def capabilities(client, queue_id):
    result = await command(client, "player_queues/alarm_capabilities", queue_id=queue_id, timeout=15)
    if not isinstance(result, dict) or result.get("protocol") != PROTOCOL or not FEATURES <= set(result.get("features", [])):
        raise AlarmError("Music alarms require the compatible pinned HA-AlarmClock MA companion (protocol 2)")
    return result


async def search_tracks(hass, speaker, query, *, resolver=resolve_client, server_resolver=resolve_server_id):
    """Read only the selected speaker's library; return bounded public metadata."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 100:
        raise AlarmError("Enter between one and 100 characters to search for a song")
    client, queue_id = resolver(hass, speaker)
    server_id = server_resolver(hass, speaker)
    await capabilities(client, queue_id)
    rows = await command(client, "music/tracks/library_items", search=query.strip(), limit=20, offset=0, timeout=15)
    if isinstance(rows, dict):
        rows = rows.get("items", [])
    if not isinstance(rows, list):
        raise AlarmError("Music Assistant returned an invalid song list")
    result = []
    for row in rows[:20]:
        if not isinstance(row, dict) or not re.fullmatch(r"library://track/[0-9]{1,20}", str(row.get("uri", ""))):
            continue
        artists = ", ".join(str(item.get("name", ""))[:100] for item in row.get("artists", [])[:3] if isinstance(item, dict))
        name = str(row.get("name", "Song"))[:200]
        result.append({"uri": row["uri"], "name": (name + (" — " + artists if artists else ""))[:300]})
    if server_resolver(hass, speaker) != server_id:
        raise AlarmError("The Music Assistant connection changed while searching. Search again")
    return {"server_id": server_id, "tracks": result}


class AlarmMusic:
    """One persisted alarm delivery, held until cancellation or external takeover.

    The start id is saved before dispatch. Following an unclean restart it may
    only reattach to that exact owned session, never submit a replacement start.
    """

    def __init__(self, manager, alarm, run, *, resolver=resolve_client, server_resolver=resolve_server_id):
        self.manager = manager
        self.alarm = alarm
        self.run = run
        self.resolver = resolver
        self.server_resolver = server_resolver
        self.client = None
        self.queue_id = None
        self.attempt = run.get("music_attempt")
        self.submitted = bool(self.attempt)
        self.takeover = False

    async def control(self, action):
        result = await command(self.client, "player_queues/alarm_control", queue_id=self.queue_id,
                               run_id=self.attempt, action=action, timeout=15)
        if not isinstance(result, dict) or result.get("protocol") != PROTOCOL or type(result.get("owned")) is not bool:
            raise AlarmError("Music Assistant returned an incompatible alarm-control response")
        return result

    async def _persist(self, **fields):
        async with self.manager.lock:
            if self.manager.runs.get(self.alarm["id"]) is not self.run:
                raise AlarmError("This alarm run was replaced")
            previous = dict(self.run)
            self.run.update(fields)
            try:
                await self.manager._save()
            except BaseException:
                self.run.clear()
                self.run.update(previous)
                raise

    async def play(self):
        self.client, self.queue_id = self.resolver(self.manager.hass, self.alarm["speaker"])
        if self.server_resolver(self.manager.hass, self.alarm["speaker"]) != self.alarm["music_server"]:
            await self._persist(music_blocked=True)
            raise AlarmError("The Music Assistant connection changed. Reselect this alarm's song before enabling music")
        if self.run.get("music_blocked"):
            raise AlarmError("Music playback needs attention. Dismiss this run and check the speaker before trying again")
        try:
            if not self.submitted:
                ready = await capabilities(self.client, self.queue_id)
                if ready.get("ready") is not True:
                    raise AlarmError("; ".join(ready.get("reasons", [])) or "The music speaker is not ready")
                message, engine, pipeline = "", "", None
                wants_speech = not self.run.get("briefing_attempted") and bool(
                    self.alarm["assistant_id"] or self.alarm["briefing_enabled"])
                if wants_speech:
                    # Save before generation too: cancellation/restart never repeats speech.
                    await self._persist(briefing_attempted=True)
                    try:
                        pipeline = resolve_assistant(self.manager.hass, self.alarm["assistant_id"], voice=True)
                        engines = [item for item in ready.get("engines", []) if item.get("entity_id") == pipeline.tts_engine]
                        if len(engines) != 1:
                            raise AlarmError("The assistant's exact HA voice is unavailable or ambiguous in Music Assistant")
                        engine = engines[0]["uid"]
                        try:
                            message = await self.manager.async_briefing(self.alarm, pipeline)
                        except Exception:
                            message = f"Good morning, {self.alarm['person'] or self.alarm['name']}. It is time to get up."
                    except AlarmError as err:
                        self.manager.warnings[f"assistant:{self.alarm['id']}"] = str(err)
                        pipeline = None
                self.attempt = str(uuid.uuid4())
                if self.manager.closed or self.run["status"] != "ringing":
                    return
                if self.server_resolver(self.manager.hass, self.alarm["speaker"]) != self.alarm["music_server"]:
                    await self._persist(music_blocked=True)
                    raise AlarmError("The Music Assistant connection changed during message preparation; playback was not started")
                await self._persist(music_attempt=self.attempt)
                # Once persisted, even a timeout/cancellation is an uncertain dispatch.
                self.submitted = True
                result = await command(self.client, "player_queues/alarm_start", queue_id=self.queue_id,
                    run_id=self.attempt, track_uri=self.alarm["music_track"], message=message,
                    tts_engine=engine, language=pipeline.tts_language if pipeline else None,
                    voice=pipeline.tts_voice if pipeline else None, music_gain=self.alarm["music_gain"] / 100,
                    speech_delay=self.alarm["speech_delay"],
                    volume_level=round(volume(self.alarm, self.run["cycles"], self.run.get("escalated", False)) * 100))
                if not isinstance(result, dict) or result.get("protocol") != PROTOCOL or result.get("status") != "playing":
                    raise AlarmError("Music Assistant did not confirm the alarm start")
                await self._persist(error="", cycles=self.run["cycles"] + 1)
                self.manager.changed()
            while True:
                state = await self.control("status")
                if not state["owned"]:
                    self.takeover = True
                    await self._persist(music_blocked=True, music_attempt=None, error="Music playback changed elsewhere. Other audio was left alone; dismiss this alarm to finish.")
                    return
                if state.get("state") == "idle":
                    # MA checks ownership again under its queue lock. Speech is not rearmed.
                    restarted = await self.control("restart")
                    if not restarted["owned"]:
                        raise AlarmError("The alarm no longer owns the music queue")
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception:
            if self.submitted:
                await self._persist(music_blocked=True)
            raise
        finally:
            if self.submitted and not self.takeover:
                await self.stop()

    async def stop(self):
        """Also allow an explicit dismissal to retry an uncertain guarded stop."""
        try:
            if self.client is None:
                self.client, self.queue_id = self.resolver(self.manager.hass, self.alarm["speaker"])
            if self.server_resolver(self.manager.hass, self.alarm["speaker"]) != self.alarm["music_server"]:
                raise AlarmError("The Music Assistant connection changed; other playback was left alone")
            stopped = await self.control("stop")
            if not stopped["owned"]:
                raise AlarmError("The music stop was not confirmed")
            await self._persist(music_attempt=None)
        except Exception:
            await self._persist(music_blocked=True,
                error="Music Assistant could not confirm the stop. Check the speaker manually before relying on this alarm.")

"""Selected-song alarms using a versioned, ownership-checked MA companion API."""

from __future__ import annotations

import asyncio
import re
import time
import uuid

from .assistants import resolve_assistant
from .ma_audio import resolve_client, resolve_server_id
from .model import AlarmError, morning_message_due, volume

PROTOCOL = 2
FEATURES = {
    "selected_track", "speech_delay", "music_only", "preserve_queue",
    "restore_playback", "queue_mode_lease",
}


async def command(client, name, *, timeout=90, **data):
    """Never expose upstream exceptions containing credentials or private speech."""
    try:
        async with asyncio.timeout(timeout):
            return await client.send_command(name, **data)
    except asyncio.CancelledError:
        raise
    except Exception:
        raise AlarmError("Music Assistant did not confirm the operation. Check Music Assistant and the speaker before trying playback again.") from None


async def capabilities(client, queue_id):
    result = await command(client, "player_queues/alarm_capabilities", queue_id=queue_id, timeout=15)
    if not isinstance(result, dict) or result.get("protocol") != PROTOCOL or not FEATURES <= set(result.get("features", [])):
        raise AlarmError("This version of Music Assistant does not support music alarms. Update Music Assistant.")
    modes = result.get("queue_modes")
    if (not isinstance(modes, dict)
            or not isinstance(modes.get("repeat_mode"), str)
            or (modes.get("autoplay_override") is not None
                and type(modes.get("autoplay_override")) is not bool)
            or type(modes.get("autoplay_enabled")) is not bool):
        raise AlarmError("Music Assistant could not confirm the queue's Repeat and Autoplay settings. Check Music Assistant before trying again.")
    return result


def require_ramp(alarm, ready):
    if alarm.get("music_ramp_enabled") and "volume_ramp" not in ready.get("features", []):
        raise AlarmError("This version of Music Assistant does not support timed volume increases. Update Music Assistant or turn off the volume ramp.")


class MusicVolumeRamp:
    """One ring's timer: no elapsed-time catch-up and no media commands.

    The companion checks the exact playback owner and detects manual volume
    changes before each write. A failed write suspends this ring, not its music.
    """

    def __init__(self, alarm, client, queue_id, run_id, *, clock=time.monotonic, suspended=False):
        self.alarm, self.client, self.queue_id, self.run_id = alarm, client, queue_id, run_id
        self.clock = clock
        self.suspended = suspended
        self.level = None
        self.next_at = clock() + alarm["music_ramp_seconds"]

    async def tick(self):
        if not self.alarm.get("music_ramp_enabled"):
            return None
        try:
            # Keep observing even after suspension, so further manual changes
            # remain authoritative across natural song repeats and cleanup.
            status = await command(self.client, "player_queues/alarm_volume",
                queue_id=self.queue_id, run_id=self.run_id, timeout=15)
            if not isinstance(status, dict) or status.get("protocol") != PROTOCOL or not status.get("owned"):
                raise AlarmError("Music volume ownership was not confirmed")
            level = status.get("volume_level")
            if type(status.get("suspended")) is not bool or status["suspended"] or type(level) is not int or not 0 <= level <= 100:
                self.suspended = True
                return "Music volume changed or is unavailable; automatic increases are paused for this ring."
            self.level = level
            if self.suspended:
                return None
            if status.get("state") != "playing":
                self.next_at = self.clock() + self.alarm["music_ramp_seconds"]
                return None
            now = self.clock()
            if now < self.next_at or level >= self.alarm["max_volume"]:
                return None
            target = min(self.alarm["max_volume"], level + self.alarm["music_ramp_step"])
            result = await command(self.client, "player_queues/alarm_volume", queue_id=self.queue_id,
                run_id=self.run_id, volume_level=target, timeout=15)
            if (not isinstance(result, dict) or result.get("protocol") != PROTOCOL or not result.get("owned")
                    or result.get("suspended") or result.get("volume_level") != target):
                raise AlarmError("Music volume increase was not confirmed")
            self.level = target
            self.next_at = self.clock() + self.alarm["music_ramp_seconds"]
        except asyncio.CancelledError:
            raise
        except Exception:
            self.suspended = True
            return "Music volume increase was not confirmed; further increases are paused for this ring. Music was not restarted."
        return None


async def search_tracks(hass, speaker, query, *, resolver=resolve_client, server_resolver=resolve_server_id):
    """Search the selected speaker's library; tolerate terms in any order."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 100:
        raise AlarmError("Enter between one and 100 characters to search for a song")
    client, queue_id = resolver(hass, speaker)
    server_id = server_resolver(hass, speaker)
    await capabilities(client, queue_id)
    query = query.strip()
    terms = list(dict.fromkeys(re.findall(r"[^\W_]+", query.casefold())))[:6]

    async def search_rows(search):
        rows = await command(
            client, "music/tracks/library_items",
            search=search, limit=20, offset=0, timeout=15,
        )
        if isinstance(rows, dict):
            rows = rows.get("items", [])
        if not isinstance(rows, list):
            raise AlarmError("Music Assistant returned an invalid song list")
        return rows[:20]

    rows = await search_rows(query)

    def row_terms(row):
        artists = row.get("artists", [])
        artist_names = [
            str(item.get("name", "")) for item in artists[:3]
            if isinstance(item, dict)
        ] if isinstance(artists, list) else []
        return set(re.findall(
            r"[^\W_]+", " ".join([str(row.get("name", "")), *artist_names]).casefold()
        ))

    # Some MA search providers treat a multi-word query like an exact phrase.
    # Only fan out when the phrase search did not return an all-term match.
    if terms and not any(all(term in row_terms(row) for term in terms) for row in rows if isinstance(row, dict)):
        token_rows = await asyncio.gather(*(search_rows(term) for term in terms))
        rows = [*rows, *(row for group in token_rows for row in group)]

    unique_rows = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        uri = str(row.get("uri", ""))
        if re.fullmatch(r"library://track/[0-9]{1,20}", uri):
            unique_rows.setdefault(uri, row)

    rows = sorted(
        unique_rows.values(),
        key=lambda row: (
            -sum(term in row_terms(row) for term in terms),
            str(row.get("name", "")).casefold(),
        ),
    )
    result = []
    for row in rows[:20]:
        artists_data = row.get("artists", [])
        artists = ", ".join(
            str(item.get("name", ""))[:100] for item in artists_data[:3]
            if isinstance(item, dict)
        ) if isinstance(artists_data, list) else ""
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
                               run_id=self.attempt, action=action,
                               queue_modes=self.run.get("music_queue_modes"), timeout=15)
        if not isinstance(result, dict) or result.get("protocol") != PROTOCOL or type(result.get("owned")) is not bool:
            raise AlarmError("Music Assistant returned an incompatible alarm-control response")
        return result

    async def restore_queue_modes(self):
        """Restore settings after takeover without issuing any playback command."""
        result = await command(self.client, "player_queues/alarm_control", queue_id=self.queue_id,
            run_id=self.attempt, action="restore_modes",
            queue_modes=self.run.get("music_queue_modes"), timeout=15)
        if (not isinstance(result, dict) or result.get("protocol") != PROTOCOL
                or type(result.get("owned")) is not bool or result["owned"]):
            raise AlarmError("Music Assistant could not safely restore the alarm queue settings")

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
                require_ramp(self.alarm, ready)
                if ready.get("ready") is not True:
                    raise AlarmError("; ".join(ready.get("reasons", [])) or "The music speaker is not ready")
                await self._persist(music_queue_modes=ready["queue_modes"])
                message, engine, pipeline = "", "", None
                wants_speech = morning_message_due(self.alarm, self.run) and bool(
                    self.alarm["assistant_id"] or self.alarm["briefing_enabled"])
                if wants_speech:
                    # Save before generation too: cancellation/restart never repeats speech.
                    await self._persist(briefing_attempted=True, briefing_snooze=self.run.get("snoozes", 0))
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
                if self.alarm.get("music_ramp_enabled"):
                    await self._persist(music_ramp_suspended=False)
                    self.manager.warnings.pop(f"volume:{self.alarm['id']}", None)
                # Once persisted, even a timeout/cancellation is an uncertain dispatch.
                self.submitted = True
                result = await command(self.client, "player_queues/alarm_start", queue_id=self.queue_id,
                    run_id=self.attempt, track_uri=self.alarm["music_track"], message=message,
                    tts_engine=engine, language=pipeline.tts_language if pipeline else None,
                    voice=pipeline.tts_voice if pipeline else None, music_gain=self.alarm["music_gain"] / 100,
                    speech_delay=self.alarm["speech_delay"],
                    queue_modes=self.run["music_queue_modes"],
                    volume_level=round(volume(self.alarm, 0 if self.alarm.get("music_ramp_enabled") else self.run["cycles"], self.run.get("escalated", False)) * 100))
                if not isinstance(result, dict) or result.get("protocol") != PROTOCOL or result.get("status") != "playing":
                    raise AlarmError("Music Assistant did not confirm the alarm start")
                await self._persist(error="", cycles=self.run["cycles"] + 1)
                self.manager.changed()
            elif self.alarm.get("music_ramp_enabled"):
                require_ramp(self.alarm, await capabilities(self.client, self.queue_id))
            ramp = MusicVolumeRamp(self.alarm, self.client, self.queue_id, self.attempt,
                suspended=self.run.get("music_ramp_suspended", False))
            while True:
                state = await self.control("status")
                if not state["owned"]:
                    self.takeover = True
                    await self._persist(music_blocked=True, error="Music playback changed elsewhere. Other audio was left alone; dismiss this alarm to finish.")
                    await self.restore_queue_modes()
                    return
                warning = await ramp.tick()
                if ramp.suspended and not self.run.get("music_ramp_suspended"):
                    await self._persist(music_ramp_suspended=True)
                if warning and self.manager.warnings.get(f"volume:{self.alarm['id']}") != warning:
                    self.manager.warnings[f"volume:{self.alarm['id']}"] = warning
                    self.manager.changed()
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
            stopped = await self.control("snooze" if self.run.get("status") == "snoozed" else "stop")
            if not stopped["owned"] and not stopped.get("released"):
                raise AlarmError("The music stop was not confirmed")
            if stopped.get("restoration_failed"):
                raise AlarmError("Previous music restoration was not confirmed")
            await self._persist(music_attempt=None, music_queue_modes=None)
        except Exception:
            await self._persist(music_blocked=True,
                error="Music Assistant could not confirm the stop. Check the speaker manually before relying on this alarm.")

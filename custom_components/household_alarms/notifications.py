"""Opt-in Companion alarm controls; delivery never blocks speaker playback."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import html
import re
from time import monotonic
import uuid

from homeassistant.util import dt as dt_util

from .model import AlarmError, snooze_until

PREFIX = "HOUSEHOLD_ALARM"
ACTIVE = {"ringing", "snoozed"}


def phone_targets(hass):
    """Only public registration metadata; never return mobile-app credentials."""
    from homeassistant.util import slugify

    services = hass.services.async_services().get("notify", {})
    platforms = {}
    entries = getattr(getattr(hass, "config_entries", None), "async_entries", None)
    for entry in entries("mobile_app") if entries else []:
        name = "mobile_app_" + slugify(str(entry.data.get("device_name", "")))
        platforms.setdefault(name, []).append(str(entry.data.get("os_name", "")).casefold())
    android = {name for name, values in platforms.items() if values == ["android"]}
    return [{"service": "notify." + name, "android": name in android}
            for name in sorted(services) if name.startswith("mobile_app_")]


def can_snooze(alarm, run):
    if run["status"] != "ringing" or run.get("escalated"):
        return False
    try:
        snooze_until(alarm, run, dt_util.now())
        return True
    except AlarmError:
        return False


def tag_for(alarm_id, run):
    occurrence = hashlib.sha256(run["started"].encode()).hexdigest()[:16]
    return f"household_alarms:{alarm_id}:{occurrence}"


class AlarmNotifications:
    """Serialize updates with occurrence-scoped Dismiss and phase-scoped Snooze.

    Action tokens are scoped to the exact active occurrence (and phase for Snooze). Anyone with
    access to the selected phone's lock screen can use its buttons by design.
    """

    def __init__(self, manager, *, targets=phone_targets, clock=monotonic):
        self.manager = manager
        self.targets = targets
        self.clock = clock
        self.task = None
        self.dirty = False
        self.last = {}
        self.shown = {}
        self.retry_after = {}

    def schedule(self):
        if self.manager.closed:
            return
        if not self.shown and not any(a.get("phone_enabled") for a in self.manager.alarms.values()) and not any(r.get("phone_target") for r in self.manager.runs.values()):
            return
        self.dirty = True
        if self.task is None or self.task.done():
            self.task = self.manager.hass.async_create_background_task(self._work(), "household_alarms_phone_controls")

    async def _work(self):
        while self.dirty and not self.manager.closed:
            self.dirty = False
            for alarm_id in set(self.manager.alarms) | set(self.shown):
                if self.clock() < self.retry_after.get(alarm_id, 0):
                    continue
                try:
                    await self._sync(alarm_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Notification/provider errors may include private endpoints.
                    self.retry_after[alarm_id] = self.clock() + 30
                    self.manager.warnings[f"phone:{alarm_id}"] = "Phone alarm controls could not be sent or cleared. Speaker playback is unchanged; check the Companion app and phone."
                    self.manager.changed()

    async def _persist(self, alarm_id, run, **values):
        async with self.manager.lock:
            if self.manager.runs.get(alarm_id) is not run:
                self.dirty = True
                return False
            previous = deepcopy(run)
            run.update(values)
            try:
                await self.manager._save()
            except BaseException:
                run.clear()
                run.update(previous)
                raise
        return True

    async def _send(self, service, data):
        if not re.fullmatch(r"notify\.mobile_app_[a-z0-9_]+", service):
            raise AlarmError("Select one Companion app phone for alarm controls")
        await self.manager._call("notify", service.split(".", 1)[1], data, timeout=15)

    async def _clear(self, service, tag):
        await self._send(service, {"message": "clear_notification", "data": {"tag": tag}})

    async def _sync(self, alarm_id):
        alarm = self.manager.alarms.get(alarm_id)
        run = self.manager.runs.get(alarm_id)
        active = bool(alarm and run and alarm.get("phone_enabled") and run["status"] in ACTIVE)
        target = alarm["phone_service"] if active else None
        tag = tag_for(alarm_id, run) if run else None
        previous = self.shown.get(alarm_id)
        if previous and (not active or previous != (target, tag)):
            await self._clear(*previous)
            self.shown.pop(alarm_id, None)
            self.last.pop(alarm_id, None)
        if not active:
            if run and run.get("phone_target"):
                if previous != (run["phone_target"], tag):
                    await self._clear(run["phone_target"], tag)
                await self._persist(alarm_id, run, phone_target="", phone_token="", phone_dismiss_token="")
            return
        if run.get("phone_target") and run["phone_target"] != target and previous != (run["phone_target"], tag):
            await self._clear(run["phone_target"], tag)
        snooze = can_snooze(alarm, run)
        fingerprint = (run["started"], run["status"], run["snoozes"], run.get("escalated", False),
                       target, alarm["name"], alarm["phone_wake_screen"], snooze)
        if self.last.get(alarm_id) == fingerprint:
            return
        token = uuid.uuid4().hex
        dismiss_token = run.get("phone_dismiss_token")
        if not dismiss_token or run.get("phone_target") != target:
            dismiss_token = uuid.uuid4().hex
        if not await self._persist(alarm_id, run, phone_token=token, phone_target=target,
                                   phone_dismiss_token=dismiss_token):
            return
        # A phase change during persistence must not publish stale controls.
        if run["status"] != fingerprint[1] or run["snoozes"] != fingerprint[2]:
            self.dirty = True
            return
        actions = [{"action": f"{PREFIX}:{alarm_id}:{dismiss_token}:dismiss", "title": "Dismiss", "authenticationRequired": False}]
        if snooze:
            actions.append({"action": f"{PREFIX}:{alarm_id}:{token}:snooze", "title": f"Snooze {alarm['snooze_minutes']} min", "authenticationRequired": False})
        data = {"tag": tag, "channel": "HA-AlarmClock controls", "importance": "high",
                "priority": "high", "ttl": 0, "visibility": "public", "persistent": True,
                "sticky": True, "alert_once": True, "notification_icon": "mdi:alarm", "actions": actions}
        status = "Alarm ringing" if run["status"] == "ringing" else "Snoozed until " + run["next_ring"]
        await self._send(target, {"title": "HA-AlarmClock", "message": html.escape(alarm["name"]) + " — " + status, "data": data})
        self.shown[alarm_id] = (target, tag)
        self.last[alarm_id] = fingerprint
        self.manager.warnings.pop(f"phone:{alarm_id}", None)
        if run["status"] == "ringing" and alarm["phone_wake_screen"]:
            android = any(item["service"] == target and item["android"] for item in self.targets(self.manager.hass))
            if android and run.get("phone_token") == token:
                try:
                    await self._send(target, {"message": "command_screen_on", "data": {"priority": "high", "ttl": 0}})
                except Exception:
                    self.manager.warnings[f"phone:{alarm_id}"] = "Phone controls were submitted, but screen wake was not confirmed. Check the Android Companion settings."
            elif not android:
                self.manager.warnings[f"phone:{alarm_id}"] = "Phone controls were submitted. Screen wake requires an identified Android Companion phone; lock-screen visibility depends on phone settings."

    async def async_event(self, event):
        action = event.data.get("action")
        if not isinstance(action, str) or len(action) > 160:
            return
        parts = action.split(":")
        if len(parts) != 4 or parts[0] != PREFIX or parts[3] not in ("dismiss", "snooze") or not re.fullmatch(r"[0-9a-f]{32}", parts[2]):
            return
        try:
            await self.manager.async_action(parts[1], parts[3], phone_token=parts[2])
        except AlarmError:
            # Stale, duplicate, terminal, cross-occurrence or disallowed snooze.
            return
        except Exception:
            self.manager.warnings[f"phone:{parts[1]}"] = "The phone action was not confirmed. Check this alarm in Home Assistant before retrying; playback was not assumed stopped."
            self.manager.changed()

    async def async_shutdown(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

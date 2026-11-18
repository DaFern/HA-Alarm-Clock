"""Authenticated, administrator-only alarm management and explicit audio tests."""

import asyncio

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .model import AlarmError
from .music import search_tracks


def manager_for(hass):
    if DOMAIN not in hass.data:
        raise HomeAssistantError("Add the HA-AlarmClock integration first")
    return hass.data[DOMAIN]


@websocket_api.websocket_command({"type": "household_alarms/list"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_list(hass, connection, msg):
    connection.send_result(msg["id"], manager_for(hass).snapshot())


@websocket_api.websocket_command({"type": "household_alarms/subscribe"})
@websocket_api.require_admin
@callback
def ws_subscribe(hass, connection, msg):
    manager = manager_for(hass)

    @callback
    def update():
        connection.send_event(msg["id"], manager.snapshot())

    manager.listeners.add(update)
    connection.subscriptions[msg["id"]] = lambda: manager.listeners.discard(update)
    connection.send_result(msg["id"])
    update()


@websocket_api.websocket_command({
    "type": "household_alarms/save", vol.Required("config"): dict,
    vol.Required("expected_revision"): int, vol.Optional("alarm_id"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save(hass, connection, msg):
    try:
        manager = manager_for(hass)
        alarm_id = await manager.async_put(msg["config"], msg["expected_revision"], msg.get("alarm_id"))
        connection.send_result(msg["id"], {"alarm_id": alarm_id, "revision": manager.revision})
    except AlarmError as err:
        connection.send_error(msg["id"], "invalid_alarm", str(err))


@websocket_api.websocket_command({
    "type": "household_alarms/delete", vol.Required("alarm_id"): str,
    vol.Required("expected_revision"): int,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete(hass, connection, msg):
    try:
        await manager_for(hass).async_delete(msg["alarm_id"], msg["expected_revision"])
        connection.send_result(msg["id"], {})
    except AlarmError as err:
        connection.send_error(msg["id"], "invalid_alarm", str(err))


@websocket_api.websocket_command({
    "type": "household_alarms/action", vol.Required("alarm_id"): str,
    vol.Required("action"): vol.In(["snooze", "dismiss", "sleep_in"]),
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_action(hass, connection, msg):
    try:
        await manager_for(hass).async_action(msg["alarm_id"], msg["action"])
        connection.send_result(msg["id"], {})
    except AlarmError as err:
        connection.send_error(msg["id"], "invalid_alarm", str(err))


@websocket_api.websocket_command({
    "type": "household_alarms/test", vol.Required("alarm_id"): str,
    vol.Required("confirmation"): str, vol.Optional("briefing", default=False): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_test(hass, connection, msg):
    try:
        result = await manager_for(hass).async_test(msg["alarm_id"], msg["confirmation"], msg["briefing"])
        connection.send_result(msg["id"], result)
    except AlarmError as err:
        connection.send_error(msg["id"], "invalid_alarm", str(err))


@websocket_api.websocket_command({"type": "household_alarms/preview", vol.Required("config"): dict})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_preview(hass, connection, msg):
    manager = manager_for(hass)
    if manager.preview_tasks:
        connection.send_error(msg["id"], "busy", "A briefing preview is already being generated")
        return
    try:
        task = asyncio.current_task()
        manager.preview_tasks.add(task)
        try:
            result = await manager.async_preview(msg["config"])
        finally:
            manager.preview_tasks.discard(task)
        connection.send_result(msg["id"], result)
    except AlarmError as err:
        connection.send_error(msg["id"], "invalid_alarm", str(err))
    except Exception:
        connection.send_error(msg["id"], "briefing_failed", "Preview failed. Check the assistant's conversation and voice settings, then try again.")


@callback
def async_register_commands(hass):
    for handler in (ws_list, ws_subscribe, ws_save, ws_delete, ws_action, ws_test, ws_preview,
                    ws_music_check, ws_music_start, ws_music_action, ws_tracks):
        websocket_api.async_register_command(hass, handler)


@websocket_api.websocket_command({
    "type": "household_alarms/tracks", vol.Required("speaker"): str,
    vol.Required("query"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_tracks(hass, connection, msg):
    try:
        connection.send_result(msg["id"], await search_tracks(hass, msg["speaker"], msg["query"]))
    except AlarmError as err:
        connection.send_error(msg["id"], "music_unavailable", str(err))


@websocket_api.websocket_command({
    "type": "household_alarms/music_check", vol.Required("speaker"): str,
    vol.Required("assistant_id"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_music_check(hass, connection, msg):
    try:
        result, *_ = await manager_for(hass).music_tests.async_check(msg["speaker"], msg["assistant_id"])
        connection.send_result(msg["id"], result)
    except AlarmError as err:
        connection.send_error(msg["id"], "music_test_unavailable", str(err))


@websocket_api.websocket_command({
    "type": "household_alarms/music_start", vol.Required("alarm_id"): str,
    vol.Required("speaker"): str, vol.Required("confirmation"): str,
    vol.Required("experimental_enabled"): bool, vol.Required("music_gain"): vol.Coerce(float),
    vol.Required("volume_level"): int, vol.Required("snooze_seconds"): int,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_music_start(hass, connection, msg):
    try:
        result = await manager_for(hass).music_tests.async_start(
            msg["alarm_id"], msg["speaker"], msg["confirmation"], msg["experimental_enabled"],
            msg["music_gain"], msg["volume_level"], msg["snooze_seconds"])
        connection.send_result(msg["id"], result)
    except AlarmError as err:
        connection.send_error(msg["id"], "music_test_failed", str(err))


@websocket_api.websocket_command({
    "type": "household_alarms/music_action", vol.Required("session_id"): str,
    vol.Required("action"): vol.In(["snooze", "dismiss", "sleep_in"]),
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_music_action(hass, connection, msg):
    try:
        result = await manager_for(hass).music_tests.async_action(msg["session_id"], msg["action"])
        connection.send_result(msg["id"], result)
    except AlarmError as err:
        connection.send_error(msg["id"], "music_test_failed", str(err))

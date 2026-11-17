"""HA-AlarmClock: opt-in speaker alarms, not a migration of existing routines."""

from datetime import timedelta
from pathlib import Path

from aiohttp import web
import voluptuous as vol

from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import callback, SupportsResponse
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.service import async_register_admin_service

from .audio import make_tone
from .const import DOMAIN
from .manager import AlarmManager
from .resources import async_register_card
from .websocket import async_register_commands

PLATFORMS = [Platform.SENSOR]


class ToneView(HomeAssistantView):
    """Only non-personal generated tones are publicly served; never briefing text."""

    url = "/api/household_alarms/tone/{name}.wav"
    name = "api:household_alarms:tone"
    requires_auth = False

    def __init__(self, tones):
        self.tones = tones

    async def get(self, request, name):
        if name not in self.tones:
            raise web.HTTPNotFound()
        return web.Response(body=self.tones[name], content_type="audio/wav")


async def async_setup(hass, config):
    """Register static resources once, including across integration reloads."""
    root = Path(__file__).parent
    await hass.http.async_register_static_paths([
        StaticPathConfig("/household_alarms/household-alarms-card.js", str(root / "frontend" / "household-alarms-card.js"), False),
    ])
    tones = await hass.async_add_executor_job(lambda: {name: make_tone(name) for name in ("chime", "bell", "digital")})
    hass.http.register_view(ToneView(tones))
    await async_register_card(hass)
    async_register_commands(hass)
    return True


async def async_setup_entry(hass, entry):
    manager = AlarmManager(hass)
    await manager.async_load()
    hass.data[DOMAIN] = manager
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def action(call):
        await manager.async_action(call.data["alarm_id"], call.service)

    async def dismiss_person(call):
        await manager.async_dismiss_person(call.data["person"])

    async def get_active(call):
        return manager.active_alarms(call.data.get("person"), call.data.get("speaker"))

    async_register_admin_service(hass, DOMAIN, "get_active", get_active,
        vol.Schema({vol.Optional("person"): str, vol.Optional("speaker"): str}),
        supports_response=SupportsResponse.ONLY)

    for name in ("snooze", "dismiss", "sleep_in"):
        async_register_admin_service(hass, DOMAIN, name, action, vol.Schema({vol.Required("alarm_id"): str}))
    async_register_admin_service(hass, DOMAIN, "dismiss_person", dismiss_person, vol.Schema({vol.Required("person"): str}))

    @callback
    def start(_event=None):
        entry.async_on_unload(async_track_time_interval(hass, manager.async_tick, timedelta(seconds=10)))
        entry.async_create_background_task(hass, manager.async_tick(), "household_alarms_initial_tick")

    if hass.is_running:
        start()
    else:
        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, start))
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, manager.async_shutdown_event))
    return True


async def async_unload_entry(hass, entry):
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_shutdown()
    for name in ("snooze", "dismiss", "sleep_in", "dismiss_person", "get_active"):
        hass.services.async_remove(DOMAIN, name)
    hass.data.pop(DOMAIN, None)
    return True

"""A compact status entity; private briefing instructions are not state attributes."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback

from .const import DOMAIN
from .manager import ACTIVE


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([AlarmStatus(entry.runtime_data)])


class AlarmStatus(SensorEntity):
    _attr_name = "HA-AlarmClock"
    _attr_unique_id = DOMAIN
    _attr_icon = "mdi:alarm"
    _attr_should_poll = False

    def __init__(self, manager):
        self.manager = manager

    @property
    def native_value(self):
        return sum(run["status"] in ACTIVE for run in self.manager.runs.values())

    @property
    def extra_state_attributes(self):
        return {
            "enabled_alarms": sum(alarm["enabled"] for alarm in self.manager.alarms.values()),
            "active_alarms": self.manager.active_alarms()["alarms"],
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.manager.sensor_entity_id = self.entity_id
        self.manager.listeners.add(self._update)
        self.async_on_remove(lambda: self.manager.listeners.discard(self._update))

    @callback
    def _update(self):
        self.async_write_ha_state()

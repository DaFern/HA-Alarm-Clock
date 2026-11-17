"""Set up a single HA-AlarmClock manager from the integrations UI."""

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class HouseholdAlarmsConfigFlow(ConfigFlow, domain=DOMAIN):
    """No credentials or existing-alarm migration is performed by this flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="HA-AlarmClock", data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

"""Register the card as a dashboard resource, including for cached app sessions."""

import logging
from urllib.parse import urlsplit

from homeassistant.components import frontend
from homeassistant.components.lovelace.const import LOVELACE_DATA

from .const import CARD_URL

_LOGGER = logging.getLogger(__name__)
CARD_PATH = "/household_alarms/household-alarms-card.js"


async def async_register_card(hass):
    """Use HA's resource collection API; never edit its storage files directly."""
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or lovelace.resource_mode != "storage":
        # Respect installations whose dashboard resources are deliberately YAML-owned.
        frontend.add_extra_js_url(hass, CARD_URL)
        _LOGGER.info("For YAML-managed dashboard resources, register %s as a module", CARD_URL)
        return
    resources = lovelace.resources
    await resources.async_get_info()
    owned = []
    for item in resources.async_items():
        url = urlsplit(item.get("url", ""))
        if not url.scheme and not url.netloc and url.path == CARD_PATH:
            owned.append(item)
    if not owned:
        await resources.async_create_item({"url": CARD_URL, "res_type": "module"})
        return
    for item in owned:
        if item.get("url") != CARD_URL or item.get("type") != "module":
            await resources.async_update_item(item["id"], {"url": CARD_URL, "res_type": "module"})

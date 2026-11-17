"""Expose generated tones through HA's supported media-source playback path."""

from homeassistant.components.media_source import MediaSource, PlayMedia, Unresolvable

from .const import DOMAIN


async def async_get_media_source(hass):
    return AlarmToneSource(hass)


class AlarmToneSource(MediaSource):
    name = "Household alarm sounds"

    def __init__(self, hass):
        super().__init__(DOMAIN)

    async def async_resolve_media(self, item):
        if item.identifier not in ("chime", "bell", "digital"):
            raise Unresolvable("Unknown household alarm sound")
        return PlayMedia(f"/api/household_alarms/tone/{item.identifier}.wav", "audio/wav")

"""Resolve named Assist pipelines without reading Home Assistant storage files."""

import asyncio
import base64

from homeassistant.components import assist_pipeline, tts

from .model import AlarmError


def assistants(hass):
    """List only the named assistants from Voice assistants settings."""
    try:
        return list(assist_pipeline.async_get_pipelines(hass))
    except KeyError:
        return []


def resolve_assistant(hass, assistant_id, *, voice=False):
    if not assistant_id:
        raise AlarmError("Choose an assistant for spoken messages. The alarm will use a tone until then.")
    pipeline = next((item for item in assistants(hass) if item.id == assistant_id), None)
    if pipeline is None:
        raise AlarmError("This assistant is no longer available. Choose another assistant; the alarm will use a tone until then.")
    if voice and (not pipeline.tts_engine or not pipeline.tts_language):
        raise AlarmError("This assistant has no configured voice. Set up text-to-speech in Settings → Voice assistants, or choose another assistant.")
    return pipeline


def speech_options(pipeline):
    return {"voice": pipeline.tts_voice} if pipeline.tts_voice else {}


async def preview_audio(hass, pipeline, message):
    """Return private audio over the authenticated admin WebSocket, not a public URL."""
    try:
        async with asyncio.timeout(60):
            media_id = tts.generate_media_source_id(hass, message, engine=pipeline.tts_engine,
                language=pipeline.tts_language, options=speech_options(pipeline), cache=False)
            extension, audio = await tts.async_get_media_source_audio(hass, media_id)
        mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "flac": "audio/flac"}.get(extension)
        if not mime or not audio or len(audio) > 8 * 1024 * 1024:
            raise ValueError("Invalid or oversized preview audio")
        return {"audio": base64.b64encode(audio).decode("ascii"), "mime_type": mime}
    except Exception as err:
        raise AlarmError("The assistant's voice could not generate audio. Check its text-to-speech settings and provider, then try Preview message again.") from err

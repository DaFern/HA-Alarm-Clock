"""Validated alarm settings and scheduling rules, independent of Home Assistant."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import math
import re
import uuid

ENTITY = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
MODES = {"weekdays", "school", "non_school", "once"}
CALENDAR_RULES = {"none", "block", "allow"}
TONES = {"chime", "bell", "digital", "none"}
RETIRED_PLAYBACK_FIELDS = {"agent", "tts", "language", "voice"}
DEFAULTS = {
    "name": "New alarm", "person": "", "enabled": False,
    "time": "07:00", "mode": "weekdays", "weekdays": [0, 1, 2, 3, 4],
    "date": "", "calendar": "", "calendar_rule": "block", "calendar_filters": "",
    "speaker": "", "tone": "chime",
    "music_enabled": False, "music_track": "", "music_track_name": "", "music_server": "",
    "music_gain": 25, "speech_delay": 0,
    "music_ramp_enabled": False, "music_ramp_step": 5, "music_ramp_seconds": 30,
    "start_volume": 20, "max_volume": 60, "volume_step": 10,
    "repeat_seconds": 60, "snooze_enabled": True, "snooze_minutes": 5,
    "max_snoozes": 3, "deadline": "", "allow_sleep_in": False,
    "notify_enabled": True, "notify_service": "",
    "phone_enabled": False, "phone_service": "", "phone_wake_screen": True,
    "bedtime_entity": "", "clear_sleep_on_dismiss": False, "briefing_enabled": False,
    "assistant_id": "", "instructions": "Give a short, friendly good morning message. Include the supplied time and weather. Do not make up information.",
    "weather": "",
    "schedule_enabled": False, "schedule_calendars": [],
    "briefing_words": 100, "schedule_include": "", "schedule_exclude": "",
}


class AlarmError(ValueError):
    """A setting or operation was rejected without changing the alarm."""


def clock(value: str) -> time:
    """Parse a strict local hour and minute."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
        raise AlarmError("Use a time in HH:MM format")
    try:
        return time.fromisoformat(value)
    except ValueError as err:
        raise AlarmError("Invalid time") from err


def validate(data: dict, alarm_id: str | None = None, *, require_speaker: bool = True) -> dict:
    """Validate a complete configuration; never accept runtime fields from clients."""
    if not isinstance(data, dict) or set(data) - (set(DEFAULTS) | RETIRED_PLAYBACK_FIELDS | {"id"}):
        raise AlarmError("Unknown alarm settings")
    # Older alarm schedules/speakers remain intact, but their independent voice
    # settings must never override a named assistant or guess which one to use.
    result = {**DEFAULTS, **{key: value for key, value in data.items() if key not in RETIRED_PLAYBACK_FIELDS}}
    result["weekdays"] = list(result["weekdays"]) if isinstance(result["weekdays"], list) else result["weekdays"]
    calendars = result["schedule_calendars"]
    if not isinstance(calendars, list) or len(calendars) > 10 or any(
        not isinstance(entity, str) or not ENTITY.fullmatch(entity) or not entity.startswith("calendar.")
        for entity in calendars
    ):
        raise AlarmError("Choose up to ten calendars for your morning message")
    result["schedule_calendars"] = list(dict.fromkeys(calendars))
    result["id"] = alarm_id or str(uuid.uuid4())
    for key in ("name", "person", "instructions", "assistant_id", "date", "calendar_filters", "schedule_include", "schedule_exclude"):
        value = result[key]
        limit = 10000 if key == "instructions" else 2000 if key in ("calendar_filters", "schedule_include", "schedule_exclude") else 100
        if not isinstance(value, str) or len(value) > limit:
            raise AlarmError(f"Invalid {key}")
        result[key] = value.strip()
    if type(result["briefing_words"]) is not int or result["briefing_words"] not in (100, 200, 300):
        raise AlarmError("Choose Short, Medium or Long for the message length")
    for key in ("calendar_filters", "schedule_include", "schedule_exclude"):
        phrases = [line.strip() for line in result[key].splitlines() if line.strip()]
        if len(phrases) > 50 or any(len(phrase) > 100 for phrase in phrases):
            raise AlarmError("Use up to 50 phrases, each no longer than 100 characters")
        result[key] = "\n".join(phrases)
    if not result["name"]:
        raise AlarmError("Give the alarm a name")
    for key in ("enabled", "snooze_enabled", "allow_sleep_in", "notify_enabled", "briefing_enabled", "schedule_enabled", "clear_sleep_on_dismiss", "music_enabled", "music_ramp_enabled", "phone_enabled", "phone_wake_screen"):
        if type(result[key]) is not bool:
            raise AlarmError(f"Invalid {key}")
    limits = {
        "start_volume": (1, 100), "max_volume": (1, 100), "volume_step": (0, 25),
        "repeat_seconds": (30, 300), "snooze_minutes": (1, 30), "max_snoozes": (0, 10),
        "music_gain": (1, 30), "speech_delay": (0, 120),
        "music_ramp_step": (1, 25), "music_ramp_seconds": (30, 300),
    }
    for key, (low, high) in limits.items():
        value = result[key]
        if type(value) is not int or not low <= value <= high:
            raise AlarmError(f"{key} must be between {low} and {high}")
    if result["start_volume"] > result["max_volume"]:
        raise AlarmError("Starting volume must not exceed maximum volume")
    if not isinstance(result["music_track"], str) or (result["music_track"] and not re.fullmatch(r"library://track/[0-9]{1,20}", result["music_track"])):
        raise AlarmError("Choose a song from this Music Assistant library")
    if not isinstance(result["music_track_name"], str) or len(result["music_track_name"]) > 300:
        raise AlarmError("Invalid song name")
    if result["music_enabled"] and not result["music_track"]:
        raise AlarmError("Choose a song before enabling music")
    if not isinstance(result["music_server"], str) or (result["music_server"] and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", result["music_server"])):
        raise AlarmError("Invalid Music Assistant connection")
    if result["music_enabled"] and not result["music_server"]:
        raise AlarmError("Search and reselect this song to bind its Music Assistant connection")
    if not isinstance(result["phone_service"], str) or (result["phone_service"] and not re.fullmatch(r"notify\.mobile_app_[a-z0-9_]+", result["phone_service"])):
        raise AlarmError("Choose a Companion app phone, not a notification group")
    if result["phone_enabled"] and not result["phone_service"]:
        raise AlarmError("Choose a phone for alarm controls")
    if not isinstance(result["mode"], str) or not isinstance(result["tone"], str) or result["mode"] not in MODES or result["tone"] not in TONES:
        raise AlarmError("Invalid schedule or sound")
    if not isinstance(result["calendar_rule"], str) or result["calendar_rule"] not in CALENDAR_RULES:
        raise AlarmError("Choose how calendar events affect this alarm")
    days = result["weekdays"]
    if not isinstance(days, list) or any(type(day) is not int or not 0 <= day <= 6 for day in days):
        raise AlarmError("Invalid repeat days")
    result["weekdays"] = sorted(set(days))
    if result["mode"] == "weekdays" and not days:
        raise AlarmError("Select at least one repeat day")
    clock(result["time"])
    if result["deadline"]:
        if clock(result["deadline"]) <= clock(result["time"]):
            raise AlarmError("Get-up deadline must be later than alarm time on the same day")
    if result["date"]:
        try:
            date.fromisoformat(result["date"])
        except ValueError as err:
            raise AlarmError("Invalid alarm date") from err
    if result["mode"] == "once" and not result["date"]:
        raise AlarmError("Select the alarm date")
    if result["mode"] == "school" and result["allow_sleep_in"]:
        raise AlarmError("Sleeping in is not available for school-day alarms")
    if result["mode"] == "school" and not result["deadline"]:
        raise AlarmError("School-day alarms need a get-up deadline")
    if result["calendar_rule"] == "allow" and (not result["calendar"] or not result["calendar_filters"].strip()):
        raise AlarmError("Choose a calendar and add at least one event title for days to allow")
    for key, domain in {
        "speaker": "media_player", "calendar": "calendar", "weather": "weather",
        "notify_service": "notify",
        "bedtime_entity": "input_boolean",
    }.items():
        value = result[key]
        if not isinstance(value, str) or (value and (not ENTITY.fullmatch(value) or not value.startswith(domain + "."))):
            raise AlarmError(f"Invalid {key}")
    if require_speaker and not result["speaker"]:
        raise AlarmError("Select the alarm speaker")
    if not result["bedtime_entity"]:
        result["clear_sleep_on_dismiss"] = False
    if result["schedule_enabled"] and not result["schedule_calendars"]:
        raise AlarmError("Choose at least one calendar for today's schedule")
    if result["schedule_enabled"] and not result["briefing_enabled"]:
        raise AlarmError("Turn on the assistant's morning message to include your schedule")
    return result


def is_school_day(day: date, events: list[dict]) -> bool:
    """Weekdays except explicit closures; ordinary school events are not holidays."""
    words = ("closed", "holiday", "half-term", "half term", "inset", "non-school day", "non school day")
    return day.weekday() < 5 and not any(
        any(word in str(event.get("summary", "")).lower() for word in words)
        for event in events
    )


def include_event_title(title: str, include: str = "", exclude: str = "") -> bool:
    """Literal case-insensitive substrings; exclusions always win."""
    title = title.casefold()
    included = [line.strip().casefold() for line in include.splitlines() if line.strip()]
    excluded = [line.strip().casefold() for line in exclude.splitlines() if line.strip()]
    return not any(phrase in title for phrase in excluded) and (not included or any(phrase in title for phrase in included))


def speech_wait_seconds(message: str) -> float:
    """Bounded conservative estimate, not a claim of verified audio completion."""
    return min(210, max(8, len(message.split()) / 1.7 + 8))


def matches(alarm: dict, day: date, school: bool, calendar_match: bool | None = None) -> bool:
    """Check schedule; unknown future calendar dates remain provisional."""
    match alarm["mode"]:
        case "school":
            return school
        case "non_school":
            return not school
        case "once":
            return alarm["date"] == day.isoformat()
        case _:
            if day.weekday() not in alarm["weekdays"]:
                return False
            if alarm.get("calendar_rule", "none") == "block" and calendar_match is True:
                return False
            if alarm.get("calendar_rule", "none") == "allow" and calendar_match is False:
                return False
            return True


def local_occurrence(day: date, value: str, zone) -> datetime | None:
    """Use the first repeated DST minute and skip nonexistent spring-forward times."""
    candidate = datetime.combine(day, clock(value), tzinfo=zone)
    roundtrip = candidate.astimezone(timezone.utc).astimezone(zone)
    if roundtrip.replace(tzinfo=None) != candidate.replace(tzinfo=None):
        return None
    return candidate


def deadline_at(alarm: dict, started: datetime) -> datetime | None:
    """Return a same-day deadline in the configured local timezone."""
    if not alarm["deadline"]:
        return None
    return local_occurrence(started.date(), alarm["deadline"], started.tzinfo)


def elapsed_after(now: datetime, seconds: float) -> datetime:
    """Add elapsed time rather than wall-clock time across a DST transition."""
    return (now.astimezone(timezone.utc) + timedelta(seconds=seconds)).astimezone(now.tzinfo)


def snooze_until(alarm: dict, run: dict, now: datetime) -> datetime:
    """Never permit a snooze at or beyond a configured get-up deadline."""
    if not alarm["snooze_enabled"] or run["snoozes"] >= alarm["max_snoozes"]:
        raise AlarmError("No snoozes remaining")
    deadline = deadline_at(alarm, datetime.fromisoformat(run["started"]).astimezone(now.tzinfo))
    if deadline and now.timestamp() >= deadline.timestamp():
        raise AlarmError("It is time to get up; the deadline has been reached")
    target = elapsed_after(now, alarm["snooze_minutes"] * 60)
    return min(target, deadline, key=lambda value: value.timestamp()) if deadline else target


def volume(alarm: dict, cycles: int, escalated: bool) -> float:
    """Return a bounded hardware volume, independent of AI output."""
    value = alarm["max_volume"] if escalated else min(
        alarm["max_volume"], alarm["start_volume"] + alarm["volume_step"] * cycles
    )
    return value / 100


def finite_number(value) -> bool:
    """Reject unavailable values, booleans, infinities and NaN from weather context."""
    return type(value) in (int, float) and math.isfinite(value)

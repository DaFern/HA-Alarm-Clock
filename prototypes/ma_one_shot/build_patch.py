"""Build a review-only unified diff against exact MA 2.10.12 source snapshots.

Never changes the checkout, installs a provider, or contacts a running server.
"""

import argparse
from difflib import unified_diff
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Upstream hook is not unique or has changed; review required")
    return text.replace(old, new, 1)


def external_command_hooks(text):
    """Apply the same guarded Stop/Pause hooks to full sources and pinned fixtures."""
    text = replace_once(text,
        "        self._check_player_permission(queue_id)\n        await self._handle_stop(queue_id)",
        "        self._check_player_permission(queue_id)\n"
        "        alarm_command = self._capture_alarm_external_command(queue_id)\n"
        "        self.mass.streams.audio.briefings.cancel_queue(queue_id)\n"
        "        alarm_command_succeeded = False\n"
        "        try:\n"
        "            await self._handle_stop(queue_id)\n"
        "            alarm_command_succeeded = True\n"
        "        finally:\n"
        "            self._confirm_alarm_external_command(alarm_command, alarm_command_succeeded)")
    text = replace_once(text,
        "        self._check_player_permission(queue_id)\n        # cancel any pending play_index calls for this queue to prevent conflicts",
        "        self._check_player_permission(queue_id)\n"
        "        alarm_command = self._capture_alarm_external_command(queue_id)\n"
        "        self.mass.streams.audio.briefings.cancel_queue(queue_id)\n"
        "        # cancel any pending play_index calls for this queue to prevent conflicts")
    text = replace_once(text,
        "        await self.mass.players._handle_cmd_pause(queue_id)\n",
        "        alarm_command_succeeded = False\n"
        "        try:\n"
        "            await self.mass.players._handle_cmd_pause(queue_id)\n"
        "            alarm_command_succeeded = True\n"
        "        finally:\n"
        "            self._confirm_alarm_external_command(alarm_command, alarm_command_succeeded)\n")
    return text


def candidates(checkout):
    lock = json.loads((HERE / "upstream.json").read_text())
    original = {}
    for rel, expected in lock["sha256"].items():
        raw = (checkout / rel).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Upstream hash mismatch: {rel}; do not apply a stale patch")
        original[rel] = raw.decode()
    changes = {}

    rel = "music_assistant/controllers/streams/audio.py"
    text = replace_once(original[rel],
        "from music_assistant.helpers.named_pipe import read_named_pipe\n",
        "from music_assistant.helpers.named_pipe import read_named_pipe\nfrom music_assistant.helpers.one_shot_briefing import OneShotMixer\n")
    text = replace_once(text, "        self.mass = mass\n        self.logger = logging.getLogger(f\"{MASS_LOGGER_NAME}.streams.audio\")",
        "        self.mass = mass\n        self.briefings = OneShotMixer()\n        self.logger = logging.getLogger(f\"{MASS_LOGGER_NAME}.streams.audio\")")
    changes[rel] = text

    rel = "music_assistant/controllers/streams/controller.py"
    text = replace_once(original[rel],
        "            # stream the audio\n            # this final ffmpeg process",
        "            audio_input = self.audio.briefings.wrap(\n                queue_id, session_id, audio_input, pcm_format\n            )\n            # stream the audio\n            # this final ffmpeg process")
    text = replace_once(text,
        "        audio_bytes = get_ffmpeg_stream(\n            audio_input=flow_stream,",
        "        flow_stream = self.audio.briefings.wrap(\n            queue_id, session_id, flow_stream, flow_pcm_format\n        )\n        audio_bytes = get_ffmpeg_stream(\n            audio_input=flow_stream,")
    text = replace_once(text,
        "                return self._count_as_output_stream(flow_stream)",
        "                flow_stream = self.audio.briefings.wrap(\n                    queue.queue_id, queue_session_id, flow_stream, pcm_format\n                )\n                return self._count_as_output_stream(flow_stream)")
    text = replace_once(text,
        "            # mirror the on_source_selected/unselected lifecycle",
        "            if queue is not None:\n                inner_stream = self.audio.briefings.wrap(\n                    queue.queue_id, queue_session_id, inner_stream, pcm_format\n                )\n            # mirror the on_source_selected/unselected lifecycle")
    changes[rel] = text

    rel = "music_assistant/controllers/player_queues/controller.py"
    text = replace_once(original[rel],
        "    committed_index,\n", "    build_queue_item,\n    committed_index,\n")
    text = external_command_hooks(text)
    text = replace_once(text,
        "from music_assistant.helpers.uri import parse_uri\n",
        "from music_assistant.helpers.one_shot_briefing import (\n"
         "    MixLevels,\n    PreparedBriefing,\n    prepare_briefing,\n)\n"
        "from music_assistant.helpers.plugin_engines import get_tts_engines\n"
        "from music_assistant.helpers.uri import parse_uri\n")
    text = replace_once(text,
        '    @api_command("player_queues/transfer", required_scope=Scope.QUEUES_CONTROL)\n',
        (HERE / "start_command.py.txt").read_text() + '\n'
         + (HERE / "test_commands.py.txt").read_text() + '\n'
         + (HERE / "alarm_commands.py.txt").read_text() + '\n'
        '    @api_command("player_queues/transfer", required_scope=Scope.QUEUES_CONTROL)\n')
    text = replace_once(text,
        '        fade_in: bool,\n    ) -> None:\n        # cancel any pending play_index calls',
        '        fade_in: bool,\n        *,\n        briefing: PreparedBriefing | None = None,\n'
        '        briefing_owner: dict[str, Any] | None = None,\n'
        '    ) -> None:\n        # cancel any pending play_index calls')
    text = replace_once(text,
        '            queue_data.session_id = shortuuid.random(length=8)\n',
        '            self.mass.streams.audio.briefings.cancel_queue(queue_id)\n'
        '            queue_data.session_id = shortuuid.random(length=8)\n'
        '            if briefing is not None:\n'
        '                if not self.mass.streams.audio.briefings.arm(\n'
        '                    queue_id, queue_data.session_id, briefing.run_id, briefing.source,\n'
        '                    levels=briefing.levels, ttl=120,\n'
        '                ):\n'
        '                    raise InvalidDataError("Briefing run was already attempted")\n')
    text = replace_once(text,
        '            self.mass.streams.audio_processing.start_session(\n',
        '            if briefing_owner is not None:\n'
        '                self.mass.streams.audio.briefings.bind_owner(\n'
        '                    queue_id, queue_data.session_id, briefing_owner\n'
        '                )\n'
         '                await self.mass.players.cmd_volume_set(\n'
         '                    queue_id, briefing_owner["volume_level"]\n'
         '                )\n'
        '            self.mass.streams.audio_processing.start_session(\n')
    changes[rel] = text
    changes["music_assistant/helpers/one_shot_briefing.py"] = (HERE / "adapter.py").read_text()
    return original, changes


def build(checkout):
    original, changes = candidates(checkout)
    return "".join("".join(unified_diff(original.get(rel, "").splitlines(keepends=True),
        text.splitlines(keepends=True), fromfile=f"a/{rel}" if rel in original else "/dev/null",
        tofile=f"b/{rel}")) for rel, text in changes.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="New diff artifact; never overwrite an existing file")
    args = parser.parse_args()
    try:
        result = build(args.checkout)
        if args.output:
            with args.output.open("x") as target:
                target.write(result)
        else:
            print(result, end="")
    except (OSError, ValueError) as err:
        parser.exit(2, f"Patch not built: {err}\n")


if __name__ == "__main__":
    main()

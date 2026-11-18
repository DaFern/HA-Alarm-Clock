"""Offline lifecycle and pinned MA filter-graph contract tests. No playback."""

import asyncio
import ast
from dataclasses import dataclass, field
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path('/data/v2/cache/opencode/ma-one-shot-upstream-2.10.12')


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


adapter = load('ma_one_shot_prototype', 'prototypes/ma_one_shot/adapter.py')
builder = load('ma_one_shot_builder', 'prototypes/ma_one_shot/build_patch.py')


def pcm(kind='f32le', channels=2, rate=48000, depth=32):
    return types.SimpleNamespace(content_type=kind, channels=channels, sample_rate=rate, bit_depth=depth)


async def source(chunks, closed=None):
    try:
        for chunk in chunks:
            yield chunk
    finally:
        if closed is not None:
            closed.set()


async def collect(stream):
    return [chunk async for chunk in stream]


class PreparationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.resolve = AsyncMock(return_value=object())
        self.query = AsyncMock(return_value=types.SimpleNamespace(duration=2))
        self.path = AsyncMock(return_value=('/trusted/engine-output.wav', None))
        self.modules = {
            'music_assistant.helpers.plugin_engines': types.SimpleNamespace(resolve_tts_engine=self.resolve),
            'music_assistant.helpers.tts': types.SimpleNamespace(
                query_tts_engine=self.query, resolve_tts_stream_path=self.path),
        }

    async def prepare(self, **kwargs):
        params = dict(mass=object(), run_id='alarm-1', message='Good morning',
                      tts_engine='ha/piper', language='en-GB', voice='selected-voice')
        params.update(kwargs)
        with patch.dict(sys.modules, self.modules):
            return await adapter.prepare_briefing(**params)

    async def test_registered_engine_receives_exact_language_and_voice(self):
        plan = await self.prepare()
        self.assertEqual(plan.source, '/trusted/engine-output.wav')
        self.assertNotIn('engine-output', repr(plan))
        self.query.assert_awaited_once_with(self.resolve.return_value, 'Good morning', 'en-GB',
                                           timeout=25, options={'voice': 'selected-voice'})

    async def test_missing_engine_does_not_query_or_fallback(self):
        self.resolve.return_value = None
        with self.assertRaisesRegex(ValueError, 'Unable to prepare'):
            await self.prepare()
        self.query.assert_not_awaited()

    async def test_invalid_inputs_never_reach_engine(self):
        for kwargs in ({'message': ''}, {'message': 'x' * 4097}, {'tts_engine': ''},
                       {'language': 'bad\n'}, {'voice': 'x' * 129},
                       {'levels': adapter.MixLevels(1, 1)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                await self.prepare(**kwargs)
        self.resolve.assert_not_awaited()

    async def test_engine_errors_do_not_expose_text_paths_or_tokens(self):
        self.query.side_effect = RuntimeError('private text /secret/file token=abc')
        with self.assertRaises(ValueError) as err:
            await self.prepare()
        self.assertNotIn('private', str(err.exception))
        self.assertTrue(err.exception.__suppress_context__)

    async def test_duration_is_bounded(self):
        for duration in (0, 241, float('inf'), float('nan')):
            self.query.return_value.duration = duration
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                await self.prepare()
        self.path.assert_not_awaited()

    async def test_provider_sources_are_still_validated(self):
        for path in ('pipe:0', 'relative.wav', 'https://user:pass@example.invalid/clip'):
            self.path.return_value = (path, None)
            with self.subTest(path=path), self.assertRaises(ValueError):
                await self.prepare()

    async def test_cancellation_is_not_swallowed(self):
        self.query.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.prepare()


class StartCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.lock = asyncio.Lock()
        self.mixer = adapter.OneShotMixer()
        self.prepared = []
        self.denied = False
        self.dispatches = []

        def handle_play_action(func):
            async def locked(instance, *args, **kwargs):
                async with self.lock:
                    return await func(instance, *args, **kwargs)
            return locked

        async def prepare(*args, **kwargs):
            self.assertTrue(self.lock.locked())
            plan = adapter.PreparedBriefing(args[1], '/trusted/voice.wav', kwargs['levels'])
            self.prepared.append(plan)
            return plan

        namespace = dict(api_command=lambda *a, **k: lambda f: f,
            handle_play_action=handle_play_action, Scope=types.SimpleNamespace(QUEUES_CONTROL='control'),
            PlayerType=types.SimpleNamespace(GROUP='group'), MediaType=types.SimpleNamespace(TRACK='track'),
            PlayerUnavailableError=ValueError, InvalidDataError=ValueError,
            prepare_briefing=prepare, MixLevels=adapter.MixLevels)
        command = (ROOT / 'prototypes/ma_one_shot/start_command.py.txt').read_text()
        exec('class Host:\n' + command, namespace)
        self.host = namespace['Host']()
        self.state = types.SimpleNamespace(type='player', active_group=None, synced_to=None,
                                           group_members=[])
        self.host.mass = types.SimpleNamespace(
            streams=types.SimpleNamespace(audio=types.SimpleNamespace(briefings=self.mixer)),
            players=types.SimpleNamespace(get_player=lambda _: types.SimpleNamespace(state=self.state)))
        def permission(_):
            if self.denied:
                raise PermissionError('denied')
        self.host._check_player_permission = permission
        self.host.get_item = lambda *args: types.SimpleNamespace(media_type='track')

        async def dispatch(queue_id, item_id, seek, fade, *, briefing):
            self.assertTrue(self.lock.locked())
            self.assertEqual(seek, 0)
            self.mixer.arm(queue_id, 'session-1', briefing.run_id, briefing.source,
                           levels=briefing.levels)
            self.dispatches.append((queue_id, item_id))
        self.host._play_index = dispatch

    async def start(self):
        await self.host.play_index_with_briefing('Kitchen', 'item-1', 'alarm-run',
                                                'Good morning', 'ha/piper')

    async def test_permission_denial_prevents_render_and_dispatch(self):
        self.denied = True
        with self.assertRaises(PermissionError):
            await self.start()
        self.assertFalse(self.prepared)
        self.assertFalse(self.dispatches)

    async def test_duplicate_concurrent_requests_only_render_and_dispatch_once(self):
        results = await asyncio.gather(self.start(), self.start(), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 1)
        self.assertEqual(len(self.prepared), 1)
        self.assertEqual(len(self.dispatches), 1)
        self.assertEqual(self.prepared[0].source, '')

    async def test_group_is_rejected_before_render(self):
        self.state.type = 'group'
        with self.assertRaisesRegex(ValueError, 'single ungrouped'):
            await self.start()
        self.assertFalse(self.prepared)

    async def test_missing_track_is_rejected_before_render(self):
        self.host.get_item = lambda *args: None
        with self.assertRaisesRegex(ValueError, 'queued track'):
            await self.start()
        self.assertFalse(self.prepared)

    async def test_dispatch_cancellation_revokes_armed_clip_and_erases_source(self):
        dispatch = self.host._play_index
        async def cancel(*args, **kwargs):
            await dispatch(*args, **kwargs)
            raise asyncio.CancelledError()
        self.host._play_index = cancel
        with self.assertRaises(asyncio.CancelledError):
            await self.start()
        self.assertFalse(self.mixer._pending)
        self.assertEqual(self.prepared[0].source, '')
        self.assertTrue(self.mixer.has_run('Kitchen', 'alarm-run'))


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        self.now = 10
        async def fake_engine(song, clip, format, levels):
            self.calls.append((clip, format, levels))
            async for chunk in song:
                yield b'mixed:' + chunk
        self.mixer = adapter.OneShotMixer(engine=fake_engine, clock=lambda: self.now)

    def arm(self, **kwargs):
        params = dict(queue_id='Kitchen Speaker', session_id='session-1', run_id='alarm-run-1',
                      source='https://voice.invalid/clip.mp3')
        params.update(kwargs)
        return self.mixer.arm(**params)

    def stream(self, *, session='session-1', chunks=None, closed=None):
        return self.mixer.wrap('Kitchen Speaker', session,
            source(chunks if chunks is not None else [b'song-a', b'song-b', b'song-tail'], closed), pcm())

    async def test_unarmed_playback_is_unchanged_and_opens_no_voice(self):
        closed = asyncio.Event()
        self.assertEqual(await collect(self.stream(closed=closed)), [b'song-a', b'song-b', b'song-tail'])
        self.assertFalse(self.calls)
        self.assertTrue(closed.is_set())

    async def test_song_is_main_input_and_complete_tail_is_forwarded(self):
        self.arm()
        self.assertEqual(await collect(self.stream()), [b'mixed:song-a', b'mixed:song-b', b'mixed:song-tail'])
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.mixer._active)
        self.assertFalse(self.mixer._pending)

    async def test_reconnection_does_not_replay_voice(self):
        self.arm()
        await collect(self.stream())
        self.assertEqual(await collect(self.stream()), [b'song-a', b'song-b', b'song-tail'])
        self.assertEqual(len(self.calls), 1)

    async def test_concurrent_consumers_claim_voice_only_once(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def blocked(song, *args):
            calls.append(1)
            started.set()
            await release.wait()
            async for chunk in song:
                yield chunk
        self.mixer.engine = blocked
        self.arm()
        first = asyncio.create_task(collect(self.stream()))
        await asyncio.wait_for(started.wait(), timeout=1)
        second = await collect(self.stream())
        release.set()
        await first
        self.assertEqual(second, [b'song-a', b'song-b', b'song-tail'])
        self.assertEqual(len(calls), 1)

    async def test_invalid_format_closes_song_and_revokes_request(self):
        closed = asyncio.Event()
        # Start the fixture so its finalizer can observe explicit closure.
        song = source([b'first', b'tail'], closed)
        await anext(song)
        self.arm()
        with self.assertRaisesRegex(ValueError, 'PCM'):
            await collect(self.mixer.wrap('Kitchen Speaker', 'session-1', song, pcm(kind='mp3')))
        self.assertTrue(closed.is_set())
        self.assertFalse(self.mixer._pending)
        self.assertFalse(self.calls)

    async def test_new_session_and_snooze_restart_are_music_only(self):
        self.arm()
        await collect(self.stream())
        self.assertFalse(self.arm(session_id='session-2'))
        self.assertEqual(await collect(self.stream(session='session-2')), [b'song-a', b'song-b', b'song-tail'])
        self.assertEqual(len(self.calls), 1)

    async def test_stale_session_cannot_claim_new_briefing(self):
        self.arm()
        await collect(self.stream(session='old-session'))
        self.assertFalse(self.calls)
        await collect(self.stream())
        self.assertEqual(len(self.calls), 1)

    async def test_other_queue_cannot_claim_briefing(self):
        self.arm()
        self.assertEqual(await collect(self.mixer.wrap('Bedroom', 'session-1', source([b'other']), pcm())), [b'other'])
        self.assertFalse(self.calls)
        await collect(self.stream())
        self.assertEqual(len(self.calls), 1)

    async def test_expired_plan_is_erased_without_playing(self):
        self.arm(ttl=1)
        plan = self.mixer._pending['Kitchen Speaker']
        self.now = 12
        await collect(self.stream())
        self.assertEqual(plan.state, 'expired')
        self.assertEqual(plan.source, '')
        self.assertFalse(self.calls)
        self.assertFalse(self.arm())

    async def test_duplicate_arm_is_idempotent(self):
        self.assertTrue(self.arm())
        self.assertFalse(self.arm())
        await collect(self.stream())
        self.assertEqual(len(self.calls), 1)

    async def test_queue_owner_cannot_be_replaced_by_another_run(self):
        self.arm()
        with self.assertRaisesRegex(ValueError, 'already'):
            self.arm(run_id='another-run')
        self.assertEqual(self.mixer._pending['Kitchen Speaker'].run_id, 'alarm-run-1')

    async def test_wrong_run_cancellation_leaves_owner_alone(self):
        self.arm()
        self.mixer.cancel('Kitchen Speaker', 'wrong-run')
        await collect(self.stream())
        self.assertEqual(len(self.calls), 1)

    async def test_cancel_before_stream_is_music_only(self):
        self.arm()
        plan = self.mixer._pending['Kitchen Speaker']
        self.mixer.cancel('Kitchen Speaker', 'alarm-run-1')
        self.assertEqual(plan.source, '')
        await collect(self.stream())
        self.assertFalse(self.calls)
        self.assertFalse(self.arm())

    async def test_stop_or_snooze_cancels_blocked_mix_and_closes_sources(self):
        started, engine_closed, song_closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def blocked(song, *args):
            try:
                async for chunk in song:
                    started.set()
                    await asyncio.Event().wait()
                    yield chunk
            finally:
                engine_closed.set()
        self.mixer.engine = blocked
        self.arm()
        task = asyncio.create_task(collect(self.stream(closed=song_closed)))
        await asyncio.wait_for(started.wait(), timeout=1)
        self.mixer.cancel_queue('Kitchen Speaker')
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(engine_closed.is_set())
        self.assertTrue(song_closed.is_set())
        self.assertFalse(self.mixer._active)

    async def test_closed_consumer_closes_mix_and_song(self):
        song_closed = asyncio.Event()
        self.arm()
        stream = self.stream(closed=song_closed)
        self.assertEqual(await anext(stream), b'mixed:song-a')
        await stream.aclose()
        self.assertTrue(song_closed.is_set())
        self.assertFalse(self.mixer._active)
        await collect(self.stream())
        self.assertEqual(len(self.calls), 1)

    async def test_failure_before_reading_song_degrades_to_music_only(self):
        secret = 'private-token-never-log'
        def fail(*args):
            raise ValueError(secret)
        self.mixer.engine = fail
        self.arm(source=f'https://voice.invalid/{secret}.mp3')
        plan = self.mixer._pending['Kitchen Speaker']
        with self.assertLogs(adapter.LOGGER, level='WARNING') as logs:
            self.assertEqual(await collect(self.stream()), [b'song-a', b'song-b', b'song-tail'])
        self.assertNotIn(secret, '\n'.join(logs.output))
        self.assertEqual(plan.source, '')
        self.assertEqual(plan.state, 'failed')
        self.assertFalse(self.arm())

    async def test_midstream_failure_does_not_replay_or_skip_song_silently(self):
        async def fail(song, *args):
            await anext(song)
            raise ValueError('voice secret')
            yield b''
        self.mixer.engine = fail
        self.arm()
        with self.assertLogs(adapter.LOGGER, level='WARNING'), self.assertRaisesRegex(RuntimeError, 'music-only'):
            await collect(self.stream())
        self.assertFalse(self.mixer._active)
        self.assertFalse(self.arm())

    async def test_fresh_run_can_use_same_queue_after_completion(self):
        self.arm()
        await collect(self.stream())
        self.arm(session_id='session-2', run_id='next-day')
        await collect(self.stream(session='session-2'))
        self.assertEqual(len(self.calls), 2)

    async def test_replay_protection_is_not_evicted_at_capacity(self):
        self.mixer.max_runs = 1
        self.arm()
        await collect(self.stream())
        with self.assertRaisesRegex(ValueError, 'run limit'):
            self.arm(run_id='new-run')
        self.assertFalse(self.arm())

    async def test_sources_are_not_in_plan_repr(self):
        self.arm(source='https://voice.invalid/private-clip?token=private')
        self.assertNotIn('private', repr(self.mixer._pending['Kitchen Speaker']))

    async def test_invalid_gains_ttl_identifiers_and_sources(self):
        for kwargs in (
            {'levels': adapter.MixLevels(music=0.9, speech=0.7)},
            {'levels': adapter.MixLevels(music=float('nan'))},
            {'levels': adapter.MixLevels(speech=True)}, {'ttl': float('inf')}, {'ttl': 0},
            {'queue_id': ''}, {'run_id': 'x' * 129}, {'session_id': 'bad\nvalue'},
            {'source': 'relative.wav'}, {'source': 'pipe:0'}, {'source': 'https://user:pass@voice.invalid/clip'},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.arm(**kwargs)


def fragment(text, start, end):
    begin = text.index(start)
    finish = text.index(end, begin)
    return text[begin:finish]


@unittest.skipUnless(SNAPSHOT.exists(), 'Pinned MA source snapshot is required for source-contract tests')
class NativeMAContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original, cls.candidate = builder.candidates(SNAPSHOT)
        dsp = cls.original['music_assistant/helpers/dsp.py']
        ffmpeg = cls.original['music_assistant/helpers/ffmpeg.py']
        namespace = {'dataclass': dataclass, 'field': field}
        exec(fragment(dsp, '@dataclass(slots=True)\nclass ComplexFilterInput:', '\n\ndef filter_to_ffmpeg_params('), namespace)
        read_args = ffmpeg.split('_INPUT_READ_ARGS: Final[list[str]] = ', 1)[1].split('\n]', 1)[0] + '\n]'
        namespace['_INPUT_READ_ARGS'] = ast.literal_eval(read_args)
        exec(fragment(ffmpeg, 'def _build_filtergraph_args(', '\n\ndef _raise_feeder_error('), namespace)
        cls.namespace = namespace

    def test_actual_ma_graph_builder_gets_nonlooping_voice_and_keeps_song(self):
        observed = {}
        def engine(**kwargs):
            observed.update(kwargs)
            return 'native-stream-placeholder'
        modules = {
            'music_assistant': types.ModuleType('music_assistant'),
            'music_assistant.helpers': types.ModuleType('music_assistant.helpers'),
            'music_assistant.helpers.dsp': types.SimpleNamespace(
                ComplexFilter=self.namespace['ComplexFilter'], ComplexFilterInput=self.namespace['ComplexFilterInput']),
            'music_assistant.helpers.ffmpeg': types.SimpleNamespace(get_ffmpeg_stream=engine),
        }
        format = pcm()
        song = object()
        with patch.dict(sys.modules, modules):
            self.assertEqual(adapter.native_mix(song, 'https://voice.invalid/clip.mp3', format, adapter.MixLevels()), 'native-stream-placeholder')
        self.assertIs(observed['audio_input'], song)
        self.assertIsNot(observed['input_format'], format)
        self.assertIs(observed['output_format'], format)
        args, filters = self.namespace['_build_filtergraph_args'](observed['filter_params'])
        self.assertIn('0', args)
        self.assertNotIn('-1', args)
        self.assertNotIn('-reconnect', args)
        self.assertNotIn('-shortest', args + filters)
        self.assertIn('-rw_timeout', args)
        self.assertIn('-t', args)
        graph = filters[1]
        self.assertIn('[0:a]volume=0.25', graph)
        self.assertIn('volume=0.7', graph)
        self.assertIn('duration=first', graph)
        self.assertIn('normalize=0', graph)

    def test_four_output_paths_have_hooks_and_ambient_mixer_is_unchanged(self):
        controller = self.candidate['music_assistant/controllers/streams/controller.py']
        self.assertEqual(controller.count('self.audio.briefings.wrap('), 4)
        self.assertNotIn('music_assistant/helpers/ffmpeg.py', self.candidate)
        self.assertNotIn('music_assistant/helpers/dsp.py', self.candidate)
        self.assertIn('input_args += ["-stream_loop", "-1"]', self.original['music_assistant/helpers/ffmpeg.py'])

    def test_stop_and_pause_cancel_after_existing_permission_checks(self):
        controller = self.candidate['music_assistant/controllers/player_queues/controller.py']
        self.assertEqual(controller.count('self.mass.streams.audio.briefings.cancel_queue(queue_id)'), 3)
        self.assertEqual(controller.count('self._check_player_permission(queue_id)\n        self.mass.streams.audio.briefings.cancel_queue(queue_id)'), 2)

    def test_start_command_preserves_scope_permission_and_queue_lock(self):
        controller = self.candidate['music_assistant/controllers/player_queues/controller.py']
        command = fragment(controller,
            '    @api_command("player_queues/play_index_with_briefing"',
            '    @api_command("player_queues/transfer"')
        self.assertIn('required_scope=Scope.QUEUES_CONTROL', command)
        self.assertIn('@handle_play_action', command)
        self.assertLess(command.index('self._check_player_permission'), command.index('await prepare_briefing'))
        self.assertIn('prepared.source = ""', command)
        self.assertNotIn('source: str', command)
        self.assertNotIn('url: str', command)

    def test_session_is_bound_synchronously_before_load_or_dispatch(self):
        controller = self.candidate['music_assistant/controllers/player_queues/controller.py']
        playback = controller[controller.index('    async def _play_index('):]
        session = playback.index('queue_data.session_id = shortuuid.random')
        armed = playback.index('self.mass.streams.audio.briefings.arm(')
        self.assertNotIn('await ', playback[session:armed])
        self.assertLess(armed, playback.index('await self._load_item('))
        self.assertLess(armed, playback.index('await self.mass.players.play_media('))

    def test_stale_or_edited_upstream_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='ma-hash-test-', dir='/data/v2/cache/opencode') as directory:
            root = Path(directory)
            lock = json.loads((ROOT / 'prototypes/ma_one_shot/upstream.json').read_text())
            path = root / next(iter(lock['sha256']))
            path.parent.mkdir(parents=True)
            path.write_text('different source')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                builder.build(root)

    def test_generated_patch_applies_without_modifying_upstream_snapshot(self):
        with tempfile.TemporaryDirectory(prefix='ma-patch-test-', dir='/data/v2/cache/opencode') as directory:
            root = Path(directory)
            for rel, content in self.original.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            patch_text = builder.build(SNAPSHOT)
            result = subprocess.run(['git', 'apply', '--check', '-'], input=patch_text, text=True, cwd=root, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for rel, content in self.original.items():
                self.assertEqual((root / rel).read_text(), content)
            self.assertIn('one_shot_briefing.py', patch_text)


if __name__ == '__main__':
    unittest.main(verbosity=2)

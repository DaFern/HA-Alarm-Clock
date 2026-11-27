"""Execute the proposed MA test command bodies with fake controllers, not a server."""

import asyncio
import ast
from enum import StrEnum
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_ma_one_shot as fixture


class State(StrEnum):
    IDLE = 'idle'
    PLAYING = 'playing'
    PAUSED = 'paused'


class RepeatMode(StrEnum):
    OFF = 'off'
    ONE = 'one'
    ALL = 'all'


class MACommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mixer = fixture.adapter.OneShotMixer()
        self.calls = []
        self.lock = asyncio.Lock()
        self.lock_owner = None
        self.denied = False
        self.scopes = {}
        def api_command(name, *, required_scope):
            self.scopes[name] = required_scope
            return lambda func: func
        def handle_play_action(func):
            async def wrapper(host, *args, **kwargs):
                if self.lock_owner is asyncio.current_task():
                    return await func(host, *args, **kwargs)
                async with self.lock:
                    self.lock_owner = asyncio.current_task()
                    try:
                        return await func(host, *args, **kwargs)
                    finally:
                        self.lock_owner = None
            return wrapper
        async def prepare(*args, **kwargs):
            self.assertTrue(self.lock.locked())
            self.calls.append('prepare')
            return fixture.adapter.PreparedBriefing(args[1], '/trusted/voice.wav', kwargs['levels'])
        def build_queue_item(queue, media):
            self.enqueues += 1
            item_id = 'test-item' if self.enqueues == 1 else f'test-item-{self.enqueues}'
            return types.SimpleNamespace(uri=media.uri, queue_item_id=item_id)
        namespace = dict(api_command=api_command, handle_play_action=handle_play_action, Any=object,
            get_tts_engines=lambda mass: self.get_engines(mass),
            Scope=types.SimpleNamespace(QUEUES_CONTROL='control'), PlaybackState=State,
            PlayerType=types.SimpleNamespace(GROUP='group'), RepeatMode=RepeatMode,
            MediaType=types.SimpleNamespace(TRACK='track'), QueueOption=types.SimpleNamespace(ADD='add'),
            PlayerUnavailableError=ValueError, InvalidDataError=ValueError,
            prepare_briefing=prepare, MixLevels=fixture.adapter.MixLevels,
            Track=types.SimpleNamespace, build_queue_item=build_queue_item)
        source = (fixture.ROOT / 'prototypes/ma_one_shot/test_commands.py.txt').read_text()
        source += '\n' + (fixture.ROOT / 'prototypes/ma_one_shot/alarm_commands.py.txt').read_text()
        exec('class Host:\n' + source, namespace)
        self.host = namespace['Host']()
        self.queue = types.SimpleNamespace(state=State.IDLE, repeat_mode='off',
                                            autoplay_enabled=False, overlay_enabled=False,
                                            current_item=None, current_index=None, index_in_buffer=None,
                                            corrected_elapsed_time=0, next_item=None)
        self.data = types.SimpleNamespace(queue=self.queue, items=[], session_id=None,
                                           autoplay_override=None)
        self.player = types.SimpleNamespace(state=types.SimpleNamespace(
            type='player', active_group=None, synced_to=None, group_members=[],
            playback_state=State.IDLE, active_source=None, volume_level=23))
        async def volume(queue, level):
            self.calls.append(('volume', level))
            self.player.state.volume_level = level
        self.host.mass = types.SimpleNamespace(
            streams=types.SimpleNamespace(audio=types.SimpleNamespace(briefings=self.mixer)),
            players=types.SimpleNamespace(get_player=lambda _: self.player, cmd_volume_set=volume))
        async def get_track(uri):
            return types.SimpleNamespace(uri=uri, available=True)
        self.host.mass.music = types.SimpleNamespace(get_item_by_uri=get_track)
        self.host._queue_data = {'Kitchen': self.data}
        self.host.update_items = lambda queue, items: setattr(self.data, 'items', items)
        async def set_repeat(queue, repeat_mode):
            self.queue.repeat_mode = repeat_mode
            self.calls.append(('repeat', repeat_mode))
        def set_autoplay(queue, enabled):
            self.data.autoplay_override = enabled
            self.queue.autoplay_enabled = enabled
            self.calls.append(('autoplay', enabled))
        self.host.set_repeat = set_repeat
        self.host.set_autoplay = set_autoplay
        self.host._resolve_default_toggles = lambda data: setattr(
            data.queue, 'autoplay_enabled',
            True if data.autoplay_override is None else data.autoplay_override)
        self.host.signal_update = lambda queue: self.calls.append(('signal_update', queue))
        self.host.get_item = lambda queue, index: self.data.items[index] if isinstance(index, int) and 0 <= index < len(self.data.items) else None
        self.host.get = lambda _: self.queue
        def permission(_):
            if self.denied:
                raise PermissionError('denied')
        self.host._check_player_permission = permission
        self.enqueues = 0
        self.positions = []
        async def play_media(queue, uri, option):
            self.assertEqual(option, 'add')
            self.data.items.append(build_queue_item(queue, types.SimpleNamespace(uri=uri)))
        self.host.play_media = play_media
        async def play_index(queue, item, seek, fade, *, briefing=None, briefing_owner=None):
            self.assertTrue(self.lock.locked())
            self.assertGreaterEqual(seek, 0)
            self.positions.append((item, seek))
            self.calls.append(('play_index', briefing is not None))
            self.mixer.cancel_queue(queue)
            self.data.session_id = 'session-' + str(len(self.calls))
            if briefing is not None:
                self.mixer.arm(queue, self.data.session_id, briefing.run_id, briefing.source,
                               levels=briefing.levels)
            if briefing_owner is not None:
                self.mixer.bind_owner(queue, self.data.session_id, briefing_owner)
            if briefing_owner is not None:
                await volume(queue, briefing_owner['volume_level'])
            self.queue.state = self.player.state.playback_state = State.PLAYING
            self.queue.current_item = next(i for i in self.data.items if i.queue_item_id == item)
            self.queue.corrected_elapsed_time = seek
            self.player.state.active_source = queue
        self.host._play_index = play_index
        async def stop(queue):
            self.calls.append('stop')
            self.queue.state = self.player.state.playback_state = State.IDLE
            self.data.session_id = None
        self.host._handle_stop = stop
        self.host._clear = lambda *a, **k: self.data.items.clear()
        self.get_engines = AsyncMock(return_value=[types.SimpleNamespace(uid='ha/tts.piper', id='tts.piper',
                                                    provider=types.SimpleNamespace(domain='hass',
                                                        get_setup_value=lambda key: 'http://supervisor/core/api'))])
        self.patch = patch.dict(sys.modules, {'music_assistant.helpers.plugin_engines':
                        types.SimpleNamespace(get_tts_engines=self.get_engines)})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def start(self, **kwargs):
        params = dict(queue_id='Kitchen', run_id='run-1', track_uri='library://track/642',
                      message='Good morning', tts_engine='ha/tts.piper', language='en_GB')
        params.update(kwargs)
        return await self.host.briefing_test_start(**params)

    async def control(self, action, run='run-1'):
        return await self.host.briefing_test_control('Kitchen', run, action)

    async def test_all_commands_require_control_scope_and_permissions(self):
        self.assertEqual(len(self.scopes), 7)
        self.assertEqual(set(self.scopes.values()), {'control'})
        self.denied = True
        for call in (self.start, lambda: self.control('stop'),
                     lambda: self.host.briefing_test_capabilities('Kitchen'),
                     lambda: self.host.alarm_volume('Kitchen', 'run-1', 25)):
            with self.assertRaises(PermissionError):
                await call()
        self.assertFalse(self.calls)

    async def test_capability_check_is_read_only_and_has_exact_engine_identity(self):
        result = await self.host.briefing_test_capabilities('Kitchen')
        self.assertTrue(result['ready'])
        self.assertEqual(result['engines'][0]['entity_id'], 'tts.piper')
        self.assertFalse(self.calls)
        self.assertEqual(self.data.items, [])

    async def test_alarm_capabilities_allow_repeat_and_autoplay_but_test_capabilities_do_not(self):
        self.queue.repeat_mode = RepeatMode.ALL
        self.queue.autoplay_enabled = True
        ordinary = await self.host.briefing_test_capabilities('Kitchen')
        self.assertFalse(ordinary['ready'])
        alarm = await self.host.alarm_capabilities('Kitchen')
        self.assertTrue(alarm['ready'])
        self.assertEqual(alarm['queue_modes'], {
            'repeat_mode': 'all', 'autoplay_override': None, 'autoplay_enabled': True,
        })
        self.assertEqual(self.queue.repeat_mode, RepeatMode.ALL)
        self.assertTrue(self.queue.autoplay_enabled)
        self.assertFalse(self.calls)

    async def test_external_home_assistant_with_same_entity_id_is_not_substituted(self):
        self.get_engines.return_value[0].provider.get_setup_value = lambda key: 'https://another-ha.invalid'
        result = await self.host.briefing_test_capabilities('Kitchen')
        self.assertEqual(result['engines'], [])

    async def test_overlay_repeat_autoplay_and_groups_block_before_tts(self):
        for obj, key, value in ((self.queue, 'overlay_enabled', True),
                (self.queue, 'autoplay_enabled', True), (self.queue, 'repeat_mode', 'one'),
                (self.player.state, 'type', 'group'), (self.player.state, 'active_group', 'group')):
            old = getattr(obj, key)
            setattr(obj, key, value)
            with self.subTest(key=key), self.assertRaises(ValueError):
                await self.start()
            setattr(obj, key, old)
        self.assertFalse(self.calls)

    async def test_nonempty_queue_is_never_replaced(self):
        existing = object()
        self.data.items.append(existing)
        with self.assertRaisesRegex(ValueError, 'empty'):
            await self.start()
        self.assertEqual(self.data.items, [existing])
        self.assertFalse(self.calls)

    async def test_untrusted_media_engine_and_volume_are_rejected(self):
        for kwargs in ({'track_uri': 'https://example.invalid/song'}, {'track_uri': 'library://track/1/x'},
                       {'tts_engine': 'unregistered'}, {'volume_level': 41}, {'volume_level': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                await self.start(**kwargs)
        self.assertFalse(self.calls)

    async def test_start_binds_only_its_new_session_and_saves_no_speech_in_owner(self):
        result = await self.start()
        self.assertEqual(result['status'], 'playing')
        owner = self.mixer.owner('Kitchen', 'run-1', self.data.session_id)
        self.assertEqual(owner['item_id'], 'test-item')
        self.assertNotIn('message', owner)
        self.assertNotIn('source', owner)

    async def alarm_start(self, run='alarm-run', queue_modes=None):
        return await self.host.alarm_start(
            queue_id='Kitchen', run_id=run, track_uri='library://track/642',
            queue_modes=queue_modes or {
                'repeat_mode': 'all', 'autoplay_override': None, 'autoplay_enabled': True,
            },
        )

    async def test_alarm_temporarily_suspends_then_restores_repeat_and_autoplay(self):
        self.queue.repeat_mode = RepeatMode.ALL
        self.queue.autoplay_enabled = True
        self.assertEqual((await self.alarm_start())['status'], 'playing')
        self.assertEqual(self.queue.repeat_mode, RepeatMode.OFF)
        self.assertFalse(self.queue.autoplay_enabled)
        self.assertFalse(self.data.autoplay_override)
        result = await self.host.alarm_control('Kitchen', 'alarm-run', 'stop')
        self.assertTrue(result['owned'])
        self.assertEqual(self.queue.repeat_mode, RepeatMode.ALL)
        self.assertTrue(self.queue.autoplay_enabled)
        self.assertIsNone(self.data.autoplay_override)

    async def test_alarm_restores_queue_modes_after_snooze(self):
        self.queue.repeat_mode = RepeatMode.ONE
        self.queue.autoplay_enabled = True
        self.data.autoplay_override = True
        await self.alarm_start(queue_modes={
            'repeat_mode': 'one', 'autoplay_override': True, 'autoplay_enabled': True,
        })
        result = await self.host.alarm_control('Kitchen', 'alarm-run', 'snooze')
        self.assertTrue(result['owned'])
        self.assertEqual(self.queue.repeat_mode, RepeatMode.ONE)
        self.assertTrue(self.queue.autoplay_enabled)
        self.assertTrue(self.data.autoplay_override)

    async def test_alarm_does_not_overwrite_queue_modes_changed_by_user(self):
        self.queue.repeat_mode = RepeatMode.ALL
        self.queue.autoplay_enabled = True
        await self.alarm_start()
        self.queue.repeat_mode = RepeatMode.ONE
        self.data.autoplay_override = True
        self.queue.autoplay_enabled = True
        await self.host.alarm_control('Kitchen', 'alarm-run', 'stop')
        self.assertEqual(self.queue.repeat_mode, RepeatMode.ONE)
        self.assertTrue(self.queue.autoplay_enabled)
        self.assertTrue(self.data.autoplay_override)

    async def test_alarm_can_restore_modes_from_ha_snapshot_after_companion_state_loss(self):
        self.queue.repeat_mode = RepeatMode.OFF
        self.queue.autoplay_enabled = False
        modes = {'repeat_mode': 'all', 'autoplay_override': None, 'autoplay_enabled': True}
        result = await self.host.alarm_control(
            'Kitchen', 'old-run', 'stop', queue_modes=modes,
        )
        self.assertTrue(result['released'])
        self.assertEqual(self.queue.repeat_mode, RepeatMode.ALL)
        self.assertTrue(self.queue.autoplay_enabled)
        self.assertIsNone(self.data.autoplay_override)

    async def test_snooze_and_restart_keep_song_and_do_not_prepare_speech_twice(self):
        await self.start()
        await self.control('snooze')
        self.assertEqual(self.queue.state, State.IDLE)
        self.assertIsNone(self.data.session_id)
        await self.control('restart')
        self.assertEqual(self.queue.state, State.PLAYING)
        self.assertEqual(self.calls.count('prepare'), 1)
        self.assertIn(('play_index', False), self.calls)
        self.assertIsNotNone(self.mixer.owner('Kitchen', 'run-1', self.data.session_id))

    async def test_stale_run_or_session_cannot_stop_other_audio(self):
        await self.start()
        self.assertFalse((await self.control('stop', run='wrong-run'))['owned'])
        self.data.session_id = 'someone-elses-session'
        self.assertFalse((await self.control('stop'))['owned'])
        self.assertNotIn('stop', self.calls)

    async def test_foreign_source_and_changed_queue_are_not_stopped(self):
        await self.start()
        self.player.state.active_source = 'other-source'
        self.assertFalse((await self.control('stop'))['owned'])
        self.player.state.active_source = 'Kitchen'
        self.data.items.append(object())
        self.assertFalse((await self.control('stop'))['owned'])
        self.assertNotIn('stop', self.calls)

    async def test_stop_restores_owned_volume_and_clears_only_test_queue(self):
        await self.start()
        self.assertTrue((await self.control('stop'))['owned'])
        self.assertEqual(self.player.state.volume_level, 23)
        self.assertFalse(self.data.items)
        self.assertFalse(self.mixer._owners)

    async def test_manual_volume_change_is_preserved(self):
        await self.start()
        self.player.state.volume_level = 32
        await self.control('stop')
        self.assertEqual(self.player.state.volume_level, 32)

    async def test_stop_before_start_tombstones_run_preventing_late_playback(self):
        self.assertFalse((await self.control('stop'))['owned'])
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            await self.start()
        self.assertFalse(self.calls)

    async def test_production_capabilities_are_distinct_from_test_protocol(self):
        result = await self.host.alarm_capabilities('Kitchen')
        self.assertEqual(result['protocol'], 2)
        self.assertIn('speech_delay', result['features'])
        self.assertIn('external_command_dismissal', result['features'])
        self.assertFalse(self.calls)

    def install_generated_queue_controls(self):
        """Run the actual patched upstream Stop/Pause, not a status-response fake."""
        # Exact upstream methods are vendored so CI/app-runtime tests don't need
        # the developer's local pristine checkout. The source contract below
        # verifies the fixture against the hash-locked upstream when available.
        source = (fixture.ROOT / 'tests/fixtures/pinned_queue_controls.py.txt').read_text()
        tree = ast.parse('class Host:\n' + fixture.builder.external_command_hooks(source))
        methods = [node for node in ast.walk(tree)
                   if isinstance(node, ast.AsyncFunctionDef) and node.name in ('stop', 'pause')]
        namespace = {'PlaybackState': State, 'ATTR_ANNOUNCEMENT_IN_PROGRESS': 'announcement',
                     'asyncio': asyncio}
        for method in methods:
            method.decorator_list = []
            exec('from __future__ import annotations\n' + ast.unparse(method), namespace)
            setattr(self.host, method.name, types.MethodType(namespace[method.name], self.host))
        self.queue.active = True
        self.host.mass.cancel_timer = lambda *args: None
        self.host._set_transitioning = lambda *args: None
        # Avoid the unrelated 30-second upstream watcher; dispatch below is real.
        self.player.extra_data = {'announcement': True}
        async def pause(queue_id):
            self.queue.state = self.player.state.playback_state = State.PAUSED
        self.host.mass.players._handle_cmd_pause = pause

    async def test_generated_pause_and_stop_preserve_exact_run_dismiss_intent_after_owner_loss(self):
        self.install_generated_queue_controls()
        for action in ('pause', 'stop'):
            run = 'external-' + action
            await self.host.alarm_start('Kitchen', run, 'library://track/22')
            await getattr(self.host, action)('Kitchen')
            self.assertIsNone(self.mixer.owner('Kitchen', run, self.data.session_id))
            status = await self.host.alarm_control('Kitchen', run, 'status')
            self.assertEqual(status, {'protocol': 2, 'owned': False, 'dismiss_requested': True})
            # Retrying status/restart must not consume intent or revive playback.
            self.assertEqual(await self.host.alarm_control('Kitchen', run, 'restart'), status)
            self.assertEqual(await self.host.alarm_control('Kitchen', run, 'status'), status)
            await self.host.alarm_control('Kitchen', run, 'stop')

    async def test_generated_pause_pending_state_prevents_transient_takeover_block(self):
        self.install_generated_queue_controls()
        await self.host.alarm_start('Kitchen', 'pending', 'library://track/22')
        entered, finish = asyncio.Event(), asyncio.Event()
        original = self.host.mass.players._handle_cmd_pause
        async def wait_for_dispatch(queue_id):
            entered.set()
            await finish.wait()
            await original(queue_id)
        self.host.mass.players._handle_cmd_pause = wait_for_dispatch
        task = asyncio.create_task(self.host.pause('Kitchen'))
        try:
            await entered.wait()
            status = await self.host.alarm_control('Kitchen', 'pending', 'status')
            self.assertEqual(status, {'protocol': 2, 'owned': False, 'command_pending': True})
            self.assertEqual(await self.host.alarm_control('Kitchen', 'pending', 'restart'), status)
        finally:
            finish.set()
            await task
        self.assertTrue((await self.host.alarm_control('Kitchen', 'pending', 'status'))['dismiss_requested'])

    async def test_generated_failed_or_cancelled_pause_does_not_confirm_dismissal(self):
        self.install_generated_queue_controls()
        for index, error in enumerate((ValueError('dispatch failed'), asyncio.CancelledError())):
            run = f'failed-{index}'
            await self.host.alarm_start('Kitchen', run, 'library://track/22')
            async def fail(*args):
                raise error
            self.host.mass.players._handle_cmd_pause = fail
            with self.assertRaises(type(error)):
                await self.host.pause('Kitchen')
            self.assertEqual(await self.host.alarm_control('Kitchen', run, 'status'),
                             {'protocol': 2, 'owned': False})

    async def test_generated_permission_denial_never_records_external_intent(self):
        self.install_generated_queue_controls()
        await self.host.alarm_start('Kitchen', 'permission', 'library://track/22')
        self.denied = True
        with self.assertRaises(PermissionError):
            await self.host.pause('Kitchen')
        self.denied = False
        self.assertEqual(await self.host.alarm_control('Kitchen', 'permission', 'status'),
                         {'protocol': 2, 'owned': True, 'state': 'playing'})

    async def test_generated_failed_stop_never_confirms_dismissal(self):
        self.install_generated_queue_controls()
        await self.host.alarm_start('Kitchen', 'failed-stop', 'library://track/22')
        async def fail(*args):
            raise ValueError('stop dispatch failed')
        self.host._handle_stop = fail
        with self.assertRaises(ValueError):
            await self.host.stop('Kitchen')
        self.assertEqual(await self.host.alarm_control('Kitchen', 'failed-stop', 'status'),
                         {'protocol': 2, 'owned': False})

    async def test_group_or_source_takeover_does_not_capture_explicit_dismissal(self):
        self.install_generated_queue_controls()
        await self.host.alarm_start('Kitchen', 'group', 'library://track/22')
        for field, value in (('active_source', 'other'), ('active_group', 'other'),
                             ('synced_to', 'other'), ('type', 'group'),
                             ('group_members', ['one', 'two'])):
            previous = getattr(self.player.state, field)
            setattr(self.player.state, field, value)
            self.assertIsNone(self.host._capture_alarm_external_command('Kitchen'))
            setattr(self.player.state, field, previous)

    async def test_takeover_disconnect_and_natural_idle_are_not_external_commands(self):
        await self.host.alarm_start('Kitchen', 'natural', 'library://track/22')
        self.queue.state = State.IDLE
        self.assertNotIn('dismiss_requested', await self.host.alarm_control('Kitchen', 'natural', 'status'))
        self.mixer.cancel_queue('Kitchen')
        self.assertEqual(await self.host.alarm_control('Kitchen', 'natural', 'status'),
                         {'protocol': 2, 'owned': False})

    async def test_generated_pause_on_different_item_never_dismisses_previous_alarm(self):
        self.install_generated_queue_controls()
        await self.host.alarm_start('Kitchen', 'old-item', 'library://track/22')
        user = types.SimpleNamespace(queue_item_id='user', uri='library://track/3')
        self.data.items.append(user)
        self.queue.current_item = user
        await self.host.pause('Kitchen')
        self.assertEqual(await self.host.alarm_control('Kitchen', 'old-item', 'status'),
                         {'protocol': 2, 'owned': False})

    async def test_external_intent_never_applies_to_another_run(self):
        self.install_generated_queue_controls()
        await self.host.alarm_start('Kitchen', 'first', 'library://track/22')
        await self.host.pause('Kitchen')
        await self.host.alarm_start('Kitchen', 'second', 'library://track/22')
        self.assertEqual(await self.host.alarm_control('Kitchen', 'second', 'status'),
                         {'protocol': 2, 'owned': True, 'state': 'playing'})
        before = list(self.positions)
        await self.host.alarm_control('Kitchen', 'first', 'stop')
        self.assertEqual(self.positions, before)
        self.assertEqual(self.queue.state, State.PLAYING)

    async def test_production_preserves_existing_tracks_and_starts_alarm_immediately(self):
        for active in (False, True):
            with self.subTest(active=active):
                original = [types.SimpleNamespace(uri='library://track/1', queue_item_id='old-1'),
                            types.SimpleNamespace(uri='library://track/2', queue_item_id='old-2')]
                self.data.items = original.copy()
                self.queue.state = self.player.state.playback_state = State.PLAYING if active else State.IDLE
                self.queue.current_item = original[0]
                self.queue.corrected_elapsed_time = 42
                run = f'preserve-{active}'
                self.assertTrue((await self.host.alarm_capabilities('Kitchen'))['ready'])
                await self.host.alarm_start('Kitchen', run, 'library://track/22')
                self.assertEqual(self.data.items[:2], original)
                self.assertEqual(self.queue.current_item.uri, 'library://track/22')
                await self.host.alarm_control('Kitchen', run, 'snooze')
                self.assertEqual(self.data.items, original)
                if active:
                    self.assertEqual(self.positions[-1], ('old-1', 42))
                await self.host.alarm_start('Kitchen', run + '-wake', 'library://track/22')
                self.assertEqual(len(self.data.items), 3)
                await self.host.alarm_control('Kitchen', run + '-wake', 'stop')
                self.assertEqual(self.data.items, original)

    async def test_production_does_not_stop_later_user_playback(self):
        await self.host.alarm_start('Kitchen', 'takeover', 'library://track/22')
        user = types.SimpleNamespace(uri='library://track/2', queue_item_id='user')
        self.data.items.append(user)
        self.queue.current_item = user
        result = await self.host.alarm_control('Kitchen', 'takeover', 'stop')
        self.assertFalse(result['owned'])
        self.assertNotIn('stop', self.calls)
        self.assertIn(user, self.data.items)

    async def test_production_duplicate_uri_is_identified_by_queue_item_not_song(self):
        existing = types.SimpleNamespace(uri='library://track/22', queue_item_id='old-copy')
        self.data.items = [existing]
        await self.host.alarm_start('Kitchen', 'same-song', 'library://track/22',
            message='Good morning', tts_engine='ha/tts.piper')
        await self.host.alarm_control('Kitchen', 'same-song', 'snooze')
        await self.host.alarm_start('Kitchen', 'same-song-wake', 'library://track/22')
        self.assertEqual(self.calls.count('prepare'), 1)
        self.assertEqual(self.data.items[0], existing)
        await self.host.alarm_control('Kitchen', 'same-song-wake', 'stop')
        self.assertEqual(self.data.items, [existing])

    async def test_production_uncertain_enqueue_is_never_duplicated(self):
        original = self.host.update_items
        def lost_response(*args, **kwargs):
            original(*args, **kwargs)
            raise ValueError('response lost')
        self.host.update_items = lost_response
        with self.assertRaises(ValueError):
            await self.host.alarm_start('Kitchen', 'lost', 'library://track/22')
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            await self.host.alarm_start('Kitchen', 'lost', 'library://track/22')
        self.assertEqual(len(self.data.items), 1)

    def prior_music(self, item_id='prior', position=73):
        item = types.SimpleNamespace(uri='library://track/5', queue_item_id=item_id)
        self.data.items.append(item)
        self.queue.current_item = item
        self.queue.current_index = len(self.data.items) - 1
        self.queue.corrected_elapsed_time = position
        self.queue.state = self.player.state.playback_state = State.PLAYING
        self.player.state.active_source = 'Kitchen'
        return item

    async def test_snooze_removes_only_alarm_and_resumes_interrupted_position(self):
        prior = self.prior_music()
        self.host._clear = lambda *a, **k: self.fail('An alarm must never clear the queue')
        await self.host.alarm_start('Kitchen', 'ring', 'library://track/22')
        alarm_id = self.queue.current_item.queue_item_id
        copy = types.SimpleNamespace(uri='library://track/22', queue_item_id='user-copy')
        self.data.items.insert(0, copy)
        result = await self.host.alarm_control('Kitchen', 'ring', 'snooze')
        self.assertTrue(result['restored'])
        self.assertEqual(self.positions[-1], (prior.queue_item_id, 73))
        self.assertEqual(self.data.items, [copy, prior])
        self.assertNotIn(alarm_id, [item.queue_item_id for item in self.data.items])
        self.assertFalse(self.mixer._owners)  # restored music is not alarm-owned

    async def test_each_snooze_wake_captures_current_music_and_new_position(self):
        self.prior_music(position=10)
        for ordinal in range(3):
            run = f'ring-{ordinal}'
            await self.host.alarm_start('Kitchen', run, 'library://track/22')
            result = await self.host.alarm_control('Kitchen', run, 'snooze')
            self.assertTrue(result['restored'])
            expected = ('prior', 10) if ordinal == 0 else (f'changed-{ordinal}', ordinal * 31)
            self.assertEqual(self.positions[-1], expected)
            self.prior_music(f'changed-{ordinal + 1}', (ordinal + 1) * 31)
        self.assertTrue(all(not i.queue_item_id.startswith('test-item') for i in self.data.items))

    async def test_dismiss_resumes_prior_music_and_duplicate_stop_never_stops_it(self):
        self.prior_music(position=112)
        await self.host.alarm_start('Kitchen', 'dismiss', 'library://track/22')
        first = await self.host.alarm_control('Kitchen', 'dismiss', 'stop')
        self.assertEqual(self.positions[-1], ('prior', 112))
        before = list(self.calls)
        second = await self.host.alarm_control('Kitchen', 'dismiss', 'stop')
        self.assertEqual(first, second)
        self.assertEqual(before, self.calls)

    async def test_dismiss_without_prior_playing_music_leaves_queue_stopped(self):
        for state in (State.IDLE, State.PAUSED):
            self.prior_music()
            self.queue.state = self.player.state.playback_state = state
            run = 'stopped-' + state
            await self.host.alarm_start('Kitchen', run, 'library://track/22')
            count = len(self.data.items) - 1
            result = await self.host.alarm_control('Kitchen', run, 'stop')
            self.assertFalse(result['restored'])
            self.assertEqual(self.queue.state, State.IDLE)
            self.assertEqual(len(self.data.items), count)

    async def test_empty_queue_is_stopped_after_dismiss(self):
        await self.host.alarm_start('Kitchen', 'empty', 'library://track/22')
        await self.host.alarm_control('Kitchen', 'empty', 'stop')
        self.assertEqual(self.data.items, [])
        self.assertEqual(self.queue.state, State.IDLE)

    async def test_deleted_prior_track_is_not_reinserted_and_user_edits_survive(self):
        prior = self.prior_music()
        await self.host.alarm_start('Kitchen', 'edited', 'library://track/22')
        self.data.items.remove(prior)
        addition = types.SimpleNamespace(uri='library://track/7', queue_item_id='addition')
        self.data.items.insert(0, addition)
        result = await self.host.alarm_control('Kitchen', 'edited', 'stop')
        self.assertFalse(result['restored'])
        self.assertEqual(self.data.items, [addition])
        self.assertEqual(self.queue.state, State.IDLE)

    async def test_new_session_takeover_cleans_only_safe_stale_item_without_restore(self):
        self.prior_music()
        await self.host.alarm_start('Kitchen', 'taken', 'library://track/22')
        user = self.prior_music('user-session', 90)
        self.data.session_id = 'new-user-session'
        before = list(self.calls)
        result = await self.host.alarm_control('Kitchen', 'taken', 'stop')
        self.assertTrue(result['released'])
        self.assertFalse(result['owned'])
        self.assertEqual(self.calls, before)
        self.assertEqual(self.queue.current_item, user)
        self.assertEqual(self.queue.current_index, 1)
        self.assertEqual([i.queue_item_id for i in self.data.items], ['prior', 'user-session'])

    async def test_uncertain_restore_is_not_dispatched_again(self):
        self.prior_music()
        await self.host.alarm_start('Kitchen', 'uncertain', 'library://track/22')
        original = self.host._play_index
        async def lost_response(*args, **kwargs):
            await original(*args, **kwargs)
            raise TimeoutError('response lost after resuming')
        self.host._play_index = lost_response
        with self.assertRaises(TimeoutError):
            await self.host.alarm_control('Kitchen', 'uncertain', 'stop')
        before = list(self.calls)
        result = await self.host.alarm_control('Kitchen', 'uncertain', 'stop')
        self.assertTrue(result['restoration_failed'])
        self.assertEqual(self.calls, before)

    async def test_user_deleted_track_during_enqueue_is_not_restored_from_snapshot(self):
        prior = self.prior_music()
        original = self.host.mass.music.get_item_by_uri
        async def edited(*args, **kwargs):
            media = await original(*args, **kwargs)
            self.data.items.remove(prior)
            self.queue.current_item = None
            return media
        self.host.mass.music.get_item_by_uri = edited
        await self.host.alarm_start('Kitchen', 'enqueue-edit', 'library://track/22')
        await self.host.alarm_control('Kitchen', 'enqueue-edit', 'stop')
        self.assertEqual(self.data.items, [])

    async def test_source_takeover_during_volume_restore_prevents_stale_resume(self):
        self.prior_music()
        await self.host.alarm_start('Kitchen', 'restore-race', 'library://track/22')
        async def volume_then_takeover(*args):
            self.player.state.active_source = 'new-source'
        self.host.mass.players.cmd_volume_set = volume_then_takeover
        before = len(self.positions)
        result = await self.host.alarm_control('Kitchen', 'restore-race', 'stop')
        self.assertFalse(result['restored'])
        self.assertEqual(len(self.positions), before)
        self.assertEqual(self.player.state.active_source, 'new-source')

    async def test_foreign_playing_source_blocks_alarm_without_mutation(self):
        self.player.state.active_source = 'line-in'
        self.player.state.playback_state = State.PLAYING
        with self.assertRaisesRegex(ValueError, 'speaker source'):
            await self.host.alarm_start('Kitchen', 'foreign-source', 'library://track/22')
        self.assertEqual(self.data.items, [])
        self.assertEqual(self.calls, [])

    async def test_early_snooze_prevents_late_start(self):
        self.assertFalse((await self.host.alarm_control('Kitchen', 'early', 'snooze'))['owned'])
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            await self.host.alarm_start('Kitchen', 'early', 'library://track/22')
        self.assertEqual(self.data.items, [])

    async def test_alarm_does_not_use_normal_enqueue_shuffle_or_replacement(self):
        self.prior_music()
        self.host.play_media = AsyncMock(side_effect=AssertionError('normal enqueue would reorder tracks'))
        await self.host.alarm_start('Kitchen', 'append-only', 'library://track/22')
        self.host.play_media.assert_not_awaited()
        self.assertEqual([i.queue_item_id for i in self.data.items], ['prior', 'test-item'])

    async def test_production_selected_song_delay_and_music_only_start(self):
        result = await self.host.alarm_start('Kitchen', 'scheduled-1', 'library://track/22',
            message='Good morning', tts_engine='ha/tts.piper', speech_delay=120)
        self.assertEqual(result['protocol'], 2)
        self.assertEqual(self.mixer._pending['Kitchen'].levels.delay_seconds, 120)
        await self.host.alarm_control('Kitchen', 'scheduled-1', 'stop')
        await self.host.alarm_start('Kitchen', 'scheduled-2', 'library://track/22')
        self.assertEqual(self.calls.count('prepare'), 1)
        self.assertTrue(self.mixer.has_run('Kitchen', 'scheduled-2'))

    async def test_production_rejects_invalid_delay_gain_track_and_voice_before_mutation(self):
        for fields in ({'speech_delay': True}, {'speech_delay': -1}, {'speech_delay': 121},
                       {'music_gain': 0}, {'music_gain': float('nan')}, {'music_gain': .31},
                       {'volume_level': 101}, {'track_uri': 'library://track/١'},
                       {'message': 'Morning', 'tts_engine': 'unregistered'}):
            params = dict(queue_id='Kitchen', run_id='production', track_uri='library://track/22')
            params.update(fields)
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                await self.host.alarm_start(**params)
        self.assertFalse(self.calls)

    async def test_ramp_changes_volume_without_restarting_or_preparing_speech(self):
        await self.start()
        before = list(self.calls)
        result = await self.host.alarm_volume('Kitchen', 'run-1', 25)
        self.assertTrue(result['owned'])
        self.assertFalse(result['suspended'])
        self.assertEqual(result['volume_level'], 25)
        self.assertEqual(self.calls, before + [('volume', 25)])
        self.assertEqual(self.mixer.owner('Kitchen', 'run-1', self.data.session_id)['volume_level'], 25)
        await self.control('stop')
        self.assertEqual(self.player.state.volume_level, 23)

    async def test_ramp_manual_change_suspends_preserves_loops_and_cleanup(self):
        await self.start()
        self.player.state.volume_level = 12
        result = await self.host.alarm_volume('Kitchen', 'run-1', 30)
        self.assertTrue(result['suspended'])
        self.assertEqual(result['volume_level'], 12)
        self.assertNotIn(('volume', 30), self.calls)
        self.queue.state = State.IDLE
        await self.host.alarm_control('Kitchen', 'run-1', 'restart')
        owner = self.mixer.owner('Kitchen', 'run-1', self.data.session_id)
        self.assertEqual(owner['volume_level'], 12)
        self.assertTrue(owner['ramp_suspended'])
        await self.control('stop')
        self.assertEqual(self.player.state.volume_level, 12)

    async def test_ramp_unknown_level_suspends_without_volume_write(self):
        await self.start()
        self.player.state.volume_level = None
        before = list(self.calls)
        result = await self.host.alarm_volume('Kitchen', 'run-1', 30)
        self.assertTrue(result['suspended'])
        self.assertEqual(before, self.calls)
        self.queue.state = State.IDLE
        with self.assertRaisesRegex(ValueError, 'Check the speaker volume'):
            await self.host.alarm_control('Kitchen', 'run-1', 'restart')
        self.assertEqual(before, self.calls)

    async def test_manual_change_between_ramp_poll_and_song_loop_is_preserved(self):
        await self.start()
        await self.host.alarm_volume('Kitchen', 'run-1')
        self.player.state.volume_level = 11
        self.queue.state = State.IDLE
        await self.host.alarm_control('Kitchen', 'run-1', 'restart')
        owner = self.mixer.owner('Kitchen', 'run-1', self.data.session_id)
        self.assertEqual(owner['volume_level'], 11)
        self.assertTrue(owner['ramp_suspended'])

    async def test_ramp_rejects_stale_run_session_source_and_group(self):
        await self.start()
        before = list(self.calls)
        self.assertFalse((await self.host.alarm_volume('Kitchen', 'stale-run', 30))['owned'])
        for obj, key, value in ((self.data, 'session_id', 'foreign'),
                (self.player.state, 'active_source', 'other'),
                (self.player.state, 'active_group', 'group'),
                (self.player.state, 'synced_to', 'group'),
                (self.player.state, 'group_members', ['Kitchen', 'Other'])):
            old = getattr(obj, key)
            setattr(obj, key, value)
            self.assertFalse((await self.host.alarm_volume('Kitchen', 'run-1', 30))['owned'])
            setattr(obj, key, old)
        self.data.items.append(object())
        self.assertFalse((await self.host.alarm_volume('Kitchen', 'run-1', 30))['owned'])
        self.assertEqual(before, self.calls)

    async def test_ramp_idle_never_changes_hardware_and_snooze_reset_only_resets_ring(self):
        await self.start()
        await self.host.alarm_volume('Kitchen', 'run-1', 30)
        await self.control('snooze')
        before = list(self.calls)
        await self.host.alarm_volume('Kitchen', 'run-1', 35)
        self.assertEqual(before, self.calls)
        await self.host.alarm_control('Kitchen', 'run-1', 'restart', volume_level=20)
        owner = self.mixer.owner('Kitchen', 'run-1', self.data.session_id)
        self.assertEqual(owner['volume_level'], 20)
        self.assertFalse(owner['ramp_suspended'])
        self.assertEqual(self.calls.count('prepare'), 1)
        with self.assertRaises(ValueError):
            await self.host.alarm_control('Kitchen', 'run-1', 'restart', volume_level=20)

    async def test_ramp_invalid_levels_never_mutate(self):
        for value in (True, 0, 101, 25.5, '25'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                await self.host.alarm_volume('Kitchen', 'run-1', value)
        self.assertFalse(self.calls)

    async def test_ramp_uncertain_dispatch_keeps_intent_without_replaying_music(self):
        await self.start()
        self.host.mass.players.cmd_volume_set = AsyncMock(side_effect=TimeoutError())
        before = list(self.calls)
        with self.assertRaises(TimeoutError):
            await self.host.alarm_volume('Kitchen', 'run-1', 30)
        self.assertEqual(before, self.calls)
        owner = self.mixer.owner('Kitchen', 'run-1', self.data.session_id)
        self.assertEqual(owner['volume_level'], 30)


if __name__ == '__main__':
    unittest.main(verbosity=2)

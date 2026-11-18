"""Execute the proposed MA test command bodies with fake controllers, not a server."""

import asyncio
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
        namespace = dict(api_command=api_command, handle_play_action=handle_play_action, Any=object,
            get_tts_engines=lambda mass: self.get_engines(mass),
            Scope=types.SimpleNamespace(QUEUES_CONTROL='control'), PlaybackState=State,
            PlayerType=types.SimpleNamespace(GROUP='group'), RepeatMode=types.SimpleNamespace(OFF='off'),
            MediaType=types.SimpleNamespace(TRACK='track'), QueueOption=types.SimpleNamespace(ADD='add'),
            PlayerUnavailableError=ValueError, InvalidDataError=ValueError,
            prepare_briefing=prepare, MixLevels=fixture.adapter.MixLevels)
        source = (fixture.ROOT / 'prototypes/ma_one_shot/test_commands.py.txt').read_text()
        source += '\n' + (fixture.ROOT / 'prototypes/ma_one_shot/alarm_commands.py.txt').read_text()
        exec('class Host:\n' + source, namespace)
        self.host = namespace['Host']()
        self.queue = types.SimpleNamespace(state=State.IDLE, repeat_mode='off',
                                            autoplay_enabled=False, overlay_enabled=False)
        self.data = types.SimpleNamespace(queue=self.queue, items=[], session_id=None)
        self.player = types.SimpleNamespace(state=types.SimpleNamespace(
            type='player', active_group=None, synced_to=None, group_members=[],
            playback_state=State.IDLE, active_source=None, volume_level=23))
        async def volume(queue, level):
            self.calls.append(('volume', level))
            self.player.state.volume_level = level
        self.host.mass = types.SimpleNamespace(
            streams=types.SimpleNamespace(audio=types.SimpleNamespace(briefings=self.mixer)),
            players=types.SimpleNamespace(get_player=lambda _: self.player, cmd_volume_set=volume))
        self.host._queue_data = {'Kitchen': self.data}
        self.host.get = lambda _: self.queue
        def permission(_):
            if self.denied:
                raise PermissionError('denied')
        self.host._check_player_permission = permission
        async def play_media(queue, uri, option):
            self.assertEqual(option, 'add')
            self.data.items.append(types.SimpleNamespace(uri=uri, queue_item_id='test-item'))
        self.host.play_media = play_media
        async def play_index(queue, item, seek, fade, *, briefing=None, briefing_owner=None):
            self.assertTrue(self.lock.locked())
            self.assertEqual(seek, 0)
            self.calls.append(('play_index', briefing is not None))
            self.mixer.cancel_queue(queue)
            self.data.session_id = 'session-' + str(len(self.calls))
            if briefing is not None:
                self.mixer.arm(queue, self.data.session_id, briefing.run_id, briefing.source,
                               levels=briefing.levels)
            self.mixer.bind_owner(queue, self.data.session_id, briefing_owner)
            if briefing_owner is not None:
                await volume(queue, briefing_owner['volume_level'])
            self.queue.state = self.player.state.playback_state = State.PLAYING
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
        self.assertFalse(self.calls)

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

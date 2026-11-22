"""Offline HA/MA adapter tests. No HA runtime, provider calls or speaker audio."""

import asyncio
import ast
from copy import deepcopy
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_alarms as fixture

ma_audio = fixture.load('ma_audio')


class MusicTestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = fixture.FakeHass()
        self.manager = fixture.AlarmManager(self.hass)
        self.alarm = fixture.model.validate(fixture.config(assistant_id='assistant-test', briefing_enabled=True))
        self.manager.alarms[self.alarm['id']] = self.alarm
        self.clock = 0
        self.calls = []
        self.owned = True
        self.state = 'playing'
        self.ready = True
        self.engines = [{'uid': 'ha-provider/tts.piper', 'entity_id': 'tts.piper'}]
        self.capability_error = False
        self.stop_error = False
        self.start_gate = None
        self.start_error = False
        self.client = types.SimpleNamespace(send_command=self.command)
        self.tests = ma_audio.MusicTests(self.manager,
            resolver=lambda *a: (self.client, 'Kitchen Speaker'), clock=lambda: self.clock)
        self.manager.music_tests = self.tests

    async def asyncTearDown(self):
        if self.start_gate is not None:
            self.start_gate.set()
        self.stop_error = False
        if self.tests.active:
            await self.tests.async_action(self.tests.session['id'], 'dismiss')
        if self.tests.task is not None:
            await asyncio.wait_for(self.tests.task, timeout=2)

    async def command(self, command, **kwargs):
        self.calls.append((command, deepcopy(kwargs)))
        if command.endswith('capabilities'):
            if self.capability_error:
                raise RuntimeError('private URL and token')
            return {'protocol': 1, 'ready': self.ready, 'reasons': ['Use an empty development queue'] if not self.ready else [],
                    'engines': self.engines}
        if command == 'music/tracks/library_items':
            return [{'uri': 'library://track/642', 'name': 'Test library song'}]
        if command.endswith('briefing_test_start'):
            if self.start_gate is not None:
                await self.start_gate.wait()
            if self.start_error:
                raise TimeoutError('private source URL')
            return {'protocol': 1, 'status': 'playing'}
        if command.endswith('briefing_test_control'):
            if kwargs['action'] == 'stop' and self.stop_error:
                raise ConnectionError('private connection')
            if kwargs['action'] == 'snooze':
                self.state = 'idle'
            if kwargs['action'] == 'restart':
                self.state = 'playing'
            return {'protocol': 1, 'owned': self.owned, 'state': self.state}
        raise AssertionError(command)

    async def settle(self, condition=lambda: True):
        for _ in range(100):
            await asyncio.sleep(0)
            if condition():
                return
        self.fail('Test worker did not reach expected state')

    async def start(self, **kwargs):
        params = dict(alarm_id=self.alarm['id'], speaker='media_player.kitchen_dev',
                      confirmation='PLAY MUSIC', enabled=True, music_gain=.25,
                      volume_level=20, snooze_seconds=10)
        params.update(kwargs)
        return await self.tests.async_start(**params)

    async def playing(self):
        await self.start()
        await self.settle(lambda: self.tests.session['status'] == 'playing')

    async def action(self, name):
        return await self.tests.async_action(self.tests.session['id'], name)

    def count(self, suffix, action=None):
        return sum(command.endswith(suffix) and (action is None or kwargs.get('action') == action)
                   for command, kwargs in self.calls)

    async def test_off_by_default_and_requires_explicit_confirmation(self):
        for kwargs in ({'enabled': False}, {'confirmation': 'PLAY'}, {'confirmation': ''}):
            with self.subTest(kwargs=kwargs), self.assertRaises(fixture.model.AlarmError):
                await self.start(**kwargs)
        self.assertFalse(self.calls)
        self.assertFalse(self.manager.owners)

    async def test_bounds_reject_before_reserving_or_network(self):
        for kwargs in ({'music_gain': float('nan')}, {'music_gain': True}, {'music_gain': .31},
                       {'volume_level': True}, {'volume_level': 41}, {'snooze_seconds': 4},
                       {'speaker': 'script.anything'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(fixture.model.AlarmError):
                await self.start(**kwargs)
        self.assertFalse(self.calls)
        self.assertFalse(self.manager.owners)

    async def test_unpatched_server_is_read_only_failure_without_secret(self):
        self.capability_error = True
        await self.start()
        await self.tests.task
        self.assertEqual(self.tests.session['status'], 'failed')
        self.assertNotIn('private', self.tests.session['message'])
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.manager.owners)

    async def test_busy_queue_does_not_select_song_generate_or_play(self):
        self.ready = False
        self.manager.async_briefing = AsyncMock()
        await self.start()
        await self.tests.task
        self.assertEqual(len(self.calls), 1)
        self.manager.async_briefing.assert_not_awaited()
        self.assertIn('empty development queue', self.tests.session['message'])

    async def test_voice_matching_is_exact_and_never_uses_display_name(self):
        self.engines = [{'uid': 'other', 'entity_id': 'tts.other', 'name': 'Piper'}]
        await self.start()
        await self.tests.task
        self.assertEqual(self.count('briefing_test_start'), 0)
        self.assertIn("assistant's selected voice", self.tests.session['message'])

    async def test_ambiguous_voice_is_rejected(self):
        self.engines *= 2
        await self.start()
        await self.tests.task
        self.assertEqual(self.count('briefing_test_start'), 0)

    async def test_start_passes_pipeline_engine_language_voice_and_separate_gain(self):
        await self.playing()
        start = next(args for command, args in self.calls if command.endswith('briefing_test_start'))
        self.assertEqual(start['tts_engine'], 'ha-provider/tts.piper')
        self.assertEqual(start['language'], 'en_GB')
        self.assertEqual(start['voice'], 'en_GB-alan-medium')
        self.assertEqual(start['music_gain'], .25)
        self.assertEqual(start['volume_level'], 20)
        self.assertEqual(start['track_uri'], 'library://track/642')
        self.assertNotEqual(start['message'], self.tests.snapshot()['message'])
        self.assertNotIn(start['message'], str(self.tests.snapshot()))

    async def test_test_does_not_save_or_mutate_alarm_runs_schedules_or_switches(self):
        alarms = deepcopy(self.manager.alarms)
        await self.playing()
        await self.action('sleep_in')
        await self.tests.task
        self.assertEqual(self.manager.alarms, alarms)
        self.assertEqual(self.manager.runs, {})
        self.assertEqual(self.manager.revision, 0)
        self.assertIsNone(self.manager.store.data)
        self.assertFalse(any(domain == 'input_boolean' for domain, *_ in self.hass.services.calls))

    async def test_snooze_restarts_same_song_without_new_message_or_song_selection(self):
        await self.playing()
        await self.action('snooze')
        await self.settle(lambda: self.tests.session['status'] == 'snoozed')
        self.clock = 11
        self.tests.event.set()
        await self.settle(lambda: self.tests.session['status'] == 'playing')
        self.assertEqual(self.count('briefing_test_control', 'restart'), 1)
        self.assertEqual(self.count('briefing_test_start'), 1)
        self.assertEqual(self.count('library_items'), 1)
        self.assertEqual(sum(domain == 'conversation' for domain, *_ in self.hass.services.calls), 1)

    async def test_natural_song_end_restarts_music_only(self):
        await self.playing()
        self.state = 'idle'
        self.tests.event.set()
        await self.settle(lambda: self.count('briefing_test_control', 'restart') == 1)
        self.assertEqual(self.count('briefing_test_start'), 1)

    async def test_takeover_releases_control_without_stopping_other_playback(self):
        await self.playing()
        self.owned = False
        self.tests.event.set()
        await self.tests.task
        self.assertEqual(self.tests.session['status'], 'interrupted')
        self.assertEqual(self.count('briefing_test_control', 'stop'), 0)
        self.assertFalse(self.manager.owners)

    async def test_unknown_start_response_is_never_retried(self):
        self.start_error = True
        await self.start()
        await self.tests.task
        self.assertEqual(self.count('briefing_test_start'), 1)
        self.assertEqual(self.count('briefing_test_control', 'stop'), 1)
        self.assertNotIn('private', self.tests.session['message'])

    async def test_failed_stop_retains_reservation_and_explicit_retry_only_stops(self):
        await self.playing()
        self.stop_error = True
        await self.action('dismiss')
        await self.tests.task
        self.assertEqual(self.tests.session['status'], 'uncertain')
        self.assertTrue(self.manager.owners)
        with self.assertRaises(fixture.model.AlarmError):
            await self.start()
        self.stop_error = False
        await self.action('dismiss')
        await self.tests.task
        self.assertFalse(self.manager.owners)
        self.assertEqual(self.tests.session['status'], 'dismissed')
        self.assertEqual(self.count('briefing_test_start'), 1)

    async def test_dismiss_during_generation_prevents_late_playback(self):
        gate = asyncio.Event()
        async def briefing(*args):
            await gate.wait()
            return 'Morning'
        self.manager.async_briefing = briefing
        await self.start()
        await self.settle(lambda: self.count('library_items') == 1)
        await self.action('dismiss')
        gate.set()
        await self.tests.task
        self.assertEqual(self.count('briefing_test_start'), 0)
        self.assertFalse(self.manager.owners)

    async def test_dismiss_during_dispatch_waits_then_guardedly_stops_without_restarting(self):
        self.start_gate = asyncio.Event()
        await self.start()
        await self.settle(lambda: self.count('briefing_test_start') == 1)
        await self.action('dismiss')
        self.start_gate.set()
        await self.tests.task
        self.assertEqual(self.count('briefing_test_control', 'stop'), 1)
        self.assertEqual(self.count('briefing_test_control', 'restart'), 0)

    async def test_second_start_and_stale_control_are_rejected(self):
        await self.playing()
        with self.assertRaises(fixture.model.AlarmError):
            await self.start()
        with self.assertRaises(fixture.model.AlarmError):
            await self.tests.async_action('old-run', 'dismiss')
        self.assertEqual(self.count('briefing_test_start'), 1)

    async def test_existing_active_alarm_prevents_test(self):
        self.manager.runs[self.alarm['id']] = {'status': 'ringing'}
        with self.assertRaises(fixture.model.AlarmError):
            await self.start()
        self.assertFalse(self.calls)

    async def test_thirty_minute_watchdog_stops_not_restarts(self):
        await self.playing()
        self.clock = 1801
        self.tests.event.set()
        await self.tests.task
        self.assertEqual(self.tests.session['status'], 'finished')
        self.assertEqual(self.count('briefing_test_control', 'stop'), 1)

    async def test_shutdown_stops_owned_test(self):
        await self.playing()
        await self.tests.async_shutdown()
        self.assertFalse(self.tests.active)
        self.assertFalse(self.manager.owners)

    async def test_regular_alarm_delivery_stops_test_before_speaker_delivery(self):
        await self.playing()
        self.alarm.update(assistant_id='', briefing_enabled=False)
        self.hass.states.set(self.alarm['speaker'], volume_level=.2)
        async def tone(*args):
            self.assertFalse(self.tests.active)
        self.manager._play_tone = AsyncMock(side_effect=tone)
        await self.manager._deliver(self.alarm['id'], test=True)
        self.manager._play_tone.assert_awaited_once()
        self.assertEqual(self.count('briefing_test_control', 'stop'), 1)

    async def test_websocket_music_handlers_all_require_admin(self):
        tree = ast.parse((fixture.ROOT / 'websocket.py').read_text())
        handlers = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name.startswith('ws_music_')]
        self.assertEqual(len(handlers), 3)
        for handler in handlers:
            decorators = [ast.unparse(decorator) for decorator in handler.decorator_list]
            self.assertIn('websocket_api.require_admin', decorators)
            self.assertIn('websocket_api.async_response', decorators)

    async def test_resolution_uses_registry_id_and_existing_client(self):
        registered = types.SimpleNamespace(config_entry_id='ma-dev', unique_id='Kitchen Speaker')
        registry = types.SimpleNamespace(async_get=lambda entity: registered)
        self.hass.config_entries = types.SimpleNamespace(async_get_entry=lambda id:
                                                        types.SimpleNamespace(domain='music_assistant', entry_id=id))
        self.client.players = types.SimpleNamespace(get=lambda id: object() if id == 'Kitchen Speaker' else None)
        registry_module = types.ModuleType('homeassistant.helpers.entity_registry')
        registry_module.async_get = lambda hass: registry
        helpers_module = types.ModuleType('homeassistant.components.music_assistant.helpers')
        helpers_module.get_music_assistant_client = lambda hass, id: self.client
        with patch.dict('sys.modules', {'homeassistant.helpers.entity_registry': registry_module,
                'homeassistant.components.music_assistant.helpers': helpers_module}):
            client, player = ma_audio.resolve_client(self.hass, 'media_player.not_a_friendly_name')
        self.assertIs(client, self.client)
        self.assertEqual(player, 'Kitchen Speaker')


if __name__ == '__main__':
    unittest.main(verbosity=2)

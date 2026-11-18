"""Offline scheduled-music tests; no authenticated server or real speaker."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_alarms as fixture

music = fixture.load('music')


class MusicSettingsTests(unittest.TestCase):
    def test_ramp_is_opt_in_and_bounds_are_strict(self):
        legacy = fixture.config()
        for key in ('music_ramp_enabled', 'music_ramp_step', 'music_ramp_seconds'):
            legacy.pop(key)
        result = fixture.model.validate(legacy)
        self.assertFalse(result['music_ramp_enabled'])
        self.assertEqual(result['volume_step'], legacy['volume_step'])
        self.assertEqual(result['repeat_seconds'], legacy['repeat_seconds'])
        for fields in ({'music_ramp_enabled': 1}, {'music_ramp_step': True},
                {'music_ramp_step': 0}, {'music_ramp_step': 26},
                {'music_ramp_seconds': 29}, {'music_ramp_seconds': 301},
                {'music_ramp_seconds': 30.5}):
            with self.subTest(fields=fields), self.assertRaises(fixture.model.AlarmError):
                fixture.model.validate(fixture.config(**fields))

    def test_legacy_alarm_keeps_schedule_speaker_and_music_off(self):
        old = fixture.config()
        for key in ('music_enabled', 'music_track', 'music_track_name', 'music_server', 'music_gain', 'speech_delay'):
            old.pop(key)
        result = fixture.model.validate(old)
        self.assertFalse(result['music_enabled'])
        self.assertEqual(result['speaker'], old['speaker'])
        self.assertEqual(result['weekdays'], old['weekdays'])
        self.assertEqual(result['speech_delay'], 0)

    def test_settings_bounds_and_selected_song(self):
        for fields in ({'music_enabled': 'yes'}, {'music_enabled': True},
                {'music_track': 'https://example.invalid/song'}, {'music_track': 'library://track/١'},
                {'speech_delay': True}, {'speech_delay': 121}, {'speech_delay': -1},
                {'music_gain': 0}, {'music_gain': 31}, {'music_gain': float('nan')},
                {'music_track_name': 'x' * 301}):
            with self.subTest(fields=fields), self.assertRaises(fixture.model.AlarmError):
                fixture.model.validate(fixture.config(**fields))
        result = fixture.model.validate(fixture.config(music_enabled=True,
            music_track='library://track/42', music_server='ma-server', speech_delay=120))
        self.assertEqual(result['music_track'], 'library://track/42')


class VolumeRampTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.alarm = fixture.model.validate(fixture.config(music_ramp_enabled=True,
            music_ramp_step=5, music_ramp_seconds=30, start_volume=20, max_volume=32))
        self.now = 0
        self.level = 20
        self.calls = []
        self.state = 'playing'
        self.owned = True
        self.manual = False
        self.fail_write = False
        self.client = types.SimpleNamespace(send_command=self.command)
        self.ramp = music.MusicVolumeRamp(self.alarm, self.client, 'Kitchen', 'run', clock=lambda: self.now)

    async def command(self, name, **data):
        self.assertEqual(name, 'player_queues/alarm_volume')
        self.assertEqual(data['run_id'], 'run')
        self.calls.append(data)
        if 'volume_level' in data:
            if self.fail_write:
                raise TimeoutError('private audio URL')
            if self.owned and not self.manual:
                self.level = data['volume_level']
        return {'protocol': 2, 'owned': self.owned, 'state': self.state,
                'volume_level': self.level, 'suspended': self.manual}

    def writes(self):
        return [call['volume_level'] for call in self.calls if 'volume_level' in call]

    async def test_intervals_percentage_points_and_cap_without_media_calls(self):
        await self.ramp.tick()
        self.now = 29.99
        await self.ramp.tick()
        self.assertFalse(self.writes())
        for now, expected in ((30, [25]), (59, [25]), (60, [25, 30]),
                (90, [25, 30, 32]), (120, [25, 30, 32])):
            self.now = now
            self.assertIsNone(await self.ramp.tick())
            self.assertEqual(self.writes(), expected)

    async def test_delayed_tick_never_bursts_or_catches_up(self):
        self.now = 600
        await self.ramp.tick()
        await self.ramp.tick()
        self.assertEqual(self.writes(), [25])
        self.now = 629
        await self.ramp.tick()
        self.assertEqual(self.writes(), [25])
        self.now = 630
        await self.ramp.tick()
        self.assertEqual(self.writes(), [25, 30])

    async def test_reattach_starts_a_fresh_interval_at_current_volume(self):
        self.now, self.level = 600, 30
        self.ramp = music.MusicVolumeRamp(self.alarm, self.client, 'Kitchen', 'run', clock=lambda: self.now)
        await self.ramp.tick()
        self.assertFalse(self.writes())
        self.now = 630
        await self.ramp.tick()
        self.assertEqual(self.writes(), [32])

    async def test_manual_change_stops_increases_for_entire_ring(self):
        self.manual = True
        self.level = 12
        self.now = 30
        self.assertIn('paused', await self.ramp.tick())
        self.manual = False
        self.now = 120
        await self.ramp.tick()
        self.assertTrue(self.ramp.suspended)
        self.assertFalse(self.writes())

    async def test_unknown_or_foreign_playback_never_changes_volume(self):
        for level, owned in ((None, True), (True, True), (20, False)):
            self.ramp.suspended = False
            self.level, self.owned, self.now = level, owned, 30
            self.assertIsNotNone(await self.ramp.tick())
            self.assertFalse(self.writes())

    async def test_nonplaying_time_does_not_count_toward_next_increase(self):
        self.state, self.now = 'idle', 30
        await self.ramp.tick()
        self.state, self.now = 'playing', 31
        await self.ramp.tick()
        self.assertFalse(self.writes())
        self.now = 60
        await self.ramp.tick()
        self.assertEqual(self.writes(), [25])

    async def test_uncertain_write_suspends_without_retry_or_private_error(self):
        self.fail_write, self.now = True, 30
        warning = await self.ramp.tick()
        self.assertIn('not confirmed', warning)
        self.assertNotIn('private', warning)
        self.now = 60
        await self.ramp.tick()
        self.assertEqual(self.writes(), [25])

    async def test_persisted_suspension_does_not_resume_after_ha_restart(self):
        self.ramp = music.MusicVolumeRamp(self.alarm, self.client, 'Kitchen', 'run',
            clock=lambda: self.now, suspended=True)
        self.now = 90
        await self.ramp.tick()
        self.assertFalse(self.writes())

    async def test_disabled_ramp_never_calls_companion(self):
        self.alarm['music_ramp_enabled'] = False
        self.now = 60
        await self.ramp.tick()
        self.assertFalse(self.calls)

    async def test_cancellation_never_sends_later_increase(self):
        self.client.send_command = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await self.ramp.tick()
        self.assertEqual(self.client.send_command.await_count, 1)


class ScheduledMusicTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = fixture.FakeHass()
        self.manager = fixture.AlarmManager(self.hass)
        self.alarm = fixture.model.validate(fixture.config(music_enabled=True,
            music_track='library://track/42', music_server='ma-server', music_track_name='Selected song', speech_delay=7,
            assistant_id='assistant-test', briefing_enabled=True))
        self.manager.alarms[self.alarm['id']] = self.alarm
        self.run = fixture.run_at(datetime.now(timezone.utc))
        self.manager.runs[self.alarm['id']] = self.run
        self.calls = []
        self.ready = True
        self.owned = True
        self.state = 'playing'
        self.start_error = False
        self.stop_error = False
        self.features = list(music.FEATURES)
        self.volume_level = 20
        self.manual_volume = False
        self.client = types.SimpleNamespace(send_command=self.command)
        self.resolver = lambda *args: (self.client, 'Kitchen')
        self.server_id = 'ma-server'
        self.server_resolver = lambda *args: self.server_id
        self.delivery = music.AlarmMusic(self.manager, self.alarm, self.run, resolver=self.resolver, server_resolver=self.server_resolver)
        self.task = None

    async def asyncTearDown(self):
        self.stop_error = False
        if self.task and not self.task.done():
            self.task.cancel()
        if self.task:
            await asyncio.gather(self.task, return_exceptions=True)

    async def command(self, name, **kwargs):
        self.calls.append((name, deepcopy(kwargs)))
        if name.endswith('capabilities'):
            return {'protocol': 2, 'features': self.features, 'ready': self.ready,
                    'reasons': ['Queue is busy'] if not self.ready else [],
                    'engines': [{'entity_id': 'tts.piper', 'uid': 'ha/tts.piper'}]}
        if name.endswith('alarm_start'):
            self.assertEqual(self.manager.store.data['runs'][self.alarm['id']]['music_attempt'], kwargs['run_id'])
            self.assertTrue(self.manager.store.data['runs'][self.alarm['id']]['briefing_attempted'])
            if self.start_error:
                raise TimeoutError('private URL')
            self.volume_level = kwargs['volume_level']
            return {'protocol': 2, 'status': 'playing'}
        if name.endswith('alarm_volume'):
            self.volume_level = kwargs.get('volume_level', self.volume_level)
            return {'protocol': 2, 'owned': self.owned, 'state': self.state,
                    'suspended': self.manual_volume, 'volume_level': self.volume_level}
        if name.endswith('alarm_control'):
            if kwargs['action'] == 'stop' and self.stop_error:
                raise TimeoutError('private URL')
            if kwargs['action'] == 'restart':
                self.state = 'playing'
                self.volume_level = kwargs.get('volume_level', self.volume_level)
            return {'protocol': 2, 'owned': self.owned, 'state': self.state}
        if name == 'music/tracks/library_items':
            return [{'uri': 'library://track/42', 'name': '<Song>', 'artists': [{'name': 'Artist'}], 'private': 'do not return'},
                    {'uri': 'https://example.invalid/song', 'name': 'Wrong'}]
        raise AssertionError(name)

    async def settle(self, condition):
        for _ in range(200):
            await asyncio.sleep(0)
            if condition():
                return
        self.fail('Worker did not settle')

    def count(self, suffix, action=None):
        return sum(name.endswith(suffix) and (action is None or args.get('action') == action)
                   for name, args in self.calls)

    async def start(self):
        self.task = asyncio.create_task(self.delivery.play())
        await self.settle(lambda: self.count('alarm_control', 'status') or self.task.done())

    async def test_selected_track_exact_voice_delay_and_persist_before_dispatch(self):
        await self.start()
        args = next(args for name, args in self.calls if name.endswith('alarm_start'))
        self.assertEqual(args['track_uri'], 'library://track/42')
        self.assertEqual(args['speech_delay'], 7)
        self.assertEqual(args['tts_engine'], 'ha/tts.piper')
        self.assertEqual(args['voice'], 'en_GB-alan-medium')
        self.assertEqual(args['music_gain'], .25)
        self.assertEqual(self.count('alarm_volume'), 0)

    async def test_ramp_requires_feature_before_message_or_playback(self):
        self.alarm['music_ramp_enabled'] = True
        self.manager.async_briefing = AsyncMock()
        with self.assertRaisesRegex(fixture.model.AlarmError, 'updated MA companion'):
            await self.delivery.play()
        self.manager.async_briefing.assert_not_awaited()
        self.assertEqual(self.count('alarm_start'), 0)

    async def test_ramp_snooze_resume_uses_starting_volume_not_cycle_increment(self):
        self.alarm['music_ramp_enabled'] = True
        self.features.append('volume_ramp')
        self.run.update(cycles=3, briefing_attempted=True)
        await self.start()
        args = next(args for name, args in self.calls if name.endswith('alarm_start'))
        self.assertEqual(args['volume_level'], self.alarm['start_volume'])
        self.assertEqual(args['message'], '')

    async def test_ramp_deadline_still_starts_at_maximum(self):
        self.alarm['music_ramp_enabled'] = True
        self.features.append('volume_ramp')
        self.run['escalated'] = True
        await self.start()
        args = next(args for name, args in self.calls if name.endswith('alarm_start'))
        self.assertEqual(args['volume_level'], self.alarm['max_volume'])

    async def test_manual_ramp_suspension_is_persisted_without_stopping_song(self):
        self.alarm['music_ramp_enabled'] = True
        self.features.append('volume_ramp')
        self.manual_volume = True
        await self.start()
        await self.settle(lambda: self.run.get('music_ramp_suspended'))
        self.assertTrue(self.manager.store.data['runs'][self.alarm['id']]['music_ramp_suspended'])
        self.assertEqual(self.count('alarm_start'), 1)
        self.assertEqual(self.count('alarm_control', 'stop'), 0)
        self.assertIn('volume:' + self.alarm['id'], self.manager.warnings)

    async def test_saved_test_ramp_snooze_resets_start_and_timer_without_speech(self):
        tester = self.manager.music_tests
        tester.resolver = self.resolver
        self.alarm['music_ramp_enabled'] = True
        self.features.append('volume_ramp')
        self.manager.runs = {}
        now = [0]
        tester.clock = lambda: now[0]
        original_command = self.command
        async def test_command(name, **kwargs):
            if name.endswith('alarm_start'):
                self.calls.append((name, deepcopy(kwargs)))
                return {'protocol': 2, 'status': 'playing'}
            return await original_command(name, **kwargs)
        self.client.send_command = test_command
        try:
            with patch.object(fixture.load('ma_audio'), 'resolve_server_id', self.server_resolver):
                await self.manager.async_test(self.alarm['id'], 'PLAY')
                await self.settle(lambda: tester.session['status'] == 'playing')
                now[0] = 30
                tester.event.set()
                await self.settle(lambda: any(name.endswith('alarm_volume') and 'volume_level' in args
                    for name, args in self.calls))
                self.assertEqual(self.volume_level, 25)
                await tester.async_action(tester.session['id'], 'snooze')
                await self.settle(lambda: tester.session['status'] == 'snoozed')
                before = len(self.calls)
                now[0] += tester.session['snooze_seconds']
                tester.event.set()
                await self.settle(lambda: tester.session['status'] == 'playing')
                restarted = next(args for name, args in self.calls[before:]
                    if name.endswith('alarm_control') and args['action'] == 'restart')
                self.assertEqual(restarted['volume_level'], self.alarm['start_volume'])
                self.assertEqual(self.count('alarm_start'), 1)
                self.assertEqual(self.volume_level, 20)
        finally:
            if tester.active:
                await tester.async_action(tester.session['id'], 'dismiss')
                await tester.task
        self.assertIsNone(self.manager.store.data)

    async def test_busy_queue_never_generates_or_dispatches(self):
        self.ready = False
        self.manager.async_briefing = AsyncMock()
        with self.assertRaises(fixture.model.AlarmError):
            await self.delivery.play()
        self.manager.async_briefing.assert_not_awaited()
        self.assertFalse(self.run.get('music_attempt'))
        self.assertEqual(self.count('alarm_start'), 0)

    async def test_cancel_stops_then_next_ring_starts_same_song_without_speech(self):
        await self.start()
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self.assertEqual(self.count('alarm_control', 'stop'), 1)
        self.assertIsNone(self.run['music_attempt'])
        self.delivery = music.AlarmMusic(self.manager, self.alarm, self.run, resolver=self.resolver, server_resolver=self.server_resolver)
        await self.start()
        args = [args for name, args in self.calls if name.endswith('alarm_start')]
        self.assertEqual(args[0]['track_uri'], args[1]['track_uri'])
        self.assertEqual(args[1]['message'], '')
        self.assertNotEqual(args[0]['run_id'], args[1]['run_id'])

    async def test_persisted_attempt_only_reattaches_without_regeneration(self):
        self.run.update(music_attempt='previous-start', briefing_attempted=True)
        self.delivery = music.AlarmMusic(self.manager, self.alarm, self.run, resolver=self.resolver, server_resolver=self.server_resolver)
        await self.start()
        self.assertEqual(self.count('alarm_start'), 0)
        self.assertFalse(any(domain == 'conversation' for domain, *_ in self.hass.services.calls))

    async def test_persisted_unowned_attempt_blocks_without_replacing_audio(self):
        self.run.update(music_attempt='previous-start', briefing_attempted=True)
        self.owned = False
        self.delivery = music.AlarmMusic(self.manager, self.alarm, self.run, resolver=self.resolver, server_resolver=self.server_resolver)
        await self.delivery.play()
        self.assertTrue(self.run['music_blocked'])
        self.assertEqual(self.count('alarm_start'), 0)
        self.assertEqual(self.count('alarm_control', 'stop'), 0)

    async def test_uncertain_start_never_retries_and_uses_guarded_stop(self):
        self.start_error = True
        with self.assertRaises(fixture.model.AlarmError):
            await self.delivery.play()
        self.assertEqual(self.count('alarm_start'), 1)
        self.assertEqual(self.count('alarm_control', 'stop'), 1)
        self.assertTrue(self.run['music_blocked'])

    async def test_uncertain_stop_keeps_persisted_identity_and_blocks_restart(self):
        await self.start()
        self.stop_error = True
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self.assertTrue(self.run['music_attempt'])
        self.assertTrue(self.run['music_blocked'])
        self.assertNotIn('private', self.run['error'])

    async def test_failed_persistence_prevents_dispatch(self):
        self.manager.store.fail = True
        with self.assertRaises(OSError):
            await self.delivery.play()
        self.assertEqual(self.count('alarm_start'), 0)
        self.assertNotIn('briefing_attempted', self.run)

    async def test_search_uses_speaker_library_and_returns_only_public_metadata(self):
        result = await music.search_tracks(self.hass, self.alarm['speaker'], 'Song', resolver=self.resolver, server_resolver=self.server_resolver)
        self.assertEqual(result, {'server_id': 'ma-server', 'tracks': [{'uri': 'library://track/42', 'name': '<Song> — Artist'}]})
        args = self.calls[-1][1]
        self.assertEqual(args['limit'], 20)
        self.assertEqual(args['search'], 'Song')
        self.assertEqual(self.count('alarm_start'), 0)

    async def test_old_test_protocol_rejected(self):
        self.client.send_command = AsyncMock(return_value={'protocol': 1, 'ready': True})
        with self.assertRaises(fixture.model.AlarmError):
            await self.delivery.play()
        self.assertFalse(self.run.get('music_attempt'))

    async def test_connection_replaced_under_same_entity_id_never_plays_wrong_song(self):
        self.server_id = 'another-server'
        with self.assertRaises(fixture.model.AlarmError):
            await self.delivery.play()
        self.assertTrue(self.run['music_blocked'])
        self.assertFalse(self.calls)

    async def test_connection_change_during_generation_cannot_dispatch_to_old_client(self):
        async def briefing(*args):
            self.server_id = 'another-server'
            return 'Good morning'
        self.manager.async_briefing = briefing
        with self.assertRaises(fixture.model.AlarmError):
            await self.delivery.play()
        self.assertEqual(self.count('alarm_start'), 0)

    async def test_natural_song_end_restarts_without_another_start_or_speech(self):
        self.state = 'idle'
        await self.start()
        self.assertEqual(self.count('alarm_control', 'restart'), 1)
        self.assertEqual(self.count('alarm_start'), 1)

    async def test_explicit_dismiss_and_sleep_in_cancel_and_stop_scheduled_playback(self):
        for action, status in (('dismiss', 'dismissed'), ('sleep_in', 'sleeping_in')):
            self.alarm['allow_sleep_in'] = True
            self.run.update(status='ringing', music_attempt=None)
            self.run.pop('music_blocked', None)
            self.delivery = music.AlarmMusic(self.manager, self.alarm, self.run,
                resolver=self.resolver, server_resolver=self.server_resolver)
            with patch.object(fixture.manager_module, 'AlarmMusic', return_value=self.delivery):
                self.hass.states.set(self.alarm['speaker'], volume_level=.2)
                self.manager._spawn(self.manager.tasks, self.alarm['id'], self.manager._deliver(self.alarm['id']))
                self.task = self.manager.tasks[self.alarm['id']]
                before = self.count('alarm_control', 'status')
                await self.settle(lambda: self.count('alarm_control', 'status') > before)
                await self.manager.async_action(self.alarm['id'], action)
            self.assertEqual(self.run['status'], status)
            self.assertIsNone(self.run['music_attempt'])
            self.assertFalse(self.manager.owners)

    async def test_saved_test_uses_selected_song_delay_and_normal_snooze_without_saving(self):
        tester = self.manager.music_tests
        tester.resolver = self.resolver
        before = deepcopy(self.manager.alarms)
        self.manager.runs = {}
        # Selected tests are runtime-only, so command assertions for saved runs do
        # not apply to their start. Keep the protocol response realistic instead.
        original_command = self.command
        async def test_command(name, **kwargs):
            if name.endswith('alarm_start'):
                self.calls.append((name, deepcopy(kwargs)))
                return {'protocol': 2, 'status': 'playing'}
            return await original_command(name, **kwargs)
        self.client.send_command = test_command
        with patch.object(fixture.load('ma_audio'), 'resolve_server_id', self.server_resolver):
            await self.manager.async_test(self.alarm['id'], 'PLAY')
            await self.settle(lambda: tester.session['status'] == 'playing' or tester.task.done())
            self.assertEqual(tester.session['status'], 'playing')
            args = next(args for name, args in self.calls if name.endswith('alarm_start'))
            self.assertEqual(args['track_uri'], 'library://track/42')
            self.assertEqual(args['speech_delay'], 7)
            self.assertEqual(tester.session['snooze_seconds'], self.alarm['snooze_minutes'] * 60)
            await tester.async_action(tester.session['id'], 'dismiss')
            await tester.task
        self.assertEqual(self.manager.alarms, before)
        self.assertIsNone(self.manager.store.data)

    async def test_scheduler_delivery_selects_music_without_tone_or_direct_tts(self):
        with patch.object(fixture.manager_module, 'AlarmMusic') as cls:
            cls.return_value.play = AsyncMock()
            self.manager._play_tone = AsyncMock()
            self.manager._speak = AsyncMock()
            self.hass.states.set(self.alarm['speaker'], volume_level=.2)
            await self.manager._deliver(self.alarm['id'])
            cls.return_value.play.assert_awaited_once()
            self.manager._play_tone.assert_not_awaited()
            self.manager._speak.assert_not_awaited()
            self.assertFalse(self.manager.owners)


if __name__ == '__main__':
    unittest.main()

"""Offline lock-screen control tests; no real phone, push or screen commands."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_alarms as fixture

notifications = fixture.load('notifications')


class PhoneSettingsTests(unittest.TestCase):
    def test_defaults_off_independent_from_help_alerts(self):
        alarm = fixture.model.validate(fixture.config(notify_enabled=True))
        self.assertFalse(alarm['phone_enabled'])
        self.assertEqual(alarm['phone_service'], '')
        for fields in ({'phone_enabled': 'yes'}, {'phone_wake_screen': 1},
                       {'phone_enabled': True}, {'phone_service': 'notify.adults'},
                       {'phone_service': 'script.anything'}):
            with self.subTest(fields=fields), self.assertRaises(fixture.model.AlarmError):
                fixture.model.validate(fixture.config(**fields))

    def test_discovery_only_returns_services_and_android_capability(self):
        hass = fixture.FakeHass()
        hass.services.async_services = lambda: {'notify': {'adults': {}, 'mobile_app_android_phone': {}, 'mobile_app_iphone': {}}}
        hass.config_entries = types.SimpleNamespace(async_entries=lambda domain: [types.SimpleNamespace(
            data={'device_name': 'Android Phone', 'os_name': 'Android', 'webhook_id': 'private-not-returned'})])
        self.assertEqual(notifications.phone_targets(hass), [
            {'service': 'notify.mobile_app_android_phone', 'android': True},
            {'service': 'notify.mobile_app_iphone', 'android': False}])


    def test_ambiguous_registration_never_authorizes_android_screen_command(self):
        hass = fixture.FakeHass()
        hass.services.async_services = lambda: {'notify': {'mobile_app_shared_name': {}}}
        hass.config_entries = types.SimpleNamespace(async_entries=lambda domain: [
            types.SimpleNamespace(data={'device_name': 'Shared Name', 'os_name': platform})
            for platform in ('Android', 'iOS')])
        self.assertEqual(notifications.phone_targets(hass), [{'service': 'notify.mobile_app_shared_name', 'android': False}])


class PhoneControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = fixture.FakeHass()
        self.manager = fixture.AlarmManager(self.hass)
        self.alarm = fixture.model.validate(fixture.config(phone_enabled=True,
            phone_service='notify.mobile_app_phone', notify_enabled=False, allow_sleep_in=True))
        self.manager.alarms[self.alarm['id']] = self.alarm
        self.run = fixture.run_at(datetime.now(timezone.utc))
        self.manager.runs[self.alarm['id']] = self.run
        self.phone = self.manager.phone_notifications
        self.android = True
        self.phone.targets = lambda hass: [{'service': self.alarm['phone_service'], 'android': self.android}]
        self.phone.schedule = lambda: None  # Drive updates deterministically except worker tests.

    async def asyncTearDown(self):
        self.manager.closed = True
        await self.phone.async_shutdown()
        for task in self.manager.tasks.values():
            task.cancel()
        await asyncio.gather(*self.manager.tasks.values(), return_exceptions=True)

    async def sync(self):
        await self.phone._sync(self.alarm['id'])

    def messages(self):
        return [data for domain, service, data, kwargs in self.hass.services.calls if domain == 'notify']

    def controls(self):
        return [data for data in self.messages() if isinstance(data.get('data', {}).get('actions'), list)]

    def action(self, kind):
        return next(row['action'] for row in self.controls()[-1]['data']['actions'] if row['action'].endswith(':' + kind))

    async def press(self, action):
        await self.phone.async_event(types.SimpleNamespace(data={'action': action}))

    async def test_first_ring_persists_nonce_before_pushing_and_requests_screen_on(self):
        async def handler(domain, service, data):
            self.assertTrue(self.manager.store.data['runs'][self.alarm['id']]['phone_token'])
        self.hass.services.handler = handler
        await self.sync()
        data = self.controls()[0]['data']
        self.assertEqual([row['title'] for row in data['actions']], ['Dismiss', 'Snooze 5 min'])
        self.assertTrue(all(not row['authenticationRequired'] for row in data['actions']))
        self.assertEqual(data['visibility'], 'public')
        self.assertEqual(data['priority'], 'high')
        self.assertEqual(data['ttl'], 0)
        self.assertTrue(data['persistent'])
        self.assertEqual(self.messages()[-1]['message'], 'command_screen_on')

    async def test_repeats_do_not_spam_push_or_screen_wake(self):
        await self.sync()
        before = len(self.messages())
        self.run['cycles'] += 3
        await self.sync()
        self.assertEqual(len(self.messages()), before)

    async def test_disabled_option_sends_nothing_even_with_help_alerts_enabled(self):
        self.alarm.update(phone_enabled=False, notify_enabled=True)
        await self.sync()
        self.assertFalse(self.messages())
        self.assertIsNone(self.manager.store.data)

    async def test_no_notification_for_saved_alarm_without_active_run(self):
        self.manager.runs.clear()
        await self.sync()
        self.assertFalse(self.messages())

    async def test_snooze_consumes_old_actions_updates_tag_and_does_not_wake_again(self):
        await self.sync()
        old_action = self.action('snooze')
        original_token = self.run['phone_token']
        old_tag = self.controls()[-1]['data']['tag']
        await self.press(old_action)
        self.assertEqual(self.run['status'], 'snoozed')
        self.assertNotEqual(self.run['phone_token'], original_token)
        await self.press(old_action)
        self.assertEqual(self.run['snoozes'], 1)
        await self.sync()
        self.assertEqual(len(self.controls()[-1]['data']['actions']), 1)
        self.assertEqual(self.controls()[-1]['data']['tag'], old_tag)
        self.assertIn('Snoozed', self.controls()[-1]['message'])
        self.assertEqual(sum(row['message'] == 'command_screen_on' for row in self.messages()), 1)

    async def test_dismiss_from_lock_screen_clears_notification_and_run(self):
        await self.sync()
        dismiss = self.action('dismiss')
        await self.press(dismiss)
        await self.sync()
        self.assertEqual(self.run['status'], 'dismissed')
        self.assertEqual(self.messages()[-1]['message'], 'clear_notification')
        self.assertEqual(sum(row['message'] == 'clear_notification' for row in self.messages()), 1)
        self.assertFalse(self.run['phone_token'])
        await self.press(dismiss)
        self.assertEqual(self.run['status'], 'dismissed')

    async def test_sleep_in_and_sleep_switch_dismissal_also_clear(self):
        for status in ('sleeping_in', 'dismissed', 'missed'):
            self.run.update(status='ringing', phone_token='', phone_target='')
            self.phone.last.clear()
            await self.sync()
            self.run['status'] = status
            await self.sync()
            self.assertEqual(self.messages()[-1]['message'], 'clear_notification')

    async def test_snooze_limit_disabled_and_deadline_hide_button_and_reject_forgery(self):
        for fields in ({'snooze_enabled': False}, {'max_snoozes': 0}):
            self.alarm.update(fields)
            self.phone.last.clear()
            await self.sync()
            self.assertEqual(len(self.controls()[-1]['data']['actions']), 1)
            await self.press(self.action('dismiss').replace(':dismiss', ':snooze'))
            self.assertEqual(self.run['snoozes'], 0)
        self.alarm.update(snooze_enabled=True, max_snoozes=3, time='07:00', deadline='07:30')
        now = datetime.now(timezone.utc).replace(hour=7, minute=31)
        self.run.update(started=now.replace(hour=7, minute=0).isoformat())
        with patch.object(notifications.dt_util, 'now', return_value=now):
            self.phone.last.clear()
            await self.sync()
            self.assertEqual(len(self.controls()[-1]['data']['actions']), 1)

    async def test_old_occurrence_and_wrong_alarm_tokens_are_rejected(self):
        await self.sync()
        old = self.action('dismiss')
        replacement = fixture.run_at(datetime.now(timezone.utc) + timedelta(days=1))
        self.manager.runs[self.alarm['id']] = replacement
        await self.press(old)
        self.assertEqual(replacement['status'], 'ringing')
        await self.press(old.replace(self.alarm['id'], 'different-alarm'))
        self.assertEqual(replacement['status'], 'ringing')

    async def test_restart_republishes_snooze_nonce_but_keeps_occurrence_dismiss(self):
        await self.sync()
        old = self.action('dismiss')
        old_snooze = self.action('snooze')
        previous = self.run['phone_token']
        restarted = notifications.AlarmNotifications(self.manager, targets=self.phone.targets)
        await restarted._sync(self.alarm['id'])
        self.assertNotEqual(self.run['phone_token'], previous)
        await self.press(old_snooze)
        self.assertEqual(self.run['status'], 'ringing')
        await self.press(old)
        self.assertEqual(self.run['status'], 'dismissed')
        self.assertFalse(any(domain == 'media_player' for domain, *_ in self.hass.services.calls))

    async def test_unknown_or_ios_target_gets_controls_but_never_android_command(self):
        self.android = False
        await self.sync()
        self.assertEqual(len(self.controls()), 1)
        self.assertFalse(any(row['message'] == 'command_screen_on' for row in self.messages()))
        self.assertIn('Android', self.manager.warnings['phone:' + self.alarm['id']])

    async def test_wake_option_can_be_disabled(self):
        self.alarm['phone_wake_screen'] = False
        await self.sync()
        self.assertEqual(len(self.messages()), 1)

    async def test_persistence_failure_prevents_any_push(self):
        self.manager.store.fail = True
        with self.assertRaises(OSError):
            await self.sync()
        self.assertFalse(self.messages())
        self.assertNotIn('phone_token', self.run)

    async def test_push_failure_is_bounded_and_never_blocks_alarm_task(self):
        async def fail(*args):
            raise OSError('private endpoint and token')
        self.hass.services.handler = fail
        self.phone.dirty = True
        await self.phone._work()
        self.assertIn('phone:' + self.alarm['id'], self.manager.warnings)
        self.assertNotIn('private', self.manager.warnings['phone:' + self.alarm['id']])
        self.assertEqual(self.run['status'], 'ringing')
        before = len(self.messages())
        self.phone.dirty = True
        await self.phone._work()
        self.assertEqual(len(self.messages()), before)

    async def test_tokens_not_exposed_in_card_snapshot(self):
        await self.sync()
        snapshot = self.manager.snapshot()
        self.assertNotIn('phone_token', snapshot['alarms'][0]['run'])
        self.assertNotIn('phone_dismiss_token', snapshot['alarms'][0]['run'])
        self.assertNotIn(self.run['phone_token'], str(snapshot))
        self.assertNotIn(self.run['phone_dismiss_token'], str(snapshot))

    async def test_malformed_foreign_and_missing_actions_are_ignored(self):
        await self.sync()
        for action in (None, {}, 'SNOOZE', 'HOUSEHOLD_ALARM:bad:x:dismiss', 'x' * 1000):
            await self.press(action)
        self.assertEqual(self.run['status'], 'ringing')

    async def test_deleted_alarm_clears_only_its_own_tag(self):
        await self.sync()
        tag = self.controls()[0]['data']['tag']
        self.manager.alarms.clear()
        self.manager.runs.clear()
        await self.sync()
        self.assertEqual(self.messages()[-1], {'message': 'clear_notification', 'data': {'tag': tag}})

    async def test_simultaneous_duplicate_snooze_actions_only_apply_once(self):
        await self.sync()
        action = self.action('snooze')
        await asyncio.gather(self.press(action), self.press(action))
        self.assertEqual(self.run['snoozes'], 1)
        self.assertEqual(self.run['status'], 'snoozed')

    async def test_phone_action_storage_failure_keeps_alarm_active_and_surfaces_warning(self):
        await self.sync()
        self.manager.store.fail = True
        await self.press(self.action('dismiss'))
        self.assertEqual(self.manager.runs[self.alarm['id']]['status'], 'ringing')
        self.assertIn('not confirmed', self.manager.warnings['phone:' + self.alarm['id']])

    async def test_screen_wake_failure_does_not_remove_submitted_controls_or_retry_audio(self):
        async def handler(domain, service, data):
            if data['message'] == 'command_screen_on':
                raise OSError('private screen transport')
        self.hass.services.handler = handler
        await self.sync()
        self.assertEqual(len(self.controls()), 1)
        self.assertIn('screen wake', self.manager.warnings['phone:' + self.alarm['id']])
        self.assertNotIn('private', str(self.manager.warnings))
        before = len(self.messages())
        await self.sync()
        self.assertEqual(len(self.messages()), before)

    async def test_scheduler_resume_rotates_snooze_token_but_old_dismiss_still_works(self):
        self.run['status'] = 'snoozed'
        await self.sync()
        previous = self.run['phone_token']
        old = self.action('dismiss')
        now = datetime.now(timezone.utc)
        self.run['next_ring'] = (now - timedelta(seconds=1)).isoformat()
        self.alarm['enabled'] = True
        self.manager._deliver = AsyncMock()
        await self.manager._tick(now)
        self.assertEqual(self.run['status'], 'ringing')
        self.assertNotEqual(self.run['phone_token'], previous)
        await self.press(old)
        self.assertEqual(self.run['status'], 'dismissed')

    async def test_initial_dismiss_survives_snooze_and_resume_even_if_push_update_is_lost(self):
        await self.sync()
        original_dismiss = self.action('dismiss')
        original_snooze = self.action('snooze')
        await self.press(original_snooze)
        await self.sync()
        self.assertEqual(self.action('dismiss'), original_dismiss)
        now = datetime.now(timezone.utc)
        self.run['next_ring'] = (now - timedelta(seconds=1)).isoformat()
        self.alarm['enabled'] = True
        self.manager._deliver = AsyncMock()
        await self.manager._tick(now)
        # The phone still displays the first notification, not the new phase.
        await self.press(original_dismiss)
        self.assertEqual(self.run['status'], 'dismissed')
        await self.press(original_snooze)
        self.assertEqual(self.run['snoozes'], 1)

    async def test_old_dismiss_also_works_while_snoozed_and_duplicate_is_harmless(self):
        await self.sync()
        dismiss = self.action('dismiss')
        await self.press(self.action('snooze'))
        await asyncio.gather(self.press(dismiss), self.press(dismiss))
        self.assertEqual(self.run['status'], 'dismissed')
        self.assertEqual(self.run['snoozes'], 1)

    async def test_dismiss_token_cannot_be_reused_to_snooze_or_snooze_token_to_dismiss(self):
        await self.sync()
        await self.press(self.action('dismiss').replace(':dismiss', ':snooze'))
        await self.press(self.action('snooze').replace(':snooze', ':dismiss'))
        self.assertEqual(self.run['status'], 'ringing')
        self.assertEqual(self.run['snoozes'], 0)

    async def test_phone_target_change_invalidates_old_dismiss(self):
        await self.sync()
        old = self.action('dismiss')
        self.alarm['phone_service'] = 'notify.mobile_app_other_phone'
        await self.sync()
        new = self.action('dismiss')
        self.assertNotEqual(old, new)
        await self.press(old)
        self.assertEqual(self.run['status'], 'ringing')
        await self.press(new)
        self.assertEqual(self.run['status'], 'dismissed')

    async def test_failed_phase_notification_update_does_not_revoke_occurrence_dismiss(self):
        await self.sync()
        old = self.action('dismiss')
        await self.press(self.action('snooze'))
        self.hass.services.handler = AsyncMock(side_effect=OSError('push unavailable'))
        with self.assertRaises(OSError):
            await self.sync()
        self.hass.services.handler = None
        await self.press(old)
        self.assertEqual(self.run['status'], 'dismissed')

    async def test_worker_is_background_and_shutdown_cancels_pending_push(self):
        gate = asyncio.Event()
        async def handler(*args):
            await gate.wait()
        self.hass.services.handler = handler
        self.phone.schedule = types.MethodType(notifications.AlarmNotifications.schedule, self.phone)
        self.phone.schedule()
        for _ in range(50):
            await asyncio.sleep(0)
            if self.messages():
                break
        self.assertTrue(self.messages())
        self.assertFalse(self.phone.task.done())
        self.manager.closed = True
        await self.phone.async_shutdown()
        self.assertTrue(self.phone.task.cancelled())


if __name__ == '__main__':
    unittest.main()

import json
from datetime import datetime
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo
from check_review_sites import required_session, validate_snapshot, read_calendar
from notify_health import alert_action, MARKER
from retry_check import retry


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.bars = [{'day': d} for d in ['2026-09-30', '2026-10-08', '2026-10-09', '2026-10-12', '2026-10-13']]

    def now(self, value):
        return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('Asia/Shanghai'))

    def test_morning_grace_does_not_alert_before_deadline(self):
        self.assertEqual(required_session(self.bars, self.now('2026-10-13T09:00')), '2026-10-09')
        self.assertEqual(required_session(self.bars, self.now('2026-10-13T10:00')), '2026-10-12')

    def test_weekends_and_holidays_use_completed_trading_observations(self):
        self.assertEqual(required_session(self.bars, self.now('2026-10-12T10:00')), '2026-10-09')
        self.assertEqual(required_session(self.bars, self.now('2026-10-11T12:00')), '2026-10-08')
        self.assertEqual(required_session(self.bars, self.now('2026-10-06T12:00')), '2026-09-30')

    def test_calendar_failover_and_total_failure(self):
        rows = [dict(day='2026-10-%02d' % i, open='1', high='2', low='1', close='2') for i in range(1, 14)]
        calls = []
        def download(url):
            calls.append(url)
            if len(calls) == 1:
                raise OSError('Primary unavailable')
            return json.dumps(rows)
        self.assertEqual(read_calendar(self.now('2026-10-13T10:00'), download), '2026-10-12')
        self.assertEqual(len(calls), 2)
        with self.assertRaises(RuntimeError):
            read_calendar(self.now('2026-10-13T10:00'), lambda _: 'bad schema')

    def test_missing_or_duplicate_report_is_a_failure(self):
        snapshot = {'id': 'dashboard:d8650926-9515-42c6-a507-4c9979168165', 'buildStatus': 'complete',
            'queries': {'reports': {'rows': [{'review_date': '2026-10-09', 'visuals': {'conclusions': [{}] * 12}}]},
                        'indicator_table': {'rows': [{'review_date': '2026-10-09'}] * 14}}}
        with self.assertRaises(ValueError): validate_snapshot(snapshot, '2026-10-12')
        self.assertEqual(validate_snapshot(snapshot, '2026-10-09'), ['2026-10-09'])
        snapshot['queries']['reports']['rows'] *= 2
        with self.assertRaises(ValueError): validate_snapshot(snapshot, '2026-10-09')

    def test_retry_recovers_and_permanent_failure_stays_failed(self):
        codes = iter([1, 124, 0]); waits = []
        result = retry(['test'], 'source-render', runner=lambda *a, **k: SimpleNamespace(returncode=next(codes)), sleep=waits.append)
        self.assertTrue(result['success']); self.assertEqual(waits, [10, 20]); self.assertEqual(len(result['attempts']), 3)
        result = retry(['test'], 'source-render', runner=lambda *a, **k: SimpleNamespace(returncode=1), sleep=lambda _: None)
        self.assertFalse(result['success']); self.assertEqual(len(result['attempts']), 3)

    def test_notifications_deduplicate_ignore_ordinary_issues_and_recover(self):
        ordinary = {'number': 1, 'body': 'normal issue'}
        alert = {'number': 2, 'body': MARKER, 'user': {'login': 'github-actions[bot]'}, 'assignees': [{'login': 'chenchen1228'}]}
        self.assertEqual(alert_action([ordinary], True), ('create', None))
        self.assertEqual(alert_action([ordinary, alert], True), ('update', alert))
        self.assertEqual(alert_action([alert], False), ('recover', [alert]))
        self.assertEqual(alert_action([ordinary], False), ('quiet', []))
        self.assertEqual(alert_action([{'number': 3, 'body': MARKER}], False), ('quiet', []))


if __name__ == '__main__': unittest.main()

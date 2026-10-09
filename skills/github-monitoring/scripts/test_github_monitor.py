"""Offline behavior tests: no GitHub login, network, or AI invocation."""

from contextlib import redirect_stdout, redirect_stderr
from datetime import timedelta
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import github_monitor as monitor


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name) / 'private' / 'state.json'
        self.rows = {'issues': [], 'issues/comments': [], 'pulls/comments': []}
        self.calls = []
        self.argv = ['--repo', 'example/project', '--recipient', 'reviewer',
                     '--allow-author', 'trusted', '--ignore-author', 'self',
                     '--state', str(self.state)]
        self.output = io.StringIO()
        self.errors = io.StringIO()

    def row(self, kind='issues/comments', author='trusted', body='agent:reviewer\n2 + 3', ident=10):
        row = {'id': ident, 'body': body, 'user': {'login': author},
               'updated_at': monitor.stamp(monitor.utc_now()), 'number': 1}
        if kind == 'issues/comments':
            row['issue_url'] = 'https://api.github.com/repos/example/project/issues/1'
        elif kind == 'pulls/comments':
            row['pull_request_url'] = 'https://api.github.com/repos/example/project/pulls/1'
        self.rows[kind].append(row)
        return row

    def command(self, argv, **kwargs):
        self.calls.append(argv)
        self.assertFalse(kwargs['shell'])
        self.assertEqual(argv[0], 'gh')
        self.assertEqual(argv[1], 'api')
        self.assertEqual(argv[argv.index('--method') + 1], 'GET')
        self.assertIn('--paginate', argv)
        suffix = argv[-1].split('?', 1)[0].split('example/project/', 1)[1]
        rows = self.rows[suffix]
        # Two pages exercise slurp flattening.
        return subprocess.CompletedProcess(argv, 0, json.dumps([rows[:1], rows[1:]]), '')

    def run_mode(self, mode='once', extra=()):
        with patch.object(monitor.subprocess, 'run', side_effect=self.command), \
                redirect_stdout(self.output), redirect_stderr(self.errors):
            return monitor.main([mode, *self.argv, *extra])

    def initialize(self, extra=()):
        self.assertEqual(self.run_mode(extra=extra), 0)
        self.calls.clear()
        self.output.seek(0)
        self.output.truncate()

    def test_baseline_does_not_replay_requests(self):
        self.row()
        self.initialize()
        self.assertEqual(self.run_mode(), 0)
        self.assertNotIn('"status": "request"', self.output.getvalue())
        self.assertIn('baseline', set(monitor.load_state(self.state)['seen'].values()))

    def test_preview_keeps_state_and_never_delivers(self):
        self.initialize()
        self.row()
        before = self.state.read_bytes()
        self.assertEqual(self.run_mode('check'), 0)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertIn('preview', self.output.getvalue())

    def test_deduplicates_across_restarts(self):
        self.initialize()
        self.row()
        self.assertEqual(self.run_mode(), 0)
        self.output.seek(0)
        self.output.truncate()
        self.assertEqual(self.run_mode(), 0)
        self.assertIn('"count": 0', self.output.getvalue())

    def test_author_recipient_and_self_filter(self):
        self.initialize()
        self.row(author='outsider', ident=1)
        self.row(author='self', ident=2)
        self.row(body='agent:builder\n2 + 3', ident=3)
        self.row(body='quoted\nagent:reviewer', ident=4)
        self.row(author='TRUSTED', ident=5)
        self.assertEqual(self.run_mode(), 0)
        self.assertIn('"count": 1', self.output.getvalue())

    def test_self_exclusion_wins_over_allowlist(self):
        self.argv += ['--allow-author', 'self']
        self.initialize()
        self.row(author='self')
        self.assertEqual(self.run_mode(), 0)
        self.assertIn('"count": 0', self.output.getvalue())

    def test_issue_pr_body_and_line_comment(self):
        self.initialize()
        self.row(kind='issues', ident=1)
        self.row(kind='issues', ident=2)['pull_request'] = {}
        self.row(kind='pulls/comments', ident=3)
        self.assertEqual(self.run_mode(), 0)
        self.assertIn('"count": 3', self.output.getvalue())
        self.assertIn('/pull/1#discussion_r3', self.output.getvalue())

    def test_only_body_edits_retrigger(self):
        self.row(kind='issues')
        self.initialize()
        self.rows['issues'][0]['updated_at'] = monitor.stamp(monitor.utc_now())
        self.assertEqual(self.run_mode(), 0)
        self.assertIn('"count": 0', self.output.getvalue())
        self.rows['issues'][0]['body'] += '\n수정된 요청'
        self.assertEqual(self.run_mode(), 0)
        self.assertIn('"count": 1', self.output.getvalue())

    def test_api_failure_does_not_advance_or_leak_stderr(self):
        self.initialize()
        before = self.state.read_bytes()
        with patch.object(self, 'command', return_value=subprocess.CompletedProcess([], 1, '', 'secret-token')):
            self.assertEqual(self.run_mode(), 1)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertNotIn('secret-token', self.errors.getvalue())

    def test_corrupt_state_not_overwritten(self):
        self.initialize()
        self.state.write_text('broken', encoding='utf-8')
        self.assertEqual(self.run_mode(), 1)
        self.assertEqual(self.state.read_text(), 'broken')

    def test_binding_change_rejected_without_state_change(self):
        self.initialize()
        before = self.state.read_bytes()
        self.assertEqual(self.run_mode(extra=('--recipient', 'builder')), 1)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertFalse(self.calls)

    def test_writer_lock_prevents_second_process(self):
        with monitor.writer_lock(self.state):
            self.assertEqual(self.run_mode(), 1)
        self.assertFalse(self.state.exists())

    def test_check_without_state_does_not_create_files(self):
        self.assertEqual(self.run_mode('check'), 1)
        self.assertFalse(self.state.parent.exists())

    def test_invalid_options_fail_before_commands(self):
        self.assertEqual(self.run_mode(extra=('--interval', '14')), 1)
        self.assertFalse(self.calls)

    def test_fifteen_second_watch_detects_new_request_without_ai(self):
        self.initialize()
        self.row()
        with patch.object(monitor.time, 'sleep', side_effect=KeyboardInterrupt) as sleep:
            self.assertEqual(self.run_mode('watch', extra=('--interval', '15')), 130)
        sleep.assert_called_once_with(15)
        self.assertIn('"status": "request"', self.output.getvalue())
        self.assertTrue(all(call[:2] == ['gh', 'api'] for call in self.calls))

    def test_mention_marker_is_ignored_and_plain_marker_is_detected(self):
        self.initialize()
        self.row(body='@agent:reviewer\nold format', ident=1)
        self.row(body='agent:reviewer\nnew format', ident=2)
        self.assertEqual(self.run_mode(), 0)
        events = [json.loads(line) for line in self.output.getvalue().splitlines()]
        requests = [event for event in events if event['status'] == 'request']
        self.assertEqual([event['event']['id'] for event in requests], [2])

    def test_watch_without_requests_never_invokes_ai(self):
        self.initialize()
        with patch.object(monitor.time, 'sleep', side_effect=KeyboardInterrupt):
            self.assertEqual(self.run_mode('watch'), 130)
        self.assertTrue(self.calls)
        self.assertTrue(all(call[:2] == ['gh', 'api'] for call in self.calls))

    def test_overlap_and_query_start_checkpoint(self):
        self.initialize()
        original_cursor = monitor.load_state(self.state)['cursor']
        old_time = monitor.datetime.fromisoformat(original_cursor.replace('Z', '+00:00'))
        later = old_time + timedelta(minutes=10)
        self.row()['updated_at'] = monitor.stamp(old_time + timedelta(minutes=5))
        with patch.object(monitor, 'utc_now', return_value=later):
            self.assertEqual(self.run_mode(), 0)
        expected = monitor.stamp(old_time - timedelta(seconds=120))
        for call in self.calls:
            self.assertEqual(parse_qs(urlsplit(call[-1]).query)['since'], [expected])
        self.assertEqual(monitor.load_state(self.state)['cursor'], monitor.stamp(later))
        self.assertIn('"count": 1', self.output.getvalue())

    def test_malformed_api_keeps_checkpoint(self):
        self.initialize()
        before = self.state.read_bytes()
        self.row()['user'] = ['unexpected']
        self.assertEqual(self.run_mode(), 1)
        self.assertEqual(self.state.read_bytes(), before)

    def test_malformed_json_keeps_checkpoint(self):
        self.initialize()
        before = self.state.read_bytes()
        with patch.object(self, 'command', return_value=subprocess.CompletedProcess([], 0, 'not-json', '')):
            self.assertEqual(self.run_mode(), 1)
        self.assertEqual(self.state.read_bytes(), before)

    def test_status_is_local_and_private_state_permissions(self):
        self.initialize()
        self.assertEqual(self.run_mode('status'), 0)
        self.assertFalse(self.calls)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.state.parent.stat().st_mode & 0o777, 0o700)


    def test_request_output_is_metadata_only_and_read_only(self):
        self.initialize()
        self.row(body='agent:reviewer\nuntrusted shell input')
        self.assertEqual(self.run_mode(), 0)
        events = [json.loads(line) for line in self.output.getvalue().splitlines()]
        request = next(event for event in events if event['status'] == 'request')
        self.assertNotIn('body', request['event'])
        self.assertNotIn('untrusted shell input', self.output.getvalue())
        self.assertIn('body_sha256', request['event'])
        self.assertEqual(set(monitor.load_state(self.state)['seen'].values()), {'notified'})
        self.assertTrue(all(call[:2] == ['gh', 'api'] for call in self.calls))

    def test_previous_state_version_preserved_without_api_calls(self):
        self.initialize()
        state = monitor.load_state(self.state)
        state['version'] = 1
        self.state.write_text(json.dumps(state), encoding='utf-8')
        before = self.state.read_bytes()
        self.assertEqual(self.run_mode(), 1)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertFalse(self.calls)
        self.assertIn('이전 버전', self.errors.getvalue())

    def test_status_rejects_previous_version_without_overwrite(self):
        self.initialize()
        state = monitor.load_state(self.state)
        state['version'] = 1
        self.state.write_text(json.dumps(state), encoding='utf-8')
        before = self.state.read_bytes()
        self.assertEqual(self.run_mode('status'), 1)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertFalse(self.calls)

    def test_unknown_processing_status_preserved(self):
        self.row()
        self.initialize()
        state = monitor.load_state(self.state)
        state['seen'] = {key: 'unexpected' for key in state['seen']}
        self.state.write_text(json.dumps(state), encoding='utf-8')
        before = self.state.read_bytes()
        self.assertEqual(self.run_mode(), 1)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertFalse(self.calls)

    def test_api_timeout_does_not_advance_state(self):
        self.initialize()
        before = self.state.read_bytes()
        with patch.object(self, 'command', side_effect=subprocess.TimeoutExpired(['gh'], 30)):
            self.assertEqual(self.run_mode(), 1)
        self.assertEqual(self.state.read_bytes(), before)

    def test_new_state_and_status_have_no_execution_binding(self):
        self.initialize()
        state = monitor.load_state(self.state)
        self.assertEqual(state['version'], 2)
        self.assertEqual(set(state['binding']), {'repo', 'recipient', 'allow_author', 'ignore_author'})
        self.assertEqual(self.run_mode('status'), 0)
        event = json.loads(self.output.getvalue().strip())
        self.assertEqual(set(event), {'status', 'cursor', 'seen'})


if __name__ == '__main__':
    unittest.main()

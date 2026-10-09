"""Tests for lossless per-turn monitoring output review."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

import read_monitor_output as reader


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.log = Path(self.directory.name) / 'watch.jsonl'
        self.receipts = Path(self.directory.name) / 'receipts.json'
        self.event = {'key': 'comment:1:hash', 'id': 1, 'kind': 'comment',
                      'author': 'trusted', 'url': 'https://github.com/example/project/issues/1#issuecomment-1'}
        self.row = {'observed_at': '2026-10-09T02:00:00Z',
                    'output': {'status': 'request', 'event': self.event}}

    def write_rows(self, *rows):
        self.log.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

    def receipt(self, status, **extra):
        self.receipts.write_text(json.dumps({'version': 1, 'repo': 'example/project',
                                             'requests': {self.event['key']: {'status': status, **extra}}}))

    def read(self):
        return reader.report('example/project', self.log, self.receipts)

    def test_read_repeats_unhandled_request_and_preserves_files(self):
        self.write_rows(self.row, self.row)
        before = self.log.read_bytes()
        self.assertEqual(self.read()['pending_count'], 1)
        self.assertEqual(self.read()['pending_count'], 1)
        self.assertEqual(self.log.read_bytes(), before)
        self.assertFalse(self.receipts.exists())

    def test_active_request_remains_visible_until_evidenced_completion(self):
        self.write_rows(self.row)
        self.receipt('active')
        self.assertEqual(self.read()['requests'][0]['receipt_status'], 'active')
        self.receipt('done', evidence='verified result')
        before = self.receipts.read_bytes()
        self.assertEqual(self.read()['pending_count'], 0)
        self.assertEqual(self.receipts.read_bytes(), before)

    def test_incomplete_line_is_read_on_next_call(self):
        row = json.dumps(self.row).encode()
        self.log.write_bytes(row[:20])
        self.assertEqual(self.read()['pending_count'], 0)
        self.assertTrue(self.read()['partial_line_ignored'])
        self.log.write_bytes(row + b'\n')
        self.assertEqual(self.read()['pending_count'], 1)

    def test_changed_request_version_is_still_pending(self):
        self.write_rows(self.row)
        self.receipt('done', evidence='old version verified')
        edited = {'output': {'status': 'request',
                            'event': {**self.event, 'key': 'comment:1:new-hash'}}}
        self.write_rows(self.row, edited)
        self.assertEqual(self.read()['pending_count'], 1)

    def test_invalid_receipts_and_foreign_repo_do_not_hide_requests(self):
        self.write_rows(self.row)
        self.receipt('done')
        with self.assertRaises(reader.OutputError):
            self.read()
        self.receipt('pending')
        self.write_rows({'output': {'status': 'request',
                                   'event': {**self.event, 'url': 'https://github.com/other/repo/issues/1'}}})
        with self.assertRaises(reader.OutputError):
            self.read()

    def test_report_omits_raw_body_and_shows_stop_status(self):
        self.row['output']['event']['body'] = 'private untrusted content'
        self.write_rows(self.row, {'status': 'stopped', 'exit_code': 1})
        result = self.read()
        self.assertNotIn('private untrusted content', json.dumps(result))
        self.assertEqual(result['last_status'], 'stopped')

    def test_invalid_observation_time_returns_sanitized_error(self):
        for value in (123, False, '', {'private': 'invalid timestamp'}):
            with self.subTest(value=value):
                self.write_rows({'observed_at': value, 'output': {'status': 'checked'}})
                output, errors = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    result = reader.main(['--repo', 'example/project', '--log', str(self.log)])
                self.assertEqual(result, 1)
                self.assertEqual(output.getvalue(), '')
                self.assertEqual(json.loads(errors.getvalue())['status'], 'error')
                self.assertNotIn('Traceback', errors.getvalue())
                self.assertNotIn(self.directory.name, errors.getvalue())


if __name__ == '__main__':
    unittest.main()

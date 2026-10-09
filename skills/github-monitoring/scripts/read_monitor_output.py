#!/usr/bin/env python3
"""Summarize the local watcher log without consuming or executing requests."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys


class OutputError(Exception):
    pass


def report(repo, log_path, receipts_path=None):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise OutputError('저장소 이름이 올바르지 않습니다.')
    receipts = {}
    if receipts_path is not None and receipts_path.exists():
        state = json.loads(receipts_path.read_text(encoding='utf-8'))
        if (not isinstance(state, dict) or state.get('version') != 1
                or state.get('repo') != repo or not isinstance(state.get('requests'), dict)):
            raise OutputError('처리 기록의 저장소·형식을 확인하세요. 원본은 변경하지 않습니다.')
        receipts = state['requests']
        for receipt in receipts.values():
            if (not isinstance(receipt, dict) or receipt.get('status') not in
                    ('pending', 'active', 'blocked', 'done', 'rejected', 'superseded')):
                raise OutputError('처리 기록의 상태가 올바르지 않습니다.')
            if receipt['status'] in ('done', 'rejected', 'superseded') and not (
                    isinstance(receipt.get('evidence'), str) and receipt['evidence'].strip()):
                raise OutputError('종료 처리 기록에는 확인 근거가 필요합니다.')

    data = log_path.read_bytes()
    complete = data if data.endswith(b'\n') else data.rpartition(b'\n')[0]
    pending = {}
    last_status = None
    last_observed = None
    last_checked = None
    fields = ('key', 'kind', 'id', 'number', 'author', 'updated_at', 'url', 'body_sha256')
    for line in complete.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise OutputError('감시 로그 형식을 확인하세요.')
        output = row.get('output', row)
        if not isinstance(output, dict):
            raise OutputError('감시 출력 형식을 확인하세요.')
        last_status = output.get('status')
        observed_at = row.get('observed_at')
        if observed_at is not None:
            if not isinstance(observed_at, str) or not observed_at.strip():
                raise OutputError('감시 시각의 형식을 확인하세요.')
            last_observed = observed_at
        if last_status == 'checked':
            last_checked = row.get('observed_at')
        if last_status != 'request':
            continue
        event = output.get('event')
        if (not isinstance(event, dict) or not isinstance(event.get('key'), str)
                or not isinstance(event.get('url'), str)
                or not re.fullmatch(rf'https://github\.com/{re.escape(repo)}/(?:issues|pull)/\d+'
                                    r'(?:#(?:issuecomment-|discussion_r)\d+)?', event['url'])):
            raise OutputError('요청 메타데이터의 저장소·형식을 확인하세요.')
        receipt = receipts.get(event['key'], {})
        if receipt.get('status') in ('done', 'rejected', 'superseded'):
            continue
        if event['key'] not in pending:
            pending[event['key']] = {
                **{field: event[field] for field in fields if field in event},
                'first_observed_at': row.get('observed_at'),
                'receipt_status': receipt.get('status', 'pending'),
            }
    age = None
    if last_checked:
        checked = datetime.fromisoformat(last_checked.replace('Z', '+00:00'))
        if checked.tzinfo is None:
            raise OutputError('감시 시각의 시간대가 없습니다.')
        age = max(0, round((datetime.now(timezone.utc) - checked).total_seconds()))
    return {'status': 'monitor_output', 'repo': repo, 'last_status': last_status,
            'last_observed_at': last_observed, 'last_checked_at': last_checked,
            'seconds_since_last_check': age, 'pending_count': len(pending),
            'requests': list(pending.values()),
            'partial_line_ignored': bool(data and not data.endswith(b'\n'))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--log', required=True, type=Path)
    parser.add_argument('--receipts', type=Path)
    args = parser.parse_args(argv)
    try:
        result = report(args.repo, args.log, args.receipts)
    except (OSError, ValueError, TypeError, OutputError):
        print(json.dumps({'status': 'error', 'message':
                          '감시 출력·처리 기록을 확인하세요. 원본은 변경하지 않습니다.'},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())

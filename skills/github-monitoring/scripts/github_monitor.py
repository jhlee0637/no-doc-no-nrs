#!/usr/bin/env python3
"""Read-only GitHub request monitor with local JSON output."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode


class MonitorError(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def stamp(value):
    return value.isoformat().replace('+00:00', 'Z')


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def run_json(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                                check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MonitorError('명령 실행 실패 또는 시간 초과; 원본 출력은 공개하지 않습니다.') from exc
    if result.returncode:
        raise MonitorError('명령 실패; 인증·권한·rate limit을 로컬에서 확인하세요.')
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MonitorError('명령의 JSON 응답이 올바르지 않습니다.') from exc


def api_list(args, suffix, params):
    endpoint = f'repos/{args.repo}/{suffix}?{urlencode({"per_page": 100, **params})}'
    pages = run_json([args.gh_bin, 'api', '--hostname', 'github.com', '--method', 'GET',
                      '--paginate', '--slurp', endpoint])
    if not isinstance(pages, list) or any(not isinstance(p, list) for p in pages):
        raise MonitorError('예상한 페이지 목록 응답이 아닙니다.')
    rows = [row for page in pages for row in page]
    if any(not isinstance(row, dict) for row in rows):
        raise MonitorError('예상한 GitHub 항목 응답이 아닙니다.')
    return rows


def collect(args, since=None):
    params = {'sort': 'updated', 'direction': 'asc'}
    if since:
        params['since'] = since
    events = []
    for suffix, kind, extra in (
        ('issues', 'body', {'state': 'all'}),
        ('issues/comments', 'comment', {}),
        ('pulls/comments', 'review_comment', {}),
    ):
        for row in api_list(args, suffix, {**params, **extra}):
            body = row.get('body') or ''
            user = row.get('user') or {}
            if not isinstance(user, dict):
                raise MonitorError('잘못된 작성자 응답입니다.')
            author = user.get('login', '')
            updated = row.get('updated_at', '')
            if not isinstance(body, str) or not isinstance(author, str):
                raise MonitorError('잘못된 본문 또는 작성자 응답입니다.')
            if not isinstance(updated, str) or not re.fullmatch(
                    r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', updated):
                raise MonitorError('변경 시각이 올바르지 않은 응답입니다.')
            if since and updated < since:
                continue
            number = row.get('number')
            if kind != 'body':
                field = 'issue_url' if kind == 'comment' else 'pull_request_url'
                parent_url = row.get(field, '')
                if not isinstance(parent_url, str):
                    raise MonitorError('댓글의 상위 항목 주소가 올바르지 않습니다.')
                match = re.fullmatch(
                    rf'https://api\.github\.com/repos/{re.escape(args.repo)}/(?:issues|pulls)/(\d+)',
                    parent_url, flags=re.IGNORECASE)
                if not match:
                    raise MonitorError('댓글의 저장소·상위 항목 주소가 올바르지 않습니다.')
                number = int(match.group(1))
            if type(number) is not int or number < 1 or type(row.get('id')) is not int:
                raise MonitorError('잘못된 요청 식별자 응답입니다.')
            digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
            key = f'{kind}:{row["id"]}:{digest}'
            url = f'https://github.com/{args.repo}/issues/{number}'
            if kind == 'comment':
                url += f'#issuecomment-{row["id"]}'
            elif kind == 'review_comment':
                url = f'https://github.com/{args.repo}/pull/{number}#discussion_r{row["id"]}'
            elif 'pull_request' in row:
                url = f'https://github.com/{args.repo}/pull/{number}'
            first_line = body.splitlines()[0].strip() if body.splitlines() else ''
            eligible = (author.lower() in args.allow_author
                        and author.lower() not in args.ignore_author
                        and first_line == f'@agent:{args.recipient}')
            events.append({'key': key, 'kind': kind, 'id': row['id'], 'number': number,
                           'author': author, 'updated_at': updated, 'url': url,
                           'body_sha256': digest, 'eligible': eligible})
    return sorted(events, key=lambda e: (e['updated_at'], e['key']))


def binding(args):
    return {'repo': args.repo, 'recipient': args.recipient,
            'allow_author': sorted(args.allow_author), 'ignore_author': sorted(args.ignore_author)}


def load_state(path):
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise MonitorError('상태를 읽을 수 없습니다. 삭제·재초기화하지 말고 확인하세요.') from exc
    if isinstance(state, dict) and state.get('version') != 2:
        raise MonitorError('이전 버전 상태는 보존하고 별도 새 상태 파일로 기준선을 설정하세요.')
    if (not isinstance(state, dict) or state.get('version') != 2
            or not isinstance(state.get('seen'), dict)
            or not isinstance(state.get('binding'), dict)
            or not isinstance(state.get('cursor'), str)):
        raise MonitorError('상태 형식이 올바르지 않습니다.')
    if any(v not in ('baseline', 'ignored', 'notified')
           for v in state['seen'].values()):
        raise MonitorError('알 수 없는 처리 상태입니다.')
    return state


def save_state(path, state):
    fd, temporary = tempfile.mkstemp(prefix='.monitor-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(state, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def writer_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = path.with_name(path.name + '.lock')
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MonitorError('이 상태 파일을 사용하는 감시 프로세스가 이미 있습니다.') from exc
        yield
    finally:
        os.close(fd)


def poll(args, preview=False):
    path = Path(args.state)
    started = stamp(utc_now())
    if not path.exists():
        if preview:
            raise MonitorError('기준선이 없습니다. 먼저 once로 초기화하세요.')
        events = collect(args)
        state = {'version': 2, 'binding': binding(args), 'cursor': started,
                 'seen': {event['key']: 'baseline' for event in events}}
        save_state(path, state)
        emit({'status': 'baseline', 'count': len(events), 'cursor': started})
        return
    state = load_state(path)
    if state['binding'] != binding(args):
        raise MonitorError('설정이 기존 상태와 다릅니다. 저장소·담당자별 별도 상태 파일을 사용하세요.')
    try:
        since = stamp(datetime.fromisoformat(state['cursor'].replace('Z', '+00:00'))
                      - timedelta(seconds=120))
    except ValueError as exc:
        raise MonitorError('상태의 체크포인트 시각이 올바르지 않습니다.') from exc
    events = collect(args, since)
    count = 0
    for event in events:
        key = event['key']
        if key in state['seen']:
            continue
        if not event['eligible']:
            if not preview:
                state['seen'][key] = 'ignored'
            continue
        count += 1
        if preview:
            emit({'status': 'preview', 'event': {k: v for k, v in event.items() if k != 'eligible'}})
            continue
        emit({'status': 'request', 'event': {k: v for k, v in event.items() if k != 'eligible'}})
        state['seen'][key] = 'notified'
    if not preview:
        state['cursor'] = started
        save_state(path, state)
    emit({'status': 'checked', 'count': count, 'preview': preview})


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('mode', choices=('once', 'check', 'watch', 'status'))
    result.add_argument('--repo', help='OWNER/REPO (github.com only)')
    result.add_argument('--recipient', help='logical agent name')
    result.add_argument('--allow-author', action='append', default=[])
    result.add_argument('--ignore-author', action='append', default=[])
    result.add_argument('--state', required=True, help='private, Git-ignored state file')
    result.add_argument('--interval', type=int, default=60)
    result.add_argument('--gh-bin', default='gh', help='single executable, not a shell expression')
    return result


def validate(args):
    if args.mode == 'status':
        return
    if (not args.repo or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo)
            or any(part in ('.', '..') for part in args.repo.split('/'))):
        raise MonitorError('--repo OWNER/REPO가 필요합니다.')
    if not args.recipient or not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,63}', args.recipient):
        raise MonitorError('논리 담당자 이름이 올바르지 않습니다.')
    if not args.allow_author:
        raise MonitorError('--allow-author를 최소 하나 지정하세요.')
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*(?:\[bot\])?', login)
           for login in args.allow_author + args.ignore_author):
        raise MonitorError('작성자 계정 이름이 올바르지 않습니다.')
    args.allow_author = {login.lower() for login in args.allow_author}
    args.ignore_author = {login.lower() for login in args.ignore_author}
    if args.interval < 30:
        raise MonitorError('감시 간격은 최소 30초입니다.')


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        validate(args)
        if args.mode == 'status':
            state = load_state(Path(args.state))
            emit({'status': 'checkpoint', 'cursor': state['cursor'], 'seen': len(state['seen'])})
        elif args.mode == 'check':
            poll(args, preview=True)
        else:
            with writer_lock(Path(args.state)):
                while True:
                    poll(args)
                    if args.mode == 'once':
                        break
                    time.sleep(args.interval)
        return 0
    except KeyboardInterrupt:
        return 130
    except (MonitorError, OSError) as exc:
        # Never echo subprocess stderr, credentials, or personalized paths.
        message = str(exc) if isinstance(exc, MonitorError) else '로컬 상태 파일 작업 실패.'
        print(json.dumps({'status': 'error', 'message': message}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

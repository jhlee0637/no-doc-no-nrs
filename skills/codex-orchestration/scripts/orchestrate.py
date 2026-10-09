#!/usr/bin/env python3
"""Local durable task queue and bounded Codex-only runner (Python 3.10+, POSIX)."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import time
import uuid


class QueueError(Exception):
    pass


class BusyError(QueueError):
    """Temporary ownership conflict; watch can defer this candidate."""


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def identifier(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value):
        raise QueueError("invalid logical identifier")
    return value


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(path):
    value = Path(path).read_text(encoding="utf-8")
    if not value.strip() or len(value.encode("utf-8")) > 1024 * 1024:
        raise QueueError("file must contain 1 byte to 1 MiB of text")
    return value


def private_file(path, mode="w"):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, mode, encoding="utf-8")


@contextmanager
def runner_lock(database):
    # Kernel releases this lock on process exit, including SIGKILL. It is NOT
    # proof that a previously launched child has stopped.
    fd = os.open(str(database) + ".runner.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BusyError("another local runner is using this database") from exc
        yield
    finally:
        os.close(fd)


class Queue:
    def __init__(self, database, clock=time.time):
        self.path = Path(database).absolute()
        self.clock = clock
        if self.path.is_symlink() or not self.path.is_file():
            raise QueueError("database missing or symlink; use init explicitly")
        self.db = sqlite3.connect(f"{self.path.as_uri()}?mode=rw", uri=True,
                                  timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        if self.db.execute("PRAGMA user_version").fetchone()[0] != 1:
            self.close()
            raise QueueError("unsupported database schema; do not reset it")

    @staticmethod
    def init(database):
        path = Path(database).absolute()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        db = sqlite3.connect(path)
        try:
            db.executescript("""
                PRAGMA synchronous=FULL;
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    workspace TEXT NOT NULL, body TEXT NOT NULL,
                    body_hash TEXT NOT NULL, dependencies TEXT NOT NULL,
                    state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 1,
                    repairs INTEGER NOT NULL DEFAULT 0,
                    due REAL, created REAL NOT NULL, updated REAL NOT NULL,
                    token TEXT, lease_until REAL, session_id TEXT,
                    posture TEXT, result TEXT, evidence TEXT, note TEXT);
                CREATE TABLE events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    attempt INTEGER NOT NULL, kind TEXT NOT NULL,
                    at REAL NOT NULL, detail TEXT NOT NULL,
                    dedupe TEXT UNIQUE);
                PRAGMA user_version=1;
            """)
            db.commit()
        finally:
            db.close()

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def task(self, task_id):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise QueueError("unknown task")
        return dict(row)

    def event(self, row, kind, detail, dedupe=None):
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO events(task_id,attempt,kind,at,detail,dedupe) "
            "VALUES(?,?,?,?,?,?)", (row["id"], row["attempt"], kind, self.clock(),
                                   json.dumps(detail, ensure_ascii=False), dedupe))
        return cursor.rowcount == 1

    def enqueue(self, task_id, owner, workspace, body, dependencies=(), delay=0):
        identifier(task_id)
        identifier(owner)
        workspace = str(Path(workspace).resolve(strict=True))
        if not Path(workspace).is_dir() or not body.strip():
            raise QueueError("existing workspace directory and nonempty brief required")
        dependencies = sorted(set(dependencies))
        now = self.clock()
        with self.transaction():
            old = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            binding = (owner, workspace, body, json.dumps(dependencies))
            if old:
                if binding != tuple(old[k] for k in ("owner", "workspace", "body", "dependencies")):
                    raise QueueError("task id already exists with different content or binding")
                return self.task(task_id)
            for dep in dependencies:
                self.task(dep)  # Existing parents only: cycles cannot be introduced.
            self.db.execute(
                "INSERT INTO tasks(id,owner,workspace,body,body_hash,dependencies,state,"
                "due,created,updated) VALUES(?,?,?,?,?,?,'queued',?,?,?)",
                (task_id, owner, workspace, body, digest(body), json.dumps(dependencies),
                 now + delay, now, now))
            row = self.task(task_id)
            self.event(row, "enqueued", {"body_sha256": row["body_hash"]})
            return row

    def ready(self, row):
        return (row["state"] == "queued" and row["due"] <= self.clock()
                and all(self.task(d)["state"] == "done"
                        for d in json.loads(row["dependencies"])))

    def claim(self, task_id, owner, lease=120):
        with self.transaction():
            row = self.task(task_id)
            if row["owner"] != owner or not self.ready(row):
                raise BusyError("task not ready or owner mismatch")
            if not self.workspace_available(row):
                raise BusyError("overlapping workspace already has an active writer")
            token = str(uuid.uuid4())
            self.db.execute("UPDATE tasks SET state='active',token=?,lease_until=?,updated=? WHERE id=?",
                            (token, self.clock() + lease, self.clock(), task_id))
            row = self.task(task_id)
            self.event(row, "claimed", {"owner": owner})
            return row

    def workspace_available(self, row):
        workspace = Path(row["workspace"])
        for other in self.db.execute("SELECT workspace FROM tasks WHERE state='active'"):
            other_path = Path(other[0])
            if workspace == other_path or workspace in other_path.parents or other_path in workspace.parents:
                return False
        return True

    def check_claim(self, task_id, attempt, token):
        row = self.task(task_id)
        if row["state"] != "active" or row["attempt"] != attempt or row["token"] != token:
            raise QueueError("stale attempt or invalid claim; result not applied")
        return row

    def heartbeat(self, task_id, attempt, token, lease=120):
        with self.transaction():
            self.check_claim(task_id, attempt, token)
            self.db.execute("UPDATE tasks SET lease_until=?,updated=? WHERE id=?",
                            (self.clock() + lease, self.clock(), task_id))

    def bind_run(self, row, posture):
        value = json.dumps(posture, sort_keys=True)
        with self.transaction():
            current = self.check_claim(row["id"], row["attempt"], row["token"])
            if current["posture"] and current["posture"] != value:
                raise QueueError("resume posture differs; do not silently broaden or switch profiles")
            self.db.execute("UPDATE tasks SET posture=? WHERE id=?", (value, row["id"]))

    def session(self, row, session_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", session_id):
            raise QueueError("invalid native session identifier")
        with self.transaction():
            current = self.check_claim(row["id"], row["attempt"], row["token"])
            if current["session_id"] and current["session_id"] != session_id:
                raise QueueError("native session changed during resume")
            self.db.execute("UPDATE tasks SET session_id=? WHERE id=?", (session_id, row["id"]))
            self.event(current, "session-recorded", {"session_id": session_id},
                       f'{row["id"]}:{row["attempt"]}:session')

    def submit(self, task_id, attempt, token, result):
        if not result.strip():
            raise QueueError("nonempty result required")
        with self.transaction():
            row = self.check_claim(task_id, attempt, token)
            self.db.execute("UPDATE tasks SET state='review',result=?,token=NULL,lease_until=NULL,"
                            "updated=? WHERE id=?", (result, self.clock(), task_id))
            self.event(row, "submitted", {"result": result, "result_sha256": digest(result)})
        return self.task(task_id)

    def change(self, task_id, action, note, evidence=None, writer_stopped=False, delay=None,
               expected_attempt=None):
        if not note.strip():
            raise QueueError("reason required")
        with self.transaction():
            row = self.task(task_id)
            if expected_attempt is not None and row["attempt"] != expected_attempt:
                raise QueueError("stale transition attempt; inspect current state")
            state, attempt, repairs = row["state"], row["attempt"], row["repairs"]
            if action == "accept":
                if state != "review" or not evidence or not evidence.strip():
                    raise QueueError("only reviewed results with verification evidence can be accepted")
                target = "done"
            elif action == "rework":
                if state != "review" or repairs >= 2:
                    raise QueueError("rework requires review and fewer than two repair cycles")
                target, attempt, repairs = "queued", attempt + 1, repairs + 1
            elif action == "requeue":
                if state not in ("active", "blocked") or not writer_stopped:
                    raise QueueError("recovery requires active/blocked and confirmed stopped writer")
                target, attempt = "queued", attempt + 1
            elif action == "block":
                if state not in ("queued", "active", "review") or (state == "active" and not writer_stopped):
                    raise QueueError("blocking active work requires confirmed stopped writer")
                target = "blocked"
            elif action == "cancel":
                if state in ("done", "cancelled") or (state == "active" and not writer_stopped):
                    raise QueueError("terminal task or writer not confirmed stopped")
                target = "cancelled"
            else:
                raise QueueError("unknown transition")
            due = self.clock() + (delay or 0) if target == "queued" or delay is not None else None
            self.db.execute("UPDATE tasks SET state=?,attempt=?,repairs=?,due=?,updated=?,"
                            "token=NULL,lease_until=NULL,note=?,evidence=? WHERE id=?",
                            (target, attempt, repairs, due, self.clock(), note, evidence, task_id))
            self.event(row, action, {"from": state, "to": target, "note": note,
                                    "next_attempt": attempt,
                                    "evidence": evidence,
                                    "evidence_sha256": digest(evidence) if evidence else None})
        return self.task(task_id)

    def list(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM tasks ORDER BY created,id")]

    def history(self, after=0):
        return [dict(row) for row in self.db.execute("SELECT * FROM events WHERE seq>? ORDER BY seq", (after,))]

    def tick(self, owner=None):
        """Durably deduplicate alerts; expiration never transfers write ownership."""
        alerts = []
        with self.transaction():
            for row in self.list():
                if owner and row["owner"] != owner:
                    continue
                kind = None
                if self.ready(row):
                    kind = "wake-ready"
                elif row["state"] == "active" and row["lease_until"] <= self.clock():
                    kind = "attention-stale"
                elif row["state"] == "blocked" and row["due"] is not None and row["due"] <= self.clock():
                    kind = "wake-blocked"
                schedule = row["lease_until"] if kind == "attention-stale" else row["due"]
                if kind and self.event(row, kind, {"state": row["state"]},
                                       f'{row["id"]}:{row["attempt"]}:{kind}:{schedule}'):
                    alerts.append({"task_id": row["id"], "attempt": row["attempt"], "kind": kind})
        return alerts


def configuration_fingerprint(profile):
    identifier(profile)
    root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    profile_path = root / (profile + ".config.toml")
    if not profile_path.is_file():
        raise QueueError("selected profile file missing; confirm installed Codex profile format")
    paths = (root / "config.toml", profile_path)
    return [hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None for path in paths]


def codex_command(row, args):
    if not args.authorize_exec or not args.profile:
        raise QueueError("Codex dispatch requires --authorize-exec and an explicitly vetted --profile")
    identifier(args.profile)
    if args.resume and not row["session_id"]:
        raise QueueError("no recorded native session; resume cannot fall back to a fresh session")
    if not args.resume and row["session_id"]:
        raise QueueError("recorded session exists; explicitly choose --resume, not a silent fresh restart")
    argv = [args.codex_bin, "exec", "--json", "--profile", args.profile,
            "--sandbox", args.sandbox, "--cd", row["workspace"],
            "-c", 'approval_policy="never"', "-c", 'model_provider="openai"',
            "-c", "sandbox_workspace_write.network_access=false",
            "-c", "sandbox_workspace_write.writable_roots=[]",
            "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
            "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true"]
    if args.resume:
        argv.extend(["resume", row["session_id"]])
    argv.append("-")
    return argv


def parse_events(lines):
    session_id, completed, failed, message = None, False, False, ""
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "thread.started":
            session_id = event.get("thread_id")
        elif event.get("type") == "turn.completed":
            completed = True
        elif event.get("type") in ("turn.failed", "error"):
            failed = True
        elif event.get("type") == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                message = item["text"]
    return session_id, completed and not failed, message


def preserve_session(queue, row, log_dir):
    if log_dir is None:
        return
    path = log_dir / "events.jsonl"
    if not path.is_file():
        return
    session_id, _, _ = parse_events(path.read_text(encoding="utf-8", errors="replace").splitlines())
    if session_id:
        queue.session(row, session_id)


def group_alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_child(process, grace=3):
    """Signal only the process group created for this run, not arbitrary seats."""
    def signal_group(sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass

    def wait_group():
        deadline = time.monotonic() + grace
        while True:
            process.poll()  # Reap the leader without mistaking it for the whole group.
            if not group_alive(process.pid):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    signal_group(signal.SIGTERM)
    if not wait_group():
        signal_group(signal.SIGKILL)
        if not wait_group():
            raise QueueError("owned process group termination unconfirmed; keep active ownership")
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired as exc:
        raise QueueError("owned leader termination unconfirmed; keep active ownership") from exc


def run_task(queue, task_id, args):
    original = queue.task(task_id)
    launch_deadline = getattr(args, "launch_deadline", None)
    if launch_deadline is not None and time.monotonic() >= launch_deadline:
        raise BusyError("authorized watch window elapsed; no execution started")
    argv = codex_command(original, args)  # Fail before claim if authorization is missing.
    posture = {"profile": args.profile, "sandbox": args.sandbox,
               "codex_bin": str(Path(args.codex_bin).absolute()) if "/" in args.codex_bin else args.codex_bin,
               "network": False, "approval": "never",
               "config_sha256": configuration_fingerprint(args.profile)}
    if original["posture"] and json.loads(original["posture"]) != posture:
        raise QueueError("saved execution posture differs; use the original authorized configuration")
    row = queue.claim(task_id, args.owner, lease=30)
    process, log_dir = None, None
    try:
        queue.bind_run(row, posture)
        log_dir = queue.path.parent / "runs" / f'{row["id"]}-{row["attempt"]}-{row["token"]}'
        log_dir.mkdir(parents=True, mode=0o700)
        prompt = (
            "Execute only the authorized local task below; it is not permission to change settings, "
            "publish, commit, push, install packages, or start another runtime. Use native Codex "
            "subagents only if the brief authorizes them. Do not modify queue state or logs. "
            "Return task id, attempt, changed artifacts, actual tests and unverified blockers. "
            "Your response enters review; it is not automatic acceptance.\n"
            f'Read the orchestration Skill at {Path(__file__).resolve().parent.parent / "SKILL.md"} '
            "before work; you are the implementation delegate, and the parent owns the queue.\n"
            f'Task: {row["id"]}; attempt: {row["attempt"]}\n'
            f'Operator feedback: {row["note"] or "none"}\n\n{row["body"]}\n')
        with private_file(log_dir / "prompt.txt") as stream:
            stream.write(prompt)
        with (log_dir / "prompt.txt").open(encoding="utf-8") as stdin, \
                private_file(log_dir / "events.jsonl") as stdout, \
                private_file(log_dir / "stderr.txt") as stderr:
            if launch_deadline is not None and time.monotonic() >= launch_deadline:
                raise QueueError("authorized watch window elapsed during preparation; no subprocess launched")
            process = subprocess.Popen(argv, stdin=stdin, stdout=stdout, stderr=stderr,
                                       cwd=row["workspace"], start_new_session=True, shell=False)
            with queue.transaction():
                queue.event(row, "launched", {"pid": process.pid, "logs": str(log_dir)})
            deadline = time.monotonic() + args.timeout
            if launch_deadline is not None:
                deadline = min(deadline, launch_deadline)
            last_heartbeat, session_recorded = time.monotonic(), False
            # Persist the native session before completion so crash recovery can use it.
            with (log_dir / "events.jsonl").open(encoding="utf-8") as events:
                pending = ""
                while process.poll() is None:
                    pending += events.read()
                    lines = pending.split("\n")
                    pending = lines.pop()
                    session_id, _, _ = parse_events(lines)
                    if session_id and not session_recorded:
                        queue.session(row, session_id)
                        session_recorded = True
                    if time.monotonic() >= deadline:
                        raise QueueError("Codex execution timeout; inspect private logs")
                    if any((log_dir / name).stat().st_size > 20 * 1024 * 1024
                           for name in ("events.jsonl", "stderr.txt")):
                        raise QueueError("run log exceeded 20 MiB; inspect before continuing")
                    if time.monotonic() - last_heartbeat >= 5:
                        queue.heartbeat(row["id"], row["attempt"], row["token"], lease=30)
                        last_heartbeat = time.monotonic()
                    time.sleep(0.1)
        session_id, complete, message = parse_events((log_dir / "events.jsonl").read_text(encoding="utf-8").splitlines())
        if session_id and not session_recorded:
            queue.session(row, session_id)
        if process.returncode != 0 or not complete or not session_id or not message.strip():
            raise QueueError("Codex run incomplete; exit zero alone is not acceptance")
        stop_child(process)
        return queue.submit(row["id"], row["attempt"], row["token"], message)
    except BaseException as exc:
        if process is not None:
            try:
                stop_child(process)
            except (QueueError, OSError, subprocess.SubprocessError):
                preserve_session(queue, row, log_dir)
                with queue.transaction():
                    queue.event(row, "stop-unconfirmed", {"reason": "inspect owned process group before recovery"})
                raise
        preserve_session(queue, row, log_dir)
        current = queue.task(task_id)
        if current["state"] == "active" and current["token"] == row["token"]:
            queue.change(task_id, "block", f"runner stopped: {type(exc).__name__}; inspect private run logs",
                         writer_stopped=True)
        raise


def public_projection(row):
    # Compact operational view, still PRIVATE (workspace/session/owner identifiers).
    return {key: row[key] for key in ("id", "owner", "workspace", "state", "attempt",
                                     "repairs", "due", "lease_until", "session_id", "note")}


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def execution_options(parser):
    parser.add_argument("--owner", required=True)
    parser.add_argument("--authorize-exec", action="store_true")
    parser.add_argument("--profile")
    parser.add_argument("--sandbox", choices=("read-only", "workspace-write"), default="read-only")
    parser.add_argument("--codex-bin", default="codex", help="one explicitly selected executable, not shell text")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--timeout", type=positive, default=300)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="private SQLite path; always use the same path")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    enqueue = commands.add_parser("enqueue")
    enqueue.add_argument("--id", required=True)
    enqueue.add_argument("--owner", required=True)
    enqueue.add_argument("--workspace", required=True)
    enqueue.add_argument("--brief-file", required=True)
    enqueue.add_argument("--depends-on", action="append", default=[])
    enqueue.add_argument("--delay", type=positive, default=0)
    commands.add_parser("status")
    show = commands.add_parser("show")
    show.add_argument("--id", required=True)
    history = commands.add_parser("events")
    history.add_argument("--after", type=int, default=0)
    commands.add_parser("recover")
    claim = commands.add_parser("claim")
    claim.add_argument("--id", required=True)
    claim.add_argument("--owner", required=True)
    claim.add_argument("--lease", type=positive, default=120)
    heartbeat = commands.add_parser("heartbeat")
    submit = commands.add_parser("submit")
    for sub in (heartbeat, submit):
        sub.add_argument("--id", required=True)
        sub.add_argument("--attempt", type=int, required=True)
        sub.add_argument("--token", required=True)
    heartbeat.add_argument("--lease", type=positive, default=120)
    submit.add_argument("--result-file", required=True)
    for action in ("accept", "rework", "requeue", "block", "cancel"):
        sub = commands.add_parser(action)
        sub.add_argument("--id", required=True)
        sub.add_argument("--attempt", type=int, required=True)
        sub.add_argument("--note", required=True)
        sub.add_argument("--writer-stopped", action="store_true")
        if action == "accept":
            sub.add_argument("--evidence-file", required=True)
        if action == "block":
            sub.add_argument("--wake-after", type=positive)
    tick = commands.add_parser("tick")
    tick.add_argument("--owner")
    run = commands.add_parser("run")
    run.add_argument("--id", required=True)
    execution_options(run)
    watch = commands.add_parser("watch")
    watch.add_argument("--duration", type=positive, required=True)
    watch.add_argument("--interval", type=positive, default=5)
    watch.add_argument("--max-runs", type=int, default=1)
    watch.add_argument("--dispatch-codex", action="store_true")
    execution_options(watch)
    args = parser.parse_args(argv)
    if args.command == "init":
        Queue.init(args.db)
        emit({"initialized": True})
        return 0
    queue = Queue(args.db)
    try:
        if args.command == "enqueue":
            result = public_projection(queue.enqueue(args.id, args.owner, args.workspace,
                                                      read_text(args.brief_file), args.depends_on, args.delay))
        elif args.command == "status":
            result = [public_projection(row) for row in queue.list()]
        elif args.command == "show":
            result = queue.task(args.id)
        elif args.command == "events":
            result = queue.history(args.after)
        elif args.command == "recover":
            result = [{**public_projection(row), "recovery":
                       "verify old writer stopped before requeue" if row["state"] == "active"
                       else "reconcile artifacts and authorization; no automatic restart"}
                      for row in queue.list() if row["state"] not in ("done", "cancelled")]
        elif args.command == "claim":
            result = queue.claim(args.id, args.owner, args.lease)
        elif args.command == "heartbeat":
            queue.heartbeat(args.id, args.attempt, args.token, args.lease)
            result = {"heartbeat": True}
        elif args.command == "submit":
            result = public_projection(queue.submit(args.id, args.attempt, args.token, read_text(args.result_file)))
        elif args.command in ("accept", "rework", "requeue", "block", "cancel"):
            # Mutating recovery is excluded while a local runner is alive.
            with runner_lock(queue.path):
                result = public_projection(queue.change(args.id, args.command, args.note,
                    read_text(args.evidence_file) if args.command == "accept" else None,
                    args.writer_stopped, getattr(args, "wake_after", None), args.attempt))
        elif args.command == "tick":
            result = queue.tick(args.owner)
        elif args.command == "run":
            with runner_lock(queue.path):
                result = public_projection(run_task(queue, args.id, args))
        else:
            if args.interval > 60 or args.max_runs < 1:
                raise QueueError("watch interval must be <=60s and max-runs >=1")
            if args.dispatch_codex and (not args.authorize_exec or not args.profile):
                raise QueueError("dispatch requires explicit execution authorization and profile")
            deadline, runs = time.monotonic() + args.duration, 0
            while time.monotonic() < deadline:
                for alert in queue.tick(args.owner):
                    emit(alert)
                if args.dispatch_codex and runs < args.max_runs:
                    candidates = [row for row in queue.list() if row["owner"] == args.owner
                                  and queue.ready(row) and queue.workspace_available(row)]
                    for candidate in candidates:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        args.timeout = min(args.timeout, remaining)
                        args.launch_deadline = deadline
                        try:
                            with runner_lock(queue.path):
                                if time.monotonic() >= deadline:
                                    break
                                result = run_task(queue, candidate["id"], args)
                        except BusyError:
                            continue
                        emit(public_projection(result))
                        runs += 1
                        break
                time.sleep(min(args.interval, max(0, deadline - time.monotonic())))
            result = {"watch_stopped": True, "runs": runs}
        emit(result)
        return 0
    finally:
        queue.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("stopped; reconcile durable state before restarting", file=sys.stderr)
        sys.exit(130)
    except (QueueError, OSError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)

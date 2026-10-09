"""Offline behavioral checks: temporary SQLite, real CLI restarts, mocked Codex."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

import orchestrate as runtime


class QueueFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "private" / "queue.sqlite3"
        self.workspace = self.root / "work"
        self.workspace.mkdir()
        self.now = 1000.0
        runtime.Queue.init(self.database)
        self.queue = runtime.Queue(self.database, clock=lambda: self.now)
        self.addCleanup(self.queue.close)

    def enqueue(self, task_id="T01", workspace=None, **options):
        return self.queue.enqueue(task_id, "main", workspace or self.workspace,
                                  "Implement add(a,b) and run four unittest cases.", **options)

    def review(self, task_id="T01"):
        row = self.queue.claim(task_id, "main")
        return self.queue.submit(task_id, row["attempt"], row["token"], "Tests: four passed.")


class QueueTests(QueueFixture):
    def test_init_never_overwrites_existing_database(self):
        self.enqueue()
        with self.assertRaises(FileExistsError):
            runtime.Queue.init(self.database)
        self.assertEqual(self.queue.task("T01")["state"], "queued")
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)

    def test_missing_database_read_does_not_create_it(self):
        missing = self.root / "missing.sqlite3"
        with self.assertRaises(runtime.QueueError):
            runtime.Queue(missing)
        self.assertFalse(missing.exists())

    def test_unknown_schema_is_not_reset(self):
        self.queue.db.execute("PRAGMA user_version=2")
        with self.assertRaises(runtime.QueueError):
            runtime.Queue(self.database)
        self.assertEqual(self.queue.db.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_symlink_database_refused(self):
        link = self.root / "link.sqlite3"
        link.symlink_to(self.database)
        with self.assertRaises(runtime.QueueError):
            runtime.Queue(link)

    def test_idempotent_enqueue_and_binding_conflict(self):
        self.enqueue()
        self.enqueue(delay=50)
        self.assertEqual(len(self.queue.list()), 1)
        self.assertEqual(len(self.queue.history()), 1)
        self.assertEqual(self.queue.task("T01")["due"], 1000)
        with self.assertRaises(runtime.QueueError):
            self.queue.enqueue("T01", "main", self.workspace, "different brief")

    def test_native_body_snapshot_not_mutable_source(self):
        brief = self.root / "brief.txt"
        brief.write_text("original", encoding="utf-8")
        self.queue.enqueue("T01", "main", self.workspace, runtime.read_text(brief))
        brief.write_text("changed", encoding="utf-8")
        self.assertEqual(self.queue.task("T01")["body"], "original")

    def test_delayed_work_and_completed_dependency(self):
        self.enqueue()
        self.enqueue("T02", dependencies=["T01"], delay=10)
        self.now += 20
        with self.assertRaises(runtime.QueueError):
            self.queue.claim("T02", "main")
        self.review()
        self.queue.change("T01", "accept", "verified", evidence="independent tests passed")
        self.assertEqual(self.queue.claim("T02", "main")["state"], "active")

    def test_missing_dependency_rolls_back_all_writes(self):
        with self.assertRaises(runtime.QueueError):
            self.enqueue(dependencies=["missing"])
        self.assertEqual(self.queue.list(), [])
        self.assertEqual(self.queue.history(), [])

    def test_due_time_observed_after_reopen(self):
        self.enqueue(delay=10)
        self.assertEqual(self.queue.tick(), [])
        reopened = runtime.Queue(self.database, clock=lambda: 1011)
        try:
            self.assertEqual(reopened.tick()[0]["kind"], "wake-ready")
            self.assertEqual(reopened.tick(), [])
        finally:
            reopened.close()

    def test_atomic_claim_concurrent_connections(self):
        self.enqueue()
        barrier = threading.Barrier(2)

        def claim():
            queue = runtime.Queue(self.database, clock=lambda: 1000)
            try:
                barrier.wait(timeout=3)
                try:
                    return queue.claim("T01", "main")["token"]
                except runtime.QueueError:
                    return None
            finally:
                queue.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sum(bool(result) for result in results), 1)

    def test_wrong_owner_cannot_claim(self):
        self.enqueue()
        with self.assertRaises(runtime.QueueError):
            self.queue.claim("T01", "other")

    def test_overlapping_workspaces_serialize_active_writers(self):
        self.enqueue()
        nested = self.workspace / "nested"
        nested.mkdir()
        self.enqueue("T02", nested)
        self.queue.claim("T01", "main")
        with self.assertRaises(runtime.QueueError):
            self.queue.claim("T02", "main")
        self.assertEqual(self.queue.task("T02")["state"], "queued")

    def test_disjoint_workspaces_can_be_claimed(self):
        self.enqueue()
        other = self.root / "other"
        other.mkdir()
        self.enqueue("T02", other)
        self.queue.claim("T01", "main")
        self.assertEqual(self.queue.claim("T02", "main")["state"], "active")

    def test_stale_lease_only_alerts_never_reassigns(self):
        self.enqueue()
        row = self.queue.claim("T01", "main", lease=10)
        self.now += 11
        self.assertEqual(self.queue.tick()[0]["kind"], "attention-stale")
        self.assertEqual(self.queue.tick(), [])
        current = self.queue.task("T01")
        self.assertEqual(current["state"], "active")
        self.assertEqual(current["token"], row["token"])
        with self.assertRaises(runtime.QueueError):
            self.queue.claim("T01", "main")

    def test_heartbeat_extends_live_claim(self):
        self.enqueue()
        row = self.queue.claim("T01", "main", lease=10)
        self.now += 9
        self.queue.heartbeat("T01", 1, row["token"], lease=10)
        self.now += 2
        self.assertEqual(self.queue.tick(), [])

    def test_renewed_lease_has_a_new_stale_alert(self):
        self.enqueue()
        row = self.queue.claim("T01", "main", lease=10)
        self.now += 11
        self.assertEqual(self.queue.tick()[0]["kind"], "attention-stale")
        self.queue.heartbeat("T01", 1, row["token"], lease=10)
        self.now += 11
        self.assertEqual(self.queue.tick()[0]["kind"], "attention-stale")
        self.assertEqual(self.queue.tick(), [])

    def test_recovery_needs_stopped_writer_and_rejects_late_results(self):
        self.enqueue()
        row = self.queue.claim("T01", "main")
        with self.assertRaises(runtime.QueueError):
            self.queue.change("T01", "requeue", "restart")
        current = self.queue.change("T01", "requeue", "verified all old writers stopped",
                                    writer_stopped=True, expected_attempt=1)
        self.assertEqual(current["attempt"], 2)
        self.queue.claim("T01", "main")
        with self.assertRaises(runtime.QueueError):
            self.queue.submit("T01", 1, row["token"], "late result")
        self.assertIsNone(self.queue.task("T01")["result"])

    def test_accept_requires_review_and_nonempty_evidence(self):
        self.enqueue()
        with self.assertRaises(runtime.QueueError):
            self.queue.change("T01", "accept", "done", evidence="passed")
        self.review()
        with self.assertRaises(runtime.QueueError):
            self.queue.change("T01", "accept", "done")
        self.assertEqual(self.queue.task("T01")["state"], "review")
        self.queue.change("T01", "accept", "verified", evidence="test and independent review output")
        self.assertEqual(self.queue.task("T01")["state"], "done")

    def test_rework_budget_and_results_preserved_in_history(self):
        self.enqueue()
        for attempt in (1, 2):
            self.review()
            current = self.queue.change("T01", "rework", "repair with reproduction", expected_attempt=attempt)
            self.assertEqual(current["repairs"], attempt)
        self.review()
        with self.assertRaises(runtime.QueueError):
            self.queue.change("T01", "rework", "another repair")
        reports = [json.loads(e["detail"])["result"] for e in self.queue.history() if e["kind"] == "submitted"]
        self.assertEqual(len(reports), 3)

    def test_stale_acceptance_attempt_refused(self):
        self.enqueue()
        self.review()
        self.queue.change("T01", "rework", "repair")
        self.review()
        with self.assertRaises(runtime.QueueError):
            self.queue.change("T01", "accept", "old review", evidence="old evidence", expected_attempt=1)

    def test_blocked_timer_wakes_without_running(self):
        self.enqueue()
        self.queue.change("T01", "block", "needs authority", delay=10)
        self.assertEqual(self.queue.tick(), [])
        self.now += 11
        self.assertEqual(self.queue.tick()[0]["kind"], "wake-blocked")
        self.assertEqual(self.queue.task("T01")["state"], "blocked")

    def test_active_cancel_needs_stopped_writer(self):
        self.enqueue()
        self.queue.claim("T01", "main")
        with self.assertRaises(runtime.QueueError):
            self.queue.change("T01", "cancel", "cancel")
        self.queue.change("T01", "cancel", "stopped confirmed", writer_stopped=True)
        self.assertEqual(self.queue.task("T01")["state"], "cancelled")
        self.assertEqual(self.queue.tick(), [])

    def test_single_runner_kernel_lock(self):
        with runtime.runner_lock(self.database):
            with self.assertRaises(runtime.QueueError):
                with runtime.runner_lock(self.database):
                    self.fail("second lock acquired")

    def test_actual_cli_restart_retains_work(self):
        self.enqueue()
        command = [sys.executable, "-B", str(Path(runtime.__file__)), "--db", str(self.database), "status"]
        result = subprocess.run(command, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0]["id"], "T01")

    def test_real_bounded_watch_never_launches_ai_by_default(self):
        self.enqueue()
        command = [sys.executable, "-B", str(Path(runtime.__file__)), "--db", str(self.database),
                   "watch", "--owner", "main", "--duration", "0.03", "--interval", "0.01"]
        result = subprocess.run(command, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.splitlines()[-1])["runs"], 0)
        self.assertEqual(self.queue.task("T01")["state"], "queued")

    def test_live_alert_watch_does_not_block_cli_acceptance(self):
        self.enqueue()
        self.review()
        command = [sys.executable, "-B", str(Path(runtime.__file__)), "--db", str(self.database)]
        watcher = subprocess.Popen(command + ["watch", "--owner", "main", "--duration", "1", "--interval", "0.01"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(0.05)
            self.assertIsNone(watcher.poll())
            evidence = self.root / "evidence.txt"
            evidence.write_text("actual verification fixture", encoding="utf-8")
            result = subprocess.run(command + ["accept", "--id", "T01", "--attempt", "1",
                                    "--note", "verified", "--evidence-file", str(evidence)],
                                    text=True, capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.queue.task("T01")["state"], "done")
        finally:
            if watcher.poll() is None:
                watcher.terminate()
            watcher.communicate(timeout=3)

    def test_dispatch_skips_busy_workspace_and_enforces_call_cap(self):
        self.enqueue()
        self.queue.claim("T01", "main")
        self.enqueue("T02")
        other = self.root / "other"
        other.mkdir()
        self.enqueue("T03", other)
        self.enqueue("T04", other)
        called = []

        def dispatch(queue, task_id, args):
            called.append(task_id)
            row = queue.claim(task_id, args.owner)
            return queue.submit(task_id, row["attempt"], row["token"], "mocked Codex result")

        with patch.object(runtime, "run_task", side_effect=dispatch), redirect_stdout(io.StringIO()):
            runtime.main(["--db", str(self.database), "watch", "--owner", "main",
                          "--duration", "0.03", "--interval", "0.001", "--max-runs", "1",
                          "--dispatch-codex", "--authorize-exec", "--profile", "vetted"])
        self.assertEqual(called, ["T03"])
        self.assertEqual(self.queue.task("T02")["state"], "queued")
        self.assertEqual(self.queue.task("T04")["state"], "queued")

    def test_expired_watch_bookkeeping_never_dispatches(self):
        self.enqueue()
        now = [0]

        def tick(queue, owner=None):
            now[0] = 2
            return []

        with patch.object(runtime.Queue, "tick", new=tick), \
                patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]), \
                patch.object(runtime.time, "sleep"), \
                patch.object(runtime, "run_task") as run, redirect_stdout(io.StringIO()):
            runtime.main(["--db", str(self.database), "watch", "--owner", "main",
                          "--duration", "1", "--dispatch-codex", "--authorize-exec", "--profile", "vetted"])
        run.assert_not_called()
        self.assertEqual(self.queue.task("T01")["state"], "queued")


class RunnerTests(QueueFixture):
    def arguments(self, **overrides):
        values = dict(owner="main", authorize_exec=True, profile="vetted",
                      sandbox="read-only", codex_bin="codex", resume=False, timeout=1)
        return argparse.Namespace(**{**values, **overrides})

    def events(self, session="test-native-session", completed=True, failed=False):
        events = [{"type": "thread.started", "thread_id": session},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": "four tests passed"}}]
        if completed:
            events.append({"type": "turn.completed"})
        if failed:
            events.append({"type": "turn.failed"})
        return "\n".join(json.dumps(e) for e in events) + "\n"

    def run_mock(self, events=None, returncode=0, args=None):
        process = Mock(pid=987654, returncode=returncode)
        process.poll.return_value = returncode

        def launch(argv, **kwargs):
            self.assertFalse(kwargs["shell"])
            self.assertTrue(kwargs["start_new_session"])
            kwargs["stdout"].write(events if events is not None else self.events())
            kwargs["stdout"].flush()
            return process

        with patch.object(runtime, "configuration_fingerprint", return_value=["base-hash", "profile-hash"]), \
                patch.object(runtime.subprocess, "Popen", side_effect=launch) as popen, \
                patch.object(runtime, "stop_child") as stop:
            result = runtime.run_task(self.queue, "T01", args or self.arguments())
            return result, popen, stop

    def test_codex_completion_enters_review_not_done(self):
        self.enqueue()
        result, _, stop = self.run_mock()
        self.assertEqual(result["state"], "review")
        self.assertEqual(result["session_id"], "test-native-session")
        stop.assert_called_once()
        logs = next((self.database.parent / "runs").iterdir())
        self.assertEqual((logs / "events.jsonl").stat().st_mode & 0o777, 0o600)

    def test_failed_codex_run_blocks_without_retry(self):
        self.enqueue()
        with self.assertRaises(runtime.QueueError):
            self.run_mock(returncode=1)
        self.assertEqual(self.queue.task("T01")["state"], "blocked")

    def test_zero_exit_without_completed_turn_is_not_success(self):
        self.enqueue()
        with self.assertRaises(runtime.QueueError):
            self.run_mock(events=self.events(completed=False))
        self.assertEqual(self.queue.task("T01")["state"], "blocked")

    def test_zero_exit_with_failed_turn_is_not_success(self):
        self.enqueue()
        with self.assertRaises(runtime.QueueError):
            self.run_mock(events=self.events(failed=True))
        self.assertEqual(self.queue.task("T01")["state"], "blocked")

    def test_missing_session_id_is_not_success(self):
        self.enqueue()
        with self.assertRaises(runtime.QueueError):
            self.run_mock(events='{"type":"turn.completed"}\n')

    def test_authorization_checked_before_claim(self):
        self.enqueue()
        with self.assertRaises(runtime.QueueError):
            runtime.run_task(self.queue, "T01", self.arguments(authorize_exec=False))
        self.assertEqual(self.queue.task("T01")["state"], "queued")

    def test_resume_targets_saved_session_and_requires_identical_posture(self):
        self.enqueue()
        self.run_mock()
        self.queue.change("T01", "rework", "fix according to review")
        with self.assertRaises(runtime.QueueError):
            runtime.run_task(self.queue, "T01", self.arguments())
        result, popen, _ = self.run_mock(args=self.arguments(resume=True))
        argv = popen.call_args.args[0]
        self.assertEqual(argv[-3:], ["resume", "test-native-session", "-"])
        self.assertNotIn("--last", argv)
        self.assertEqual(result["state"], "review")

    def test_resume_rejects_changed_sandbox_before_claim(self):
        self.enqueue()
        self.run_mock()
        self.queue.change("T01", "rework", "fix")
        with patch.object(runtime, "configuration_fingerprint", return_value=["base-hash", "profile-hash"]):
            with self.assertRaises(runtime.QueueError):
                runtime.run_task(self.queue, "T01", self.arguments(resume=True, sandbox="workspace-write"))
        self.assertEqual(self.queue.task("T01")["state"], "queued")

    def test_profile_contents_change_detected_before_resume(self):
        self.enqueue()
        self.run_mock()
        self.queue.change("T01", "rework", "fix")
        with patch.object(runtime, "configuration_fingerprint", return_value=["new-base", "profile-hash"]):
            with self.assertRaises(runtime.QueueError):
                runtime.run_task(self.queue, "T01", self.arguments(resume=True))

    def test_resume_never_falls_back_to_fresh(self):
        row = self.enqueue()
        with self.assertRaises(runtime.QueueError):
            runtime.codex_command(row, self.arguments(resume=True))

    def test_command_forces_bounded_sandbox_and_no_permission_bypass(self):
        row = self.enqueue()
        argv = runtime.codex_command(row, self.arguments())
        self.assertIn('approval_policy="never"', argv)
        self.assertIn("sandbox_workspace_write.network_access=false", argv)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)
        self.assertNotIn("--skip-git-repo-check", argv)
        self.assertEqual(argv[-1], "-")

    def test_invalid_profile_path_refused(self):
        row = self.enqueue()
        with self.assertRaises(runtime.QueueError):
            runtime.codex_command(row, self.arguments(profile="../other"))

    def test_configuration_fingerprint_does_not_read_auth(self):
        profile_root = self.root / "profiles"
        profile_root.mkdir()
        (profile_root / "vetted.config.toml").write_text('model="example"', encoding="utf-8")
        (profile_root / "auth.json").write_text("not-json-secret-placeholder", encoding="utf-8")
        with patch.dict(os.environ, {"CODEX_HOME": str(profile_root)}):
            hashes = runtime.configuration_fingerprint("vetted")
        self.assertIsNone(hashes[0])
        self.assertEqual(len(hashes[1]), 64)

    def test_timeout_stops_only_owned_process_and_marks_blocked(self):
        self.enqueue()
        process = Mock(pid=987654, returncode=None)
        process.poll.return_value = None
        with patch.object(runtime, "configuration_fingerprint", return_value=["base", "profile"]), \
                patch.object(runtime.subprocess, "Popen", return_value=process), \
                patch.object(runtime.time, "monotonic", side_effect=[0, 0, 2]), \
                patch.object(runtime, "stop_child") as stop:
            with self.assertRaises(runtime.QueueError):
                runtime.run_task(self.queue, "T01", self.arguments())
        stop.assert_called_once_with(process)
        self.assertEqual(self.queue.task("T01")["state"], "blocked")

    def test_keyboard_interrupt_persists_blocked_instead_of_retrying(self):
        self.enqueue()
        with patch.object(runtime, "configuration_fingerprint", return_value=["base", "profile"]), \
                patch.object(runtime.subprocess, "Popen", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                runtime.run_task(self.queue, "T01", self.arguments())
        self.assertEqual(self.queue.task("T01")["state"], "blocked")

    def test_unread_native_session_is_preserved_on_timeout(self):
        self.enqueue()
        process = Mock(pid=987654, returncode=None)
        process.poll.return_value = None

        def stop(process):
            log_dir = next((self.database.parent / "runs").iterdir())
            (log_dir / "events.jsonl").write_text(
                '{"type":"thread.started","thread_id":"test-interrupted-session"}\n', encoding="utf-8")

        with patch.object(runtime, "configuration_fingerprint", return_value=["base", "profile"]), \
                patch.object(runtime.subprocess, "Popen", return_value=process), \
                patch.object(runtime.time, "monotonic", side_effect=[0, 0, 2]), \
                patch.object(runtime, "stop_child", side_effect=stop):
            with self.assertRaises(runtime.QueueError):
                runtime.run_task(self.queue, "T01", self.arguments())
        self.assertEqual(self.queue.task("T01")["state"], "blocked")
        self.assertEqual(self.queue.task("T01")["session_id"], "test-interrupted-session")

    def test_watch_window_expired_before_claim_cannot_launch(self):
        self.enqueue()
        with patch.object(runtime.time, "monotonic", return_value=2), \
                patch.object(runtime.subprocess, "Popen") as popen:
            with self.assertRaises(runtime.BusyError):
                runtime.run_task(self.queue, "T01", self.arguments(launch_deadline=1))
        popen.assert_not_called()
        self.assertEqual(self.queue.task("T01")["state"], "queued")

    def test_watch_window_expired_during_preparation_cannot_launch(self):
        self.enqueue()
        with patch.object(runtime, "configuration_fingerprint", return_value=["base", "profile"]), \
                patch.object(runtime.time, "monotonic", side_effect=[0, 2]), \
                patch.object(runtime.subprocess, "Popen") as popen:
            with self.assertRaises(runtime.QueueError):
                runtime.run_task(self.queue, "T01", self.arguments(launch_deadline=1))
        popen.assert_not_called()
        self.assertEqual(self.queue.task("T01")["state"], "blocked")

    def test_group_cleanup_escalates_even_when_leader_already_exited(self):
        process = Mock(pid=987654)
        process.poll.return_value = 0
        with patch.object(runtime, "group_alive", side_effect=[True, False]), \
                patch.object(runtime.os, "killpg") as kill:
            runtime.stop_child(process, grace=0)
        self.assertEqual([call.args[1] for call in kill.call_args_list],
                         [runtime.signal.SIGTERM, runtime.signal.SIGKILL])

    def test_unconfirmed_group_never_releases_ownership(self):
        process = Mock(pid=987654)
        process.poll.return_value = 0
        with patch.object(runtime, "group_alive", return_value=True), patch.object(runtime.os, "killpg"):
            with self.assertRaises(runtime.QueueError):
                runtime.stop_child(process, grace=0)

    def test_cleanup_failure_keeps_task_active_and_audits_it(self):
        self.enqueue()
        process = Mock(pid=987654, returncode=0)
        process.poll.return_value = 0

        def launch(argv, **kwargs):
            kwargs["stdout"].write(self.events())
            kwargs["stdout"].flush()
            return process

        with patch.object(runtime, "configuration_fingerprint", return_value=["base", "profile"]), \
                patch.object(runtime.subprocess, "Popen", side_effect=launch), \
                patch.object(runtime, "stop_child", side_effect=runtime.QueueError("unconfirmed")):
            with self.assertRaises(runtime.QueueError):
                runtime.run_task(self.queue, "T01", self.arguments())
        self.assertEqual(self.queue.task("T01")["state"], "active")
        self.assertEqual(self.queue.history()[-1]["kind"], "stop-unconfirmed")

    def test_real_owned_process_group_termination(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        try:
            runtime.stop_child(process, grace=0.2)
            self.assertIsNotNone(process.poll())
            self.assertFalse(runtime.group_alive(process.pid))
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)

    def test_no_unsupported_events_count_as_completion(self):
        self.assertEqual(runtime.parse_events(["bad JSON", "[]", '{"type":"unrelated"}']), (None, False, ""))


if __name__ == "__main__":
    unittest.main()

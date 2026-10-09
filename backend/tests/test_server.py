import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from PIL import Image

from backend.app.server import AssetCache, SCHEMA, Settings, build_server
from backend.app.pipeline import PipelineFailure


def png():
    stream = io.BytesIO()
    Image.new("RGB", (12, 8), "green").save(stream, "PNG")
    return stream.getvalue()


def multipart(*, overrides=None, extra=None, content=None, mime="image/png", filename="hand.png", reference=None):
    reference = reference or {"id": "local-mock-reference", "version": "0"}
    fields = {"schema_version": SCHEMA, "request_id": "request-123", "exercise": "basic_grip", "handedness": "right", "reference_id": reference["id"], "reference_version": reference["version"]}
    fields.update(overrides or {})
    boundary = "test-coach-boundary"
    chunks = []
    for name, value in [*fields.items(), *(extra or [])]:
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    chunks.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode(), png() if content is None else content, f"\r\n--{boundary}--\r\n".encode()])
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.server = build_server(self.settings, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, *, body=None, headers=None, method=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method or ("POST" if body is not None else "GET"), path, body, headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def analyze(self, *, scenario=None, headers=None, **kwargs):
        body, mime = multipart(**kwargs)
        headers = {"Content-Type": mime, **(headers or {})}
        if scenario is not None:
            headers["X-Local-Coach-Scenario"] = scenario
        status, response_headers, content = self.request("/api/coach/analyze", body=body, headers=headers)
        return status, response_headers, json.loads(content)

    def test_config_and_real_upload_asset_roundtrip(self):
        status, headers, body = self.request("/api/coach/config")
        config = json.loads(body)
        self.assertEqual((status, config["schema_version"], config["mode"]), (200, SCHEMA, "mock"))
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, _, result = self.analyze(headers={"Origin": "http://127.0.0.1:5173"})
        self.assertEqual(status, 200)
        self.assertEqual((result["source"], result["outcome"], result["request_id"]), ("mock", "feedback", "request-123"))
        self.assertIsNone(result["retake"])
        self.assertIsNone(result["error"])
        url = result["feedback"]["image"]["url"]
        self.assertNotIn("hand.png", url)
        status, headers, content = self.request(url)
        self.assertEqual((status, headers["Content-Type"], headers["Cache-Control"]), (200, "image/png", "no-store"))
        with Image.open(io.BytesIO(content)) as image:
            self.assertEqual(image.size, (32, 24))

    def test_mock_retake_and_error_exclusive_payloads(self):
        for scenario in ("retake", "error"):
            status, _, value = self.analyze(scenario=scenario)
            self.assertEqual((status, value["outcome"]), (503 if scenario == "error" else 200, scenario))
            self.assertIsNotNone(value[scenario])
            for other in {"feedback", "retake", "error"} - {scenario}:
                self.assertIsNone(value[other])

    def test_bad_fields_duplicates_and_reference_echo_request_id(self):
        cases = [dict(extra=[("exercise", "basic_grip")]), dict(extra=[("unknown", "x")]), dict(overrides={"reference_id": "missing"}), dict(overrides={"schema_version": "other"}), dict(overrides={"handedness": "left"})]
        for case in cases:
            status, _, value = self.analyze(**case)
            self.assertEqual(status, 400)
            self.assertEqual(value["request_id"], "request-123")
            self.assertEqual(value["source"], "mock")
        for invalid in ("", "x" * 65, "한글", "contains space"):
            _, _, value = self.analyze(overrides={"request_id": invalid})
            self.assertIsNone(value["request_id"])

    def test_corrupt_wrong_format_and_too_large_images(self):
        self.assertEqual(self.analyze(content=b"\x89PNG\r\n\x1a\ncorrupt")[0], 400)
        self.assertEqual(self.analyze(mime="image/jpeg")[0], 415)
        self.assertEqual(self.analyze(content=b"x" * (5 * 1024 * 1024 + 1))[0], 413)
        gif = io.BytesIO()
        Image.new("RGB", (2, 2)).save(gif, "GIF")
        self.assertEqual(self.analyze(content=gif.getvalue())[0], 415)
        large = io.BytesIO()
        Image.new("RGB", (4001, 3000)).save(large, "PNG")
        status, _, value = self.analyze(content=large.getvalue())
        self.assertEqual((status, value["error"]["code"]), (413, "image_too_large"))
        self.assertIn("1200만", value["error"]["message"])

    def test_body_limit_and_malformed_multipart(self):
        status, _, body = self.request("/api/coach/analyze", body=b"", headers={"Content-Length": str(6 * 1024 * 1024 + 1), "Content-Type": "multipart/form-data; boundary=x"})
        self.assertEqual((status, json.loads(body)["error"]["code"]), (413, "body_too_large"))
        status, _, _ = self.request("/api/coach/analyze", body=b"not multipart", headers={"Content-Type": "multipart/form-data; boundary=x"})
        self.assertEqual(status, 400)

    def test_foreign_origin_and_non_loopback_host_rejected_on_get_and_post(self):
        for path in ("/api/coach/config", "/api/coach/assets/missing.png"):
            self.assertEqual(self.request(path, headers={"Origin": "http://foreign.invalid"})[0], 403)
        self.assertEqual(self.analyze(headers={"Origin": "null"})[0], 403)
        self.assertEqual(self.request("/api/coach/config", headers={"Host": f"foreign.invalid:{self.server.server_port}"})[0], 403)
        status, headers, _ = self.request("/api/coach/config", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(status, 200)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_busy_and_missing_asset(self):
        self.settings.gate.acquire()
        try:
            status, _, value = self.analyze()
        finally:
            self.settings.gate.release()
        self.assertEqual((status, value["error"]["code"], value["request_id"]), (503, "busy", "request-123"))
        self.assertEqual(self.request("/api/coach/assets/" + "a" * 32 + ".png")[0], 404)

    def poll_job_until_complete(self, url):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status, _, body = self.request(url)
            value = json.loads(body)
            if status != 202:
                return status, value
            time.sleep(.01)
        self.fail("async worker did not complete")

    def test_async_accepts_pending_then_feedback_and_rejects_busy_upload(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        class Runner:
            reference = {"id": "async-reference", "version": "1"}
            def run(self, content, *, timeout=None):
                entered.set()
                if not release.wait(2):
                    raise PipelineFailure('timeout')
                return {"source": "analysis", "outcome": "feedback", "feedback": {
                    "status": "assessable", "comment": "안내", "corrections": [],
                    "image": {"mime_type": "image/png", "width": 12, "height": 8}}}, png()
        self.settings.mode, self.settings.runner = 'analysis', Runner()
        status, _, value = self.analyze(reference=self.settings.reference, headers={'X-Coach-Async':'1'})
        self.assertEqual((status, value['status'], value['request_id']), (202, 'pending', 'request-123'))
        self.assertRegex(value['job_url'], r'^/api/coach/jobs/[A-Za-z0-9_-]{32}$')
        self.assertTrue(entered.wait(1))
        status, _, body = self.request(value['job_url'])
        self.assertEqual((status, json.loads(body)['status']), (202, 'pending'))
        busy, _, result = self.analyze(reference=self.settings.reference, headers={'X-Coach-Async':'1'})
        self.assertEqual((busy, result['error']['code']), (503, 'busy'))
        release.set()
        status, result = self.poll_job_until_complete(value['job_url'])
        self.assertEqual((status, result['outcome'], result['request_id']), (200, 'feedback', 'request-123'))
        self.assertIsNone(result['error'])
        self.assertEqual(self.request(result['feedback']['image']['url'])[0], 200)
        self.assertTrue(self.settings.gate.acquire(blocking=False))
        self.settings.gate.release()

    def test_async_worker_failure_is_safe_and_releases_gate(self):
        class Runner:
            reference = {"id": "async-reference", "version": "1"}
            def run(self, content, *, timeout=None):
                raise RuntimeError('secret original provider body')
        self.settings.mode, self.settings.runner = 'analysis', Runner()
        status, _, accepted = self.analyze(reference=self.settings.reference, headers={'X-Coach-Async':'1'})
        self.assertEqual(status, 202)
        status, result = self.poll_job_until_complete(accepted['job_url'])
        self.assertEqual((status, result['outcome'], result['error']['code']), (502, 'error', 'pipeline_failed'))
        self.assertIsNone(result['feedback'])
        self.assertIsNone(result['retake'])
        self.assertNotIn('secret original', json.dumps(result))
        self.assertTrue(self.settings.gate.acquire(blocking=False))
        self.settings.gate.release()

    def test_cache_ttl_and_bounded_eviction(self):
        now = [100.0]
        cache = AssetCache(ttl=10, capacity=2, clock=lambda: now[0])
        urls = [cache.put(str(index).encode()) for index in range(3)]
        tokens = [url.split("/")[-1][:-4] for url in urls]
        self.assertIsNone(cache.get(tokens[0]))
        self.assertEqual(cache.get(tokens[2]), b"2")
        now[0] += 10
        self.assertIsNone(cache.get(tokens[2]))


    def test_analysis_header_rejected_and_preparation_source_preserved(self):
        class Runner:
            reference = {"id": "analysis-reference", "version": "1"}
            def __init__(self):
                self.called = 0
            def run(self, content, *, timeout=None):
                self.called += 1
                assert content == png()
                assert 0 < timeout <= 180
                return {"source": "preparation", "outcome": "retake", "retake": {"reason": "no_hand_detected", "message": "다시 촬영하세요."}}, None
        runner = Runner()
        self.settings.mode, self.settings.runner = "analysis", runner
        status, _, value = self.analyze(reference=runner.reference, scenario="feedback")
        self.assertEqual((status, value["source"], runner.called), (400, "analysis", 0))
        status, _, value = self.analyze(reference=runner.reference)
        self.assertEqual((status, value["source"], value["outcome"], runner.called), (200, "preparation", "retake", 1))
        status, _, value = self.analyze()
        self.assertEqual((status, value["source"], runner.called), (400, "analysis", 1))

    def test_cache_byte_budget_evicts_before_ttl_and_expiry_releases_bytes(self):
        now = [0]
        cache = AssetCache(ttl=10, capacity=16, max_bytes=5, clock=lambda: now[0])
        first = cache.put(b"abc").split("/")[-1][:-4]
        second = cache.put(b"def").split("/")[-1][:-4]
        self.assertIsNone(cache.get(first))
        self.assertEqual(cache.get(second), b"def")
        self.assertEqual(cache.bytes, 3)
        with self.assertRaises(ValueError):
            cache.put(b"123456")
        now[0] = 11
        self.assertIsNone(cache.get(second))
        self.assertEqual(cache.bytes, 0)

    def test_finite_positive_time_and_cache_settings(self):
        for value in (0, -1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                Settings(deadline_seconds=value)
            with self.assertRaises(ValueError):
                Settings(asset_ttl_seconds=value)
            with self.assertRaises(ValueError):
                AssetCache(ttl=value)

    def test_partial_upload_has_whole_request_deadline(self):
        self.settings.deadline_seconds = 0.1
        body, mime = multipart()
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        connection.putrequest("POST", "/api/coach/analyze")
        connection.putheader("Content-Length", str(len(body)))
        connection.putheader("Content-Type", mime)
        connection.endheaders()
        connection.send(body[:10])
        started = time.monotonic()
        response = connection.getresponse()
        value = json.loads(response.read())
        connection.close()
        self.assertEqual((response.status, value["error"]["code"]), (408, "request_timeout"))
        self.assertLess(time.monotonic() - started, 1)

    def test_normal_shutdown_waits_for_active_handler_cleanup(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        class Runner:
            reference = {"id": "shutdown-reference", "version": "1"}
            def run(self, content, *, timeout=None):
                started.set()
                release.wait(timeout=1)
                finished.set()
                return {"source": "preparation", "outcome": "retake", "retake": {"reason": "no_hand_detected", "message": "다시 촬영하세요."}}, None
        self.settings.mode, self.settings.runner = "analysis", Runner()
        client = threading.Thread(target=lambda: self.analyze(reference=self.settings.reference))
        client.start()
        self.assertTrue(started.wait(timeout=1))
        closing = threading.Thread(target=self.server.server_close)
        closing.start()
        time.sleep(0.03)
        self.assertTrue(closing.is_alive())
        release.set()
        closing.join(timeout=2)
        client.join(timeout=2)
        self.assertTrue(finished.is_set())
        self.assertFalse(closing.is_alive())


if __name__ == "__main__":
    unittest.main()

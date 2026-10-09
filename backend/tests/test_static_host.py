import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from backend.app.server import Settings, build_server
from backend.tests.test_server import multipart


class StaticHostTests(unittest.TestCase):
    def setUp(self):
        self.private = tempfile.TemporaryDirectory()
        self.root = Path(self.private.name)
        self.build = self.root / "dist"
        self.build.mkdir()
        (self.build / "assets").mkdir()
        (self.build / "fonts").mkdir()
        (self.build / "index.html").write_text('<!doctype html><script src="/assets/main.js"></script>')
        (self.build / "assets/main.js").write_text("console.log('build output')")
        (self.build / "assets/main.css").write_text("body{color:green}")
        (self.build / "fonts/local.woff2").write_bytes(b"test-font")
        (self.root / "private-canary.txt").write_text("PRIVATE-CANARY-DO-NOT-SERVE")
        for relative in ("assets/leak.json", "assets/main.js.map", "assets/.secret.png", "backend.py", "assets/private.html"):
            (self.build / relative).write_text("PRIVATE-CANARY-DO-NOT-SERVE")
        (self.build / "assets/external.png").symlink_to(self.root / "private-canary.txt")
        (self.build / "assets/internal.js").symlink_to(self.build / "assets/main.js")
        (self.build / "assets/directory").symlink_to(self.root, target_is_directory=True)
        self.server = build_server(Settings(frontend_dir=self.build), port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.private.cleanup()

    def request(self, target, *, headers=None, body=None, method=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method or ("POST" if body is not None else "GET"), target, body, headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def assert_security_headers(self, headers):
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        csp = headers["Content-Security-Policy"]
        for directive in ("script-src 'self'", "style-src 'self'", "connect-src 'self'", "font-src 'self'", "frame-ancestors 'none'", "object-src 'none'", "base-uri 'none'", "form-action 'none'", "worker-src 'none'"):
            self.assertIn(directive, csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)

    def test_built_index_assets_fonts_fixed_mime_and_security_headers(self):
        for target, mime in (("/", "text/html; charset=utf-8"), ("/index.html", "text/html; charset=utf-8"), ("/assets/main.js", "text/javascript; charset=utf-8"), ("/assets/main.css?v=1", "text/css; charset=utf-8"), ("/fonts/local.woff2", "font/woff2")):
            status, headers, body = self.request(target)
            self.assertEqual(status, 200, target)
            self.assertEqual(headers["Content-Type"], mime)
            self.assertTrue(body)
            self.assert_security_headers(headers)

    def test_private_unknown_files_directory_listing_traversal_and_links_rejected(self):
        paths = ["/etc/secrets", "/backend.py", "/src/main.ts", "/assets/", "/fonts/", "/assets/leak.json", "/assets/main.js.map", "/assets/private.html", "/assets/.secret.png", "/assets/external.png", "/assets/internal.js", "/assets/directory/private-canary.txt", "/../private-canary.txt", "/assets/../../private-canary.txt", "/assets/%2e%2e/%2e%2e/private-canary.txt", "/assets/%2f..%2fprivate-canary.txt", "/assets/%5cprivate-canary.txt", "/assets/%252e%252e/private-canary.txt", "/assets/main.js%00", "/assets/%GG/main.js", "/assets/../index.html"]
        for target in paths:
            status, headers, body = self.request(target)
            self.assertEqual(status, 404, target)
            self.assertNotIn(b"PRIVATE-CANARY", body)
            self.assert_security_headers(headers)

        for target in ("http://foreign.invalid/assets/main.js", "//assets/main.js"):
            status, headers, body = self.request(target, headers={"Host": f"127.0.0.1:{self.server.server_port}"})
            self.assertEqual(status, 403)
            self.assertNotIn(b"build output", body)
            self.assert_security_headers(headers)

    def test_origin_fetch_site_and_host_checks_cover_static_and_api(self):
        for target in ("/", "/assets/main.js", "/api/coach/config"):
            for headers in ({"Origin": "http://foreign.invalid"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}, {"Host": f"foreign.invalid:{self.server.server_port}"}):
                status, response_headers, body = self.request(target, headers=headers)
                self.assertEqual(status, 403)
                self.assertNotIn(b"build output", body)
                self.assert_security_headers(response_headers)
        origin = f"http://127.0.0.1:{self.server.server_port}"
        self.assertEqual(self.request("/", headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"})[0], 200)

    def test_duplicate_host_and_origin_are_rejected(self):
        for duplicate in ("Host", "Origin", "Sec-Fetch-Site"):
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
            connection.putrequest("GET", "/", skip_host=duplicate == "Host")
            value = f"127.0.0.1:{self.server.server_port}" if duplicate == "Host" else f"http://127.0.0.1:{self.server.server_port}" if duplicate == "Origin" else "same-origin"
            connection.putheader(duplicate, value)
            connection.putheader(duplicate, value)
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.close()

    def test_api_mock_upload_config_and_asset_work_with_static_host(self):
        status, headers, content = self.request("/api/coach/config")
        self.assertEqual((status, json.loads(content)["mode"]), (200, "mock"))
        self.assert_security_headers(headers)
        body, mime = multipart()
        origin = f"http://127.0.0.1:{self.server.server_port}"
        status, headers, content = self.request("/api/coach/analyze", body=body, headers={"Content-Type": mime, "Origin": origin})
        result = json.loads(content)
        self.assertEqual((status, result["source"], result["outcome"]), (200, "mock", "feedback"))
        self.assert_security_headers(headers)
        status, headers, content = self.request(result["feedback"]["image"]["url"])
        self.assertEqual(status, 200)
        self.assertTrue(content.startswith(b"\x89PNG"))
        self.assert_security_headers(headers)
        status, headers, _ = self.request("/api/coach/analyze", body=body, headers={"Content-Type": mime, "Origin": "http://foreign.invalid"})
        self.assertEqual(status, 403)
        self.assert_security_headers(headers)

    def test_missing_index_symlink_index_and_root_are_invalid_startup(self):
        no_index = self.root / "empty"
        no_index.mkdir()
        with self.assertRaises(ValueError):
            Settings(frontend_dir=no_index)
        (no_index / "index.html").symlink_to(self.build / "index.html")
        with self.assertRaises(ValueError):
            Settings(frontend_dir=no_index)
        link = self.root / "build-link"
        link.symlink_to(self.build, target_is_directory=True)
        with self.assertRaises(ValueError):
            Settings(frontend_dir=link)

    def test_protocol_error_has_security_headers(self):
        status, headers, _ = self.request("/", method="OPTIONS")
        self.assertEqual(status, 501)
        self.assert_security_headers(headers)


if __name__ == "__main__":
    unittest.main()

"""Provisional same-origin localhost API; mock mode never invokes analysis."""
import argparse
from collections import OrderedDict
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
from pathlib import Path
import re
import secrets
import socket
import sys
import threading
import time
from urllib.parse import urlsplit

from PIL import Image

from .pipeline import PipelineFailure, PipelineRunner
from .static import StaticFrontend


SCHEMA = "local-coach-v1"
MAX_BODY = 6 * 1024 * 1024
MAX_IMAGE = 5 * 1024 * 1024
MAX_PIXELS = 12_000_000
FIELDS = {"schema_version", "request_id", "exercise", "handedness", "reference_id", "reference_version"}
REQUEST_ID = re.compile(r"[\x21-\x7e]{1,64}\Z")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; "
       "img-src 'self' blob: data:; font-src 'self'; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'; worker-src 'none'")
ERROR_MESSAGES = {
    "image_too_large": "5 MiB 및 1200만 픽셀 이하의 사진을 선택해 주세요.",
    "body_too_large": "업로드 요청은 6 MiB 이하여야 합니다. 더 작은 사진을 선택해 주세요.",
    "unsupported_image": "정상적인 JPEG 또는 PNG 사진을 선택해 주세요.",
    "invalid_image": "사진을 열 수 없습니다. 정상적인 JPEG 또는 PNG 사진을 다시 선택해 주세요.",
    "busy": "다른 분석이 진행 중입니다. 작업이 끝난 뒤 다시 시도해 주세요.",
    "timeout": "대기 시간이 초과되었습니다. 잠시 뒤 다시 시도해 주세요.",
    "request_timeout": "업로드 대기 시간이 초과되었습니다. 다시 시도해 주세요.",
    "reference_mismatch": "기준 설정이 일치하지 않습니다. 기준 설정을 다시 조회한 뒤 재시도해 주세요.",
}


class InputFailure(Exception):
    def __init__(self, code="invalid_request", status=400, request_id=None):
        super().__init__(code)
        self.code, self.status, self.request_id = code, status, request_id


def valid_request_id(value):
    return isinstance(value, str) and REQUEST_ID.fullmatch(value) is not None


def parse_multipart(content_type, body):
    if not content_type or "\r" in content_type or "\n" in content_type:
        raise InputFailure()
    try:
        message = BytesParser(policy=policy.default).parsebytes(b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
        if message.get_content_type() != "multipart/form-data" or not message.get_boundary() or not message.is_multipart() or message.defects:
            raise InputFailure()
        parts = list(message.iter_parts())
        values = {}
        files = []
        malformed = False
        for part in parts:
            name = part.get_param("name", header="content-disposition")
            if part.defects or part.is_multipart() or part.get_content_disposition() != "form-data" or not isinstance(name, str) or part.get("Content-Transfer-Encoding"):
                malformed = True
                continue
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                malformed = True
                continue
            if name == "image":
                files.append((part.get_filename(), part.get_content_type(), payload))
            else:
                try:
                    value = payload.decode("utf-8")
                except UnicodeDecodeError:
                    malformed = True
                    continue
                values.setdefault(name, []).append(value)
                if part.get_filename() is not None:
                    malformed = True
        ids = values.get("request_id", [])
        request_id = ids[0] if len(ids) == 1 and valid_request_id(ids[0]) else None
        if malformed or len(parts) != 7 or set(values) != FIELDS or any(len(items) != 1 for items in values.values()) or len(files) != 1 or not files[0][0]:
            raise InputFailure(request_id=request_id)
        return {name: items[0] for name, items in values.items()}, files[0][1], files[0][2]
    except InputFailure:
        raise
    except Exception as exc:
        raise InputFailure() from exc


def validate_image(content, mime_type):
    if len(content) > MAX_IMAGE:
        raise InputFailure("image_too_large", 413)
    png = content.startswith(b"\x89PNG\r\n\x1a\n")
    jpeg = content.startswith(b"\xff\xd8\xff")
    expected = "PNG" if png else "JPEG" if jpeg else None
    if expected is None or mime_type != ("image/png" if png else "image/jpeg"):
        raise InputFailure("unsupported_image", 415)
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format != expected:
                raise InputFailure("unsupported_image", 415)
            if image.width * image.height > MAX_PIXELS:
                raise InputFailure("image_too_large", 413)
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
    except InputFailure:
        raise
    except Exception as exc:
        raise InputFailure("invalid_image") from exc


class AssetCache:
    def __init__(self, ttl=600, capacity=16, max_bytes=64 * 1024 * 1024, clock=time.monotonic):
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl <= 0 or type(capacity) is not int or capacity <= 0 or type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("invalid_cache_options")
        self.ttl, self.capacity, self.max_bytes, self.clock = ttl, capacity, max_bytes, clock
        self.bytes = 0
        self.items = OrderedDict()
        self.lock = threading.Lock()

    def _expire(self):
        now = self.clock()
        for token, (expiry, content) in list(self.items.items()):
            if expiry <= now:
                self.bytes -= len(content)
                del self.items[token]

    def put(self, content):
        if len(content) > self.max_bytes:
            raise ValueError("asset_exceeds_cache_budget")
        with self.lock:
            self._expire()
            token = secrets.token_urlsafe(24)
            self.items[token] = (self.clock() + self.ttl, content)
            self.bytes += len(content)
            while len(self.items) > self.capacity or self.bytes > self.max_bytes:
                _, (_, evicted) = self.items.popitem(last=False)
                self.bytes -= len(evicted)
            return "/api/coach/assets/" + token + ".png"

    def get(self, token):
        with self.lock:
            self._expire()
            entry = self.items.get(token)
            return entry[1] if entry else None


@dataclass
class Settings:
    mode: str = "mock"
    runner: PipelineRunner | None = None
    deadline_seconds: float = 180
    asset_ttl_seconds: int = 600
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")
    cache: AssetCache | None = None
    gate: threading.Lock = field(default_factory=threading.Lock)
    frontend_dir: Path | None = None
    static_frontend: StaticFrontend | None = field(default=None, init=False, repr=False)

    def __post_init__(self):
        for value in (self.deadline_seconds, self.asset_ttl_seconds):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("invalid_time_budget")
        if self.mode not in ("mock", "analysis") or (self.mode == "analysis" and self.runner is None):
            raise ValueError("invalid_mode")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1") or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
                raise ValueError("invalid_origin")
        if self.cache is None:
            self.cache = AssetCache(self.asset_ttl_seconds)
        if self.frontend_dir is not None:
            self.static_frontend = StaticFrontend(self.frontend_dir)

    @property
    def reference(self):
        return self.runner.reference if self.mode == "analysis" else {"id": "local-mock-reference", "version": "0"}

    def config(self):
        return {"schema_version": SCHEMA, "mode": self.mode, "exercise": "basic_grip", "handedness": "right", "reference": self.reference, "deadline_seconds": self.deadline_seconds, "asset_ttl_seconds": self.asset_ttl_seconds}

    def envelope(self, request_id=None):
        return {"schema_version": SCHEMA, "request_id": request_id, "exercise": "basic_grip", "handedness": "right", "reference": self.reference, "source": self.mode, "outcome": "error", "feedback": None, "retake": None, "error": None}


def mock_result(scenario):
    if scenario == "retake":
        return {"source": "mock", "outcome": "retake", "retake": {"reason": "mock_retake", "message": "재촬영 안내의 모의 예시입니다. 실제 사진 품질을 판단하지 않았습니다."}}, None
    if scenario == "error":
        return {"source": "mock", "outcome": "error", "error": {"code": "mock_service_error", "message": "서비스 오류의 모의 예시입니다. 실제 분석은 수행하지 않았습니다."}}, None
    image = Image.new("RGB", (32, 24), "#c9d9bd")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return {"source": "mock", "outcome": "feedback", "feedback": {"status": "assessable", "comment": "HTTP 연결 검증용 모의 응답입니다. 선택한 사진을 분석하지 않았습니다.", "corrections": [{"joint_name": "예시 관절", "instruction": "관절별 안내의 표시를 확인하기 위한 모의 문구입니다."}], "image": {"mime_type": "image/png", "width": 32, "height": 24}}}, output.getvalue()


def build_server(settings=None, *, port=8000):
    settings = settings or Settings()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            # No request paths, uploaded filenames, or provider logs on console.
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            super().end_headers()

        def send_content(self, status, content, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                pass

        def send_json(self, status, value):
            self.send_content(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def fail(self, code, status=400, request_id=None):
            value = settings.envelope(request_id)
            value["error"] = {"code": code, "message": ERROR_MESSAGES.get(code, "요청을 처리하지 못했습니다. 입력과 로컬 서버 설정을 확인하고 다시 시도해 주세요.")}
            self.send_json(status, value)

        def origin_allowed(self):
            # BaseHTTPRequestHandler normalizes leading // in self.path; inspect
            # the original target so absolute/network-path forms remain blocked.
            request_parts = self.requestline.split()
            if len(request_parts) < 2 or not request_parts[1].startswith("/") or request_parts[1].startswith("//"):
                return False
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            raw_hosts = self.headers.get_all("Host", [])
            if len(raw_hosts) != 1 or raw_hosts[0] not in hosts:
                return False
            origins = self.headers.get_all("Origin", [])
            fetch_sites = self.headers.get_all("Sec-Fetch-Site", [])
            if fetch_sites and (len(fetch_sites) != 1 or fetch_sites[0] not in ("same-origin", "same-site", "none")):
                return False
            return not origins or (len(origins) == 1 and origins[0] in {"http://" + raw_hosts[0], *settings.allowed_origins})

        def do_GET(self):
            if not self.origin_allowed():
                self.fail("origin_not_allowed", 403)
                return
            if self.path == "/api/coach/config":
                self.send_json(200, settings.config())
                return
            match = re.fullmatch(r"/api/coach/assets/([A-Za-z0-9_-]{32})\.png", self.path)
            content = settings.cache.get(match[1]) if match else None
            if match is None and settings.static_frontend is not None:
                static = settings.static_frontend.get(self.path)
                if static is not None:
                    self.send_content(200, *static)
                    return
            if content is None:
                self.fail("asset_not_found", 404)
                return
            self.send_content(200, content, "image/png")

        def do_POST(self):
            started = time.monotonic()
            request_id = None
            if not self.origin_allowed():
                self.fail("origin_not_allowed", 403)
                return
            if self.path != "/api/coach/analyze":
                self.fail("not_found", 404)
                return
            try:
                lengths = self.headers.get_all("Content-Length", [])
                if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0]):
                    raise InputFailure("invalid_content_length", 411 if not lengths else 400)
                length = int(lengths[0])
                if length > MAX_BODY:
                    raise InputFailure("body_too_large", 413)
                chunks = []
                received = 0
                while received < length:
                    remaining = settings.deadline_seconds - (time.monotonic() - started)
                    if remaining <= 0:
                        raise InputFailure("request_timeout", 408)
                    self.connection.settimeout(min(10, remaining))
                    chunk = self.rfile.read1(min(65536, length - received))
                    if not chunk:
                        raise InputFailure()
                    chunks.append(chunk)
                    received += len(chunk)
                self.connection.settimeout(10)
                body = b"".join(chunks)
                if len(body) != length:
                    raise InputFailure()
                fields, mime, content = parse_multipart(self.headers.get("Content-Type"), body)
                request_id = fields["request_id"] if valid_request_id(fields["request_id"]) else None
                if request_id is None or fields["schema_version"] != SCHEMA or fields["exercise"] != "basic_grip" or fields["handedness"] != "right":
                    raise InputFailure()
                if (fields["reference_id"], fields["reference_version"]) != (settings.reference["id"], settings.reference["version"]):
                    raise InputFailure("reference_mismatch")
                validate_image(content, mime)
                scenario_headers = self.headers.get_all("X-Local-Coach-Scenario", [])
                if settings.mode == "analysis" and scenario_headers:
                    raise InputFailure("test_header_not_allowed")
                scenario = scenario_headers[0] if scenario_headers else "feedback"
                if len(scenario_headers) > 1 or scenario not in ("feedback", "retake", "error"):
                    raise InputFailure("invalid_scenario")
                if not settings.gate.acquire(blocking=False):
                    self.fail("busy", 503, request_id)
                    return
                try:
                    if settings.mode == "mock":
                        result, image = mock_result(scenario)
                    else:
                        result, image = settings.runner.run(content, timeout=settings.deadline_seconds - (time.monotonic() - started))
                    value = settings.envelope(request_id)
                    value.update(result)
                    if image is not None:
                        value["feedback"]["image"]["url"] = settings.cache.put(image)
                    self.send_json(503 if value["outcome"] == "error" else 200, value)
                finally:
                    settings.gate.release()
            except InputFailure as exc:
                self.fail(exc.code, exc.status, exc.request_id or request_id)
            except PipelineFailure as exc:
                self.fail(exc.code, 504 if exc.code == "timeout" else 502, request_id)
            except (socket.timeout, TimeoutError):
                self.fail("request_timeout", 408, request_id)
            except Exception:
                self.fail("pipeline_failed", 502, request_id)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    # Normal shutdown waits for active bounded requests and their private cleanup.
    server.daemon_threads = False
    server.settings = settings
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mock", "analysis"), default="mock")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--landmarker-model", type=Path)
    parser.add_argument("--pipeline-python", default=sys.executable)
    parser.add_argument("--allowed-origin", action="append", default=[])
    parser.add_argument("--frontend-dir", type=Path, help="빌드된 frontend 디렉터리만 같은 origin에서 제공")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port는 1~65535여야 합니다.")
    if args.mode == "analysis" and (args.catalog is None or args.landmarker_model is None):
        parser.error("analysis 모드에는 catalog와 landmarker-model이 필요합니다.")
    try:
        runner = PipelineRunner(args.catalog, args.landmarker_model, python=args.pipeline_python) if args.mode == "analysis" else None
        origins = ("http://127.0.0.1:5173", "http://localhost:5173", *args.allowed_origin)
        settings = Settings(args.mode, runner, allowed_origins=origins, frontend_dir=args.frontend_dir)
        server = build_server(settings, port=args.port)
    except Exception:
        parser.exit(2, "로컬 서버 설정을 확인하세요. 분석 모드의 기준·모델·인터프리터와 지정한 frontend의 index.html이 필요합니다.\n")
    print(f"Local coach API: http://127.0.0.1:{args.port} (mode={args.mode}; provisional contract)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

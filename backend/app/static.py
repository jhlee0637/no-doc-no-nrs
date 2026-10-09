"""Narrow build-output reader for the optional localhost frontend host."""
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit


MIME_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}
PRIVATE_SEGMENTS = {"etc", "backend", "src", "node_modules", "contracts", "docs", "scripts", "skills"}


class StaticFrontend:
    def __init__(self, directory):
        requested = Path(directory).absolute()
        if requested.is_symlink() or not requested.is_dir():
            raise ValueError("invalid_frontend_directory")
        self.root = requested.resolve(strict=True)
        if self._read(("index.html",)) is None:
            raise ValueError("frontend_index_required")

    def _read(self, parts):
        # Directory-relative opens avoid following a symlink inserted between
        # validation and reading. The build directory itself is trusted input.
        descriptor = None
        file_descriptor = None
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            descriptor = os.open(self.root, flags)
            for part in parts[:-1]:
                following = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = following
            file_descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
                return None
            with os.fdopen(file_descriptor, "rb") as stream:
                file_descriptor = None
                return stream.read()
        except (OSError, ValueError):
            return None
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
            if descriptor is not None:
                os.close(descriptor)

    def get(self, target):
        try:
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or parsed.fragment or not target.startswith("/") or target.startswith("//"):
                return None
            raw_path = parsed.path
            if re.search(r"%(?:2f|5c)", raw_path, re.IGNORECASE):
                return None
            path = unquote(raw_path, encoding="utf-8", errors="strict")
        except (UnicodeError, ValueError):
            return None
        if any(character in path for character in ("\\", "\x00", "%")) or any(ord(character) < 32 or ord(character) == 127 for character in path):
            return None
        if path in ("/", "/index.html"):
            parts = ("index.html",)
            mime = "text/html; charset=utf-8"
        else:
            parts = tuple(path[1:].split("/"))
            if len(parts) < 2 or parts[0] not in ("assets", "fonts") or any(not part or part.startswith(".") or part.lower() in PRIVATE_SEGMENTS for part in parts):
                return None
            mime = MIME_TYPES.get(Path(parts[-1]).suffix.lower())
            if mime is None:
                return None
        content = self._read(parts)
        return (content, mime) if content is not None else None

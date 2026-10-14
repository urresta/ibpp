"""Thin client for the ibdocs.re file API.

The site is an AList/OpenList file server, so instead of scraping HTML we use
its JSON API: POST /api/fs/list to browse folders and GET /p/<path> to
download a file. Folder listings are cached on disk because past sessions
practically never change.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from . import __version__

BASE_URL = "https://ibdocs.re"
USER_AGENT = f"ibpp/{__version__} (IB past paper fetcher)"


class ApiError(RuntimeError):
    pass


class Client:
    def __init__(self, cache_dir: Path, *, refresh: bool = False,
                 ttl: float = 3 * 24 * 3600, timeout: float = 30):
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.ttl = ttl
        self.timeout = timeout

    def list_dir(self, path: str) -> list[dict]:
        """Return the entries of a folder: dicts with name, size and is_dir."""
        cache_file = self.cache_dir / (hashlib.sha1(path.encode()).hexdigest() + ".json")
        if not self.refresh:
            try:
                if time.time() - cache_file.stat().st_mtime < self.ttl:
                    return json.loads(cache_file.read_text("utf-8"))
            except (OSError, ValueError):
                pass

        body = json.dumps({"path": path, "page": 1, "per_page": 0, "refresh": False}).encode()
        request = urllib.request.Request(
            BASE_URL + "/api/fs/list", data=body, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
        payload = self._request_json(request)
        if payload.get("code") != 200:
            raise ApiError(f"{path}: {payload.get('message') or 'unexpected response'}")
        entries = (payload.get("data") or {}).get("content") or []

        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(entries), "utf-8")
            os.replace(tmp, cache_file)
        except OSError:
            pass
        return entries

    def download(self, path: str, dest: Path,
                 progress: Callable[[int, int], None] | None = None) -> Path:
        """Download the file at `path` on the server to `dest`."""
        request = urllib.request.Request(BASE_URL + "/p" + quote(path),
                                         headers={"User-Agent": USER_AGENT})
        tmp = dest.with_name(dest.name + ".part")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response, open(tmp, "wb") as out:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                while chunk := response.read(64 * 1024):
                    out.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            os.replace(tmp, dest)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            tmp.unlink(missing_ok=True)
            raise ApiError(f"download failed for {dest.name}: {exc}") from exc
        return dest

    def _request_json(self, request: urllib.request.Request) -> dict:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    raise ApiError(f"ibdocs.re answered HTTP {exc.code}") from exc
                last_error = exc
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = exc
            time.sleep(1 + attempt)
        raise ApiError(f"could not reach {BASE_URL} ({last_error})")

"""Config, cache and history locations, following each OS's conventions."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP = "ibpp"


def _dir(kind: str) -> Path:
    home = Path.home()
    if os.name == "nt":
        roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return {"config": roaming / APP, "data": roaming / APP, "cache": local / APP / "cache"}[kind]
    if sys.platform == "darwin":
        support = home / "Library" / "Application Support" / APP
        return {"config": support, "data": support, "cache": home / "Library" / "Caches" / APP}[kind]
    env, fallback = {"config": ("XDG_CONFIG_HOME", ".config"), "data": ("XDG_DATA_HOME", ".local/share"),
                     "cache": ("XDG_CACHE_HOME", ".cache")}[kind]
    return Path(os.environ.get(env) or home / fallback) / APP


def config_dir() -> Path:
    return _dir("config")


def cache_dir() -> Path:
    return _dir("cache")


def data_dir() -> Path:
    return _dir("data")


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
    os.replace(tmp, path)


@dataclass
class SubjectChoice:
    key: str
    level: str = "HL"
    legacy: bool = False  # also include the previous syllabus' papers


@dataclass
class Config:
    subjects: list[SubjectChoice] = field(default_factory=list)
    lang: str = "en"
    download_dir: str = ""
    viewer: str = ""  # command to open PDFs with; empty = system default

    @staticmethod
    def path() -> Path:
        return config_dir() / "config.json"

    @property
    def download_path(self) -> Path:
        return Path(self.download_dir).expanduser() if self.download_dir else Path.home() / "IB Past Papers"

    @classmethod
    def load(cls) -> Config:
        try:
            raw = json.loads(cls.path().read_text("utf-8"))
        except (OSError, ValueError):
            return cls()
        subjects = [SubjectChoice(**s) for s in raw.get("subjects", [])]
        return cls(subjects=subjects, lang=raw.get("lang", "en"),
                   download_dir=raw.get("download_dir", ""), viewer=raw.get("viewer", ""))

    def save(self) -> None:
        _write_json(self.path(), asdict(self))


class History:
    """Papers you've opened, so random picks can favour ones you haven't done."""

    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "history.json"
        try:
            self.entries: list[dict] = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self.entries = []
        self._seen = {e["path"] for e in self.entries}

    def seen(self, server_path: str) -> bool:
        return server_path in self._seen

    def add(self, server_path: str, subject: str, description: str) -> None:
        self.entries.append({"path": server_path, "subject": subject, "paper": description,
                             "opened": time.strftime("%Y-%m-%d %H:%M")})
        self._seen.add(server_path)
        self._save()

    def clear(self) -> None:
        self.entries, self._seen = [], set()
        self._save()

    def _save(self) -> None:
        try:
            _write_json(self.path, self.entries)
        except OSError:
            pass

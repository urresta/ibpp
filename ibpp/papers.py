"""Finding past papers and their markschemes in the ibdocs.re folder tree.

Layout on the server:

    /IB PAST PAPERS - YEAR/2024 Examination Session/May 2024 Examination Session/
        Mathematics/Mathematics_analysis_and_approaches_paper_1__TZ1_HL.pdf

Group folders are named "Group 5 - Mathematics" up to ~2018 and just
"Mathematics" afterwards, and filenames drift between single and double
underscores, so names are parsed token by token rather than matched exactly.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

from .api import Client
from .catalog import Subject

ROOT = "/IB PAST PAPERS - YEAR"
MONTHS = {"may": 5, "november": 11}
MONTH_NAMES = {5: "May", 11: "November"}
LANGUAGES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German"}

_LANG_TOKENS = {"spanish": "es", "french": "fr", "german": "de", "[german]": "de"}
_GROUP_KEYWORDS = {
    1: ("language and literature",),
    2: ("language acquisition",),
    3: ("individuals",),
    4: ("science",),
    5: ("math",),
    6: ("arts",),
}
_YEAR_DIR = re.compile(r"^(\d{4}) Examination Session$", re.I)
_SESSION_DIR = re.compile(r"^(May|November) (\d{4}) Examination Session$", re.I)
_PAPER_NAME = re.compile(r"^(?P<subject>.+?)_paper_(?P<rest>.+)$", re.I)
_WORKERS = 8


@dataclass(frozen=True, order=True)
class Session:
    year: int
    month: int
    path: str = field(compare=False)

    @property
    def label(self) -> str:
        return f"{MONTH_NAMES[self.month]} {self.year}"


@dataclass(frozen=True)
class Paper:
    session: Session
    name: str
    path: str
    size: int
    subject: str          # filename prefix, e.g. "Physics"
    number: str           # "1", "2", "1A"...
    variant: str          # "case study", "Calculus", "text booklet"... or ""
    tz: int | None
    level: str | None     # "HL", "SL", "HLSL" or None
    markscheme: bool
    lang: str
    fallback: bool = False  # English stand-in when the requested language is missing

    def sort_key(self) -> tuple:
        digits = re.match(r"\d+", self.number)
        return (self.session, int(digits[0]) if digits else 0, self.number,
                self.variant.lower(), self.tz or 0, self.level or "", self.lang)

    def ident(self) -> tuple:
        return (self.session, self.subject.lower(), self.number, self.variant.lower(),
                self.tz, self.level, self.markscheme, self.lang)

    def describe(self) -> str:
        parts = [self.session.label, f"Paper {self.number}" + (f" ({self.variant})" if self.variant else "")]
        if self.tz is not None:
            parts.append(f"TZ{self.tz}")
        if self.level:
            parts.append(self.level)
        if self.lang != "en":
            parts.append(LANGUAGES[self.lang])
        if self.markscheme:
            parts.append("markscheme")
        return " · ".join(parts)


def parse_filename(name: str) -> dict | None:
    """Split e.g. "Physics_paper_2__TZ1_HL_markscheme_Spanish.pdf" into its parts."""
    stem, dot, ext = name.rpartition(".")
    if not dot or ext.lower() != "pdf":
        return None
    match = _PAPER_NAME.match(stem)
    if not match:
        return None
    tokens = [t for t in match["rest"].split("_") if t]
    if not tokens or not re.fullmatch(r"\d[A-Za-z]?", tokens[0]):
        return None

    info = {"subject": match["subject"].strip("_"), "number": tokens[0].upper(),
            "tz": None, "level": None, "markscheme": False, "lang": "en"}
    extras = []
    for token in tokens[1:]:
        low = token.lower()
        if re.fullmatch(r"tz\d", low):
            info["tz"] = int(low[2])
        elif low in ("hl", "sl", "hlsl"):
            info["level"] = low.upper()
        elif low == "markscheme":
            info["markscheme"] = True
        elif low in _LANG_TOKENS:
            info["lang"] = _LANG_TOKENS[low]
        else:
            extras.append(token)
    info["variant"] = " ".join(extras)
    return info


def available_sessions(client: Client, years: set[int] | None = None,
                       months: set[int] | None = None) -> list[Session]:
    year_dirs = [f"{ROOT}/{e['name']}" for e in client.list_dir(ROOT)
                 if e.get("is_dir") and (m := _YEAR_DIR.match(e["name"]))
                 and (years is None or int(m[1]) in years)]
    sessions = []
    with ThreadPoolExecutor(_WORKERS) as pool:
        for year_dir, entries in zip(year_dirs, pool.map(client.list_dir, year_dirs)):
            for entry in entries:
                match = _SESSION_DIR.match(entry["name"])
                if not (entry.get("is_dir") and match):
                    continue
                month = MONTHS[match[1].lower()]
                if months is None or month in months:
                    sessions.append(Session(int(match[2]), month, f"{year_dir}/{entry['name']}"))
    return sorted(sessions)


def subject_files(client: Client, session: Session, subject: Subject,
                  legacy: bool = False) -> list[Paper]:
    """Every paper and markscheme of `subject` in one exam session."""
    prefixes = {p.lower() for p in subject.prefixes + (subject.legacy if legacy else ())}
    keywords = [k for group in subject.groups for k in _GROUP_KEYWORDS[group]]
    found, seen = [], set()
    for entry in client.list_dir(session.path):
        if not entry.get("is_dir") or not any(k in entry["name"].lower() for k in keywords):
            continue
        group_dir = f"{session.path}/{entry['name']}"
        for item in sorted(client.list_dir(group_dir), key=lambda e: e["name"]):
            info = None if item.get("is_dir") else parse_filename(item["name"])
            if not info or info["subject"].lower() not in prefixes:
                continue
            paper = Paper(session=session, name=item["name"], path=f"{group_dir}/{item['name']}",
                          size=int(item.get("size") or 0), **info)
            # Older sessions list the same file twice (single vs double underscore).
            if paper.ident() not in seen:
                seen.add(paper.ident())
                found.append(paper)
    return found


Library = dict[Session, list[Paper]]


def load_library(client: Client, subject: Subject, years: set[int] | None = None,
                 months: set[int] | None = None, legacy: bool = False) -> Library:
    sessions = available_sessions(client, years, months)
    with ThreadPoolExecutor(_WORKERS) as pool:
        results = pool.map(lambda s: subject_files(client, s, subject, legacy), sessions)
        return {s: files for s, files in zip(sessions, results) if files}


def _level_ok(level: str | None, wanted: str | None) -> bool:
    return wanted is None or level in (None, "HLSL", wanted)


def _levels_compatible(a: str | None, b: str | None) -> bool:
    return a == b or None in (a, b) or "HLSL" in (a, b)


def number_matches(number: str, wanted: str | None) -> bool:
    """"1" also matches the new physics papers "1A" and "1B"."""
    if not wanted:
        return True
    wanted = wanted.upper()
    return number == wanted or (wanted.isdigit() and number.startswith(wanted)
                                and number[len(wanted):].isalpha())


def question_papers(library: Library, *, level: str | None = None, lang: str = "en",
                    number: str | None = None, tz: int | None = None) -> list[Paper]:
    """Question papers in `lang`, falling back to English where no translation exists."""
    out = []
    for files in library.values():
        groups: dict[tuple, list[Paper]] = {}
        for p in files:
            if (not p.markscheme and _level_ok(p.level, level) and number_matches(p.number, number)
                    and (tz is None or p.tz == tz)):
                groups.setdefault((p.number, p.variant.lower(), p.level), []).append(p)
        for group in groups.values():
            wanted = [p for p in group if p.lang == lang]
            if wanted:
                out += wanted
            elif lang != "en":
                out += [replace(p, fallback=True) for p in group if p.lang == "en"]
    return sorted(out, key=Paper.sort_key)


def markschemes_for(paper: Paper, library: Library) -> list[Paper]:
    """The best-matching markscheme(s) for a question paper.

    Prefers the same variant, level, time zone and language, in that order.
    Translated papers often carry no time zone, so several English
    markschemes can tie; all of them are returned for the caller to choose.
    """
    candidates = [m for m in library.get(paper.session, [])
                  if m.markscheme and m.subject.lower() == paper.subject.lower()
                  and m.number == paper.number and _levels_compatible(m.level, paper.level)]

    def rank(m: Paper) -> tuple:
        return (m.variant.lower() == paper.variant.lower(), m.level == paper.level,
                m.tz == paper.tz, m.lang == paper.lang, m.lang == "en")

    if not candidates:
        return []
    best = max(map(rank, candidates))
    return sorted((m for m in candidates if rank(m) == best), key=Paper.sort_key)

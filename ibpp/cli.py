"""Command-line interface.

    ibpp                          guided mode
    ibpp physics 2024             words in any order: subject, years, may/nov, p1, tz1, hl/sl
    ibpp random | list | setup | log | config
"""

from __future__ import annotations

import argparse
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from . import __version__, catalog, papers, store, ui
from .api import ApiError, Client
from .catalog import Subject
from .papers import LANGUAGES, MONTH_NAMES, Library, Paper
from .store import Config, History, SubjectChoice
from .ui import bold, cyan, dim, green, red, yellow


class Abort(Exception):
    """Stops the current command and prints the message as an error."""


# ── the query language: `ibpp physics 2019-2023 may p2 tz1` ──────────────────

_LANG_WORDS = {
    "en": "en", "english": "en",
    "es": "es", "sp": "es", "spanish": "es", "espanol": "es", "español": "es",
    "fr": "fr", "french": "fr", "francais": "fr", "français": "fr",
    "de": "de", "german": "de", "deutsch": "de",
}
_PAPER_WORD = re.compile(r"(?:p|paper)?(\d[ab]?)")
_TZ_WORD = re.compile(r"tz(\d)")
_YEARS_WORD = re.compile(r"[\d,-]*\d[\d,-]*")


def parse_years(text: str | None) -> set[int] | None:
    """"2024", "2019-2023", "2019,2021", "2020-", "-2018", "19-23" → years (None = any)."""
    text = re.sub(r"\s*-\s*", "-", (text or "").strip().lower())
    if text in ("", "any", "all"):
        return None

    def year(token: str, fallback: int) -> int:
        if not token:
            return fallback
        if not token.isdigit() or len(token) not in (2, 4):
            raise ValueError(f"'{token}' isn't a year")
        return int(token) + (2000 if len(token) == 2 else 0)

    years: set[int] = set()
    for part in re.split(r"[,\s]+", text):
        if "-" in part:
            lo, _, hi = part.partition("-")
            a, b = sorted((year(lo, 1990), year(hi, 2100)))
            years.update(range(a, b + 1))
        elif part:
            years.add(year(part, 0))
    return years


def describe_years(years: set[int] | None) -> str:
    if not years:
        return "any year"
    lo, hi = min(years), max(years)
    if len(years) == 1:
        return str(lo)
    if len(years) == hi - lo + 1:
        return f"{lo}+" if hi >= 2100 else f"{lo}–{hi}"
    return ", ".join(map(str, sorted(years)))


@dataclass
class Query:
    subject: str | None = None
    years: set[int] | None = None
    months: set[int] | None = None
    number: str | None = None
    tz: int | None = None
    level: str | None = None
    lang: str | None = None

    @property
    def has_filters(self) -> bool:
        return any(v is not None for v in (self.years, self.months, self.number, self.tz))

    @property
    def single_year(self) -> bool:
        return self.years is not None and len(self.years) == 1

    def describe(self) -> str:
        parts = [describe_years(self.years)]
        if self.months:
            parts.append(" & ".join(MONTH_NAMES[m] for m in sorted(self.months)))
        if self.number:
            parts.append(f"Paper {self.number}")
        if self.tz is not None:
            parts.append(f"TZ{self.tz}")
        return " · ".join(parts)


def parse_query(words: list[str]) -> Query:
    q, subject_words = Query(), []
    for word in words:
        w = word.lower()
        if m := _PAPER_WORD.fullmatch(w):
            q.number = m[1].upper()
        elif m := _TZ_WORD.fullmatch(w):
            q.tz = int(m[1])
        elif _YEARS_WORD.fullmatch(w):
            try:
                q.years = (q.years or set()) | (parse_years(w) or set())
            except ValueError as exc:
                raise Abort(f"{exc}. Years look like 2024, 2019-2023 or 2020-") from None
        elif w in ("may", "nov", "november"):
            q.months = (q.months or set()) | {5 if w == "may" else 11}
        elif w in ("hl", "sl"):
            q.level = w.upper()
        elif w in _LANG_WORDS:
            q.lang = _LANG_WORDS[w]
        else:
            subject_words.append(w)
    q.subject = "-".join(subject_words) or None
    return q


# ── shared pieces ────────────────────────────────────────────────────────────

@dataclass
class Ctx:
    cfg: Config
    client: Client
    history: History
    lang: str
    open_ms: bool = False
    no_open: bool = False
    include_done: bool = False
    picked_subject: bool = False  # the subject menu was just shown, so skip the header once


def label(choice: SubjectChoice) -> str:
    return f"{catalog.get(choice.key).name} {choice.level}"


def pretty_path(path: Path) -> str:
    if os.name != "nt":
        try:
            return "~/" + str(path.relative_to(Path.home()))
        except ValueError:
            pass
    return str(path)


def header(ctx: Ctx, choice: SubjectChoice) -> None:
    if ctx.picked_subject:
        ctx.picked_subject = False
        return
    print(f"{bold(cyan('ibpp'))} {dim('·')} {bold(label(choice))} {dim('·')} {dim(LANGUAGES[ctx.lang])}")


def resolve_subject(ctx: Ctx, q: Query, ask: bool = False) -> tuple[Subject, SubjectChoice]:
    mine = ctx.cfg.subjects
    if q.subject and not ask:
        subject = lookup_subject(q.subject, [c.key for c in mine])
        choice = next((c for c in mine if c.key == subject.key), SubjectChoice(subject.key))
    elif not mine:
        raise Abort("Pick your subjects first with `ibpp setup`, or name one: `ibpp physics 2024`")
    elif len(mine) == 1:
        choice = mine[0]
    else:
        choice = mine[ui.select("Subject", [f"{label(c)}" for c in mine])]
        ctx.picked_subject = True
    if q.level:
        choice = replace(choice, level=q.level)
    return catalog.get(choice.key), choice


def lookup_subject(words: str, prefer: list[str]) -> Subject:
    try:
        return catalog.lookup(words, prefer=prefer)
    except LookupError as exc:
        error = str(exc)
    parts = words.split("-")
    for i, word in enumerate(parts):  # "physics 20x": say which word made no sense
        try:
            catalog.lookup(word, prefer=prefer)
        except LookupError:
            continue
        unknown = [w for j, w in enumerate(parts) if j != i]
        if unknown:
            error = f"didn't understand '{' '.join(unknown)}'"
        break
    raise Abort(f"{error[0].upper()}{error[1:]}.\n" + dim("  Subjects: " + ", ".join(s.key for s in catalog.SUBJECTS))
                + "\n" + dim("  Filters: 2024, 2019-2023, may, nov, p1, tz1, hl, sl. See `ibpp --help`."))


def search(ctx: Ctx, subject: Subject, choice: SubjectChoice, q: Query) -> tuple[Library, list[Paper]]:
    with ui.spinner(f"Looking up {subject.name} papers…"):
        library = papers.load_library(ctx.client, subject, q.years, q.months, legacy=choice.legacy)
    found = papers.question_papers(library, level=choice.level, lang=ctx.lang, number=q.number, tz=q.tz)
    if not found:
        raise Abort(f"No {label(choice)} papers for {q.describe()}.")
    return library, found


def paper_row(ctx: Ctx, paper: Paper, extra: str = "") -> str:
    name = f"Paper {paper.number}" + (f" {paper.variant}" if paper.variant else "")
    tz = f"TZ{paper.tz}" if paper.tz is not None else ""
    cells = [f"{paper.session.label:<13}", f"{name:<9}", f"{tz:<3}", f"{paper.level or '':<4}"]
    if paper.fallback:
        cells.append(yellow("English only"))
    if extra:
        cells.append(extra)
    if ctx.history.seen(paper.path):
        cells.append(green("✓ done"))
    return "  ".join(cells).rstrip()


def pick_random(ctx: Ctx, found: list[Paper]) -> Paper:
    fresh = found if ctx.include_done else [p for p in found if not ctx.history.seen(p.path)]
    paper = random.choice(fresh or found)
    note = f"out of {len(found)}" if fresh else f"you've done all {len(found)}, so it's a repeat"
    print(f"{cyan('⚄')} Random pick {dim(f'({note})')}")
    return paper


def choose_paper(ctx: Ctx, found: list[Paper]) -> Paper:
    if len(found) == 1:
        return found[0]
    if not ui.INTERACTIVE:
        raise Abort(f"{len(found)} papers match. Narrow it down (p1, tz1, may) or use `ibpp random`.")
    i = ui.select("Paper", ["Surprise me"] + [paper_row(ctx, p) for p in found])
    return pick_random(ctx, found) if i == 0 else found[i - 1]


def fetch(ctx: Ctx, choice: SubjectChoice, paper: Paper) -> Path:
    folder = ctx.cfg.download_path / label(choice) / f"{paper.session.year} {MONTH_NAMES[paper.session.month]}"
    dest = folder / paper.name
    if dest.is_file() and (not paper.size or dest.stat().st_size == paper.size):
        return dest
    folder.mkdir(parents=True, exist_ok=True)
    try:
        return ctx.client.download(paper.path, dest, lambda done, total: ui.progress(paper.name, done, total))
    finally:
        ui.clear_status()


def open_file(ctx: Ctx, path: Path) -> None:
    detach = {"start_new_session": True} if os.name != "nt" else {}
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    try:
        if ctx.cfg.viewer:
            subprocess.Popen([*shlex.split(ctx.cfg.viewer, posix=os.name != "nt"), str(path)], **quiet, **detach)
        elif os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)], **quiet)
        else:
            subprocess.Popen(["xdg-open", str(path)], **quiet, **detach)
    except OSError as exc:
        print(yellow(f"  Couldn't open it ({exc}). Pick a PDF viewer with `ibpp setup`."))


def show_file(ctx: Ctx, choice: SubjectChoice, paper: Paper) -> None:
    path = fetch(ctx, choice, paper)
    if not ctx.no_open:
        open_file(ctx, path)
    print(f"{green('✓')} {'Saved' if ctx.no_open else 'Opened'} {bold(paper.describe())}")
    print(dim(f"  {pretty_path(path)}"))


def study(ctx: Ctx, choice: SubjectChoice, paper: Paper, library: Library) -> None:
    """Open a paper, then its markscheme once you're done with it."""
    show_file(ctx, choice, paper)
    if paper.fallback:
        print(yellow(f"  There's no {LANGUAGES[ctx.lang]} version of this one, so here's the English paper."))
    ctx.history.add(paper.path, label(choice), paper.describe())

    schemes = papers.markschemes_for(paper, library)
    if not schemes:
        print(dim("  No markscheme for this one on ibdocs."))
        return
    if not ctx.open_ms:
        if ctx.no_open or not ui.INTERACTIVE:
            print(dim("  Markscheme available: add --ms to get it too."))
            return
        print()
        if ui.select("When you're done", ["Open the markscheme", "Skip it"]) == 1:
            return
    if len(schemes) > 1 and ui.INTERACTIVE:
        options = [f"TZ{s.tz}" if s.tz is not None else s.describe() for s in schemes]
        schemes = [schemes[ui.select("Markscheme for which time zone?", options)]]
    for scheme in schemes:
        show_file(ctx, choice, scheme)


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_find(ctx: Ctx, q: Query) -> None:
    """`ibpp [subject] [filters]`: guided when there are no filters, else straight to it."""
    if not ctx.cfg.subjects and not q.subject:
        if not ui.INTERACTIVE:
            raise Abort("Pick your subjects first with `ibpp setup`.")
        print(f"{bold('Welcome to ibpp!')} {dim('First, your subjects.')}")
        setup_wizard(ctx)
        print()
    subject, choice = resolve_subject(ctx, q)
    header(ctx, choice)
    if not q.has_filters:
        return guided(ctx, subject, choice)
    library, found = search(ctx, subject, choice, q)
    paper = choose_paper(ctx, found) if q.single_year or len(found) == 1 else pick_random(ctx, found)
    study(ctx, choice, paper, library)


def ask_search(ctx: Ctx, subject: Subject, choice: SubjectChoice) -> tuple[Query, Library, list[Paper]]:
    def check(value: str) -> str | None:
        try:
            parse_years(value)
        except ValueError as exc:
            return f"{exc}. Try 2024 or 2019-2023."
        return None

    while True:
        q = Query(years=parse_years(ui.text("Year", placeholder="any, 2024 or 2019-2023",
                                            blank="any", validate=check)))
        try:
            library, found = search(ctx, subject, choice, q)
        except Abort as exc:
            print(red(f"✗ {exc}"))
            continue
        if not q.single_year:
            numbers = sorted({p.number[0] for p in found})
            if len(numbers) > 1:
                i = ui.select("Paper", ["Any"] + [f"Paper {n}" for n in numbers])
                if i:
                    q.number = numbers[i - 1]
                    found = [p for p in found if papers.number_matches(p.number, q.number)]
        return q, library, found


def guided(ctx: Ctx, subject: Subject, choice: SubjectChoice) -> None:
    q, library, found = ask_search(ctx, subject, choice)
    while True:
        paper = choose_paper(ctx, found) if q.single_year else pick_random(ctx, found)
        study(ctx, choice, paper, library)
        print()
        actions = [("again", f"Another from {q.describe()}"), ("new", "New search")]
        if len(ctx.cfg.subjects) > 1:
            actions.append(("switch", "Switch subject"))
        actions.append(("quit", "Quit"))
        action = actions[ui.select("What next?", [text for _, text in actions])][0]
        if action == "quit":
            return
        if action == "switch":
            subject, choice = resolve_subject(ctx, Query(), ask=True)
        if action in ("new", "switch"):
            print()
            header(ctx, choice)
            q, library, found = ask_search(ctx, subject, choice)


def cmd_random(ctx: Ctx, q: Query) -> None:
    subject, choice = resolve_subject(ctx, q)
    header(ctx, choice)
    library, found = search(ctx, subject, choice, q)
    study(ctx, choice, pick_random(ctx, found), library)


def cmd_list(ctx: Ctx, q: Query) -> None:
    subject, choice = resolve_subject(ctx, q)
    library, found = search(ctx, subject, choice, q)
    header(ctx, choice)
    last = None
    for paper in found:
        if paper.session != last:
            print()
            last = paper.session
        ms = "" if papers.markschemes_for(paper, library) else dim("no markscheme")
        print("  " + paper_row(ctx, paper, ms))
    print(dim(f"\n  {len(found)} papers · {q.describe()}"))


_VIEWERS = [("zathura", "Zathura"), ("sioyek", "Sioyek"), ("okular", "Okular"), ("evince", "Evince"),
            ("papers", "Papers"), ("atril", "Atril"), ("xreader", "Xreader"), ("qpdfview", "qpdfview"),
            ("mupdf", "MuPDF"), ("firefox", "Firefox"), ("chromium", "Chromium"),
            ("google-chrome-stable", "Chrome"), ("brave", "Brave")]


def _system_pdf_app() -> str:
    try:
        out = subprocess.run(["xdg-mime", "query", "default", "application/pdf"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.removesuffix(".desktop").split(".")[-1]


def ask_viewer(current: str) -> str:
    if os.name == "nt" or sys.platform == "darwin":
        return current
    found = [(cmd, name) for cmd, name in _VIEWERS if shutil.which(cmd)]
    if current and current not in [cmd for cmd, _ in found]:
        found.insert(0, (current, current))
    if not found:
        return ""
    system = _system_pdf_app()
    options = ["System default" + (f" ({system})" if system else "")] + [name for _, name in found]
    default = next((i + 1 for i, (cmd, _) in enumerate(found) if cmd == current), 0)
    i = ui.select("Open PDFs with", options, default=default)
    return "" if i == 0 else found[i - 1][0]


def setup_wizard(ctx: Ctx) -> None:
    cfg = ctx.cfg
    current = {c.key: c for c in cfg.subjects}
    subjects = catalog.SUBJECTS
    picked = ui.checkbox("Your subjects", [s.name for s in subjects],
                         selected=[i for i, s in enumerate(subjects) if s.key in current])
    chosen = []
    for i in picked:
        subject, prev = subjects[i], current.get(subjects[i].key)
        level = ("HL", "SL")[ui.select(f"{subject.name} level", ["HL", "SL"],
                                       default=1 if prev and prev.level == "SL" else 0)]
        legacy = bool(subject.legacy) and ui.confirm(f"Include {subject.legacy_note}?",
                                                     default=bool(prev and prev.legacy))
        chosen.append(SubjectChoice(subject.key, level, legacy))

    codes = list(LANGUAGES)
    cfg.lang = codes[ui.select("Paper language", list(LANGUAGES.values()), default=codes.index(cfg.lang))]
    cfg.viewer = ask_viewer(cfg.viewer)
    cfg.download_dir = ui.text("Save PDFs in", default=pretty_path(cfg.download_path))
    cfg.subjects = chosen
    cfg.save()
    ctx.lang = cfg.lang
    print(f"{green('✓')} All set")


def cmd_setup(ctx: Ctx, words: list[str]) -> None:
    if not words:
        if not ui.INTERACTIVE:
            raise Abort("Run `ibpp setup` in a terminal, or list your subjects: ibpp setup physics:hl math-aa:hl")
        setup_wizard(ctx)
        print(dim("  Run ibpp to start."))
        return
    subjects = []
    for spec in words:  # physics:hl, math-aa:hl:legacy
        name, *flags = spec.lower().split(":")
        subject = lookup_subject(name, [])
        subjects.append(SubjectChoice(subject.key, "SL" if "sl" in flags else "HL", "legacy" in flags))
    ctx.cfg.subjects, ctx.cfg.lang = subjects, ctx.lang
    ctx.cfg.save()
    print(f"{green('✓')} {', '.join(map(label, subjects))} · {LANGUAGES[ctx.lang]}")


def cmd_log(ctx: Ctx, words: list[str]) -> None:
    if words[:1] == ["clear"]:
        if ui.confirm("Forget every paper you've done?"):
            ctx.history.clear()
            print(f"{green('✓')} Log cleared")
        return
    entries = ctx.history.entries
    if not entries:
        print(dim("Nothing yet. Go do a paper!"))
        return
    for e in entries[-20:]:
        print(f"  {dim(e['opened'])}  {e['subject']:<12}  {e['paper']}")
    print(dim(f"\n  {len(entries)} papers done"))


def cmd_config(ctx: Ctx) -> None:
    cfg = ctx.cfg
    rows = [("Subjects", ", ".join(label(c) + (" +old syllabus" if c.legacy else "") for c in cfg.subjects) or "—"),
            ("Language", LANGUAGES[cfg.lang]),
            ("PDF viewer", cfg.viewer or "system default"),
            ("Downloads", pretty_path(cfg.download_path)),
            ("Config", pretty_path(Config.path())),
            ("Cache", pretty_path(store.cache_dir()))]
    for name, value in rows:
        print(f"  {dim(f'{name:<12}')}{value}")
    print(dim("\n  Change these with `ibpp setup`."))


# ── entry point ──────────────────────────────────────────────────────────────

def help_text() -> str:
    h = lambda s: bold(s)  # noqa: E731
    return f"""{bold(cyan('ibpp'))} · IB past papers from your terminal

{h('Usage')}
  ibpp                            guided mode
  ibpp <subject> [filters]        find a paper (a range gives you a random one)
  ibpp random [subject] [filters] random paper you haven't done yet
  ibpp list [subject] [filters]   see what's available
  ibpp setup                      subjects, language, PDF viewer
  ibpp log                        papers you've done
  ibpp config                     current settings

{h('Filters')} {dim('(any order)')}
  2024  2019-2023  2020-          year or range
  may  nov                        session
  p1  p2  p3  p1b                 paper
  tz1  tz2                        time zone
  hl  sl                          level

{h('Options')}
  --es  --en  --fr  --de          paper language
  --ms                            open the markscheme straight away
  --no-open                       just download
  --all                           random: include papers you've done
  --refresh                       re-fetch the paper index

{h('Examples')}
  ibpp physics 2024               pick from 2024's papers
  ibpp physics 2019-2023 p2       random paper 2 from 2019–2023
  ibpp math 2023 may p1 tz2 --ms  that exact paper, with markscheme"""


class _ArgParser(argparse.ArgumentParser):
    def error(self, message: str):
        raise Abort(f"{message}. See `ibpp --help`.")


def _parser() -> argparse.ArgumentParser:
    p = _ArgParser(prog="ibpp", add_help=False)
    p.add_argument("words", nargs="*")
    for flag, code in (("--en", "en"), ("--es", "es"), ("--sp", "es"), ("--fr", "fr"), ("--de", "de")):
        p.add_argument(flag, dest="lang", action="store_const", const=code)
    p.add_argument("--ms", action="store_true")
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    p.add_argument("-V", "--version", action="store_true")
    return p


COMMANDS = {"random": cmd_random, "r": cmd_random, "list": cmd_list, "ls": cmd_list}


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_intermixed_args(argv)
        if args.help or args.words[:1] == ["help"]:
            print(help_text())
            return 0
        if args.version:
            print(f"ibpp {__version__}")
            return 0

        words = list(args.words)
        command = words.pop(0).lower() if words and words[0].lower() in (*COMMANDS, "setup", "log", "config") else None
        cfg = Config.load()
        ctx = Ctx(cfg=cfg, client=Client(store.cache_dir(), refresh=args.refresh), history=History(),
                  lang=args.lang or cfg.lang, open_ms=args.ms, no_open=args.no_open, include_done=args.all)
        if command == "setup":
            cmd_setup(ctx, words)
        elif command == "log":
            cmd_log(ctx, words)
        elif command == "config":
            cmd_config(ctx)
        else:
            q = parse_query(words)
            if q.lang and not args.lang:
                ctx.lang = q.lang
            COMMANDS.get(command, cmd_find)(ctx, q)
        return 0
    except Abort as exc:
        print(red(f"✗ {exc}"), file=sys.stderr)
    except ApiError as exc:
        print(red(f"✗ {exc}"), file=sys.stderr)
    except (KeyboardInterrupt, EOFError):
        print()
        return 130
    return 1

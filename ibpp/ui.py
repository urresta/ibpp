"""A tiny terminal UI kit: arrow-key menus, checklists, text prompts, spinners.

No dependencies. When stdin/stdout isn't a terminal (pipes, scripts) every
prompt falls back to plain numbered input.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
from contextlib import contextmanager
from typing import Callable, Iterable

if os.name == "nt":
    import msvcrt

    os.system("")  # turns on ANSI escape handling in the Windows console
else:
    import select as _select
    import termios
    import tty

COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
INTERACTIVE = sys.stdin.isatty() and sys.stdout.isatty()


def _style(code: str):
    return lambda text: f"\x1b[{code}m{text}\x1b[0m" if COLOR else str(text)


bold, dim, red, green, yellow, cyan = (_style(c) for c in ("1", "2", "31", "32", "33", "36"))

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def plain(text: str) -> str:
    return _ANSI.sub("", text)


def _truncate(text: str, width: int) -> str:
    if len(plain(text)) <= width:
        return text
    out, shown, i = [], 0, 0
    while i < len(text) and shown < width - 1:
        if m := _ANSI.match(text, i):
            out.append(m.group())
            i = m.end()
        else:
            out.append(text[i])
            shown += 1
            i += 1
    return "".join(out) + "…" + ("\x1b[0m" if COLOR else "")


def _write(text: str, stream=sys.stdout) -> None:
    stream.write(text)
    stream.flush()


# ── keyboard ─────────────────────────────────────────────────────────────────

def _key_name(ch: str) -> str:
    if ch in ("\r", "\n"):
        return "enter"
    if ch == " ":
        return "space"
    if ch in ("\x7f", "\x08"):
        return "backspace"
    if ch in ("\x03", "\x1b"):
        raise KeyboardInterrupt
    if ch == "\x04":
        raise EOFError
    if ch == "\x15":
        return "clear"  # Ctrl+U
    return ch


def _read_key() -> str:
    if os.name == "nt":
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(msvcrt.getwch(), "")
        return _key_name(ch)

    fd = sys.stdin.fileno()
    data = os.read(fd, 1)
    if data == b"\x1b":
        if not _select.select([fd], [], [], 0.05)[0]:
            raise KeyboardInterrupt  # a lone Esc
        seq = os.read(fd, 1)
        if seq in (b"[", b"O"):  # read exactly one escape sequence, up to its final byte
            while len(seq) < 8 and not (0x40 <= seq[-1] <= 0x7E and len(seq) > 1):
                seq += os.read(fd, 1)
        return {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left",
                b"OA": "up", b"OB": "down"}.get(seq, "")
    if data and data[0] >= 0xC0:  # multi-byte UTF-8 character
        data += os.read(fd, 1 if data[0] < 0xE0 else 2 if data[0] < 0xF0 else 3)
    return _key_name(data.decode("utf-8", "replace"))


@contextmanager
def _keys(hide_cursor: bool = True):
    fd = old = None
    if os.name != "nt":
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        tty.setcbreak(fd)
    if hide_cursor:
        _write("\x1b[?25l")
    try:
        yield
    finally:
        if old is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if hide_cursor:
            _write("\x1b[?25h")


class _Block:
    """A block of lines redrawn in place as the user presses keys."""

    def __init__(self):
        self.row = 0  # the line of the block the cursor is on
        self.drawn = False

    def draw(self, lines: list[str], cursor: tuple[int, int] | None = None) -> None:
        width = shutil.get_terminal_size().columns - 1
        lines = [_truncate(line, width) for line in lines]
        out = []
        if self.drawn:
            out.append(f"\x1b[{self.row}A" if self.row else "")
            out.append("\r\x1b[J")
        out.append("\n".join(lines))
        last = len(lines) - 1
        if cursor:
            row, col = cursor
            out.append((f"\x1b[{last - row}A" if last - row else "") + "\r" + (f"\x1b[{col}C" if col else ""))
            self.row = row
        else:
            self.row = last
        _write("".join(out))
        self.drawn = True

    def close(self, line: str) -> None:
        self.draw([line])
        _write("\n")


def _answered(question: str, answer: str) -> str:
    answer = re.sub(r"\s{2,}", "  ", plain(answer).strip())
    return f"{green('✓')} {question} {dim('·')} {cyan(answer)}"


def _window(count: int, index: int) -> range:
    size = max(3, min(count, shutil.get_terminal_size().lines - 4, 12))
    top = min(max(0, index - size // 2), max(0, count - size))
    return range(top, min(count, top + size))


# ── prompts ──────────────────────────────────────────────────────────────────

def select(question: str, options: list[str], default: int = 0) -> int:
    """Arrow-key menu. Returns the index of the chosen option."""
    if not INTERACTIVE:
        return _plain_select(question, options, default)
    index, block = default, _Block()
    with _keys():
        while True:
            lines = [f"{cyan('?')} {bold(question)}"]
            for i in _window(len(options), index):
                lines.append(f"{cyan('❯')} {cyan(options[i])}" if i == index else f"  {options[i]}")
            if len(lines) - 1 < len(options):
                lines.append(dim(f"  {index + 1}/{len(options)}"))
            block.draw(lines)

            key = _read_key()
            if key in ("up", "k"):
                index = (index - 1) % len(options)
            elif key in ("down", "j"):
                index = (index + 1) % len(options)
            elif key.isdigit() and 1 <= int(key) <= len(options):
                index = int(key) - 1
            elif key == "enter":
                block.close(_answered(question, options[index]))
                return index


def checkbox(question: str, options: list[str], selected: Iterable[int] = (), empty: str = "") -> list[int]:
    """Multi-select list: space toggles, enter confirms. Needs at least one pick,
    unless `empty` names what picking nothing means (then it returns [])."""
    chosen = set(selected)
    if not INTERACTIVE:
        return _plain_checkbox(question, options, chosen, empty)
    index, block, error = 0, _Block(), ""
    with _keys():
        while True:
            lines = [f"{cyan('?')} {bold(question)}"]
            shown = _window(len(options), index)
            for i in shown:
                mark = green("●") if i in chosen else dim("○")
                text = cyan(options[i]) if i == index else options[i]
                lines.append(f"{cyan('❯') if i == index else ' '} {mark} {text}")
            hint = "space to select · enter when done"
            if empty:
                hint += f" · none = {empty.lower()}"
            if len(shown) < len(options):
                hint = f"{index + 1}/{len(options)} · {hint}"
            lines.append(red(f"  {error}") if error else dim(f"  {hint}"))
            block.draw(lines)

            key = _read_key()
            if key in ("up", "k"):
                index = (index - 1) % len(options)
            elif key in ("down", "j"):
                index = (index + 1) % len(options)
            elif key == "space":
                chosen ^= {index}
                error = ""
            elif key == "enter":
                if chosen or empty:
                    answer = ", ".join(options[i] for i in sorted(chosen)) or empty
                    block.close(_answered(question, answer))
                    return sorted(chosen)
                error = "Select at least one with space."


def text(question: str, *, default: str = "", placeholder: str = "", blank: str = "",
         validate: Callable[[str], str | None] | None = None) -> str:
    """One-line text input. `placeholder` greys out until you type; Enter on an
    empty line returns `default`. `validate` returns an error message or None."""
    if not INTERACTIVE:
        return _plain_text(question, default, validate)
    buf, error, block = "", "", _Block()
    hint = placeholder or default
    with _keys(hide_cursor=False):
        while True:
            prefix = f"{cyan('?')} {bold(question)} {dim('›')} "
            lines = [prefix + (buf or dim(hint))]
            if error:
                lines.append(red(f"  {error}"))
            block.draw(lines, cursor=(0, len(plain(prefix)) + len(buf)))

            key = _read_key()
            if key == "enter":
                value = buf.strip() or default
                error = validate(value) if validate else None
                if not error:
                    block.close(_answered(question, value or blank or "—"))
                    return value
            elif key == "backspace":
                buf = buf[:-1]
            elif key == "clear":
                buf = ""
            elif key == "space":
                buf += " "
            elif len(key) == 1 and key.isprintable():
                buf += key
                error = ""


def confirm(question: str, default: bool = False) -> bool:
    return select(question, ["Yes", "No"], default=0 if default else 1) == 0


# ── fallbacks for pipes and scripts ──────────────────────────────────────────

def _plain_select(question: str, options: list[str], default: int) -> int:
    print(question)
    for i, option in enumerate(options, 1):
        print(f"  {i}) {plain(option)}")
    while True:
        answer = input(f"[{default + 1}] > ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1


def _plain_checkbox(question: str, options: list[str], chosen: set[int], empty: str = "") -> list[int]:
    print(f"{question} (numbers separated by spaces{f', blank = {empty.lower()}' if empty else ''})")
    for i, option in enumerate(options, 1):
        print(f"  {i}) {plain(option)}")
    while True:
        picks = {int(n) - 1 for n in re.findall(r"\d+", input("> ")) if 1 <= int(n) <= len(options)}
        if picks or chosen or empty:
            return sorted(picks or chosen)


def _plain_text(question: str, default: str, validate) -> str:
    while True:
        value = input(f"{question}{f' [{default}]' if default else ''}: ").strip() or default
        error = validate(value) if validate else None
        if not error:
            return value
        print(error)


# ── status output ────────────────────────────────────────────────────────────

@contextmanager
def spinner(message: str):
    if not sys.stderr.isatty():
        yield
        return
    stop = threading.Event()

    def spin() -> None:
        frames, i = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", 0
        while not stop.is_set():
            _write(f"\r\x1b[K{cyan(frames[i % len(frames)])} {dim(message)}", sys.stderr)
            i += 1
            stop.wait(0.08)

    _write("\x1b[?25l", sys.stderr)
    thread = threading.Thread(target=spin, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        _write("\r\x1b[K\x1b[?25h", sys.stderr)


def progress(name: str, done: int, total: int) -> None:
    if not sys.stderr.isatty():
        return
    bar_width = 20
    room = max(10, shutil.get_terminal_size().columns - bar_width - 12)
    name = name if len(name) <= room else name[: room - 1] + "…"
    if total:
        filled = bar_width * done // total
        tail = f"{cyan('━' * filled)}{dim('━' * (bar_width - filled))} {done * 100 // total:>3}%"
    else:
        tail = f"{done // 1024} KB"
    _write(f"\r\x1b[K{dim('↓')} {name} {tail}", sys.stderr)


def clear_status() -> None:
    if sys.stderr.isatty():
        _write("\r\x1b[K", sys.stderr)

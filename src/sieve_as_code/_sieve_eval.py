"""Evaluate the previewable Sieve subset against one message (FR-RETRO.2).

Anything outside the subset raises `UnsupportedSieve`; it is never guessed.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import NamedTuple

from sieve_as_code._model import UnsupportedSieve

_MAX_RECIPIENT_KEYS = 10  # BR-10
_FLAGS = {"\\seen", "\\flagged"}  # BR-12
_FIELDS = {"from", "to", "subject"}
_LOWER = {ord(c): ord(c) + 32 for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
_TOKEN = re.compile(
    r"""(?P<space>[ \t\r\n]+)|(?P<hash>\#[^\n]*)|(?P<block>/\*.*?\*/)
    |(?P<string>"(?:[^"\\]|\\.)*")|(?P<tag>:[A-Za-z_][A-Za-z0-9_]*)
    |(?P<number>[0-9]+[KMGkmg]?)|(?P<word>[A-Za-z_][A-Za-z0-9_]*)|(?P<sym>[{}()\[\],;])""",
    re.VERBOSE | re.DOTALL,
)


# BR-30: Proton's generated spam guard, as lower-cased token values up to its `{`.
_SPAM_GUARD = (
    *("if", "allof", "(", "environment", ":matches"),
    *('"vnd.proton.spam-threshold"', '"*"', ",", "spamtest", ":value", '"ge"'),
    *(":comparator", '"i;ascii-numeric"', '"${1}"', ")", "{"),
)
_GUARD_BLOCKS = (("}",), ("return", ";", "}"))


def _fold(text: str) -> str:
    """The `i;ascii-casemap` comparator: ASCII letters only (BR-7)."""
    return text.translate(_LOWER)


@dataclass(frozen=True)
class MailMessage:
    """One `messages list` row; `to_keys` are the recipient keys it matched."""

    id: str
    subject: str
    from_name: str
    from_address: str
    time: int
    unread: bool
    labels: frozenset[str]
    to_keys: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Outcome:
    """What one filter would do to one message (BR-8)."""

    files: tuple[str, ...]
    flags: frozenset[str]
    expire_days: int | None


@dataclass
class _State:
    files: list[str] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    expire_days: int | None = None


_Test = Callable[[MailMessage], bool]
_Command = Callable[[MailMessage, _State], bool]  # True when `stop` ran


@dataclass(frozen=True)
class CompiledScript:
    """A parsed script: every `fileinto` target and the folded `to` keys it needs."""

    program: tuple[_Command, ...]
    mailboxes: tuple[str, ...]
    recipient_keys: tuple[str, ...]


class _Token(NamedTuple):
    kind: str
    value: str
    line: int


def _tokens(text: str) -> list[_Token]:
    found: list[_Token] = []
    pos, line = 0, 1
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if match is None or text.startswith("text:", pos):
            what = "text block" if text.startswith("text:", pos) else "character"
            raise UnsupportedSieve(what, line)
        kind = match.lastgroup or ""
        value = match.group()
        if kind not in {"space", "hash", "block"}:
            found.append(_Token(kind, value, line))
        line += value.count("\n")
        pos = match.end()
    found.append(_Token("end", "", line))
    return found


def _unquote(literal: str) -> str:
    return re.sub(r"\\(.)", r"\1", literal[1:-1], flags=re.DOTALL)


def _wildcard(pattern: str) -> re.Pattern[str]:
    """`:matches` pattern: `*` and `?` match, `\\` escapes (BR-7)."""
    out: list[str] = []
    chars = iter(_fold(pattern))
    for char in chars:
        if char == "\\":
            out.append(re.escape(next(chars, "\\")))
        else:
            out.append({"*": ".*", "?": "."}.get(char) or re.escape(char))
    return re.compile("".join(out), re.DOTALL)


def _matcher(op: str, key: str) -> Callable[[str], bool]:
    folded = _fold(key)
    if op == "is":
        return lambda value: _fold(value) == folded
    if op == "contains":
        return lambda value: folded in _fold(value)
    pattern = _wildcard(key)
    return lambda value: pattern.fullmatch(_fold(value)) is not None


def _address_part(address: str, part: str) -> str:
    local, at, domain = address.rpartition("@")
    if not at:
        local, domain = address, ""
    return {"all": address, "localpart": local, "domain": domain}[part]


class _Parser:
    """Recursive descent over the BR-6 subset; collects targets and recipient keys."""

    def __init__(self, text: str) -> None:
        self.tokens = _tokens(text)
        self.pos = 0
        self.mailboxes: list[str] = []
        self.keys: list[str] = []

    @property
    def current(self) -> _Token:
        return self.tokens[self.pos]

    def _fail(self, construct: str) -> UnsupportedSieve:
        return UnsupportedSieve(construct, self.current.line)

    def _take(self) -> _Token:
        token = self.current
        self.pos += 1
        return token

    def _expect(self, value: str) -> None:
        if self.current.value != value or self.current.kind not in {"sym", "word"}:
            raise self._fail("syntax")
        self.pos += 1

    def _strings(self) -> list[str]:
        """A string or a bracketed list of strings."""
        if self.current.kind == "string":
            return [_unquote(self._take().value)]
        self._expect("[")
        values = [self._string()]
        while self.current.value == ",":
            self.pos += 1
            values.append(self._string())
        self._expect("]")
        return values

    def _string(self) -> str:
        if self.current.kind != "string":
            raise self._fail("syntax")
        return _unquote(self._take().value)

    def _skip_spam_guard(self) -> bool:
        """BR-30: skip the exact Proton spam guard at the current position."""
        values = [t.value.lower() for t in self.tokens[self.pos :]]
        if tuple(values[: len(_SPAM_GUARD)]) != _SPAM_GUARD:
            return False
        rest = tuple(values[len(_SPAM_GUARD) :])
        for block in _GUARD_BLOCKS:
            if rest[: len(block)] == block:
                self.pos += len(_SPAM_GUARD) + len(block)
                return True
        return False

    def commands(self, top: bool) -> tuple[_Command, ...]:
        program: list[_Command] = []
        leading = top  # BR-30: the guard may follow `require` commands only
        while self.current.kind != "end" and (top or self.current.value != "}"):
            if leading and self._skip_spam_guard():
                leading = False
                continue
            leading = leading and self.current.value.lower() == "require"
            program.append(self._command())
        return tuple(program)

    def _block(self) -> tuple[_Command, ...]:
        self._expect("{")
        body = self.commands(top=False)
        self._expect("}")
        return body

    def _command(self) -> _Command:
        token = self._take()
        if token.kind != "word":
            self.pos -= 1
            raise self._fail("syntax")
        name = token.value.lower()
        if name == "if":
            return self._if()
        handlers: dict[str, Callable[[], _Command]] = {
            "require": self._require,
            "stop": self._stop,
            "fileinto": self._fileinto,
            "expire": self._expire,
        }
        if name in {"addflag", "setflag", "removeflag"}:
            return self._flags(name)
        if name not in handlers:
            raise UnsupportedSieve(name, token.line)
        return handlers[name]()

    def _require(self) -> _Command:
        self._strings()
        self._expect(";")
        return lambda _m, _s: False

    def _stop(self) -> _Command:
        self._expect(";")
        return lambda _m, _s: True

    def _fileinto(self) -> _Command:
        if self.current.kind == "tag":
            raise self._fail(self.current.value.lower())
        target = self._string()
        self._expect(";")
        self.mailboxes.append(target)

        def run(_m: MailMessage, state: _State) -> bool:
            state.files.append(target)
            return False

        return run

    def _flags(self, name: str) -> _Command:
        values = {_fold(flag) for flag in self._strings()}
        self._expect(";")
        if not values <= _FLAGS:
            raise self._fail("flag")

        def run(_m: MailMessage, state: _State) -> bool:
            if name == "addflag":
                state.flags |= values
            elif name == "setflag":
                state.flags = set(values)
            else:
                state.flags -= values
            return False

        return run

    def _expire(self) -> _Command:
        unit, count = self._string(), self._string()
        self._expect(";")
        if _fold(unit) != "day" or not (count.isascii() and count.isdigit()):
            raise self._fail("expire")
        days = int(count)
        if days < 1:
            raise self._fail("expire")

        def run(_m: MailMessage, state: _State) -> bool:
            state.expire_days = days
            return False

        return run

    def _if(self) -> _Command:
        branches: list[tuple[_Test | None, tuple[_Command, ...]]] = []
        test = self._test()
        branches.append((test, self._block()))
        while self.current.kind == "word" and self.current.value.lower() == "elsif":
            self.pos += 1
            test = self._test()
            branches.append((test, self._block()))
        if self.current.kind == "word" and self.current.value.lower() == "else":
            self.pos += 1
            branches.append((None, self._block()))

        def run(message: MailMessage, state: _State) -> bool:
            for condition, body in branches:
                if condition is None or condition(message):
                    return _run(body, message, state)
            return False

        return run

    def _test(self) -> _Test:
        token = self._take()
        name = token.value.lower() if token.kind == "word" else ""
        if name in {"true", "false"}:
            return lambda _m: name == "true"
        if name == "not":
            inner = self._test()
            return lambda m: not inner(m)
        if name in {"allof", "anyof"}:
            return self._group(all if name == "allof" else any)
        if name in {"address", "header"}:
            return self._match(name)
        raise UnsupportedSieve(name or "syntax", token.line)

    def _group(self, combine: Callable[[list[bool]], bool]) -> _Test:
        self._expect("(")
        tests = [self._test()]
        while self.current.value == ",":
            self.pos += 1
            tests.append(self._test())
        self._expect(")")
        return lambda m: combine([test(m) for test in tests])

    def _match(self, kind: str) -> _Test:
        op, part = "is", "all"
        while self.current.kind == "tag":
            tag = self._take().value.lower()[1:]
            if tag in {"is", "contains", "matches"}:
                op = tag
            elif tag in {"all", "localpart", "domain"} and kind == "address":
                part = tag
            else:
                self.pos -= 1
                raise self._fail(f":{tag}")
        fields = {_fold(name) for name in self._strings()}
        keys = self._strings()
        if not fields <= _FIELDS:
            raise self._fail("header name")
        tests = [self._field_test(f, kind, op, part, keys) for f in sorted(fields)]
        return lambda m: any(test(m) for test in tests)

    def _field_test(
        self, name: str, kind: str, op: str, part: str, keys: list[str]
    ) -> _Test:
        if name == "to":
            if op == "matches" or part != "all":
                raise self._fail("to test")
            folded = [_fold(key) for key in keys]
            self.keys.extend(key for key in folded if key not in self.keys)
            if len(self.keys) > _MAX_RECIPIENT_KEYS:
                raise self._fail("recipient keys")
            return lambda m: any(key in m.to_keys for key in folded)
        matchers = [_matcher(op, key) for key in keys]
        if name == "subject":
            return lambda m: any(match(m.subject) for match in matchers)
        if kind == "address":
            return lambda m: bool(m.from_address) and any(
                match(_address_part(m.from_address, part)) for match in matchers
            )

        def header(message: MailMessage) -> bool:
            named = f"{message.from_name} <{message.from_address}>"
            value = named if message.from_name else message.from_address
            return any(match(value) for match in matchers)

        return header


def _run(body: tuple[_Command, ...], message: MailMessage, state: _State) -> bool:
    return any(command(message, state) for command in body)


def compile_script(script: str) -> CompiledScript:
    """Parse `script` once; raise `UnsupportedSieve` outside the subset. BR-6, BR-11."""
    parser = _Parser(script)
    try:
        program = parser.commands(top=True)
    except RecursionError:
        raise UnsupportedSieve("nesting", parser.current.line) from None
    targets = tuple({t.casefold(): t for t in reversed(parser.mailboxes)}.values())[
        ::-1
    ]
    return CompiledScript(program, targets, tuple(parser.keys))


def evaluate(compiled: CompiledScript, message: MailMessage) -> Outcome:
    """Run the script alone over `message`. BR-8."""
    state = _State()
    _run(compiled.program, message, state)
    ordered = tuple({t.casefold(): t for t in reversed(state.files)}.values())[::-1]
    return Outcome(ordered, frozenset(state.flags), state.expire_days)

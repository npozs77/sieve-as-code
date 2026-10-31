"""Declared filter files: load, validate and render (FR-DECL.1-5, FR-DECL.7)."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from sieve_as_code.model import Filter, FilterOrder, ValidationError
from sieve_as_code.settings import AccountPaths

_FILTER_KEYS = frozenset({"name", "raw_sieve", "enabled"})

# BR-17: extension-gated commands and tags; both match case-insensitively.
_COMMAND_EXTENSIONS = {
    "fileinto": "fileinto",
    "reject": "reject",
    "ereject": "ereject",
    "vacation": "vacation",
    "include": "include",
    "set": "variables",
    "addflag": "imap4flags",
    "setflag": "imap4flags",
    "removeflag": "imap4flags",
}
_TAG_EXTENSIONS = {"copy": "copy", "regex": "regex"}
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Mailbox:
    """A `fileinto` target; `name` is None when it is not a plain quoted string."""

    line: int
    name: str | None


@dataclass(frozen=True)
class ScriptFacts:
    """What `plan` needs from a script: `require` extensions and `fileinto` targets."""

    required: frozenset[str]
    mailboxes: tuple[Mailbox, ...]


class _Scanner:
    """One pass over a Sieve script for BR-16, BR-17 and facts; never judges grammar."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.line = 1
        self.open: list[tuple[str, int]] = []
        self.required: set[str] = set()
        self.uses: list[tuple[str, int, str]] = []
        self.command_position = True
        self.in_require = False
        self.mailbox_line: int | None = None
        self.mailbox: str | None = None
        self.mailboxes: list[Mailbox] = []

    def problem(self) -> str | None:
        """First certain error as `line N: ...`, or None."""
        while self.pos < len(self.text):
            found = self._step()
            if found:
                return found
        self._end_fileinto()
        if self.open:
            char, line = self.open[-1]
            return f"line {line}: unbalanced {char!r}"
        for name, line, extension in self.uses:
            if extension not in self.required:
                return f'line {line}: {name!r} needs require "{extension}"'
        return None

    def _step(self) -> str | None:
        text, pos = self.text, self.pos
        char = text[pos]
        if char == "\n":
            self.line += 1
        elif char == "#":
            self.pos = text.find("\n", pos) if "\n" in text[pos:] else len(text)
            return None
        elif text.startswith("/*", pos):
            return self._skip_block_comment()
        elif char == '"':
            return self._read_string()
        elif char in "{[":
            self.open.append((char, self.line))
            self.command_position = char == "{"
        elif char in "}]":
            return self._close(char)
        elif char == ";":
            self._end_fileinto()
            self.command_position = True
            self.in_require = False
        elif char == ":" and (tag := _WORD.match(text, pos + 1)):
            self._use_tag(tag.group().lower())
            self.pos = tag.end()
            return None
        elif word := _WORD.match(text, pos):
            return self._read_word(word)
        self.pos += 1
        return None

    def _skip_block_comment(self) -> str | None:
        end = self.text.find("*/", self.pos + 2)
        if end == -1:
            return f"line {self.line}: unterminated comment"
        self.line += self.text.count("\n", self.pos, end)
        self.pos = end + 2
        return None

    def _read_string(self) -> str | None:
        text, start = self.text, self.line
        pos = self.pos + 1
        while pos < len(text) and text[pos] != '"':
            if text[pos] == "\\":
                pos += 1
            self.line += text[pos : pos + 1] == "\n"
            pos += 1
        if pos >= len(text):
            return f"line {start}: unterminated string"
        if self.in_require:
            self.required.add(text[self.pos + 1 : pos].lower())
        if self.mailbox_line is not None:
            value = text[self.pos + 1 : pos]
            self.mailbox = None if "${" in value else re.sub(r"\\(.)", r"\1", value)
        self.pos = pos + 1
        self.command_position = False
        return None

    def _close(self, char: str) -> str | None:
        if char == "]":
            self.mailbox = None
        wanted = "{" if char == "}" else "["
        if not self.open or self.open[-1][0] != wanted:
            return f"line {self.line}: unbalanced {char!r}"
        self.open.pop()
        self.command_position = char == "}"
        self.pos += 1
        return None

    def _use_tag(self, tag: str) -> None:
        if tag in _TAG_EXTENSIONS:
            self.uses.append((f":{tag}", self.line, _TAG_EXTENSIONS[tag]))
        self.command_position = False

    def _read_word(self, word: re.Match[str]) -> str | None:
        name = word.group().lower()
        self.pos = word.end()
        rest = self.text[self.pos :].split("\n", 1)[0]
        if name == "text" and re.fullmatch(r":[ \t\r]*(#.*)?", rest):
            return self._skip_text_block(len(rest))
        if self.command_position:
            if name in _COMMAND_EXTENSIONS:
                self.uses.append((name, self.line, _COMMAND_EXTENSIONS[name]))
            self.in_require = name == "require"
            if name == "fileinto":
                self.mailbox_line, self.mailbox = self.line, None
                self.command_position = False
                return None
        self.mailbox = None
        self.command_position = False
        return None

    def _end_fileinto(self) -> None:
        """Unit 4 BR-17: the last argument before `;` is the mailbox."""
        if self.mailbox_line is not None:
            self.mailboxes.append(Mailbox(self.mailbox_line, self.mailbox))
            self.mailbox_line = None

    def _skip_text_block(self, rest_length: int) -> str | None:
        start = self.line
        lines = self.text[self.pos + rest_length :].split("\n")
        for count, body_line in enumerate(lines[1:], start=1):
            if body_line.rstrip("\r") == ".":
                self.line += count
                self.pos += rest_length + sum(len(item) + 1 for item in lines[:count])
                self.pos += len(body_line)
                self.mailbox = None
                self.command_position = False
                return None
        return f"line {start}: unterminated text: block"


def _script_problem(script: str) -> str | None:
    """BR-16, BR-17, BR-18: a certain structural error in `script`, else None."""
    return _Scanner(script).problem()


def script_facts(script: str) -> ScriptFacts:
    """`require` extensions and `fileinto` targets of `script` (Unit 4 BR-17)."""
    scanner = _Scanner(script)
    scanner.problem()
    return ScriptFacts(frozenset(scanner.required), tuple(scanner.mailboxes))


def normalize_whitespace(script: str) -> str:
    """Tabs to 4 spaces, no trailing whitespace per line or at the end. BR-12."""
    return "\n".join(line.expandtabs(4).rstrip() for line in script.split("\n")).rstrip(
        "\n"
    )


def _check_filter(label: str, item: Filter) -> None:
    """BR-4, BR-16, BR-17 for one filter; `label` names the file or filter."""
    for field in ("name", "raw_sieve"):
        value: Any = getattr(item, field)
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{label}: '{field}' must be a non-blank string")
    enabled: Any = item.enabled
    if not isinstance(enabled, bool):
        raise ValidationError(f"{label}: 'enabled' must be true or false")
    if found := _script_problem(item.raw_sieve):
        raise ValidationError(f"{label}: raw_sieve {found}")


def _check_duplicates(filters: Sequence[Filter], labels: Sequence[str] | None) -> None:
    """BR-6; `labels` are the file names when loaded from files."""
    seen: dict[str, int] = {}
    for index, item in enumerate(filters):
        if item.name in seen:
            where = f" ({labels[seen[item.name]]}, {labels[index]})" if labels else ""
            raise ValidationError(f"duplicate filter name {item.name!r}{where}")
        seen[item.name] = index


def _check_order(filters: Sequence[Filter], order: FilterOrder, label: str) -> None:
    """BR-8: the sequence lists every declared filter exactly once."""
    declared = {item.name for item in filters}
    listed: set[str] = set()
    for name in order.sequence:
        if name in listed:
            raise ValidationError(f"{label}: 'sequence' lists {name!r} twice")
        if name not in declared:
            raise ValidationError(f"{label}: 'sequence' lists unknown filter {name!r}")
        listed.add(name)
    for name in sorted(declared - listed):
        raise ValidationError(f"{label}: 'sequence' is missing filter {name!r}")


def validate_declared(filters: Sequence[Filter], order: FilterOrder) -> None:
    """Raise `ValidationError` on the first FR-DECL.5 or FR-DECL.7 failure. BR-9."""
    for item in filters:
        _check_filter(f"filter {item.name!r}", item)
    _check_duplicates(filters, None)
    _check_order(filters, order, "order")


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise ValidationError(f"{path.name}: cannot read as YAML ({error})") from error
    if not isinstance(parsed, dict):
        raise ValidationError(f"{path.name}: must be a YAML mapping")
    return parsed


def _load_filter(path: Path) -> Filter:
    """BR-3, BR-4, BR-5, BR-16, BR-17 for one file."""
    entry = _read_mapping(path)
    for key in entry:
        if key not in _FILTER_KEYS:
            raise ValidationError(f"{path.name}: unknown key {key!r}")
    for field in ("name", "raw_sieve"):
        if field not in entry:
            raise ValidationError(f"{path.name}: missing field '{field}'")
    item = Filter(
        name=entry["name"],
        raw_sieve=entry["raw_sieve"],
        enabled=entry.get("enabled", True),
    )
    _check_filter(path.name, item)
    return item


def _load_order(path: Path) -> FilterOrder:
    """BR-7."""
    entry = _read_mapping(path)
    if set(entry) != {"sequence"}:
        raise ValidationError(f"{path.name}: must hold exactly the key 'sequence'")
    names = entry["sequence"]
    if not isinstance(names, list) or not all(
        isinstance(name, str) and name.strip() for name in names
    ):
        raise ValidationError(f"{path.name}: 'sequence' must be a list of filter names")
    return FilterOrder(sequence=tuple(names))


def load_declared(paths: AccountPaths) -> tuple[list[Filter], FilterOrder]:
    """Parse and validate an account's filter files and order file. BR-1 to BR-9."""
    if not paths.filters_dir.is_dir():
        raise ValidationError(
            f"filters directory {paths.filters_dir} not found; "
            "run `sieve-as-code import` or create it"
        )
    if not paths.order_file.is_file():
        raise ValidationError(
            f"order file {paths.order_file} not found; "
            "run `sieve-as-code import` or create it"
        )
    files = sorted(path for path in paths.filters_dir.glob("*.yaml") if path.is_file())
    filters = [_load_filter(path) for path in files]
    _check_duplicates(filters, [path.name for path in files])
    order = _load_order(paths.order_file)
    _check_order(filters, order, paths.order_file.name)
    return filters, order


def _filter_filename(name: str) -> str:
    """BR-10: `<name>.yaml` that cannot leave or hide inside the directory."""
    safe = re.sub(r"[/\\\x00]", "_", name)
    if safe.startswith("."):
        safe = "_" + safe[1:]
    return f"{safe}.yaml"


class _BlockDumper(yaml.SafeDumper):
    """Writes multi-line strings as `|` literal blocks. BR-13."""


_BlockDumper.add_representer(
    str,
    lambda dumper, value: dumper.represent_scalar(
        "tag:yaml.org,2002:str", value, style="|" if "\n" in value else None
    ),
)


def _dump(data: dict[str, Any]) -> str:
    return yaml.dump(
        data, Dumper=_BlockDumper, sort_keys=False, allow_unicode=True, width=1000
    )


def render(
    filters: Sequence[Filter], order: FilterOrder, paths: AccountPaths
) -> dict[Path, str]:
    """File text per path for the declared files; writes nothing. BR-10 to BR-14."""
    rendered: dict[Path, str] = {paths.order_file: _dump({"sequence": order.sequence})}
    owners: dict[str, str] = {}
    for item in filters:
        filename = _filter_filename(item.name)
        key = unicodedata.normalize("NFC", filename).casefold()
        if key in owners:
            raise ValidationError(
                f"filters {owners[key]!r} and {item.name!r} would share "
                f"the file name {filename!r}"
            )
        owners[key] = item.name
        entry: dict[str, Any] = {
            "name": item.name,
            "raw_sieve": normalize_whitespace(item.raw_sieve),
        }
        if not item.enabled:
            entry["enabled"] = False
        rendered[paths.filters_dir / filename] = _dump(entry)
    return rendered

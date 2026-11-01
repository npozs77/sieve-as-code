"""Write live filters or plain `.sieve` files into the declared files (FR-DISC.2-3)."""

import os
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path

from sieve_as_code.client import ProtonClient
from sieve_as_code.declared import (
    free_filename,
    load_local,
    normalize_whitespace,
    render,
    validate_declared,
)
from sieve_as_code.live import discover
from sieve_as_code.model import (
    Filter,
    FilterOrder,
    Rename,
    SieveAsCodeError,
    ValidationError,
)
from sieve_as_code.settings import AccountPaths

_SIEVE_SUFFIX = ".sieve"


@dataclass(frozen=True)
class ImportReport:
    """Outcome of an import; names and paths only. BR-11, BR-16."""

    refused: bool = False
    new: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    reordered: bool = False
    preserved: tuple[str, ...] = ()
    written: tuple[Path, ...] = ()
    renamed: tuple[Rename, ...] = ()

    @property
    def ok(self) -> bool:
        """True unless the import was refused."""
        return not self.refused


@dataclass(frozen=True)
class _Incoming:
    """Filters to import; `sequence` is the live order, None for single/file modes."""

    filters: tuple[Filter, ...]
    sequence: tuple[str, ...] | None
    keep_local_enabled: bool


def import_live(
    paths: AccountPaths,
    client: ProtonClient,
    name: str | None = None,
    force: bool = False,
) -> ImportReport:
    """Import all live filters, or only `name`; refuse differences without `force`."""
    if paths.account != client.account:  # BR-1
        raise ValidationError(
            f"account mismatch: files are for {paths.account!r}, "
            f"client is for {client.account!r}"
        )
    live = discover(client)  # BR-2
    chosen = live.filters
    if name is not None:  # BR-3
        chosen = tuple(item for item in chosen if item.name == name)
        if not chosen:
            raise ValidationError(f"no live filter named {name!r}")
    incoming = _Incoming(
        tuple(replace(item, live_id=None) for item in chosen),
        live.order.sequence if name is None else None,
        keep_local_enabled=False,
    )
    return replace(_import(paths, incoming, force), renamed=live.renames)


def import_sieve_files(
    paths: AccountPaths, sources: Sequence[Path], force: bool = False
) -> ImportReport:
    """Import plain `.sieve` files as filters named by file name. BR-4."""
    filters: list[Filter] = []
    seen: dict[str, Path] = {}
    for source in sources:
        if source.suffix.lower() != _SIEVE_SUFFIX:
            raise ValidationError(f"{source}: not a {_SIEVE_SUFFIX} file")
        name = source.stem
        if name in seen:
            raise ValidationError(
                f"{seen[name]} and {source} both name filter {name!r}"
            )
        seen[name] = source
        try:
            script = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValidationError(f"{source}: cannot read ({exc.strerror})") from exc
        except UnicodeDecodeError as exc:
            raise ValidationError(f"{source}: not valid UTF-8") from exc
        filters.append(Filter(name, script))
    return _import(paths, _Incoming(tuple(filters), None, True), force)


@dataclass(frozen=True)
class _Local:
    """Local filters by name with their file, and the order file's sequence."""

    by_name: dict[str, tuple[Path, Filter]]
    sequence: tuple[str, ...] | None


def _import(paths: AccountPaths, incoming: _Incoming, force: bool) -> ImportReport:
    """Validate, compare with local state, then refuse or write. BR-5 to BR-12."""
    names = tuple(item.name for item in incoming.filters)
    validate_declared(list(incoming.filters), FilterOrder(names))  # BR-5
    files, sequence = load_local(paths)  # BR-6
    local = _Local({item.name: (path, item) for path, item in files.items()}, sequence)
    filters = [
        (
            replace(item, enabled=local.by_name[item.name][1].enabled)
            if incoming.keep_local_enabled and item.name in local.by_name
            else item
        )
        for item in incoming.filters
    ]
    new = tuple(item.name for item in filters if item.name not in local.by_name)
    changed = tuple(item.name for item in filters if _differs(item, local))  # BR-7
    merged, preserved, reordered = _new_order(incoming, new, local)
    if (changed or reordered) and not force:  # BR-11
        return ImportReport(True, new, changed, reordered, preserved)
    todo = _files_to_write(paths, filters, set(new) | set(changed), local)
    if local.sequence is None or merged != local.sequence:
        order_text = render([], FilterOrder(merged), paths)[paths.order_file]
        todo.append((paths.order_file, order_text))
    if todo:
        _write_files(paths, todo)
    written = tuple(path for path, _ in todo)
    return ImportReport(False, new, changed, reordered, preserved, written)


def _differs(item: Filter, local: _Local) -> bool:
    """BR-7: a local filter of this name with another script or `enabled`."""
    if item.name not in local.by_name:
        return False
    have = local.by_name[item.name][1]
    return (
        normalize_whitespace(have.raw_sieve) != normalize_whitespace(item.raw_sieve)
        or have.enabled != item.enabled
    )


def _new_order(
    incoming: _Incoming, new: tuple[str, ...], local: _Local
) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    """BR-8 to BR-10: the new sequence, preserved local-only names, reordered flag."""
    listed = [n for n in dict.fromkeys(local.sequence or ()) if n in local.by_name]
    current = listed + sorted(n for n in local.by_name if n not in listed)
    if incoming.sequence is None:
        return tuple(current) + new, (), False
    live = set(incoming.sequence)
    preserved = tuple(name for name in current if name not in live)
    merged = incoming.sequence + preserved
    moved = [name for name in merged if name in local.by_name] != current
    return merged, preserved, local.sequence is not None and moved


def _filter_text(item: Filter, paths: AccountPaths) -> str:
    """The rendered file text of one filter (Unit 3 BR-13)."""
    rendered = render([item], FilterOrder((item.name,)), paths)
    del rendered[paths.order_file]
    return next(iter(rendered.values()))


def _files_to_write(
    paths: AccountPaths, filters: list[Filter], selected: set[str], local: _Local
) -> list[tuple[Path, str]]:
    """BR-12, BR-13: path and text of each new or changed filter, in incoming order."""
    taken = {path.name for path in paths.filters_dir.glob("*")}
    todo: list[tuple[Path, str]] = []
    for item in filters:
        if item.name not in selected:
            continue
        if item.name in local.by_name:
            path = local.by_name[item.name][0]
        else:
            filename = free_filename(item.name, taken)
            taken.add(filename)
            path = paths.filters_dir / filename
        todo.append((path, _filter_text(item, paths)))
    return todo


def _write_files(paths: AccountPaths, todo: list[tuple[Path, str]]) -> None:
    """BR-14: temp file and `os.replace` per file; `OSError` becomes a named error."""
    for path, text in todo:
        temp = path.with_name(f".{path.name}.tmp")
        try:
            paths.filters_dir.mkdir(parents=True, exist_ok=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(text, encoding="utf-8")
            os.replace(temp, path)
        except OSError as exc:
            with suppress(OSError):
                temp.unlink()
            raise SieveAsCodeError(f"cannot write {path}: {exc.strerror}") from exc

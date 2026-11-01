"""An in-memory `proton` standing in for the subprocess boundary."""

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_PREFIX = ["--profile", "work", "--no-input", "--output", "json"]


@dataclass(frozen=True)
class Call:
    """One recorded `proton` invocation."""

    argv: list[str]
    stdin: str | None
    path: tuple[str, ...]

    @property
    def verb(self) -> str:
        return self.path[-1]


@dataclass
class FakeProton:
    """Models filters, order, folders, labels and the account id; records calls.

    A test steers failures with `failures`, `outputs` and `hangs`, keyed by the
    command path joined with spaces, e.g. "mail settings filters list".
    """

    version_output: str = "proton version 4.3.0\n"
    version_exit: int = 0
    account_id: str = "Kd91mQxT7v"
    signed_in: bool = True
    missing: bool = False
    filters: list[dict[str, Any]] = field(default_factory=list)
    folders: list[dict[str, Any]] = field(default_factory=list)
    labels: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    failures: dict[str, tuple[int, str]] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    hangs: set[str] = field(default_factory=set)
    calls: list[Call] = field(default_factory=list)
    _counter: int = 0

    def add_filter(self, name: str, sieve: str = "keep;", status: int = 1) -> str:
        """Seed a live filter at the end of the order; returns its id."""
        self._counter += 1
        live_id = f"f{self._counter}"
        self.filters.append(
            {"id": live_id, "name": name, "status": status, "sieve": sieve}
        )
        return live_id

    def names(self) -> list[str]:
        return [entry["name"] for entry in self.filters]

    def run(
        self,
        argv: list[str],
        input: str | None = None,  # noqa: A002 - mirrors subprocess.run
        **options: Any,
    ) -> subprocess.CompletedProcess[str]:
        """Stands in for `subprocess.run`."""
        if self.missing:
            raise FileNotFoundError(argv[0])
        if argv[1:] == ["--version"]:
            self.calls.append(Call(argv, input, ("--version",)))
            return self._done(argv, self.version_exit, self.version_output)
        assert argv[1:6] == _PREFIX, f"unexpected argv prefix: {argv[1:6]}"
        path, args = self._split(argv[6:])
        self.calls.append(Call(argv, input, path))
        key = " ".join(path)
        if key in self.hangs:
            raise subprocess.TimeoutExpired(argv, options.get("timeout", 0))
        if key in self.failures:
            code, stderr = self.failures[key]
            return self._done(argv, code, "", stderr)
        if key in self.outputs:
            return self._done(argv, 0, self.outputs[key])
        code, body, stderr = self._handlers()[path](args, input)
        return self._done(
            argv, code, json.dumps(body) if body is not None else "", stderr
        )

    @staticmethod
    def _done(
        argv: list[str], code: int, out: str, err: str = ""
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, code, out, err)

    def _split(self, rest: list[str]) -> tuple[tuple[str, ...], list[str]]:
        for size in (4, 3, 2):
            if tuple(rest[:size]) in self._handlers():
                return tuple(rest[:size]), rest[size:]
        raise AssertionError(f"command not modelled: {rest}")

    def _handlers(
        self,
    ) -> dict[tuple[str, ...], Callable[[list[str], str | None], tuple[int, Any, str]]]:
        filters = ("mail", "settings", "filters")
        return {
            ("account", "get"): self._account_get,
            (*filters, "list"): self._filters_list,
            (*filters, "get"): self._filters_get,
            (*filters, "create"): self._filters_create,
            (*filters, "update"): self._filters_update,
            (*filters, "delete"): self._filters_delete,
            (*filters, "enable"): lambda a, _: self._set_status(a, 1),
            (*filters, "disable"): lambda a, _: self._set_status(a, 0),
            (*filters, "reorder"): self._filters_reorder,
            (*filters, "apply"): lambda _a, _: (0, {"action": "applied"}, ""),
            ("mail", "settings", "folders", "list"): lambda _a, _: self._listing(
                "folders", self.folders
            ),
            ("mail", "settings", "labels", "list"): lambda _a, _: self._listing(
                "labels", self.labels
            ),
            (
                "mail",
                "settings",
                "folders",
                "create",
            ): lambda a, _: self._create_target(a, self.folders),
            ("mail", "settings", "labels", "create"): lambda a, _: self._create_target(
                a, self.labels
            ),
            ("mail", "messages", "list"): lambda _a, _: self._listing(
                "messages", self.messages
            ),
        }

    def _account_get(self, args: list[str], stdin: str | None) -> tuple[int, Any, str]:
        if not self.signed_in:
            return 2, None, "not signed in"
        return 0, {"id": self.account_id, "profile": "work", "session": "valid"}, ""

    def _listing(self, key: str, rows: list[dict[str, Any]]) -> tuple[int, Any, str]:
        return 0, {key: rows, "count": len(rows)}, ""

    def _find(self, ref: str) -> dict[str, Any] | None:
        return next((e for e in self.filters if ref in (e["id"], e["name"])), None)

    def _filters_list(self, args: list[str], stdin: str | None) -> tuple[int, Any, str]:
        assert args == ["--limit", "0"]
        summaries = [{k: e[k] for k in ("id", "name", "status")} for e in self.filters]
        return (
            0,
            {"filters": summaries, "count": len(summaries), "total": len(summaries)},
            "",
        )

    def _filters_get(self, args: list[str], stdin: str | None) -> tuple[int, Any, str]:
        entry = self._find(args[0])
        return (0, entry, "") if entry else (3, None, "no such filter")

    def _filters_create(
        self, args: list[str], stdin: str | None
    ) -> tuple[int, Any, str]:
        assert args[2:4] == ["--sieve", "-"] and stdin is not None
        live_id = self.add_filter(args[1], stdin, 0 if "--disabled" in args else 1)
        return (
            0,
            {"action": "created", "count": 1, "ids": [live_id], "kind": "filter"},
            "",
        )

    def _filters_update(
        self, args: list[str], stdin: str | None
    ) -> tuple[int, Any, str]:
        entry = self._find(args[0])
        if entry is None:
            return 3, None, "no such filter"
        assert args[1:] == ["--sieve", "-"] and stdin is not None
        entry["sieve"] = stdin
        return 0, {"action": "updated"}, ""

    def _filters_delete(
        self, args: list[str], stdin: str | None
    ) -> tuple[int, Any, str]:
        entry = self._find(args[0])
        if entry is None:
            return 3, None, "no such filter"
        if "--yes" not in args:
            return 1, None, "confirmation needed"
        self.filters.remove(entry)
        return 0, {"action": "deleted"}, ""

    def _set_status(self, args: list[str], status: int) -> tuple[int, Any, str]:
        entry = self._find(args[0])
        if entry is None:
            return 3, None, "no such filter"
        entry["status"] = status
        return 0, {"action": "updated"}, ""

    def _filters_reorder(
        self, args: list[str], stdin: str | None
    ) -> tuple[int, Any, str]:
        named = [e for ref in args if (e := self._find(ref)) is not None]
        self.filters[:] = named + [e for e in self.filters if e not in named]
        return 0, {"action": "reordered"}, ""

    def _create_target(
        self, args: list[str], rows: list[dict[str, Any]]
    ) -> tuple[int, Any, str]:
        name = args[1]
        parent = next(
            (r for r in self.folders if "--parent" in args and r["id"] == args[3]), None
        )
        path = f"{parent['path']}/{name}" if parent else name
        rows.append({"id": f"t{len(rows) + 1}", "name": name, "path": path})
        return 0, {"action": "created"}, ""

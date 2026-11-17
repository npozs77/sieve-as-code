"""Live smoke tests (NFR-TEST.2); run with `make live`."""

import contextlib

import yaml

from sieve_as_code import cli
from sieve_as_code._model import ClientError
from tests.live.conftest import Live, scratch

KEEP = "keep;"
STOP = "stop;"


def live_names(live: Live) -> list[str]:
    return [ref.name for ref in live.client.list_filters()]


def declare(live: Live, **scripts: str) -> None:
    live.paths.filters_dir.mkdir(parents=True, exist_ok=True)
    for name, script in scripts.items():
        entry = {"name": name, "raw_sieve": script}
        (live.paths.filters_dir / f"{name}.yaml").write_text(yaml.safe_dump(entry))
    live.paths.order_file.write_text(yaml.safe_dump({"sequence": list(scripts)}))


def test_create_update_enable_disable_delete(live: Live) -> None:
    name = scratch("crud")
    live_id = live.client.create_filter(name, KEEP, enabled=False)
    assert [r.enabled for r in live.client.list_filters() if r.name == name] == [False]
    live.client.enable_filter(live_id)
    live.client.update_filter(live_id, STOP)
    assert live.client.get_filter(live_id).raw_sieve.strip() == STOP
    live.client.disable_filter(live_id)
    assert [r.enabled for r in live.client.list_filters() if r.name == name] == [False]
    live.client.delete_filter(live_id)
    assert name not in live_names(live)


def test_reorder(clean_account: Live) -> None:
    first = clean_account.client.create_filter(scratch("a"), KEEP)
    second = clean_account.client.create_filter(scratch("b"), KEEP)
    clean_account.client.reorder_filters([second, first])
    assert live_names(clean_account) == [scratch("b"), scratch("a")]


def test_backup_snapshot_holds_the_live_filter(live: Live) -> None:
    live.client.create_filter(scratch("snap"), KEEP)
    assert cli.main(["backup"]) == 0
    snapshots = list(live.paths.backups_dir.glob("*.json"))
    assert len(snapshots) == 1 and scratch("snap") in snapshots[0].read_text()


def test_import_live_filter_and_sieve_file(live: Live) -> None:
    name = scratch("imp")
    live.client.create_filter(name, KEEP)
    assert cli.main(["import", name, "--force"]) == 0
    written = yaml.safe_load((live.paths.filters_dir / f"{name}.yaml").read_text())
    assert written["raw_sieve"].strip() == KEEP
    source = live.paths.filters_dir.parent / f"{scratch('file')}.sieve"
    source.write_text(STOP + "\n")
    assert cli.main(["import", "--sieve", str(source)]) == 0
    assert (live.paths.filters_dir / f"{scratch('file')}.yaml").exists()


def test_apply_then_restore_round_trip(clean_account: Live) -> None:
    declare(clean_account, **{scratch("rt"): KEEP})
    assert cli.main(["apply", "--yes"]) == 0
    assert live_names(clean_account) == [scratch("rt")]
    assert cli.main(["restore", "--yes"]) == 0
    assert live_names(clean_account) == []


def test_invalid_script_is_rejected_and_leaves_no_filter(clean_account: Live) -> None:
    declare(clean_account, **{scratch("bad"): "frobnicate;"})
    assert cli.main(["apply", "--yes"]) == 1
    assert live_names(clean_account) == []
    with contextlib.suppress(ClientError):
        clean_account.client.create_filter(scratch("bad"), "frobnicate;")
    assert scratch("bad") not in live_names(clean_account)

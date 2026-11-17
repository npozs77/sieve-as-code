# sieve-as-code

Proton Mail Sieve filters as code: plan before apply, backup before every write, restore on demand. Built on [`proton-cli`](https://github.com/roman-16/proton-cli) only.

**Status: feature-complete, not released.** The CLI and the Python API cover every command below; publishing is still to do. Design: [`concept.md`](concept.md).

## Requirements

- Python 3.12 or newer.
- [`proton-cli`](https://github.com/roman-16/proton-cli) 4.3.0 or newer (`proton`), signed in to every account you manage (one `proton` profile per account). 4.3.0 is the tested range: an older version prints a warning on stderr and continues; a newer one runs silently.

## Configuration

Environment variables only; [`.env.example`](.env.example) lists them.

| Variable | Default | Meaning |
|----------|---------|---------|
| `SIEVE_AS_CODE_FILTERS_DIR` | `$XDG_CONFIG_HOME/sieve-as-code`, else `~/.config/sieve-as-code` | Root of the declared files, one directory per account |
| `SIEVE_AS_CODE_STATE_DIR` | `$XDG_STATE_HOME/sieve-as-code`, else `~/.local/state/sieve-as-code` | Root of backups, retroactive snapshots and the audit log |
| `SIEVE_AS_CODE_ACCOUNT` | `default` | Account (`proton` profile) used when none is given |
| `SIEVE_AS_CODE_PROTON_CLI` | `proton` | Path of the `proton` binary |
| `SIEVE_AS_CODE_KEEP_DAYS` | unset | `backup` keeps snapshots newer than this many days (with `KEEP_LAST`, either keeps one) |
| `SIEVE_AS_CODE_KEEP_LAST` | unset | `backup` keeps this many newest snapshots; both unset means nothing is pruned |

## Multiple accounts

An account is a `proton` profile name. Each account has its own declared files, backups, retroactive snapshots and audit log; a command acts on exactly one account.

```sh
proton --profile personal account login     # once per account
proton --profile personal account get       # check: Session valid, Unlocked yes
export SIEVE_AS_CODE_ACCOUNT=personal       # default account; --account NAME overrides it per command
```

Layout (default roots; see [Configuration](#configuration)):

```
~/.config/sieve-as-code/<account>/{filters/, order.yaml, account.id}
~/.local/state/sieve-as-code/<account>/{backups/, retroactive/, audit.log}
```

`account.id` holds a fingerprint of the Proton account, written on first use. If a profile is later signed in to a different Proton account, every command stops with "profile '<account>' now belongs to a different Proton account", and `restore` refuses a snapshot taken from another account. Delete `account.id` only if you mean to adopt the new account.

## Usage

```sh
sieve-as-code import                 # live filters -> declared files (--force to overwrite)
sieve-as-code import --sieve a.sieve # plain .sieve files -> declared files
sieve-as-code discover               # print live filters in the declared format
sieve-as-code plan                   # script diffs, declared vs live; changes nothing; exit 1 on drift
sieve-as-code apply --yes            # snapshot, then write only what differs (--allow-delete removes live-only filters)
sieve-as-code backup                 # snapshot live filters (--keep-days N, --keep-last N prune old ones)
sieve-as-code backup-diff A B        # compare two snapshots
sieve-as-code restore [BACKUP] --yes # pre-restore snapshot, then roll back
sieve-as-code apply-retroactive NAME # preview, typed name and reason, then run on existing mail
sieve-as-code retroactive-status [SNAPSHOT]  # done / pending / unexpected since a run
sieve-as-code retroactive-audit      # messages each enabled filter would change
```

Every command takes `--account NAME` and prints the account and its fingerprint first. Exit codes: 0 success, 1 refused, failed or a diff remains, 2 usage or validation error, 130 interrupted. `plan` exits 1 on drift and prints each created script and a unified diff of each change; a diff you asked to see with `backup-diff` is output, so it exits 0.

A rename is a delete plus a create: identity is the filter `name`.

Behaviour:
- `plan` is the drift detector and reports structure problems in the declared files before anything is written.
- Every write needs a preceding plan and `--yes`; a snapshot is taken first.
- Live filters that share a name are shown as `name`, `name (1)`, … and the renames are reported; nothing in Proton is renamed.
- A live-only filter is disabled, never deleted, unless you explicitly override.
- `apply` stops at the first failure and reports what succeeded, failed and was not attempted; there is no automatic rollback, `restore` is the way back.
- Every write and check is appended to a local audit log (names and counts, never scripts).

## Python API

```python
import sieve_as_code as sac

result = sac.plan(account="personal")      # PlanResult
sac.apply(account="personal", confirmed=True)
```

`sieve_as_code.__all__` is the whole public surface; everything else is internal. Each function takes its subject positionally and the rest by keyword, resolves the account (`account=None` as for the CLI) and connects itself. Results are frozen dataclasses that only gain fields with defaults; `SieveAsCodeError`, `ValidationError`, `ClientError` and `BackupError` are public.

| Function | Result |
|----------|--------|
| `discover`, `load_declared` | `FilterSet` |
| `plan`, `backup_diff(a, b)` | `PlanResult` |
| `apply(confirmed=, allow_delete=)` | `ApplyReport` |
| `restore(ref=None, confirmed=)` | `RestoreReport` |
| `import_live(name=None, force=)`, `import_sieve_files(sources, force=)` | `ImportReport` |
| `backup(keep_days=, keep_last=)` | `Snapshot` |
| `retroactive_preview(name)`, `apply_retroactive(name, confirmed_name=, reason=)` | `RetroPreview`, `RetroReport` |
| `retroactive_status(ref=None)`, `retroactive_audit()` | `RetroStatus`, `RetroAudit` |
| `validate_declared(declared)` | raises `ValidationError` |

Versioning follows semver and is provisional until 1.0: the 0.x API may still change, with a [changelog](CHANGELOG.md) entry. Direction up to 1.0: [`ROADMAP.md`](ROADMAP.md).

## Declared files

Per account, `<SIEVE_AS_CODE_FILTERS_DIR>/<account>/filters/<name>.yaml` holds one filter and `<account>/order.yaml` the order:

```yaml
name: receipts
raw_sieve: |-
  require ["fileinto"];
  if header :contains "subject" "receipt" { fileinto "Receipts"; }
enabled: false   # optional, default true
```

```yaml
sequence:
  - receipts
```

- Identity is `name`; the file name is only a label. `/` and `\` in a name become `_` in the file name, and names whose file names differ only by case are refused when files are written.
- Loading checks structure only: keys, types, unique names, a complete order, and certain Sieve errors (unbalanced braces, unterminated strings, `fileinto` and similar used without `require`). Proton remains the authority on the rest.

> **Use at your own risk.** This tool changes the filters of a real mailbox through an unofficial client, and a retroactive run can move years of mail with no way to cancel it. It is provided as is, without warranty (see [`LICENSE`](LICENSE)). Read the plan, keep the backups, and test on an account you can afford to break.

Licence: MIT.

## Integration tests

`make integration` runs against two real accounts and is skipped otherwise: `SIEVE_AS_CODE_IT_ACCOUNTS=<profile>,<other profile>` enables the read-only isolation tests. Add `SIEVE_AS_CODE_IT_WRITE=1` for an apply/restore round trip that writes one disabled, unmatchable filter to the second account, which must have no filters, and removes it. Profile names are never stored in the repository.

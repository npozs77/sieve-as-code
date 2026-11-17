# sieve-as-code

Proton Mail Sieve filters as code: plan before apply, backup before every write, restore on demand. Built on [`proton-cli`](https://github.com/roman-16/proton-cli) only.

**Status: work in progress, not released.** Built so far: configuration and per-account paths, the audit log, the `proton` client, declared files with validation, the library functions `discover` and `plan`, backup (`write_backup`, `read_backup`, `diff_backups`), `apply_plan` and `restore`, `import_live` and `import_sieve_files`, and retroactive `preview`, `run`, `status` and `audit_all` (no CLI yet). Not built yet: the CLI, so the commands under [Planned usage](#planned-usage) do not work yet. Design: [`concept.md`](concept.md).

## Requirements

- Python 3.12 or newer.
- [`proton-cli`](https://github.com/roman-16/proton-cli) 4.3.0 or newer (`proton`), signed in to every account you manage (one `proton` profile per account).

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

## Planned usage

```sh
sieve-as-code import                 # live filters -> declared files (--force to overwrite)
sieve-as-code discover               # print live filters in the declared format
sieve-as-code plan                   # diff declared vs live; changes nothing
sieve-as-code apply --yes            # snapshot, then write only what differs
sieve-as-code backup                 # snapshot live filters on demand
sieve-as-code backup-diff A B        # compare two snapshots
sieve-as-code restore [BACKUP] --yes # pre-restore snapshot, then roll back
sieve-as-code apply-retroactive NAME # preview, typed confirmation, then run on existing mail
```

Every command takes `--account NAME`. Also planned: `retroactive-status` and `retroactive-audit`, and a Python API with one function per command.

Intended behaviour:
- `plan` is the drift detector and reports structure problems in the declared files before anything is written.
- Every write needs a preceding plan and `--yes`; a snapshot is taken first.
- Live filters that share a name are shown as `name`, `name (1)`, … and the renames are reported; nothing in Proton is renamed.
- A live-only filter is disabled, never deleted, unless you explicitly override.
- `apply` stops at the first failure and reports what succeeded, failed and was not attempted; there is no automatic rollback, `restore` is the way back.
- Every write and check is appended to a local audit log (names and counts, never scripts).

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

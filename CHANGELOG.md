# Changelog

Format: [Keep a Changelog](https://keepachangelog.com). Semver, provisional until 1.0: the 0.x API and CLI options may still change, with an entry here.

## Unreleased (first release, 0.1.0)

Proton Mail Sieve filters as code on top of `proton-cli`: declare, plan, apply, back up, restore. Tested with `proton-cli` 4.3.0 and Python 3.12, 3.13 and 3.14.

### Commands

- `discover`: print live filters in the declared format. Filters sharing a name are shown as `name`, `name (1)`, …; nothing in Proton is renamed.
- `plan`: diff declared against live without changing anything. Lists missing folders and labels, creates, content and `enabled` changes, one reorder, and enabled live-only filters. Flags destructive extensions such as `vnd.proton.expire`. The outcome (`clean`, `drift`) is audit-logged.
- `apply [--yes] [--allow-delete]`: shows the plan and refuses to write without `--yes`. Snapshots first, writes only what differs, and stops at the first failure with a report of succeeded, failed and not attempted. Live-only filters are disabled, not deleted, unless `--allow-delete`. A repeat `apply` with no changes writes nothing.
- `import [NAME] [--force]` and `import --sieve FILE…`: write live filters or plain `.sieve` files into the declared files. Differing local files are listed and refused without `--force`; local-only filters are never deleted.
- `backup [--keep-days N] [--keep-last N]`: snapshot the live filters on demand; writes nothing when live state equals the latest snapshot. Optional pruning by newest N and/or age, from the flags or `SIEVE_AS_CODE_KEEP_LAST` and `SIEVE_AS_CODE_KEEP_DAYS`; the newest snapshot is never removed.
- `backup-diff A B`: the plan-style difference between two snapshots.
- `restore [BACKUP] [--yes]`: returns live filters to a snapshot (default: latest). Takes a snapshot of the current state first and aborts if that fails, deletes filters created after the backup, re-reads live state and succeeds only when it equals the backup.
- `apply-retroactive NAME`: runs one filter on existing mail. Prints a read-only preview first (count and, per message, date, sender, subject, location and action; Spam excluded), then requires the typed filter name and a reason. A confirmed run saves its preview as a snapshot (10-day retention) and is audit-logged with name and reason.
- `retroactive-status [SNAPSHOT]`: done, pending and unexpected messages against a run's snapshot.
- `retroactive-audit`: per enabled filter, how many existing messages a run would change, with notes for approximate and not-previewable filters.
- Every command takes `--account NAME` and prints the account and its fingerprint first. Exit codes: 0 success, 1 refused, failed or a diff remains, 2 usage or validation error, 130 interrupted.

### Safety

- No write to Proton without a plan and `--yes` (or the typed confirmation).
- Snapshots are versioned, checksummed, owner-only and never overwrite an existing file; reading verifies version and checksum.
- Account guard: each account has a fingerprint (first 12 hex characters of a SHA-256 of the Proton account id, never the email). A profile signed in to a different account stops every command, and `restore`, `backup-diff` and `retroactive-status` refuse a foreign snapshot.
- Audit log per account: append-only JSON lines with names, counts, outcome and timestamp; never scripts, senders or subjects.
- Scripts reach `proton-cli` on stdin only; sessions are checked before every command and nothing prompts interactively. A `proton-cli` older than the tested 4.3.0 warns on stderr and continues.
- Error messages carry only the first line of `proton`'s diagnostic, capped at 200 characters.

### Declared files

- One YAML file per filter (`name`, `raw_sieve`, optional `enabled`) plus an order file; all are validated before any plan or write, with errors naming the file and field.
- Structural checks on scripts: unbalanced braces or brackets, unterminated strings or comments, and extension commands used without `require`. Proton stays the authority on everything else.
- Per account: `<SIEVE_AS_CODE_FILTERS_DIR>/<account>/filters/*.yaml` and `order.yaml`; state in `<SIEVE_AS_CODE_STATE_DIR>/<account>/` (`backups/`, `retroactive/`, `audit.log`). Account names with a path separator, `..` or a leading `.` are rejected.
- Configuration by environment variables only (`.env.example` lists them); there is no `.env` loader.

### Retroactive preview

- Evaluates `address` and `header` tests on from, to and subject, `fileinto`, the `\Seen` and `\Flagged` flags, `expire`, `stop`, and Proton's generated spam guard. Anything else is reported as not previewable, never guessed, and the typed confirmation still gates the run.
- Recipient (`to`) tests are answered by Proton's recipient search, so those results are marked approximate; at most 10 distinct `to` addresses per filter.

### Python API

- `sieve_as_code.__all__` is the whole public surface: 14 functions (`discover`, `plan`, `apply`, `import_live`, `import_sieve_files`, `backup`, `backup_diff`, `restore`, `retroactive_preview`, `apply_retroactive`, `retroactive_status`, `retroactive_audit`, `load_declared`, `validate_declared`), frozen result dataclasses and the errors `SieveAsCodeError`, `ValidationError`, `ClientError`, `BackupError`.
- Subjects are positional, everything else keyword-only; each function resolves the account, connects and checks it. Paths and the client are not part of the API. Results only gain fields with defaults.

### Testing

- 668 unit tests (including property-based tests) at 100% line coverage; `proton-cli` is faked only at its subprocess boundary.
- Opt-in live smoke suite (`make live`, needs `SIEVE_AS_CODE_LIVE_TEST=1` and `SIEVE_AS_CODE_ACCOUNT`) using only throwaway filters named `sieve-as-code-test-*`, and opt-in two-account isolation tests (`make integration`).

### Known limitations

- Depends on the unofficial `proton-cli`; `--dry-run` is never trusted as proof a push will succeed.
- A rename is a delete plus a create: identity is the filter `name`.
- No automatic rollback; `restore` is the way back.
- The preview models one filter in isolation (as `filters apply NAME` runs it) and not the combined effect of all filters on a new message; `:list`, other header names, other flags and custom comparators make a filter not previewable.
- Retroactive runs cannot be cancelled once started.

# sieve-as-code — Concept

## What this is

Proton Mail Sieve filters managed as code: one YAML file per filter plus an order file, a plan (diff) before every write, a backup before every apply, and a typed confirmation before anything that touches existing mail. A Terraform-style discover → plan → apply loop for one or more Proton accounts, built on `proton-cli` only.

## Problem & audience

Proton's web UI gives filters no version history, no diff, no audit trail, and no safe way to preview a change. A mistake is invisible until it misroutes mail. The audience is Proton users who keep a non-trivial filter set and want it reviewable, reproducible and restorable. One account per command (several accounts supported), single operator, no staging account assumed: every design choice assumes mistakes land on the real mailbox.

## Scope

**In**
- Declarative filters: `name`, `raw_sieve`, optional `enabled`; order in a separate file.
- `discover`, `plan`, `apply`, `import`, `backup`, `restore`.
- Creating the folders and labels a filter files into, before the filters that need them.
- Retroactive runs (`filters apply`) behind a preview and a typed confirmation, plus status and audit reports.
- Audit log of every check and write: names and counts, never Sieve content.

**Out**
- Any backend other than `proton-cli`; no provider abstraction.
- UI scraping, own SRP login, manual-paste upload.
- Mail features beyond filters (aliases, DNS, search, reading mail).
- A structured filter vocabulary: a filter's content is its Sieve script, stored and pushed verbatim.

## Model

| Concept | Rule |
|---|---|
| Filter | `raw_sieve` verbatim; identity is `name`; `live_id` comes only from Proton |
| Order | One file; a reorder is one diff entry, never one per moved filter |
| Source of truth | The local files; `plan` is the drift detector, no baseline file |
| Targets | Folders and labels named by `fileinto` are listed by `plan` and created by `apply` before any filter write |

## Safety defaults

- Every real write is preceded by `plan` output and an explicit `--yes`.
- A snapshot of all live filters (content, `enabled`, order) is written before any write; `restore` returns to one and verifies the result.
- Stop on the first failure and report succeeded / failed / not attempted. No automatic rollback.
- A retroactive run shows which messages would change, excludes Spam, and requires the filter name and a reason typed back. It cannot be cancelled once started.
- Scripts reach `proton-cli` via `--sieve -` on stdin only; `--dry-run` is never treated as proof a push will succeed.

## Constraints

- `proton-cli` is unofficial and unaudited and stores a session on disk. State the tested version range; check the version at startup.
- `filters apply` runs asynchronously over the full mailbox history with no progress, cancel or scope preview.
- The retroactive preview evaluates a Sieve subset (`address`/`header` tests on from, to, subject; `fileinto`, flags, `expire`); anything else is reported as not previewable, never guessed.
- Default-allow filtering only: act on positively identified patterns, or label without hiding. Block-unless-known lists lose real mail when senders change domains.

## Roadmap

1. Per-filter size limit check in validation.
2. Flag destructive Proton extensions (`vnd.proton.expire`) in the plan.
3. Backup checksums, a versioned format, and backup-to-backup diff.
4. Disable instead of delete on apply; cleanup only with a verified backup.
5. Refuse to drop live-only filters without an explicit override.
6. Document that a rename is a delete plus a create.
7. Read other tools' `.sieve` files as-is on import.

## Prior art

| Project | Approach |
|---|---|
| terabyte/protonfusion | Playwright UI scraper: backup, consolidate, sync, restore, diff |
| brokenalarms/hey-proton | Sieve set plus generator; manual upload; label and group sync |
| poli0981/proton-sieve-filters | Curated `.sieve` files from YAML; manual upload |
| johnforeland/proton-filter-cli | Go; directory of `.sieve` files synced via the API; no 2FA, no backup |

None combines a declarative source, plan/diff, backup/restore and the safeguards above. The README states how this differs.

## Open items

- Licence: MIT (decided).
- Package and CLI names.
- Where the specs live for this repo (lean, public).
- Python version and packaging (`uv`).

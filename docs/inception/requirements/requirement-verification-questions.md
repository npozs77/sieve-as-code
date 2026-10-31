# Requirement Verification Questions

Maturity: MVP. Source: `concept.md`. All questions answered.

## Functional

### Q1. Declarative source layout
One YAML file per filter plus an order file. Filter fields?
- A) `name`, `raw_sieve`, optional `enabled` only
- B) A plus optional `description`/`tags` metadata
- C) Other

[Suggested]: A
[Justification]: Concept "Scope/In": "`name`, `raw_sieve`, optional `enabled`; order in a separate file."
[Answer]: A — Matches the concept's declarative model; any other key is a load error.

### Q2. Filter identity and rename
- A) Identity is `name`; rename = delete + create (documented)
- B) Identity is a stable local `id`; rename is an update

[Suggested]: A
[Justification]: Concept Model: "identity is `name`"; Roadmap 7: "a rename is a delete plus a create."
[Answer]: A — Identity is `name` alone; duplicate names are rejected on load.

### Q3. Plan scope
What must `plan` report?
- A) Filter create/update/delete, order change (one entry), and folders/labels to create
- B) A only for filters; targets handled silently in `apply`
- C) Other

[Suggested]: A
[Justification]: Concept Model "Targets": "listed by `plan` and created by `apply` before any filter write."
[Answer]: A — Plan entries: creates, content changes, enabled changes, deletes, one reorder entry, missing targets.

### Q4. Live-only filters (exist in Proton, not locally)
- A) `plan` shows them as deletes; `apply` deletes them (MVP), override flag deferred
- B) `apply` refuses to delete live-only filters without an explicit flag from day one
- C) `plan` shows them; `apply` never deletes them

[Suggested]: B
[Justification]: Roadmap 6 ("Refuse to drop live-only filters without an explicit override") and the concept's "mistakes land on the real mailbox" stance; pulling it into MVP is cheap and safer than A. Roadmap 5 (disable instead of delete) stays post-MVP.
[Answer]: B — A live-only filter is never deleted by default: `plan` shows it, `apply` refuses to drop it without an explicit override (Roadmap 6). See Q17 for disable-instead-of-delete.

### Q5. `import` behaviour
- A) Write one YAML per live filter plus the order file into an empty/new directory; refuse to overwrite existing files
- B) A, with overwrite behind `--force`
- C) Also read other tools' `.sieve` files (Roadmap 8) in MVP

[Suggested]: A
[Justification]: Safety Patterns rule "check existence before overwriting"; Roadmap 8 is explicitly later.
[Answer]: B — Import refuses to overwrite differing local files unless `--force`, showing the local-vs-live diff; local-only filters are never deleted.

### Q6. Backup and restore
- A) Snapshot JSON (content, `enabled`, order) auto-written before every write; `restore` takes a snapshot path, shows a plan, requires `--yes`, then verifies by re-reading live state
- B) A, plus checksums and format version (Roadmap 4) in MVP
- C) Other

[Suggested]: B
[Justification]: A matches Safety defaults ("`restore` returns to one and verifies"). B adds a format version field only; cheap now, painful to retrofit.  Checksums/backup diff stay post-MVP unless you say otherwise.
[Answer]: B — Format version and per-backup checksum verified on read, plus backup-to-backup diff (Roadmap 4), in MVP.

### Q7. Retroactive run (`filters apply`)
- A) In MVP: preview of affected messages (Sieve subset), Spam excluded, typed filter name + reason, not cancellable, plus status/audit reports
- B) Deferred to post-MVP

[Suggested]: A
[Justification]: Concept Scope/In lists "Retroactive runs ... behind a preview and a typed confirmation, plus status and audit reports."
[Answer]: A — Preview, typed filter name + reason, Spam excluded, saved preview snapshot (10-day retention), status and audit reports.

### Q8. Unpreviewable filters in a retroactive run
When a filter uses Sieve outside the supported subset:
- A) Report "not previewable"; refuse to run unless the user passes an explicit extra flag
- B) Report "not previewable" and allow the typed confirmation to proceed
- C) Refuse always

[Suggested]: B
[Justification]: Concept Constraints: "reported as not previewable, never guessed"; the typed confirmation already gates the run. Pick A if you want a second barrier.
[Answer]: B — An unsupported preview is reported as not previewable, never guessed, and the typed confirmation still gates the run.

## Non-functional

### Q9. `proton-cli` version policy
- A) Hard-fail at startup outside the tested range (documented)
- B) Warn outside the range, proceed for read-only commands, hard-fail for writes
- C) Warn only

[Suggested]: B
[Justification]: Concept Constraints: "State the tested version range; check the version at startup." Read-only `discover`/`plan` carry no write risk.
[Answer]: C — Tested version range documented; outside it, warn on stderr (detected vs tested) and continue, never hard-fail on version. Unparseable output or a rejected command still fails loudly as a `proton-cli` error. Unreadable version: warn and continue.

### Q10. Audit log
- A) Append-only local file, one line per check/write: timestamp, command, filter names, counts, outcome; never Sieve content
- B) A, with stdout/stderr of `proton-cli` captured as well

[Suggested]: A
[Justification]: Concept Scope/In: "names and counts, never Sieve content"; raw CLI output could leak content.
[Answer]: A — JSONL: timestamp, kind (write|check), outcome (clean|drift|invalid), detail with names and counts. Never Sieve content.

### Q11. Configuration and secrets
- A) Env vars only (path to `proton-cli`, filters dir, backup dir, audit log path); no secrets handled — session lives in `proton-cli`
- B) Env vars plus a config file

[Suggested]: A
[Justification]: quality-simplicity rule "No config systems for <10 values"; Concept Constraints: `proton-cli` "stores a session on disk", so this tool holds no credentials.
[Answer]: A — No `.env` loader (Q22). Paths come from environment variables; no credentials are held (the session lives in `proton-cli`). Variable names to be set in requirements.

### Q12. Python version and packaging
- A) Python 3.12+, `uv`, `pyproject.toml`, console script entry point, pinned deps
- B) Python 3.11+, plain pip/venv
- C) Other (state version)

[Suggested]: A
[Justification]: Concept Open items: "Python version and packaging (`uv`)." Python conventions require pinned versions and a venv.
[Answer]: A — Python >=3.12 (supported until 2028-10-31); tested on 3.12–3.14. uv, pytest, Hypothesis, pinned deps.

### Q13. Package and CLI names
- A) Package `sieve_as_code`, CLI `sieve-as-code`
- B) Package `sieve_as_code`, short CLI alias as well
- C) Other (state names)

[Suggested]: A
[Justification]: Concept Open items lists names as undecided; `sac` is taken (Homebrew Seismic Analysis Code, PyPI Semantic Audio Companion); `sieve-as-code` is free on PyPI.
[Answer]: A — Package `sieve_as_code`, CLI `sieve-as-code` (`sac` is taken on Homebrew and PyPI).

### Q14. Library surface
Profile says `cli` + `library`. What is the public library API?
- A) Documented functions for load/validate, plan, apply, backup, restore (the CLI is a thin wrapper)
- B) Library is internal only; only the CLI is a supported interface
- C) Other

[Suggested]: A
[Justification]: Profile `artifact_type: [cli, library]`; programs import the package at a pinned version (FR-CLI.2).
[Answer]: A — Documented functions for load/validate, plan, apply, import, backup, restore are the supported API; the CLI wraps them.

### Q15. Test strategy
- A) pytest + Hypothesis for parsing/validation/plan logic; `proton-cli` mocked at the subprocess boundary only; no live-account tests in CI
- B) A, plus an opt-in live-account smoke test run manually

[Suggested]: A
[Justification]: Concept: "no staging account"; python-conventions make Hypothesis the default for business logic; testing rules allow mocking external boundaries only.
[Answer]: A — pytest + Hypothesis; `proton-cli` reached only through one subprocess-boundary module. Optional manual smoke test against a free account (Q18).

### Q16. Repo specs (concept open item)
Where do the SDD specs live for this public repo?
- A) `docs/` committed in this repo (lean)
- B) `docs/` kept untracked/private; only code and README published

[Suggested]: A
[Justification]: Concept Open items asks for lean, public specs here.
[Answer]: A — `docs/` committed in this repo.

## Scope

### Q17. Roadmap items in MVP
Concept Roadmap 2–8 are all feasible now and cheaper to design in than to retrofit. Include them?
- A) All of 2–8: per-filter size limit check in validation (2); plan flags destructive Proton extensions such as `vnd.proton.expire` (3); backup checksums, version, backup diff (4); live-only filters disabled instead of deleted, deletion only via explicit override with a verified backup (5, 6); rename documented as delete + create (7); `import` reads plain `.sieve` files (8)
- B) A minus item 8 (`.sieve` import) and item 5
- C) Other

[Suggested]: A
[Justification]: Items 2, 3, 4, 6, 7 are validation, plan output, or format decisions that change data shapes if added later. Item 5 uses the existing enable/disable operations. Item 8 is the largest; it is an import path only and does not affect the core model. Roadmap 1 (extraction) is the build itself, not a requirement.
[Answer]: A — Roadmap 2–8 all in MVP.

### Q18. Multiple accounts
The tool must manage filters for several Proton accounts (for example a Duo/family plan). How is an account identified and kept apart?
- A) Account = `proton-cli` profile; one account per command via `--account`/env; per-account directories under two root env vars; per-account audit log; snapshots record the account
- B) A single config file listing accounts and their paths
- C) One run may act on several accounts (`--all`)

[Suggested]: A
[Justification]: `proton-cli` already isolates sessions by `--profile`, so the tool adds no credential handling. Directories by convention avoid a config file (quality-simplicity: fewer than 10 values). One account per command keeps every confirmation unambiguous; `--all` multiplies the blast radius and can be added later without breaking A.
[Answer]: A — as suggested. A free account is usable for manual smoke tests (Q15 option B); its one-filter limit means it cannot exercise reorder.

### Q19. Live testing with throwaway filters
Live behaviour cannot be faked. How is it tested?
- A) Opt-in smoke suite that creates and deletes throwaway filters on a chosen account; no runtime staging inside the tool
- B) A, and `apply` also stages every write against a disposable filter first
- C) No live tests

[Suggested]: A
[Justification]: Throwaway filters are the established way to test against Proton. Staging inside `apply` only proves the subprocess call fires, adds extra writes to a real mailbox on every run, and cannot validate the real change (a retroactive run especially). The suite can also measure the per-filter size limit (FR-DECL.6).
[Answer]: A — as suggested.

### Q20. Binding files and snapshots to the real Proton account
A profile name is a local label; `proton account login` can attach a different Proton account to it. How are files and snapshots bound to the right mailbox?
- A) Profile name only
- B) Fingerprint of the Proton account `id`, stored in a marker file and in snapshots; mismatch refuses
- C) Store the email

[Suggested]: B
[Justification]: The `id` is opaque and stable; a 12-hex SHA-256 prefix reveals nothing and still catches a re-pointed profile. Storing the email would put personal data into a committed directory.
[Answer]: B — as suggested. The marker is created on first use (trust on first use).

### Q21. Live-only filters, restore and reorder
How do live-only filters (present in Proton, absent locally) behave across plan, apply, restore and reorder?
- A) Apply disables them (FR-APPLY.5); an already-disabled one is informational in `plan`; restore deletes filters created after the backup after writing its own pre-restore snapshot; reorder compares only filters present on both sides and names the declared filters, leaving the rest after them
- B) Treat them as drift every run
- C) Restore also only disables

[Suggested]: A
[Justification]: A keeps a second `apply` a no-op (NFR-REL.1) and lets restore reach an empty diff (FR-BAK.4). Reorder semantics are `proton-cli`'s own: "Name the filters that should run first, in order; the rest keep the order they are in."
[Answer]: A — as suggested.

### Q22. `.env` loader
- A) No loader; ship `.env.example`; users load it with `direnv`, `uv run --env-file`, systemd or their shell
- B) Built-in loader reading a `.env` file

[Suggested]: A
[Justification]: Every environment already has a loader; a built-in one needs a lookup location that can silently change which account or directory a write targets, plus parsing edge cases.
[Answer]: A — as suggested.

### Q23. Retroactive run when declared differs from live
- A) Warn in the preview that the run uses the live script; do not block
- B) Refuse until `apply` has made live match declared
- C) Say nothing

[Suggested]: A
[Justification]: The run acts on the live script, and the preview is built from it, so the preview is accurate; the typed confirmation already gates the run. Blocking would stop a deliberate run of a live filter while other filters are drifting.
[Answer]: A — as suggested.

### Q24. Default directories and platforms
- A) Defaults follow XDG: filters under `$XDG_CONFIG_HOME/sieve-as-code` (else `~/.config/sieve-as-code`), state under `$XDG_STATE_HOME/sieve-as-code` (else `~/.local/state/sieve-as-code`); the env vars override; Linux and macOS only, Windows unsupported
- B) No default; the env vars are required
- C) One default root under `~/.local/share`

[Suggested]: A
[Justification]: XDG is the Linux convention (also used by gh and uv on macOS) and splits user-authored files (config) from generated ones (state), in a few stdlib lines with no `platformdirs` dependency (NFR-DEP.1).
[Answer]: A — as suggested; Windows unsupported.

### Q25. Proton's diagnostic in error messages
- A) A terminal error includes the first line of `proton`'s stderr (capped at 200 characters); the audit log and logs never do
- B) Error messages never include `proton` output

[Suggested]: A
[Justification]: That line is `proton`'s only reason for rejecting a script (FR-APPLY.4) and the only way an operator can fix it; a cap limits length, not content, so the safeguard is where it goes: the terminal, never a file.
[Answer]: A — as suggested.

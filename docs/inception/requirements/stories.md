# User Stories

Acceptance criteria cite requirement IDs; they do not restate them.

## Epic 1 — Getting started

| ID | Story | Acceptance |
|---|---|---|
| US-1.1 | As a Filter Maintainer, I want to import my live filters into YAML files so that my existing set becomes the source of truth. | One file per filter plus the order file; differing local files need `--force` and show a diff (FR-DISC.2, FR-DECL.1–3) |
| US-1.2 | As a Filter Maintainer, I want to view live filters without changing anything so that I can inspect my account safely. | Read-only; duplicate live names are an error (FR-DISC.1, FR-PLAN.6) |
| US-1.3 | As a Filter Maintainer, I want to import plain `.sieve` files so that I can bring in scripts written elsewhere. | File name becomes filter name (FR-DISC.3) |

## Epic 2 — Changing filters

| ID | Story | Acceptance |
|---|---|---|
| US-2.1 | As a Filter Maintainer, I want to see what a change would do before it happens so that no mistake reaches my mailbox unseen. | Diff of creates, changes, `enabled`, live-only, reorder, missing targets; destructive extensions and oversize scripts flagged (FR-PLAN.1, FR-PLAN.3, FR-PLAN.5, FR-DECL.5, FR-DECL.6) |
| US-2.2 | As a Filter Maintainer, I want writes to need explicit confirmation and stop at the first failure so that a half-applied change is understood. | `--yes` required; succeeded / failed / not attempted report (FR-APPLY.1, FR-APPLY.4, FR-APPLY.6, NFR-SAFE.1) |
| US-2.3 | As a Filter Maintainer, I want a reorder shown as one change so that the diff stays readable. | One entry however many moved (FR-PLAN.2, FR-APPLY.2) |
| US-2.4 | As a Filter Maintainer, I want filters removed from my files to be disabled, not deleted, so that I can recover. | Disable by default; delete needs override plus same-run backup (FR-APPLY.5) |
| US-2.5 | As a Filter Maintainer, I want to know when the live account has drifted from my files so that I can reconcile. | Outcome `clean`/`drift`/`invalid` logged; second `apply` writes nothing (FR-PLAN.4, NFR-REL.1) |

## Epic 3 — Recovery

| ID | Story | Acceptance |
|---|---|---|
| US-3.1 | As a Filter Maintainer, I want a backup before every write and on demand so that I can always go back. | Versioned, checksummed, owner-only, never overwritten (FR-BAK.1–3) |
| US-3.2 | As a Filter Maintainer, I want restore to prove it worked so that I trust the result. | Plan first; success only when the post-restore diff is empty (FR-BAK.4) |
| US-3.3 | As a Filter Maintainer, I want to compare two backups so that I can see what changed between them. | Plan-style diff of two snapshots (FR-BAK.5) |

## Epic 4 — Retroactive runs

| ID | Story | Acceptance |
|---|---|---|
| US-4.1 | As a Filter Maintainer, I want to see which existing messages a filter would touch so that I can judge the run. | Count and per-message detail, Spam excluded, unsupported Sieve reported not previewable (FR-RETRO.1, FR-RETRO.2) |
| US-4.2 | As a Filter Maintainer, I want to type the filter name and a reason before an irreversible run so that I cannot start it by accident. | Typed confirmation; audit-logged (FR-RETRO.3) |
| US-4.3 | As a Filter Maintainer, I want to check afterwards what the background run did so that I know it finished. | Done / pending / unexpected against the saved snapshot (FR-RETRO.4) |
| US-4.4 | As a Filter Maintainer, I want to see the retroactive effect of all enabled filters so that I can spot surprises. | Per-filter counts and notes (FR-RETRO.5) |

## Epic 5 — Setup and integration

| ID | Story | Acceptance |
|---|---|---|
| US-5.1 | As a Library Integrator, I want documented functions with typed results so that I can build on the tool. | Public API as listed in FR-CLI.2; CLI is a wrapper |
| US-5.2 | As a Filter Maintainer, I want to point the tool at my directories with environment variables so that setup is one export. | FR-CLI.3 |
| US-5.3 | As a Filter Maintainer, I want a warning, not a failure, on an untested `proton-cli` version so that newer releases keep working. | NFR-REL.3, NFR-REL.2 |

## Epic 6 — Multiple accounts

| ID | Story | Acceptance |
|---|---|---|
| US-6.1 | As a Filter Maintainer, I want to keep the filters of several Proton accounts side by side so that a family or Duo plan is managed from one machine. | Account = `proton-cli` profile; separate files, backups, snapshots, audit log per account; unsafe names rejected (FR-ACCT.1, FR-ACCT.2, FR-ACCT.5) |
| US-6.2 | As a Filter Maintainer, I want every plan and prompt to name the account so that I never apply one account's filters to another. | Account and fingerprint named in output and prompts; a re-pointed profile or a snapshot from another account is refused (FR-ACCT.3, FR-ACCT.4) |

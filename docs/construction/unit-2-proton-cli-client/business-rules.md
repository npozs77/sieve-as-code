# Business Rules — Unit 2: Proton CLI client

Output shapes marked ✔ were confirmed live against `proton` 4.2.3 and re-confirmed on 4.3.0 (list, get, create, delete; 2026-10-31); ? = taken from the documented text labels or exit-code table, to be confirmed by the live smoke suite (NFR-TEST.2).

| ID | Rule (condition → outcome) | Source |
|----|----------------------------|--------|
| BR-1 | Every command runs as `[binary, "--profile", account, "--no-input", "--output", "json", *command]`; the binary is `proton_cli()`, the profile is the account name. The version probe is `[binary, "--version"]`. | FR-ACCT.1, NFR-REL.2 |
| BR-2 | `create` and `update` pass the script as `--sieve -` with the script on stdin; the script never appears in argv or in any `ClientError` field. | FR-APPLY.3, NFR-SAFE.2 |
| BR-3 | The client never passes `--dry-run`. | FR-APPLY.3 |
| BR-4 | Read methods (`list_filters`, `get_filter`, `list_folders`, `list_labels`, `list_messages`) and the `connect` probes use only the verbs `list`, `get` and `--version`. | FR-PLAN.6 |
| BR-5 | One client method is exactly one `proton` process; a failed command is never retried. | concept (safety defaults) |
| BR-6 | `connect(paths)` runs, in order: version probe (BR-8), `account get` (BR-7), fingerprint check (BR-9); it returns a client only if all pass, and runs no other command before them. | NFR-REL.2, FR-ACCT.4 |
| BR-7 | `account get` exiting 2 → `ClientError` telling the operator to run `proton --profile <account> account login`; the client never prompts. | NFR-REL.2 |
| BR-8 | The first `x.y.z` in `--version` output is compared numerically with the tested minimum `(4, 3, 0)`. Below it → one stderr warning (detected vs tested) and continue; at or above → silent; probe fails or no `x.y.z` found → one stderr warning and continue. | NFR-REL.3 |
| BR-9 | Fingerprint = first 12 hex characters of SHA-256 of the string `id` in `account get` (✔ 4.3.0: `id`, a string). First use: write it plus a newline to `account_marker`, exclusive-create, file `0o600`, directory `0o700`. Later: marker content (stripped) differs → `ClientError` naming account, both fingerprints and the marker path; nothing is overwritten. | FR-ACCT.4 |
| BR-10 | A non-zero exit → `ClientError` carrying `exit_code`, the command path (verbs only, no arguments), a hint by code — 1 read `--help`, 2 sign in, 3 not found, 4 use the id a listing printed, 5 Proton or network trouble, check with `list` before repeating a write, 6 a confirmation policy refuses it, 7 a `proton` bug, other unexpected — and the first line of stderr, capped at 200 characters. | NFR-OPS.1, NFR-REL.3, RVQ-Q25 |
| BR-11 | Output that is not a JSON object with the expected keys and types → `ClientError` "unexpected proton output for `<command path>`"; stdout is never echoed. | NFR-REL.3 |
| BR-12 | Binary not found → `ClientError` naming `SIEVE_AS_CODE_PROTON_CLI`; no answer within the timeout (30 s; 120 s for `list_messages`) → `ClientError` naming the seconds. | NFR-OPS.1 |
| BR-13 | Listings pass `--limit 0`; a listing reporting `has_more` true → `ClientError` (a truncated listing would make `plan` create duplicates). | FR-PLAN.1 |
| BR-14 | `list_filters` returns `FilterRef(live_id, name, enabled)` in `proton`'s response order, which is execution order; `enabled` is `status != 0` (✔). | FR-DISC.1 |
| BR-15 | `get_filter(live_id)` returns `Filter(name, raw_sieve=sieve, enabled, live_id)` from `{id, name, status, sieve}` (✔); `raw_sieve` is returned verbatim. | FR-DECL.3 |
| BR-16 | `create_filter` returns `ids[0]` of the response (✔); a missing, empty or non-string id → shape error. `enabled=False` adds `--disabled`. | FR-APPLY.2 |
| BR-17 | `delete_filter` always passes `--yes`; the confirmation belongs to the caller (`apply`, `restore`). | FR-APPLY.5 |
| BR-18 | `reorder_filters(live_ids)` is one call with the ids in the given order; an empty list → `ValueError`. | FR-APPLY.2 |
| BR-19 | `list_folders` and `list_labels` return `MailTarget(id, name, path)`; `path` is the response `path` or, if absent, `name` (✔). `create_folder` adds `--parent ID` only when a parent id is given; `create_label` and `create_folder` take no other flags. | FR-PLAN.3 |
| BR-20 | `list_messages(to=None)` runs `messages list --folder all --limit 0`, adding `--to ADDRESS` when given, and returns the `messages` list as dicts; their fields are fixed by Unit 8. | FR-RETRO.1 |
| BR-21 | `apply_retroactively(live_id)` is one `filters apply ID` call that returns when the process returns; the client never polls. | CON-2 |

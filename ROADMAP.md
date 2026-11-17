# Roadmap

Direction between the first release (0.1.0) and 1.0. Items are candidates, not promises; each is specified as a change before it is built. Size: **small** (no change to commands, options, signatures or file formats) or **large** (any of those changes).

## 0.2: review and automation

| Feature | Why | Size |
|---------|-----|------|
| Preview a declared, not-yet-applied filter | A refactored filter cannot be previewed until it is live | large (new input) |
| Unmanaged filter list | `apply` disables live-only filters; filters Proton manages itself (newsletter filters) should be left alone | large (new configuration) |
| `validate` command | The check exists in the API (`validate_declared`); a command makes it usable as a pre-commit or CI step | large |

## 0.3: tests and scope

| Feature | Why | Size |
|---------|-----|------|
| `test` command: sample messages with expected folders and flags, per filter | Filters testable without touching mail; needs the evaluator exposed as API | large |
| `apply NAME` / `--only` | Change one filter without applying the whole plan | large (new option) |
| `--output json` | Scripting and wrappers | large |
| More Sieve in the preview | Constructs that change nothing visible, once checked against Proton's behaviour | small each |

Some preview limits come from the data, not the code: the message listing carries only from, to and subject, so tests on other headers and contact-group lists (`:list`) cannot be previewed.

## 1.0

1.0 is a stability promise, not a feature set:

- Published on PyPI, with CI and the guides (user, developer, architecture) published.
- The CLI options and `sieve_as_code.__all__` unchanged across at least two 0.x releases.
- At least one real project using the library.
- The live smoke suite green against the current `proton-cli`, and a compatibility check for new `proton-cli` releases (the dependency is unofficial).

## After 1.0

- Several accounts in one run (`--all-accounts`).
- Optional encryption of snapshots, which hold scripts and sender lists.

## Not planned

- A structured rule vocabulary inside this tool: a filter's content stays its Sieve script. A separate tool can generate the declared files and hand them to this one.
- Any backend other than `proton-cli`, UI scraping, mail features beyond filters.
- Windows (Linux and macOS only).

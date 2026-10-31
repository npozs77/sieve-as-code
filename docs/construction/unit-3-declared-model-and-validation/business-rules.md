# Business Rules — Unit 3: Declared model and validation

| ID | Rule (condition → outcome) | Source |
|----|----------------------------|--------|
| BR-1 | The account's filters directory or order file is missing → `ValidationError` naming the path and suggesting `import`. An existing empty directory with `sequence: []` is valid (zero filters). | FR-DECL.2, FR-DECL.5 |
| BR-2 | Only `*.yaml` files directly inside the filters directory are filters, read in sorted filename order; other files and subdirectories are ignored. | FR-DECL.1 |
| BR-3 | A filter file that is unreadable, invalid YAML, or not a mapping → `ValidationError` naming the file. A key other than `name`, `raw_sieve`, `enabled` → `ValidationError` naming the file and key. A missing `name` or `raw_sieve` → `ValidationError` naming the file and field. | FR-DECL.1, FR-DECL.5 |
| BR-4 | `name` must be a string that is not blank; `raw_sieve` a string that is not blank (whitespace-only is blank); `enabled`, when present, a boolean (default `True`). Anything else → `ValidationError` naming the file and field. | FR-DECL.5 |
| BR-5 | `raw_sieve` is returned exactly as parsed: loading and validating never trim, re-indent or normalise it. | FR-DECL.3 |
| BR-6 | Two filters with the same `name` (exact, case-sensitive) → `ValidationError` naming the name; when loaded from files, both file names. | FR-DECL.4, FR-DECL.5 |
| BR-7 | The order file must be a mapping whose only key is `sequence`, a list of non-blank strings; any other shape or key → `ValidationError` naming the order file and field. | FR-DECL.2, FR-DECL.5 |
| BR-8 | `sequence` containing a name twice, a name no declared filter has, or missing a declared filter's name → `ValidationError` naming the order file and that name. | FR-DECL.5 |
| BR-9 | Every error is a `ValidationError` carrying the first failure found (files in BR-2 order, with BR-16–17 after BR-4 in each file, then BR-6, then BR-7–8); messages never contain `raw_sieve` text. Loading and validating read files only and write nothing. | FR-DECL.5, NFR-SAFE.2 |
| BR-10 | A filter's file name is `<name>.yaml` with each `/`, `\` and NUL replaced by `_` and a leading `.` replaced by `_`. The file name is only a label: identity is `name` inside the file, so any file name loads. | FR-DECL.4, FR-ACCT.2 |
| BR-11 | `render` compares file names after Unicode NFC normalisation and case folding; two filters that match (`Foo`/`foo`, `a/b`/`a_b`, `.x`/`_x`) → `ValidationError` naming both filter names, and nothing is rendered. | FR-DECL.4 |
| BR-12 | `render` writes each script normalised: tabs expanded to 4 spaces, trailing whitespace removed from every line, trailing newlines removed. `normalize_whitespace` is public and idempotent. | FR-DECL.3 |
| BR-13 | A rendered filter file holds `name`, `raw_sieve` (as a `|` literal block when it has newlines) and `enabled: false` only when disabled; the rendered order file holds `sequence`. Non-ASCII text is written as is. | FR-DECL.1, FR-DECL.2 |
| BR-14 | `render` returns a mapping from path to file text (filters under the filters directory, order at the order-file path) and writes nothing; the caller writes. | FR-DECL.3 |
| BR-15 | For any valid filters and order, loading the rendered files gives the same names, `enabled` flags and sequence, and each script equals `normalize_whitespace` of the original; an already normalised script is unchanged. | FR-DECL.3 |
| BR-16 | A script with an unbalanced `{` `}` or `[` `]`, or an unterminated quoted string, `/* */` comment or `text:` block → `ValidationError` naming the file (the filter name when in memory) and the line. Braces and brackets inside strings, `text:` blocks and comments (`#`, `/* */`) are ignored. | FR-DECL.7 |
| BR-17 | A script using an extension-gated command or tag without that extension in any `require` list → `ValidationError` naming the file, line and extension. Table: `fileinto`, `reject`, `ereject`, `vacation`, `include` (commands of the same name); `set` → `variables`; `addflag`, `setflag`, `removeflag` → `imap4flags`; tag `:copy` → `copy`; tag `:regex` → `regex`. | FR-DECL.7 |
| BR-18 | What BR-16 and BR-17 cannot prove wrong passes: unknown commands, unknown or `vnd.proton.*` extensions in `require`, a missing `;`, any other grammar fault. | FR-DECL.7 |

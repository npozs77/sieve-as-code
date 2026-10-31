# sieve-as-code

Proton Mail Sieve filters as code: plan before apply, backup before every write, restore on demand. Built on [`proton-cli`](https://github.com/roman-16/proton-cli) only.

**Status: concept only, no code yet.** See [`concept.md`](concept.md).

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

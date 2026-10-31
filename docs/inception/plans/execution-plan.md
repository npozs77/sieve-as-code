# Execution Plan — sieve-as-code

**Date**: 2026-10-31
**Status**: Draft

---

## Change Impact Assessment

| Area | Impact | Description |
|---|---|---|
| User-facing | Yes | New CLI and library |
| Structural | Yes | New `sieve_as_code` package, packaging, CI |
| Data model | Yes | Filter YAML, order file, backup JSON, audit JSONL |
| API surface | Yes | 10 CLI commands, documented library functions |
| NFR impact | Yes | Safety (confirmations, backups), no-content logging |

## Risk Assessment

| Attribute | Value |
|---|---|
| Risk Level | Medium |
| Rollback Complexity | Medium (restore from backup; no staging account assumed) |
| Testing Complexity | Medium (no live-account tests in CI) |
| Key Risks | (1) Writes land on a real mailbox: mitigated by plan, `--yes`, pre-write backup, disable-not-delete. (2) `proton-cli` output changes: mitigated by one subprocess boundary module and loud parse errors. (3) Retroactive preview misjudges Sieve: mitigated by a deliberately small evaluated subset and "not previewable" reporting. |

---

## Phases to Execute

### INCEPTION PHASE

- [x] Requirements Analysis
- [x] Application Design
- [x] Unit Decomposition

### CONSTRUCTION PHASE

| Unit | Depends On | Estimated Complexity |
|------|-----------|---------------------|
| Unit 1 — Foundation | None | Low |
| Unit 2 — Proton CLI client | 1 | Medium |
| Unit 3 — Declared model and validation | 1 | Medium |
| Unit 4 — Discover and plan | 2, 3 | High |
| Unit 5 — Backup | 2, 4 | Medium |
| Unit 6 — Apply and restore | 4, 5 | High |
| Unit 7 — Import | 3, 4 | Medium |
| Unit 8 — Retroactive run | 2, 4 | High |
| Unit 9 — CLI and public API | 4–8 | Medium |

### OPERATIONS PHASE

- [ ] Documentation (README, tested `proton-cli` range, rename note)
- [ ] Deployment (PyPI packaging, CI, dependency updates)
- [ ] Verification (acceptance run against a real account by the maintainer)

---

## Stages to Skip

| Stage | Justification |
|-------|--------------|
| services.md | No service layer: library functions are called directly by the CLI |
| content-architecture.md | No content site or document set to organise beyond README |
| Cloud/infrastructure design | Stack has `cloud: none`, `infrastructure: none` |

---

## Success Criteria

1. All "Must" requirements implemented and tested.
2. Build from clean state succeeds on Python 3.12–3.14.
3. Requirements Success Criteria 1–5 hold in the maintainer's acceptance run.

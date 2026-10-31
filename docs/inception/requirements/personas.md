# Personas

| Persona | Who | Core need |
|---|---|---|
| Filter Maintainer | A Proton user who keeps a non-trivial filter set (possibly on several accounts) and runs the CLI against them | Change filters with a visible diff, a backup and a way back; run a filter over old mail without surprises |
| Library Integrator | A Python developer who imports `sieve_as_code` into their own tooling | Stable documented functions and structured results instead of parsing CLI output |

## Walkthroughs

**Filter Maintainer**: imports the live filters once, keeps the YAML in git, edits a script, runs `plan` to see the diff and flagged extensions, runs `apply --yes`, and finds a pre-write backup if the result is wrong. Occasionally runs `apply-retroactive` for a new filter after reading the preview. Backed by US-1.1, US-2.1–2.5, US-3.1–3.3, US-4.1–4.4, US-5.2, US-5.3, US-6.1, US-6.2.

**Library Integrator**: calls the load/validate, plan, apply, backup and restore functions from their own code and receives typed results. Backed by US-5.1.

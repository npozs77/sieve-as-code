# Component Dependencies

```
cli ─▶ __init__ (public API) ─▶ restore ─▶ apply ─▶ plan ─▶ live ─▶ client
                              │            │         │       │
                              │            ▼         ▼       ▼
                              └▶ retroactive ─▶ sieve_eval   declared ─▶ model
                              └▶ backup ─▶ live
audit ◀─ plan, apply, restore, retroactive      settings ◀─ client, declared, backup, audit, retroactive
```

| Component | Depends on |
|---|---|
| model | — |
| settings | — |
| audit | settings |
| client | settings, model |
| declared | settings, model |
| live | client, model |
| importer | live, declared, plan, model |
| plan | live, client, declared, model, audit |
| backup | live, settings, model |
| apply | plan, client, backup, audit |
| restore | backup, apply, plan, live, audit |
| sieve_eval | — |
| retroactive | client, sieve_eval, live, settings, audit |
| cli | all public functions |

`importer` is separate from `live` so that `plan` (which needs `discover`) and the import diff (which needs `plan`) stay acyclic.

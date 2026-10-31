# Unit Dependencies

| Unit | Depends on |
|---|---|
| 1 Foundation | — |
| 2 Proton CLI client | 1 |
| 3 Declared model and validation | 1 |
| 4 Discover and plan | 2, 3 |
| 5 Backup | 2, 4 |
| 6 Apply and restore | 4, 5 |
| 7 Import | 3, 4 |
| 8 Retroactive run | 2, 4 |
| 9 CLI and public API | 4, 5, 6, 7, 8 |

Component edges in `component-dependency.md` are consistent with these: `backup` uses `live` (Unit 4), `apply`/`restore` use `plan` and `backup`, `retroactive` uses `client` and `live`.

# JSON output

`--json FILE` writes a list, best rank first. Keys are sorted. Each item:

| key | meaning |
|---|---|
| `asset`, `change` | what changed. `change` is `column_removed`, `type_changed`, `type_widened`, `column_added`, `table_removed`, or `standing:<issue>`. |
| `columns` | the columns touched |
| `hazard`, `dose`, `exposure`, `receptor`, `uncertainty` | the five factors |
| `risk` | their product, to two decimals |
| `band` | `Act`, `Monitor` or `No Action` |
| `rank`, `naive_rank` | position by risk, and position by downstream count alone |
| `naive_downstream` | how many consumers are downstream |
| `reasons` | the sentences shown in the report |
| `consumers` | `[asset, steps away, queries a month or null]` for each consumer |

`--since` reads this file back, so keep the keys `asset`, `change`, `risk` and `band`.

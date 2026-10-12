# Input format

## catalog.json

```json
{
  "assets": [
    {
      "id": "warehouse.customers",
      "platform": "warehouse",
      "schema": {"id": "int", "email": "string"},
      "tags": ["pii"],
      "domain": "customer",
      "owner": "data-team",
      "key_columns": ["id"],
      "usage": {"queries_30d": 5200},
      "standing_issues": ["nullable key"]
    }
  ],
  "edges": [
    {"from": "warehouse.customers", "to": "looker.churn", "columns": ["id", "email"]}
  ]
}
```

| field | meaning |
|---|---|
| `id`, `schema` | required. Schema is column name to type. |
| `tags`, `domain`, `platform` | decide how sensitive the consumers are. |
| `owner` | leave it out if you do not track owners. Include it empty if nobody owns the table: that raises uncertainty. |
| `key_columns` | a change to these is worse. |
| `usage.queries_30d` | `null` means unmeasured, which raises uncertainty. `0` means measured and unused. |
| `standing_issues` | problems that already existed. They score zero. |
| edge `columns` | optional. If given, consumers that never read the changed columns are ignored. If left out, the consumer counts and uncertainty goes up. |

## baseline.json

Column name to type for every table, as last saved. Make one with `--write-baseline`.

## Exit codes

| code | meaning |
|---|---|
| 0 | ran fine (and nothing reached the `--fail-on` band) |
| 1 | something reached the `--fail-on` band |
| 2 | bad input: missing file, broken JSON, bad setting |

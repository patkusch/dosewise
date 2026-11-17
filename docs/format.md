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
| `sensitivity` | a number that replaces the tag, domain and platform guess for this consumer. |
| `usage.queries_prev_30d` | optional. If a consumer is queried 1.5x more than this, the finding says so. |
| `usage.queries_30d` | `null` means unmeasured, which raises uncertainty. `0` means measured and unused. |
| `standing_issues` | problems that already existed. They score zero. |
| edge `columns` | optional. If given, consumers that never read the changed columns are ignored. If left out, the consumer counts and uncertainty goes up. |

## From dbt

`--from-dbt manifest.json` builds the catalog from dbt instead of a hand-written file, so the
baseline is a set of schemas taken from a manifest rather than from your catalog:

```bash
python3 -m dosewise --from-dbt target/manifest.json --write-baseline base.json
python3 -m dosewise --from-dbt target/manifest.json --baseline base.json
```

| dbt | becomes |
|---|---|
| a `model`, `source` or `snapshot` node | one asset, id = the node's `unique_id` |
| `depends_on.nodes` | an edge `from` parent `to` child, when both are tables above |
| declared `columns` (`data_type`), or measured types from `--dbt-catalog` | the asset's `schema` |
| `tags` and `config.tags` | `tags` |
| `meta.owner` | `owner` (missing = owners are not tracked, `null` or `""` = nobody owns it) |
| `meta.domain`, or the node's `group` | `domain` |
| `meta.sensitivity` | `sensitivity` |
| `meta.queries_30d`, `meta.queries_prev_30d` | `usage` |
| `meta.key_columns`, `meta.standing_issues` | the same fields |

Tests, seeds, macros and exposures are not tables, so they are left out. Types are lowercased,
because a warehouse reports `INTEGER` where the YAML says `integer` and a change of case is not a
change of type.

`--dbt-catalog target/catalog.json` (from `dbt docs generate`) supplies the columns and types the
warehouse really has, which is what a type change needs. Pass it on every run, not just the first:
a baseline saved with measured types compared against a manifest that only has declared ones still
shows the type differences, because "unknown" is not "varchar". A column nobody described, in
neither the YAML nor the catalog, is `unknown`.

dbt's lineage does not say which columns flow, so every consumer counts and the finding says the
evidence is incomplete. A hand-written catalog can be more precise with `columns` on an edge.

## baseline.json

Column name to type for every table, as last saved. Make one with `--write-baseline`.

## Exit codes

| code | meaning |
|---|---|
| 0 | ran fine (and nothing reached the `--fail-on` band) |
| 1 | something reached the `--fail-on` band |
| 2 | bad input: missing file, broken JSON, bad setting |

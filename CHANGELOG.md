# Changes

## 0.3.1
- `--version` and `--top N`.
- Duplicate asset ids are rejected; lineage that mentions an unknown table warns.
- A filtered-out report says "Nothing to show."

## 0.3.0
- Consumers are weighed by business domain as well as tags.
- A change to a key column is worse than to an ordinary one.
- `--format github` for CI annotations; the report has a by-band summary line.
- `docs/format.md` describes the input and exit codes.
- Tests prove input order never changes the result.

## 0.2.0
- Options: `--fail-on`, `--only`, `--explain`, `--max-hops`, `--stability`, `--write-baseline`, `--html`, `--csv`.
- A missing owner now counts as missing evidence.
- A dropped table is scored, not just dropped columns.
- Each verdict says what would change it.
- Bad settings and missing files give a plain message.
- Lineage cycles no longer count a table as its own consumer.

## 0.1.0
- First version: hazard x dose x exposure x receptor x uncertainty, with a written reference case for the action line.

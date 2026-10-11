# Changes

## 0.2.0
- Options: `--fail-on`, `--only`, `--explain`, `--max-hops`, `--stability`, `--write-baseline`, `--html`, `--csv`.
- A missing owner now counts as missing evidence.
- A dropped table is scored, not just dropped columns.
- Each verdict says what would change it.
- Bad settings and missing files give a plain message.
- Lineage cycles no longer count a table as its own consumer.

## 0.1.0
- First version: hazard x dose x exposure x receptor x uncertainty, with a written reference case for the action line.

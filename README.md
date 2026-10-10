# Dosewise

Data quality tools find hundreds of problems and mark them all critical, so people stop reading. Dosewise ranks them the way a toxicologist would: a break only matters in proportion to who is actually exposed to it.

Inspired by the idea behind [Paracelsus](https://devpost.com/software/paracelsus) (a DataHub hackathon project). This is an independent, standalone rebuild of the idea. It reads a plain JSON file, so there is no catalog to install and nothing to sign up for.

## What it does

You give it your tables, how they feed each other, and a saved copy of what each table looked like yesterday. It tells you which changes need a person today, which can wait, and which are not changes at all.

```
Risk = Hazard x Dose x Exposure x Receptor sensitivity x Uncertainty
```

- **Hazard**: how bad this kind of change is (removing a column is worse than adding one).
- **Dose**: what share of the table's columns the change touches.
- **Exposure**: how much the tables downstream are actually queried, counting less the further away they are.
- **Receptor sensitivity**: who is on the other end. Personal data, finance and executive dashboards weigh more.
- **Uncertainty**: missing evidence raises the score. A table with no usage data is not treated as unused, because "nobody uses it" and "nobody measured it" look the same.

Problems that were already there and have not changed score exactly zero. A healthy catalog gives a quiet report.

## Try it

```bash
python3 -m dosewise --catalog data/catalog.json --baseline data/baseline.json
```

No installs needed (standard library only). The sample catalog is invented. In it, two tables named `addresses` lose the same two columns. The one with six tables downstream that nobody queries ranks first by downstream count and fifth by real risk. A table people actually query, with personal data behind it, is the one that needs action.

## Using your own catalog

`catalog.json` holds `assets` (id, platform, `schema` of column name to type, `tags`, `usage.queries_30d` or null if unmeasured) and `edges` (`from` feeds `to`, with optional `columns` if you know which columns flow). `baseline.json` is the saved schema from the last good run. Keep it under version control so the result is the same every run.

The action line is not fitted to the data. It comes from a written reference case in `dosewise/engine.py` (a quarter of columns removed, 1,000 queries a month one step away, personal data, nothing missing). Change that case to match your own idea of "worth waking someone for".

## What it does not do

- It has only been run on the invented sample, never on a real catalog.
- Lineage is followed four steps and no further.
- Weights are starting guesses, set in `DEFAULT_CONFIG` and meant to be tuned.
- There is no language model. Every number comes from arithmetic you can read.

## Tests

```bash
pip install pytest && python -m pytest
```

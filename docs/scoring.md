# How the score works

One finding is one change to one table, compared with the saved baseline.

**Hazard** is how bad that kind of change is. Removing a column or a table is 1.0. Changing a type so values no longer fit is 0.8. A type change that keeps every value (int to bigint) is 0.2, the same as adding a column. Touching a key column multiplies this by 1.5.

**Dose** is the share of the table's columns the change touches.

**Exposure** is how much the tables downstream are queried. Each one counts its monthly queries, halved for every step away. The total is squashed with a logarithm so one huge table does not drown the rest. If anything is downstream, exposure never drops below 0.3, because "nobody measured it" is not "nobody uses it".

**Receptor sensitivity** is the most sensitive consumer: personal data 2.0, finance 1.8, executive 1.5, dashboards 1.3, otherwise 1.0.

**Uncertainty** starts at 1 and goes up for each gap: consumers with no usage data (up to +0.5), lineage that does not say which columns flow (up to +0.5), and a table with an empty owner (+0.5).

Multiply the five and you have the risk. Problems that were already there score zero.

**Bands** come from a written reference case: a quarter of the columns removed, 1,000 queries a month one step away, personal data, nothing missing. At or above its score is Act. At or above a quarter of it is Monitor. Anything below is No Action.

Every number is a starting guess. `--stability` shows how many verdicts survive changing each weight by half, and `--config` lets you set your own.

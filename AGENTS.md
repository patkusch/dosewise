# Working in dosewise

Rank data-catalog breakages by who is actually exposed: hazard x dose x exposure x sensitivity x uncertainty

## Run the tests

```bash
python -m pytest
```

Every test should pass before you start and after you finish.

## Where things are

- `tests/`: the tests
- `docs/`: written documentation
- `data/`: sample data

## Before you commit

- Make sure the tests pass.
- Put changes people will notice in `CHANGELOG.md`.
- Do not put real passwords, keys or private data in test files or examples. Use made-up ones.

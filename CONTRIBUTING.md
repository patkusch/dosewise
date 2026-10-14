# Contributing

```bash
pip install pytest ruff
python -m pytest
ruff check --isolated --select E,F,W --ignore E501 .
```

- Every number comes from arithmetic. Please do not put a language model in the scoring path.
- A new factor needs a test that shows the ranking it changes, and a line in `docs/scoring.md`.
- The sample catalog is made by `data/make_sample.py`. Change the script and re-run it; do not edit the JSON by hand.
- Weights are guesses. If you tune one, say what real catalog you tuned it on.

# Development and review

Use Python 3.11 or 3.12 and install `python -m pip install -r requirements.txt` in a virtual
environment. Work from the repository root.

```bash
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m pytest --cov=src --cov-report=term-missing
python -m build
python -m src.pipeline
```

Changes to features, simulation, rules or calibration must include a regression test
and a regenerated benchmark: `python -m src.evaluate --output reports`. Review the CSV
results as well as the chart. Explain metric regressions and changes to the model card.
Do not tune against the five committed evaluation seeds and then describe them as unseen.

Preserve units in field names, UTC timestamps, nullable AIS identity and per-track causal
ordering. Never include credentials or real sensor logs in fixtures. Keep code and commit
messages free of decorative symbols. Use logging for pipeline diagnostics.

Serialization changes require explicit schema-version consideration. Changes to alert
identity must document replay consequences for a receiving Foundry integration.

Service changes must preserve request replay, transaction boundaries, review revision
checks and artifact compatibility validation. The test suite includes a real loopback
HTTP smoke test. CI additionally builds and exercises the non-root Docker image.

# Reproducible benchmark

5 independent synthetic evaluation cohorts; 21,600 observations per method.
Mean +/- sample standard deviation across seeds. Threshold: 0.65.

| Method | Precision | Recall | Average precision | Brier score |
| --- | ---: | ---: | ---: | ---: |
| rules | 1.0000 +/- 0.0000 | 0.9500 +/- 0.0000 | 0.9583 +/- 0.0000 | 0.0083 +/- 0.0000 |
| isolation | 0.9190 +/- 0.0131 | 0.9967 +/- 0.0067 | 0.9625 +/- 0.0094 | 0.0131 +/- 0.0021 |
| hybrid | 0.9992 +/- 0.0019 | 0.9981 +/- 0.0021 | 0.9987 +/- 0.0023 | 0.0005 +/- 0.0004 |

All methods receive an independently fitted isotonic calibrator.
The rules-only comparison is essential: the generator injects events that match
the rules. High scores demonstrate fixture consistency, not field generalization.
Use benchmark.csv for per-seed confusion counts and reliability.csv for bin counts.

Reproduce: `python -m src.evaluate --output reports`

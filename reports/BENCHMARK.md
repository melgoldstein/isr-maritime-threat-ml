# Reproducible benchmark

5 independent synthetic evaluation cohorts; 21,600 observations per method.
Mean +/- sample standard deviation across seeds. Threshold: 0.65.

| Method | Precision | Recall | Average precision | Brier score |
| --- | ---: | ---: | ---: | ---: |
| rules | 1.0000 +/- 0.0000 | 0.9500 +/- 0.0000 | 0.9583 +/- 0.0000 | 0.0083 +/- 0.0000 |
| isolation | 0.9179 +/- 0.0254 | 0.9981 +/- 0.0036 | 0.9599 +/- 0.0105 | 0.0133 +/- 0.0043 |
| hybrid | 0.9989 +/- 0.0018 | 0.9981 +/- 0.0021 | 0.9987 +/- 0.0023 | 0.0005 +/- 0.0004 |

All methods receive an independently fitted isotonic calibrator.
The rules-only comparison is essential: the generator injects events that match
the rules. High scores demonstrate fixture consistency, not field generalization.
Use benchmark.csv for per-seed confusion counts and reliability.csv for bin counts.

Reproduce: `python -m src.evaluate --output reports`

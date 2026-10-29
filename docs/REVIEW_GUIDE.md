# Technical review guide

## Suggested walkthrough

1. Run `python -m pytest --cov=src --cov-report=term-missing` to inspect executable contracts.
2. Run `python -m src.pipeline` and compare `metrics.json` with the scored Parquet file.
3. Read the feature implementation alongside its causality and dateline regression tests.
4. Inspect `IsolationThreatDetector.fit` to distinguish unsupervised fitting from labeled calibration.
5. Run `python -m src.evaluate` and compare all three ablations, including their false positives.
6. Inspect the typed Ontology payload and the explicit deployment boundary in the Foundry guide.

## Design decisions to discuss

**Why a hybrid?** Rules retain interpretable evidence for known discrepancies. Isolation
scores provide a ranking for observations that do not yet satisfy persistence thresholds.
The ablation measures whether that additional complexity helps on the specified fixture.

**Why isotonic calibration?** It learns a monotone mapping without imposing a sigmoid.
Its flexibility also creates a risk of overfitting a small or narrow calibration cohort.
The separate evaluation cohort measures that risk only within the simulator distribution.

**Why keep missing AIS nullable?** A radar contact can persist without an AIS report.
Treating missing identity as an empty string or invented MMSI would confuse identity with
observation availability. Radar contact identity remains the staging primary key.

**Why stage action proposals?** Dataset ingestion and action application are different
Foundry operations. A local JSON file cannot create an Ontology or guarantee submission
permissions. The boundary is explicit and allows deployment-specific validation.

**What would change first with real sensors?** Establish track-association quality and
measurement provenance, collect analyst labels, measure event-level latency and workload,
then reconsider thresholds and calibration using an external evaluation set.

## Evidence checklist

| Claim | Inspectable evidence |
| --- | --- |
| No future observations in feature windows | Prefix-causality test |
| No scenario label in inference | Truth-column exclusion test |
| Cohort separation | Track-overlap guard and benchmark seed-triple guard |
| Replay-stable alert identity | JSON/Parquet round-trip and repeat-export test |
| Stable schema with no alerts | Empty-output Arrow schema test |
| Benefit from ML contribution | Rules / isolation / hybrid benchmark |
| Portability | Python 3.11 and 3.12 CI, package build and installed CLI smoke test |

This project makes no claims about classified systems, live deployment, institutional
endorsement, or operational validation. Review it as a reproducible software and ML study.

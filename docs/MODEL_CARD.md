# Model card

## Purpose

Prioritize anomalous synthetic maritime contacts for analyst review. The score estimates
membership in the simulator's anomaly class. It does not infer intent, identify vessels,
or recommend an operational response. No field evaluation has been performed.

## Training and calibration

For evaluation seed `s`, reference tracks use `s + 1` and calibration tracks use `s + 2`.
Every cohort contains 48 contacts with 90 observations per contact. Track IDs include the
seed, and calibration rejects reference contact overlap. The reference cohort contains
both normal and anomalous observations; no truth labels are used to fit IsolationForest.

IsolationForest uses 200 estimators, default subsampling, `contamination="auto"`, and one
worker. Its negative `score_samples` values are ranked against the reference distribution.
The contamination setting does not determine the final threshold: the pipeline uses
calibrated scores rather than the estimator's binary `predict` output.

The hybrid evidence is `max(0.8 * reference_percentile, rule_floor)`, where `rule_floor`
is 0.85 for any qualifying rule and zero otherwise. Isotonic regression maps this evidence
to a probability-like score using independent labeled calibration contacts. Out-of-range
evidence clips to the fitted calibration endpoints. Final alerts use a fixed 0.65 threshold.
This is an unsupervised base estimator with supervised calibration, not a wholly
unsupervised learning pipeline.

## Evaluation design

Evaluation seeds are 42, 142, 242, 342 and 442. The two associated cohorts for each seed
are also disjoint from all other benchmark cohorts. Every ablation uses the same partitions,
feature matrix and threshold, and receives its own isotonic calibrator.

| Ablation | Input to calibration |
| --- | --- |
| Rules | Rule floor only |
| Isolation | Reference percentile only |
| Hybrid | Maximum of scaled reference percentile and rule floor |

Metrics include observation-level precision, recall, average precision, Brier score and
false-positive rate. Per-seed confusion matrices and ten-bin reliability summaries are
committed under `reports/`. Error bars are variability across five seeds, not an estimate
of uncertainty for an operational population. The evaluation does not measure alert
latency, operator workload, identity switches, or event-level incident recall.

## Interpretation

Rules achieve perfect precision in this fixture while missing early dark-loitering
observations. Isolation evidence recovers more of these observations but also flags more
normal traffic. The hybrid reduces that tradeoff in this controlled distribution.
The benchmark supports this implementation choice within the simulator; it does not
demonstrate that hybrid scoring is generally superior.

The generator and rules share design assumptions. Synthetic cohorts differ in random
trajectories and sensor noise, but share geography, anomaly construction, class proportions
and sampling frequency. Separate seeds prevent identical-track reuse, not simulator bias.

## Failure modes and follow-up experiments

| Failure mode | Consequence | Required experiment before deployment |
| --- | --- | --- |
| Legitimate slow turns with missing AIS | Elevated anomaly score | Labeled fishing, anchorage and port traffic |
| Changed anomaly prevalence | Miscalibrated score | Temporal recalibration with held-out field labels |
| Radar association errors | Artificial jumps and identity confusion | Track-association uncertainty evaluation |
| RCS aspect or sea-state variation | Spurious signature mismatch | Sensor-specific conditional baselines |
| Outages or irregular cadence | Missing or stale kinematic evidence | Gap-aware observation policy and sensor health gates |
| Unseen behavior | Poor rank ordering or missed incidents | Scenario holdouts and geographically external validation |

The current implementation resets dark duration after gaps above two minutes and prevents
a loitering flag until ten contiguous intervals are available. It still scores other
features during gaps; that is not a complete missing-sensor strategy.

## Reproducibility boundary

Random states, installed versions, cohort seeds and calibration knots are recorded.
Exact outputs may change with dependency versions. The frozen requirements record the
local Python 3.12 environment; CI also exercises the declared ranges on Python 3.11.
Pipeline runs persist a model bundle for independent inference. The service loads a frozen
bundle and rejects runtime/source mismatches. See [the serving guide](SERVING.md).

## Frozen-model challenge suite

Version 0.2 adds seed-9042 scenario constructions withheld from fitting and calibration.
The detector is loaded from a saved bundle and is never updated during the experiment.
The suite measures false-alert episodes per benign vessel-hour, affected-contact event
recall and median detection delay, with thresholds 0.3, 0.65 and 0.9 reported together.
Results and precise assumptions appear in [the stress report](../reports/stress/STRESS.md).
Fishing deliberately uses the same observations as anomalous loitering with a benign
interpretation; no classifier can resolve that ambiguity from these features alone.

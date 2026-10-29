# Engineering reference

## Sensor and scoring contract

See the [field dictionary](DATA_DICTIONARY.md) for units, nullability and feature order.



The committed `data/sector_7_tracks.csv` contains 48 contacts and 90 observations per
contact. Cargo, tanker and fishing tracks follow noisy cruise trajectories. Injected
events include a persistent AIS position offset, radar-only slow circular movement,
and a radar signature inconsistent with the declared vessel class. Synthetic MMSIs
are identifiers for this fixture only. Radar association supplies the stable contact
ID even when AIS disappears; association uncertainty is outside this simulator.

Coordinates use WGS84 latitude/longitude with a spherical great-circle approximation.
Distance is metres, speed is knots, turn rate is degrees/minute, timestamps are UTC.
RCS uses **dBsm**, not dBm: cross-section and received radar power are different quantities.
The class-dependent RCS baselines are illustrative and omit aspect, frequency and sea state.

Feature windows are causal and isolated by track. Duplicate timestamps and invalid
coordinates fail validation. Missing AIS remains explicit in the sensor log; derived
unavailable residuals use zero while AIS absence accumulates separately. First-observation
motion features use zero and `history_ready=false`. Radar turn rate uses circular angle
differences. Loitering requires ten observations with mean speed below 3 knots and mean
turn rate above 8 degrees/minute; dark loitering also requires ten minutes of AIS absence.
Intervals above two minutes reset accumulated dark duration and invalidate the loitering
window until ten contiguous intervals are present. Course uses spherical initial bearings,
including crossings of the antimeridian.

IsolationForest fits the seed-43 reference cohort. Its anomaly magnitude becomes an
empirical reference percentile, scaled to 0.8. Deterministic evidence supplies a floor
of 0.85 for speed disagreement above 12 knots, AIS/radar separation above 500 metres,
dark loitering, or an RCS residual above 10 dB. Isotonic regression calibrates this
combined evidence using the independent seed-44 labeled cohort. Seed 42 is evaluation
only. Scenario labels never enter the feature matrix or scoring path.

`threat_score` is a calibrated synthetic anomaly likelihood in [0, 1]. It is not an
operational probability of hostile intent. Cohorts have disjoint contact IDs but share
a simulator; field validation must account for sensor quality, traffic prevalence,
geography and previously unseen behaviors. Threshold selection requires operational
costs and analyst review. Live deployment would also require track association,
sensor-health gates, model persistence, drift monitoring and calibrated field labels.

## Artifacts and lineage

| Output | Contract |
| --- | --- |
| `artifacts/scored_tracks.parquet` | Full observation history with evidence, scores and scenario truth |
| `artifacts/maritime_vessels.parquet` | One latest flagged observation per contact, explicit nullable MMSI and UTC timestamp |
| `artifacts/ontology_payload.json` | Versioned object snapshots and proposed action parameters |
| `artifacts/metrics.json` | Precision, recall, average precision, Brier score and scenario recall |
| `artifacts/run_manifest.json` | Seeds, dependency versions, CSV SHA-256, feature order and calibration knots |

The flagged snapshot is the last flagged observation, which may precede the latest
observation. It is not a current fleet-state table. Alert IDs are deterministic UUIDs
derived from schema version, contact and observation time. A Foundry receiver must
enforce idempotency; producing the same ID does not itself prevent repeated actions.


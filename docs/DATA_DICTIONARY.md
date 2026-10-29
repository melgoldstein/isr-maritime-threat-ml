# Sensor and feature dictionary

## Observation identity

One row represents a fused contact observation. The unique key is `(track_id, timestamp)`.
`track_id` is a radar-association identifier, not a persistent real-world vessel identity.
The simulator observes each contact every minute. UTC timestamps are timezone-aware after
ingestion. Duplicate keys, empty cohorts, missing radar coordinates, and unsupported
classes are rejected before feature construction.

| Field | Type / unit | Missingness and meaning |
| --- | --- | --- |
| `track_id` | string | Required; stable within one simulated contact |
| `timestamp` | UTC datetime | Required; feature computation sorts within contact |
| `mmsi` | nullable string | Missing during the dark-vessel interval; synthetic only |
| `vessel_class` | cargo / tanker / fishing | Known simulated class, retained during AIS absence |
| `radar_latitude`, `radar_longitude` | degrees | Required; bounds [-90, 90], [-180, 180] |
| `ais_latitude`, `ais_longitude` | nullable degrees | Missing AIS location is retained as null |
| `sog_knots` | nullable knots | Nonnegative reported speed over ground |
| `cog_deg` | nullable degrees | Reported course in [0, 360) |
| `radar_rcs_dbsm` | dB relative to 1 square metre | Required, finite radar cross-section |
| `scenario` | string | Evaluation annotation; excluded from model input |
| `is_anomaly` | boolean | Synthetic truth; calibration/evaluation only |

## Model input order

The `FEATURE_COLUMNS` list is the authoritative order. The manifest records it for every run.

| Feature | Unit / range | Construction |
| --- | --- | --- |
| `implied_speed_knots` | knots | Radar great-circle distance divided by elapsed time |
| `sog_delta_knots` | knots | Absolute difference between AIS-implied speed and reported SOG |
| `turn_rate_deg_min` | degrees/minute | Absolute circular change of radar-derived initial bearing |
| `sensor_separation_m` | metres | Simultaneous great-circle AIS/radar disagreement |
| `rcs_residual_db` | dB | Absolute deviation from the simulated class baseline |
| `dark_minutes` | minutes | Accumulated AIS absence across contiguous radar observations |
| `loitering_flag` | 0 or 1 | Slow speed and persistent turning over ten contiguous intervals |

Unavailable derived residuals use zero. This convention is explicit but imperfect: a zero
residual can mean agreement or insufficient observations. AIS absence has its own feature;
`history_ready` records whether a prior observation exists but is not a model input.
`rcs_mismatch_flag` is used by deterministic rules and is not a separate model feature.

## Ontology mapping

`vesselId` maps to `track_id`, `lastObserved` to the latest **flagged** timestamp, and position
to that observation's radar coordinates. It is possible for newer unflagged observations
to exist. The exported table describes flagged-contact snapshots, not complete fleet state.
`reasonCodes` describes rules satisfied at the snapshot, or `STATISTICAL_NOVELTY` when the
score alone generated the alert. These are evidence labels, not causal explanations of
the forest's internal decision path.

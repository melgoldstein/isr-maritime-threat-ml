import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from src.features.kinematics import FEATURE_COLUMNS, engineer_features, haversine_m
from src.ingest.ais_simulator import simulate_tracks
from src.models.isolation_detector import IsolationThreatDetector
from src.palantir.ontology_mapper import VESSEL_SCHEMA, export_ontology
from src.pipeline import run_pipeline


def test_great_circle_and_antimeridian() -> None:
    distances = haversine_m(
        np.array([0.0, 0.0]), np.array([0.0, 179.9]), np.array([0.0, 0.0]), np.array([1.0, -179.9])
    )
    np.testing.assert_allclose(distances, [111195.08, 22239.02], atol=1)


def test_features_are_causal_and_order_invariant() -> None:
    tracks = simulate_tracks(vessels=8, observations=30)
    full = engineer_features(tracks)
    shuffled = engineer_features(tracks.sample(frac=1, random_state=8))
    pd.testing.assert_frame_equal(full, shuffled)
    cutoff = pd.Timestamp("2026-01-01T00:20:00Z")
    prefix = engineer_features(tracks.loc[tracks.timestamp <= cutoff])
    pd.testing.assert_frame_equal(
        full.loc[full.timestamp <= cutoff, FEATURE_COLUMNS].reset_index(drop=True),
        prefix[FEATURE_COLUMNS],
    )
    assert full.loc[full.scenario == "dark_loitering", "loitering_flag"].max() == 1
    assert np.isfinite(full[FEATURE_COLUMNS]).all().all()


def test_duplicate_and_invalid_coordinates_rejected() -> None:
    tracks = simulate_tracks(vessels=8, observations=30)
    with pytest.raises(ValueError, match="Duplicate"):
        engineer_features(pd.concat([tracks, tracks.iloc[:1]]))
    tracks.loc[0, "radar_latitude"] = 91
    with pytest.raises(ValueError, match="coordinates"):
        engineer_features(tracks)


def test_calibration_isolation_and_truth_exclusion() -> None:
    reference = engineer_features(simulate_tracks(1, 8, 30))
    calibration = engineer_features(simulate_tracks(2, 8, 30))
    detector = IsolationThreatDetector()
    with pytest.raises(ValueError, match="disjoint"):
        detector.fit(reference, reference)
    detector.fit(reference, calibration)
    scores = detector.score(calibration)
    hidden_truth = calibration.drop(columns=["scenario", "is_anomaly"])
    np.testing.assert_array_equal(scores.threat_score, detector.score(hidden_truth).threat_score)
    assert scores.threat_score.between(0, 1).all()
    with pytest.raises(ValueError, match="threshold"):
        detector.score(calibration, 1.1)


@pytest.mark.parametrize(
    "column,value", [("sog_knots", -1), ("cog_deg", 360), ("radar_rcs_dbsm", float("inf"))]
)
def test_invalid_sensor_measurements_rejected(column: str, value: float) -> None:
    tracks = simulate_tracks(vessels=8, observations=30)
    tracks.loc[0, column] = value
    with pytest.raises(ValueError):
        engineer_features(tracks)


def test_empty_ontology_has_stable_schema(tmp_path: Path) -> None:
    contacts = pd.DataFrame(columns=["track_id", "timestamp", "flagged"])
    contacts["flagged"] = contacts.flagged.astype(bool)
    payload = export_ontology(contacts, tmp_path)
    assert payload["objects"] == []
    assert pq.read_schema(tmp_path / "maritime_vessels.parquet") == VESSEL_SCHEMA


def test_pipeline_contract_and_idempotent_alerts(tmp_path: Path) -> None:
    metrics = run_pipeline(tmp_path / "output", tmp_path / "tracks.csv")
    assert metrics["precision"] > 0.9
    assert metrics["recall"] > 0.9
    payload_path = tmp_path / "output/ontology_payload.json"
    payload = json.loads(payload_path.read_text())
    assert len({vessel["vesselId"] for vessel in payload["objects"]}) == len(payload["objects"])
    assert all(action["parameters"]["status"] == "PENDING_REVIEW" for action in payload["actions"])
    scored_tracks = pd.read_parquet(tmp_path / "output/scored_tracks.parquet")
    repeated = export_ontology(scored_tracks, tmp_path / "repeat")
    assert repeated == payload

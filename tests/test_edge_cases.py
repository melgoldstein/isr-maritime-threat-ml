from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from src.features.kinematics import engineer_features
from src.ingest.ais_simulator import simulate_tracks
from src.models.isolation_detector import IsolationThreatDetector


def test_dateline_crossing_preserves_course() -> None:
    contact = simulate_tracks(vessels=8, observations=30).iloc[:4].copy()
    contact["radar_latitude"] = 0.0
    contact["radar_longitude"] = [179.998, 179.999, -180.0, -179.999]
    enriched = engineer_features(contact)
    np.testing.assert_allclose(enriched.turn_rate_deg_min, 0, atol=1e-8)
    np.testing.assert_allclose(enriched.implied_speed_knots.iloc[1:], 3.60243, atol=0.001)


def test_observation_gap_resets_dark_duration_and_loitering() -> None:
    tracks = simulate_tracks(vessels=8, observations=90)
    contact = tracks.loc[tracks.scenario == "dark_loitering"].copy()
    contact.loc[contact.index[60:], "timestamp"] = contact.loc[contact.index[60:], "timestamp"].map(
        lambda observed_at: observed_at.to_pydatetime() + timedelta(hours=1)
    )
    enriched = engineer_features(contact)
    assert enriched.dark_minutes.iloc[59] > 10
    assert enriched.dark_minutes.iloc[60] == 0
    assert enriched.loitering_flag.iloc[60:70].eq(0).all()


def test_unfitted_detector_has_actionable_error() -> None:
    with pytest.raises(ValueError, match="Fit the detector"):
        IsolationThreatDetector().score(pd.DataFrame())


@pytest.mark.parametrize("mode", ["rules", "isolation", "hybrid"])
def test_ablation_modes_are_deterministic(mode: str) -> None:
    reference = engineer_features(simulate_tracks(1, 8, 30))
    calibration = engineer_features(simulate_tracks(2, 8, 30))
    detector = IsolationThreatDetector(evidence_mode=mode)
    detector.fit(reference, calibration)
    first = detector.score(calibration)
    second = detector.score(calibration)
    np.testing.assert_array_equal(first.threat_score, second.threat_score)
    assert first.threat_score.between(0, 1).all()


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError, match="evidence mode"):
        IsolationThreatDetector(evidence_mode="unknown").fit(pd.DataFrame(), pd.DataFrame())

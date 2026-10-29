"""Isolation scoring with independent synthetic-label isotonic calibration."""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.isotonic import IsotonicRegression

from src.features.kinematics import FEATURE_COLUMNS


def rule_evidence(tracks: pd.DataFrame) -> tuple[np.ndarray, list[list[str]]]:
    reasons: list[list[str]] = []
    floors: list[float] = []
    for contact in tracks.itertuples():
        evidence: list[str] = []
        if contact.sog_delta_knots > 12 or contact.sensor_separation_m > 500:
            evidence.append("KINEMATIC_INCONSISTENCY")
        if contact.dark_minutes >= 10 and contact.loitering_flag:
            evidence.append("DARK_LOITERING")
        if contact.rcs_mismatch_flag:
            evidence.append("RCS_CLASS_MISMATCH")
        reasons.append(evidence)
        floors.append(0.85 if evidence else 0.0)
    return np.asarray(floors), reasons


@dataclass
class IsolationThreatDetector:
    seed: int = 42
    forest: IsolationForest = field(init=False)
    calibrator: IsotonicRegression = field(init=False)
    reference_scores: np.ndarray = field(init=False)

    def fit(self, reference_tracks: pd.DataFrame, calibration_tracks: pd.DataFrame) -> None:
        if set(reference_tracks.track_id) & set(calibration_tracks.track_id):
            raise ValueError("Reference and calibration vessels must be disjoint")
        if calibration_tracks["is_anomaly"].nunique() != 2:
            raise ValueError("Calibration requires both positive and negative labels")
        self.forest = IsolationForest(
            n_estimators=200, contamination="auto", random_state=self.seed, n_jobs=1
        )
        self.forest.fit(reference_tracks[FEATURE_COLUMNS])
        self.reference_scores = np.sort(
            -self.forest.score_samples(reference_tracks[FEATURE_COLUMNS])
        )
        self.calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1)
        self.calibrator.fit(
            self._combined_evidence(calibration_tracks),
            calibration_tracks["is_anomaly"].astype(int),
        )

    def _combined_evidence(self, tracks: pd.DataFrame) -> np.ndarray:
        isolation_scores = -self.forest.score_samples(tracks[FEATURE_COLUMNS])
        percentiles = np.searchsorted(self.reference_scores, isolation_scores, side="right")
        novelty = percentiles / len(self.reference_scores)
        rule_floor, _ = rule_evidence(tracks)
        return np.maximum(novelty * 0.8, rule_floor)

    def score(self, tracks: pd.DataFrame, threshold: float = 0.65) -> pd.DataFrame:
        if not 0 <= threshold <= 1:
            raise ValueError("Alert threshold must be between zero and one")
        scored_tracks = tracks.copy()
        scored_tracks["isolation_score"] = -self.forest.score_samples(tracks[FEATURE_COLUMNS])
        scored_tracks["combined_evidence"] = self._combined_evidence(tracks)
        scored_tracks["threat_score"] = self.calibrator.predict(scored_tracks["combined_evidence"])
        _, reasons = rule_evidence(tracks)
        scored_tracks["reason_codes"] = reasons
        scored_tracks["flagged"] = scored_tracks["threat_score"] >= threshold
        return scored_tracks

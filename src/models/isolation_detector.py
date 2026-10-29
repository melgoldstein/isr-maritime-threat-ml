"""Isolation scoring with independent synthetic-label isotonic calibration."""

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.ensemble import IsolationForest
from sklearn.isotonic import IsotonicRegression
from sklearn.utils.validation import check_is_fitted

from src.features.kinematics import FEATURE_COLUMNS


def rule_evidence(tracks: pd.DataFrame) -> tuple[NDArray[np.float64], list[list[str]]]:
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
    evidence_mode: Literal["hybrid", "isolation", "rules"] = "hybrid"
    forest: IsolationForest = field(init=False)
    calibrator: IsotonicRegression = field(init=False)
    reference_scores: NDArray[np.float64] = field(init=False)

    def fit(self, reference_tracks: pd.DataFrame, calibration_tracks: pd.DataFrame) -> None:
        if self.evidence_mode not in {"hybrid", "isolation", "rules"}:
            raise ValueError("Unsupported evidence mode")
        if reference_tracks.empty or calibration_tracks.empty:
            raise ValueError("Reference and calibration cohorts must be nonempty")
        if set(reference_tracks.track_id) & set(calibration_tracks.track_id):
            raise ValueError("Reference and calibration vessels must be disjoint")
        if calibration_tracks["is_anomaly"].nunique() != 2:
            raise ValueError("Calibration requires both positive and negative labels")
        if not calibration_tracks["is_anomaly"].isin([False, True]).all():
            raise ValueError("Calibration labels must be binary")
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

    def _combined_evidence(self, tracks: pd.DataFrame) -> NDArray[np.float64]:
        isolation_scores = -self.forest.score_samples(tracks[FEATURE_COLUMNS])
        percentiles = np.searchsorted(self.reference_scores, isolation_scores, side="right")
        novelty = percentiles / len(self.reference_scores)
        rule_floor, _ = rule_evidence(tracks)
        if self.evidence_mode == "isolation":
            return novelty
        if self.evidence_mode == "rules":
            return rule_floor
        return np.maximum(novelty * 0.8, rule_floor)

    def score(self, tracks: pd.DataFrame, threshold: float = 0.65) -> pd.DataFrame:
        if not hasattr(self, "calibrator"):
            raise ValueError("Fit the detector before scoring contacts")
        check_is_fitted(self.calibrator)
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

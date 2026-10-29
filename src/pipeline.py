"""Reproducible local training, evaluation, and Ontology staging."""

import argparse
import hashlib
import json
import logging
from importlib.metadata import version
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, precision_score, recall_score

from src.features.kinematics import FEATURE_COLUMNS, engineer_features
from src.ingest.ais_simulator import simulate_tracks, write_tracks
from src.models.artifact import save_model
from src.models.isolation_detector import IsolationThreatDetector
from src.palantir.ontology_mapper import export_ontology

LOGGER = logging.getLogger(__name__)


def run_pipeline(
    output: Path, tracks_path: Path, seed: int = 42, threshold: float = 0.65
) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    reference = engineer_features(simulate_tracks(seed + 1))
    calibration = engineer_features(simulate_tracks(seed + 2))
    evaluation = engineer_features(write_tracks(tracks_path, seed))
    detector = IsolationThreatDetector(seed)
    detector.fit(reference, calibration)
    bundle = save_model(detector, output / "models")
    scored_tracks = detector.score(evaluation, threshold)
    scored_tracks.to_parquet(output / "scored_tracks.parquet", index=False)
    ontology_payload = export_ontology(scored_tracks, output)
    labels = scored_tracks["is_anomaly"].astype(int)
    probabilities = scored_tracks["threat_score"]
    metrics: dict[str, object] = {
        "precision": float(precision_score(labels, scored_tracks["flagged"], zero_division=0)),
        "recall": float(recall_score(labels, scored_tracks["flagged"], zero_division=0)),
        "average_precision": float(average_precision_score(labels, probabilities)),
        "brier_score": float(brier_score_loss(labels, probabilities)),
        "observations": len(scored_tracks),
        "flagged_observations": int(scored_tracks["flagged"].sum()),
        "scenario_recall": {
            scenario: float(subset.loc[subset.is_anomaly, "flagged"].mean())
            for scenario, subset in scored_tracks.groupby("scenario")
            if subset.is_anomaly.any()
        },
    }
    manifest = {
        "schema_version": "1.0.0",
        "model_version": version("isr-maritime-threat-ml"),
        "model_id": bundle.name,
        "model_bundle": str(bundle.resolve()),
        "seed": seed,
        "reference_seed": seed + 1,
        "calibration_seed": seed + 2,
        "threshold": threshold,
        "features": FEATURE_COLUMNS,
        "sensor_sha256": hashlib.sha256(tracks_path.read_bytes()).hexdigest(),
        "calibration_scope": "Synthetic scenarios only; not operational threat probability",
        "dependencies": {
            package: version(package) for package in ["numpy", "pandas", "scikit-learn", "pyarrow"]
        },
        "calibration_knots": {
            "evidence": detector.calibrator.X_thresholds_.tolist(),
            "probability": detector.calibrator.y_thresholds_.tolist(),
        },
        "reference_score_quantiles": np.quantile(
            detector.reference_scores, [0, 0.5, 0.9, 0.99, 1]
        ).tolist(),
    }
    for filename, payload in [("metrics.json", metrics), ("run_manifest.json", manifest)]:
        (output / filename).write_text(
            json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    LOGGER.info(
        "Exported %d vessel alerts; precision %.3f, recall %.3f",
        len(ontology_payload["objects"]),
        metrics["precision"],
        metrics["recall"],
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--tracks", type=Path, default=Path("data/sector_7_tracks.csv"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--threshold", type=float, default=0.65)
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run_pipeline(arguments.output, arguments.tracks, arguments.seed, arguments.threshold)


if __name__ == "__main__":
    main()

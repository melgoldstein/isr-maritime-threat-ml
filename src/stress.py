"""Challenge a frozen model with sensor failures and unseen behavior constructions."""

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.features.kinematics import engineer_features
from src.ingest.ais_simulator import simulate_tracks
from src.models.artifact import load_model

LOGGER = logging.getLogger(__name__)


def challenge_cohorts(seed: int = 9042) -> dict[str, pd.DataFrame]:
    source = simulate_tracks(seed)
    normal = source.loc[source.scenario == "benign"].copy()
    cohorts = {"normal_transit": normal.copy()}
    outage = normal.copy()
    minute = outage.timestamp.dt.minute + outage.timestamp.dt.hour * 60
    outage.loc[
        minute.between(35, 55), ["mmsi", "ais_latitude", "ais_longitude", "sog_knots", "cog_deg"]
    ] = None
    cohorts["ais_outage_during_transit"] = outage
    noisy = normal.copy()
    generator = np.random.default_rng(seed + 100)
    noisy["radar_latitude"] += generator.normal(0, 0.001, len(noisy))
    noisy["radar_longitude"] += generator.normal(0, 0.001, len(noisy))
    cohorts["degraded_radar"] = noisy
    aspect = normal.copy()
    aspect.loc[minute.ge(30), "radar_rcs_dbsm"] += 12
    cohorts["benign_rcs_aspect_change"] = aspect
    fishing = source.loc[source.scenario == "dark_loitering"].copy()
    fishing["is_anomaly"] = False
    cohorts["legitimate_fishing_without_ais"] = fishing
    drift = normal.copy()
    drift["ais_latitude"] += np.maximum(minute.to_numpy() - 30, 0) * 0.0001
    drift["is_anomaly"] = minute.ge(30)
    cohorts["gradual_position_drift"] = drift
    for scenario, contacts in cohorts.items():
        contacts["scenario"] = scenario
        contacts["track_id"] = scenario + "-" + contacts["track_id"]
    return cohorts


def operational_metrics(scored: pd.DataFrame) -> dict[str, object]:
    """Count contiguous false-alert episodes and one anomaly event per affected contact."""
    false_episodes = 0
    detected_events = 0
    anomaly_events = 0
    delays: list[float] = []
    for _, contact in scored.sort_values("timestamp").groupby("track_id"):
        false_flags = contact.flagged & ~contact.is_anomaly
        false_episodes += int((false_flags & ~false_flags.shift(fill_value=False)).sum())
        anomalous = contact.loc[contact.is_anomaly]
        if not anomalous.empty:
            anomaly_events += 1
            detections = anomalous.loc[anomalous.flagged]
            if not detections.empty:
                detected_events += 1
                delays.append(
                    (detections.timestamp.iloc[0] - anomalous.timestamp.iloc[0]).total_seconds()
                    / 60
                )
    benign_hours = float((~scored.is_anomaly).sum() / 60)
    return {
        "observations": len(scored),
        "benign_vessel_hours": benign_hours,
        "false_alert_episodes": false_episodes,
        "false_episodes_per_benign_vessel_hour": false_episodes / benign_hours
        if benign_hours
        else None,
        "flagged_observation_fraction": float(scored.flagged.mean()),
        "anomaly_events": anomaly_events,
        "detected_events": detected_events,
        "event_recall": detected_events / anomaly_events if anomaly_events else None,
        "median_detection_delay_minutes": float(np.median(delays)) if delays else None,
    }


def evaluate_stress(bundle: Path, destination: Path) -> pd.DataFrame:
    detector, manifest = load_model(bundle)
    measurements: list[dict[str, object]] = []
    for scenario, contacts in challenge_cohorts().items():
        enriched = engineer_features(contacts)
        for threshold in (0.3, 0.65, 0.9):
            scored = detector.score(enriched, threshold)
            measurements.append(
                {"scenario": scenario, "threshold": threshold, **operational_metrics(scored)}
            )
        LOGGER.info("Evaluated challenge %s", scenario)
    destination.mkdir(parents=True, exist_ok=True)
    results = pd.DataFrame(measurements)
    results.to_csv(destination / "stress.csv", index=False)
    (destination / "manifest.json").write_text(
        json.dumps(
            {
                "model_id": manifest["model_id"],
                "model_runtime": manifest["runtime"],
                "challenge_seed": 9042,
                "thresholds": [0.3, 0.65, 0.9],
                "protocol": "Frozen model; no fitting, recalibration or threshold selection",
                "exposure": "One minute per observation; false alerts count contiguous episodes",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = [
        "# Frozen-model stress evaluation",
        "",
        "Model is fixed before challenge generation. No test-time recalibration.",
        "",
        "| Scenario | False episodes / benign vessel-hour | Event recall | Median delay (min) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for result in results.loc[results.threshold == 0.65].itertuples():
        recall = "n/a" if pd.isna(result.event_recall) else f"{result.event_recall:.3f}"
        delay = (
            "n/a"
            if pd.isna(result.median_detection_delay_minutes)
            else f"{result.median_detection_delay_minutes:.1f}"
        )
        report.append(
            f"| {result.scenario} | "
            f"{result.false_episodes_per_benign_vessel_hour:.3f} | {recall} | {delay} |"
        )
    report.extend(
        [
            "",
            "Reported operating point: 0.65. CSV includes 0.3 and 0.9 sensitivity checks.",
            "A long false alarm counts as one episode; inspect flagged-observation fraction",
            "in the CSV to assess persistent alert burden. Delay excludes undetected events.",
            "",
            "Legitimate fishing deliberately reuses dark-loitering sensor patterns with",
            "a benign interpretation. The available features cannot distinguish intent.",
            "The RCS shift represents omitted aspect effects; radar degradation increases",
            "position noise to roughly 100 metres.",
            "These are synthetic challenges, not field trials.",
            "",
            "The gradual drift starts at minute 30 and grows by 0.0001 latitude degrees",
            "per minute. An event is one affected contact; exposure assumes one-minute cadence.",
            "",
        ]
    )
    (destination / "STRESS.md").write_text("\n".join(report), encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/stress"))
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    evaluate_stress(arguments.bundle, arguments.output)


if __name__ == "__main__":
    main()

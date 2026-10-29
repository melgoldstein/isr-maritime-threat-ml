"""Reproduce ablations across independent simulation cohorts."""

import argparse
import hashlib
import json
import logging
from importlib.metadata import version
from pathlib import Path

import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_score,
    recall_score,
)

from src.features.kinematics import engineer_features
from src.ingest.ais_simulator import simulate_tracks
from src.models.isolation_detector import IsolationThreatDetector

LOGGER = logging.getLogger(__name__)
BENCHMARK_SEEDS = (42, 142, 242, 342, 442)


def evaluate_benchmark(destination: Path, seeds: tuple[int, ...] = BENCHMARK_SEEDS) -> None:
    """Fit and calibrate each ablation independently with the same cohort partitions."""
    cohort_seeds = [cohort_seed for seed in seeds for cohort_seed in (seed, seed + 1, seed + 2)]
    if not seeds or len(set(cohort_seeds)) != len(cohort_seeds):
        raise ValueError("Benchmark seeds must define nonempty, disjoint cohort triples")
    destination.mkdir(parents=True, exist_ok=True)
    measurements: list[dict[str, object]] = []
    reliability_rows: list[dict[str, object]] = []
    for seed in seeds:
        reference = engineer_features(simulate_tracks(seed + 1))
        calibration = engineer_features(simulate_tracks(seed + 2))
        evaluation = engineer_features(simulate_tracks(seed))
        for mode in ("rules", "isolation", "hybrid"):
            detector = IsolationThreatDetector(seed=seed, evidence_mode=mode)
            detector.fit(reference, calibration)
            scored = detector.score(evaluation)
            labels = scored["is_anomaly"].astype(int)
            tn, fp, fn, tp = confusion_matrix(labels, scored.flagged, labels=[0, 1]).ravel()
            measurements.append(
                {
                    "seed": seed,
                    "method": mode,
                    "precision": float(precision_score(labels, scored.flagged, zero_division=0)),
                    "recall": float(recall_score(labels, scored.flagged, zero_division=0)),
                    "average_precision": float(
                        average_precision_score(labels, scored.threat_score)
                    ),
                    "brier_score": float(brier_score_loss(labels, scored.threat_score)),
                    "false_positive_rate": float(fp / (fp + tn)),
                    "true_negative": int(tn),
                    "false_positive": int(fp),
                    "false_negative": int(fn),
                    "true_positive": int(tp),
                }
            )
            for bin_index in range(10):
                lower = bin_index / 10
                members = scored.loc[
                    scored.threat_score.ge(lower)
                    & (
                        scored.threat_score.lt((bin_index + 1) / 10)
                        if lower < 0.9
                        else scored.threat_score.le(1)
                    )
                ]
                if not members.empty:
                    reliability_rows.append(
                        {
                            "seed": seed,
                            "method": mode,
                            "bin_lower": float(lower),
                            "count": len(members),
                            "mean_prediction": float(members.threat_score.mean()),
                            "observed_fraction": float(members.is_anomaly.mean()),
                        }
                    )
        LOGGER.info("Evaluated benchmark cohort %d", seed)
    benchmark = pd.DataFrame(measurements)
    benchmark.to_csv(destination / "benchmark.csv", index=False)
    pd.DataFrame(reliability_rows).to_csv(destination / "reliability.csv", index=False)
    manifest = {
        "evaluation_seeds": seeds,
        "reference_seed_offset": 1,
        "calibration_seed_offset": 2,
        "vessels_per_cohort": 48,
        "observations_per_vessel": 90,
        "threshold": 0.65,
        "source_sha256": {
            str(module.relative_to(Path(__file__).parent)).replace("\\", "/"): hashlib.sha256(
                module.read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest()
            for module in sorted(Path(__file__).parent.rglob("*.py"))
        },
        "uncertainty": "sample standard deviation across seeds; not a CI",
        "dependencies": {
            package: version(package)
            for package in ("numpy", "pandas", "scikit-learn", "matplotlib")
        },
    }
    (destination / "benchmark_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    _render_comparison(benchmark, destination)
    summary = [
        "# Reproducible benchmark",
        "",
        f"{len(seeds)} independent synthetic evaluation cohorts; "
        f"{len(seeds) * 4320:,} observations per method.",
        "Mean +/- sample standard deviation across seeds. Threshold: 0.65.",
        "",
        "| Method | Precision | Recall | Average precision | Brier score |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for mode in ("rules", "isolation", "hybrid"):
        cohort = benchmark.loc[benchmark.method == mode]
        cells = [
            f"{cohort[metric].mean():.4f} +/- {cohort[metric].std():.4f}"
            for metric in ("precision", "recall", "average_precision", "brier_score")
        ]
        summary.append(f"| {mode} | " + " | ".join(cells) + " |")
    summary.extend(
        [
            "",
            "All methods receive an independently fitted isotonic calibrator.",
            "The rules-only comparison is essential: the generator injects events that match",
            "the rules. High scores demonstrate fixture consistency, not field generalization.",
            "Use benchmark.csv for per-seed confusion counts and reliability.csv for bin counts.",
            "",
            "Reproduce: `python -m src.evaluate --output reports`",
            "",
        ]
    )
    (destination / "BENCHMARK.md").write_text("\n".join(summary), encoding="utf-8")


def _render_comparison(benchmark: pd.DataFrame, destination: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    figure, axes = plt.subplots(1, 2, figsize=(10, 3.8), layout="constrained")
    methods = ["rules", "isolation", "hybrid"]
    colors = ["#8294a6", "#367aa0", "#163b52"]
    for axis, metric, title in zip(
        axes,
        ["recall", "brier_score"],
        ["Detection recall | higher is better", "Brier score | lower is better"],
        strict=True,
    ):
        aggregates = benchmark.groupby("method")[metric].agg(["mean", "std"]).loc[methods]
        axis.bar(
            methods, aggregates["mean"], yerr=aggregates["std"], color=colors, capsize=4, width=0.55
        )
        axis.set_title(title, loc="left", fontsize=11, pad=14)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_axisbelow(True)
        axis.grid(axis="y", alpha=0.15)
        axis.set_ylim(bottom=0, top=1.1 if metric == "recall" else None)
    figure.suptitle("MARITIME ISR / Synthetic benchmark", x=0.01, ha="left", fontsize=14)
    figure.savefig(destination / "benchmark.png", dpi=180, facecolor="white")
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports"))
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    evaluate_benchmark(arguments.output)


if __name__ == "__main__":
    main()

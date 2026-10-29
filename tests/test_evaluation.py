import json
from pathlib import Path

import pandas as pd
import pytest

from src.evaluate import evaluate_benchmark


def test_benchmark_exports_complete_comparisons(tmp_path: Path) -> None:
    evaluate_benchmark(tmp_path, seeds=(42, 142))
    measurements = pd.read_csv(tmp_path / "benchmark.csv")
    assert len(measurements) == 6
    assert set(measurements.method) == {"rules", "isolation", "hybrid"}
    counts = measurements[["true_negative", "false_positive", "false_negative", "true_positive"]]
    assert counts.sum(axis=1).eq(4320).all()
    reliability = pd.read_csv(tmp_path / "reliability.csv")
    assert reliability.groupby(["method", "seed"])["count"].sum().eq(4320).all()
    assert (tmp_path / "benchmark.png").read_bytes().startswith(b"\x89PNG")
    manifest = json.loads((tmp_path / "benchmark_manifest.json").read_text())
    assert manifest["evaluation_seeds"] == [42, 142]


def test_benchmark_rejects_overlapping_cohorts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="disjoint"):
        evaluate_benchmark(tmp_path, seeds=(42, 43))

"""Content-addressed model bundles for a trusted local deployment directory."""

import hashlib
import io
import json
import platform
from importlib.metadata import version
from pathlib import Path

import joblib

from src.features.kinematics import FEATURE_COLUMNS
from src.models.isolation_detector import IsolationThreatDetector


def runtime_contract() -> dict[str, object]:
    source_root = Path(__file__).resolve().parents[1]
    return {
        "schema_version": 1,
        "python": ".".join(platform.python_version_tuple()[:2]),
        "features": FEATURE_COLUMNS,
        "dependencies": {
            package: version(package)
            for package in ("numpy", "pandas", "scikit-learn", "scipy", "joblib")
        },
        "source_sha256": {
            relative: hashlib.sha256(
                (source_root / relative).read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest()
            for relative in (
                "features/kinematics.py",
                "models/isolation_detector.py",
                "ingest/ais_simulator.py",
            )
        },
    }


def save_model(detector: IsolationThreatDetector, registry: Path) -> Path:
    if not hasattr(detector, "reference_scores"):
        raise ValueError("Only fitted models can be saved")
    serialized_model = io.BytesIO()
    joblib.dump(detector, serialized_model, compress=3)
    model_bytes = serialized_model.getvalue()
    runtime = runtime_contract()
    model_sha256 = hashlib.sha256(model_bytes).hexdigest()
    model_id = hashlib.sha256(
        model_bytes + json.dumps(runtime, sort_keys=True).encode()
    ).hexdigest()
    bundle = registry / model_id
    bundle.mkdir(parents=True, exist_ok=True)
    manifest = {
        "model_id": model_id,
        "model_sha256": model_sha256,
        "seed": detector.seed,
        "evidence_mode": detector.evidence_mode,
        "runtime": runtime,
    }
    (bundle / "model.joblib").write_bytes(model_bytes)
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return bundle


def load_model(bundle: Path) -> tuple[IsolationThreatDetector, dict[str, object]]:
    """Load only administrator-produced bundles; a checksum is not a trust signature."""
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("runtime") != runtime_contract():
        raise ValueError("Model runtime contract differs; rebuild with the serving environment")
    model_bytes = (bundle / "model.joblib").read_bytes()
    if hashlib.sha256(model_bytes).hexdigest() != manifest.get("model_sha256"):
        raise ValueError("Model checksum mismatch")
    expected_id = hashlib.sha256(
        model_bytes + json.dumps(manifest["runtime"], sort_keys=True).encode()
    ).hexdigest()
    if expected_id != manifest.get("model_id"):
        raise ValueError("Model identity mismatch")
    detector = joblib.load(io.BytesIO(model_bytes))
    if not isinstance(detector, IsolationThreatDetector):
        raise ValueError("Unexpected model type")
    return detector, manifest

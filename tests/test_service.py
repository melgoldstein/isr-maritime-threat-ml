import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import uvicorn
from fastapi.testclient import TestClient

from scripts.smoke_service import smoke_service
from src.features.kinematics import engineer_features
from src.ingest.ais_simulator import simulate_tracks
from src.models.artifact import load_model, save_model
from src.models.isolation_detector import IsolationThreatDetector
from src.service.api import create_app
from src.service.store import AlertStore, ReplayConflict
from src.stress import evaluate_stress, operational_metrics

API_KEY = "test-only-key-not-for-deployment"


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    detector = IsolationThreatDetector()
    detector.fit(engineer_features(simulate_tracks(43)), engineer_features(simulate_tracks(44)))
    return save_model(detector, tmp_path_factory.mktemp("registry"))


@pytest.fixture
def sensor_request() -> dict[str, object]:
    contacts = simulate_tracks(42, 8, 30).drop(columns=["scenario", "is_anomaly"])
    observations = json.loads(contacts.to_json(orient="records", date_format="iso"))
    return {"request_id": "fixture-42", "observations": observations}


def test_persisted_model_scores_identically(tmp_path: Path) -> None:
    original = IsolationThreatDetector()
    original.fit(
        engineer_features(simulate_tracks(43, 8, 30)), engineer_features(simulate_tracks(44, 8, 30))
    )
    bundle = save_model(original, tmp_path)
    restored, manifest = load_model(bundle)
    contacts = engineer_features(simulate_tracks(42, 8, 30))
    np.testing.assert_array_equal(
        original.score(contacts).threat_score, restored.score(contacts).threat_score
    )
    assert manifest["model_id"] == bundle.name


def test_artifact_integrity_and_runtime_rejected(bundle: Path, tmp_path: Path) -> None:
    manifest = json.loads((bundle / "manifest.json").read_text())
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "model.joblib").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        load_model(tmp_path)
    (tmp_path / "model.joblib").write_bytes((bundle / "model.joblib").read_bytes())
    manifest["model_id"] = "incorrect"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="identity"):
        load_model(tmp_path)
    manifest["runtime"]["features"] = []
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="runtime"):
        load_model(tmp_path)
    with pytest.raises(ValueError, match="fitted"):
        save_model(IsolationThreatDetector(), tmp_path)


def test_api_auth_validation_replay_and_restart(
    bundle: Path, tmp_path: Path, sensor_request: dict[str, object]
) -> None:
    database = tmp_path / "alerts.sqlite3"
    headers = {"X-API-Key": API_KEY}
    with TestClient(create_app(bundle, database, API_KEY)) as client:
        assert client.get("/health").json()["model_id"] == bundle.name
        assert client.get("/v1/model").status_code == 401
        assert client.get("/v1/model", headers=headers).status_code == 200
        first = client.post("/v1/score", json=sensor_request, headers=headers)
        assert first.status_code == 200, first.text
        repeated = client.post("/v1/score", json=sensor_request, headers=headers)
        assert repeated.json() == first.json()
        assert len(first.json()["observations"]) == 240
        assert "isr_requests_total 1" in client.get("/metrics", headers=headers).text
        assert client.get("/v1/alerts", headers=headers).json()
        alert_id = first.json()["ontology"]["actions"][0]["parameters"]["alertId"]
        decision = {
            "model_id": bundle.name,
            "expected_revision": 0,
            "disposition": "DISMISSED",
            "analyst_ref": "analyst-1",
            "rationale": "Known synthetic calibration fixture.",
        }
        reviewed = client.post(f"/v1/alerts/{alert_id}/review", json=decision, headers=headers)
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["revision"] == 1
        assert (
            client.post(f"/v1/alerts/{alert_id}/review", json=decision, headers=headers).status_code
            == 409
        )
        assert (
            client.post("/v1/alerts/missing/review", json=decision, headers=headers).status_code
            == 404
        )
        history = client.get(
            f"/v1/alerts/{alert_id}/history", params={"model_id": bundle.name}, headers=headers
        ).json()
        assert history == [reviewed.json()]
        conflict = dict(sensor_request, threshold=0.9)
        assert client.post("/v1/score", json=conflict, headers=headers).status_code == 409
        invalid = dict(
            sensor_request,
            observations=[sensor_request["observations"][0]] * 2,
            request_id="duplicates",
        )
        assert client.post("/v1/score", json=invalid, headers=headers).status_code == 422
        injected = dict(
            sensor_request, observations=[dict(sensor_request["observations"][0], is_anomaly=True)]
        )
        assert client.post("/v1/score", json=injected, headers=headers).status_code == 422
        invalid_coordinate = dict(
            sensor_request,
            observations=[dict(sensor_request["observations"][0], radar_latitude=91)],
        )
        assert client.post("/v1/score", json=invalid_coordinate, headers=headers).status_code == 422
    with TestClient(create_app(bundle, database, API_KEY)) as restarted:
        assert (
            restarted.post("/v1/score", json=sensor_request, headers=headers).json() == first.json()
        )
        assert "isr_requests_total 1" in restarted.get("/metrics", headers=headers).text
        alerts = restarted.get("/v1/alerts", headers=headers).json()
        assert any(alert["status"] == "DISMISSED" for alert in alerts)


def test_concurrent_commits_are_idempotent(tmp_path: Path) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3")
    response = {
        "model_id": "model-1",
        "ontology": {"actions": [{"parameters": {"alertId": "alert-1"}}]},
    }
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: store.commit("same", "hash", response), range(8)))
    assert all(result == response for result in results)
    assert store.counts() == {"requests": 1, "alerts": 1}
    store.commit("another", "another-hash", response)
    assert store.counts() == {"requests": 2, "alerts": 1}
    with pytest.raises(ReplayConflict):
        store.commit("same", "changed", response)
    assert store.list_alerts(offset=1) == []


def test_service_configuration_requires_secret(
    bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ISR_MODEL_BUNDLE", str(bundle))
    monkeypatch.setenv("ISR_DATABASE", str(tmp_path / "configured.sqlite3"))
    monkeypatch.setenv("ISR_API_KEY", "short")
    with pytest.raises(ValueError, match="24"):
        create_app()
    monkeypatch.setenv("ISR_API_KEY", API_KEY)
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200


def test_frozen_stress_protocol(bundle: Path, tmp_path: Path) -> None:
    before = (bundle / "model.joblib").read_bytes()
    results = evaluate_stress(bundle, tmp_path)
    assert len(results) == 18
    assert (bundle / "model.joblib").read_bytes() == before
    assert results.loc[results.scenario == "normal_transit", "anomaly_events"].eq(0).all()
    assert results.loc[results.scenario == "gradual_position_drift", "anomaly_events"].eq(36).all()


def test_operational_metrics_count_episodes_and_misses() -> None:
    scored = pd.DataFrame(
        {
            "track_id": ["contact-a"] * 6,
            "timestamp": pd.date_range("2026-01-01", periods=6, freq="min", tz="UTC"),
            "is_anomaly": [False, False, False, True, True, True],
            "flagged": [True, True, False, False, True, True],
        }
    )
    metrics = operational_metrics(scored)
    assert metrics["false_alert_episodes"] == 1
    assert metrics["median_detection_delay_minutes"] == 1
    scored["flagged"] = False
    assert operational_metrics(scored)["median_detection_delay_minutes"] is None


def test_live_http_smoke(bundle: Path, tmp_path: Path) -> None:
    application = create_app(bundle, tmp_path / "live.sqlite3", API_KEY)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(application, log_level="error"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            smoke_service(f"http://127.0.0.1:{port}", API_KEY)
        finally:
            server.should_exit = True
            worker.join(timeout=10)
        assert not worker.is_alive()

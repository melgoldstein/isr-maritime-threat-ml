"""Serve a frozen model; each request supplies a complete bounded track window."""

import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from src.features.kinematics import FEATURE_COLUMNS, engineer_features
from src.models.artifact import load_model
from src.palantir.ontology_mapper import build_ontology_payload
from src.service.store import AlertStore, ReplayConflict

LOGGER = logging.getLogger(__name__)


class SensorObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    track_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    timestamp: AwareDatetime
    mmsi: str | None = Field(default=None, pattern=r"^\d{9}$")
    vessel_class: Literal["cargo", "tanker", "fishing"]
    radar_latitude: float = Field(ge=-90, le=90)
    radar_longitude: float = Field(ge=-180, le=180)
    ais_latitude: float | None = Field(default=None, ge=-90, le=90)
    ais_longitude: float | None = Field(default=None, ge=-180, le=180)
    sog_knots: float | None = Field(default=None, ge=0)
    cog_deg: float | None = Field(default=None, ge=0, lt=360)
    radar_rcs_dbsm: float


class ScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    request_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    threshold: float = Field(default=0.65, ge=0, le=1)
    observations: list[SensorObservation] = Field(min_length=1, max_length=5000)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: int = Field(ge=0)
    disposition: Literal["CONFIRMED_ANOMALY", "DISMISSED"]
    analyst_ref: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=12, max_length=2000)


def create_app(
    bundle: Path | None = None, database: Path | None = None, api_key: str | None = None
) -> FastAPI:
    """Uvicorn factory; artifact and key must be provided before process startup."""
    bundle = bundle or Path(os.environ["ISR_MODEL_BUNDLE"])
    database = database or Path(os.environ.get("ISR_DATABASE", "artifacts/alerts.sqlite3"))
    api_key = api_key or os.environ.get("ISR_API_KEY", "")
    if len(api_key) < 24:
        raise ValueError("ISR_API_KEY must contain at least 24 characters")
    detector, manifest = load_model(bundle)
    store = AlertStore(database)
    application = FastAPI(title="Maritime ISR Inference", version="0.2.0")

    def authorize(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if x_api_key is None or not secrets.compare_digest(x_api_key.encode(), api_key.encode()):
            raise HTTPException(status_code=401, detail="Invalid API key")

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready", "model_id": manifest["model_id"]}

    @application.get("/v1/model", dependencies=[Depends(authorize)])
    def model_manifest() -> dict[str, object]:
        return manifest

    @application.get(
        "/metrics", dependencies=[Depends(authorize)], response_class=PlainTextResponse
    )
    def metrics() -> str:
        return "".join(
            f"# TYPE isr_{name}_total counter\nisr_{name}_total {count}\n"
            for name, count in store.counts().items()
        )

    @application.get("/v1/alerts", dependencies=[Depends(authorize)])
    def alerts(
        limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)
    ) -> list[dict[str, object]]:
        return store.list_alerts(limit, offset)

    @application.post("/v1/alerts/{alert_id}/review", dependencies=[Depends(authorize)])
    def review(alert_id: str, request: ReviewRequest) -> dict[str, object]:
        decision = request.model_dump(exclude={"model_id", "expected_revision"})
        decision["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        try:
            return store.review(request.model_id, alert_id, request.expected_revision, decision)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Alert not found") from error
        except ReplayConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/v1/alerts/{alert_id}/history", dependencies=[Depends(authorize)])
    def review_history(
        alert_id: str, model_id: str = Query(pattern=r"^[a-f0-9]{64}$")
    ) -> list[dict[str, object]]:
        return store.review_history(model_id, alert_id)

    @application.post("/v1/score", dependencies=[Depends(authorize)])
    def score(request: ScoreRequest) -> dict[str, object]:
        fingerprint = hashlib.sha256(
            json.dumps(
                {"model_id": manifest["model_id"], "request": request.model_dump(mode="json")},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        try:
            if previous := store.lookup(request.request_id, fingerprint):
                return previous
            contacts = pd.DataFrame(
                [observation.model_dump() for observation in request.observations]
            )
            enriched = engineer_features(contacts)
            scored = detector.score(enriched, request.threshold)
            observation_scores = [
                {
                    "track_id": contact.track_id,
                    "timestamp": contact.timestamp.isoformat(),
                    "threat_score": float(contact.threat_score),
                    "flagged": bool(contact.flagged),
                    "reason_codes": list(contact.reason_codes)
                    or (["STATISTICAL_NOVELTY"] if contact.flagged else []),
                    "evidence": {
                        feature: float(getattr(contact, feature)) for feature in FEATURE_COLUMNS
                    },
                }
                for contact in scored.itertuples()
            ]
            response = {
                "request_id": request.request_id,
                "model_id": manifest["model_id"],
                "observations": observation_scores,
                "ontology": build_ontology_payload(scored),
            }
            result = store.commit(request.request_id, fingerprint, response)
            LOGGER.info(
                "Scored request %s: %d observations, model %s",
                request.request_id,
                len(scored),
                manifest["model_id"],
            )
            return result
        except ReplayConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return application

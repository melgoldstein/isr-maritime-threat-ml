"""Versioned staging records for configured Foundry object and action types."""

import json
from pathlib import Path
from typing import TypedDict
from uuid import NAMESPACE_URL, uuid5

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


class MaritimeVesselObject(TypedDict):
    vesselId: str
    mmsi: str | None
    lastObserved: str
    latitude: float
    longitude: float
    threatScore: float
    reasonCodes: list[str]


class AlertParameters(TypedDict):
    alertId: str
    vesselId: str
    observedAt: str
    threatScore: float
    reasonCodes: list[str]
    status: str


class IsrThreatAlertAction(TypedDict):
    actionType: str
    parameters: AlertParameters


VESSEL_SCHEMA = pa.schema(
    [
        pa.field("vesselId", pa.string(), nullable=False),
        pa.field("mmsi", pa.string()),
        pa.field("lastObserved", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("latitude", pa.float64(), nullable=False),
        pa.field("longitude", pa.float64(), nullable=False),
        pa.field("threatScore", pa.float64(), nullable=False),
        pa.field("reasonCodes", pa.list_(pa.string()), nullable=False),
    ]
)


def build_ontology_payload(scored_tracks: pd.DataFrame) -> dict[str, object]:
    vessels: list[MaritimeVesselObject] = []
    actions: list[IsrThreatAlertAction] = []
    flagged = scored_tracks.loc[scored_tracks["flagged"]].sort_values("timestamp")
    # One staging snapshot per contact; event history remains in scored_tracks.parquet.
    for contact in flagged.groupby("track_id", sort=True).tail(1).itertuples():
        observed_at = contact.timestamp.isoformat()
        reasons = list(contact.reason_codes) or ["STATISTICAL_NOVELTY"]
        vessel: MaritimeVesselObject = {
            "vesselId": contact.track_id,
            "mmsi": None if pd.isna(contact.mmsi) else str(contact.mmsi),
            "lastObserved": observed_at,
            "latitude": float(contact.radar_latitude),
            "longitude": float(contact.radar_longitude),
            "threatScore": float(contact.threat_score),
            "reasonCodes": reasons,
        }
        vessels.append(vessel)
        actions.append(
            {
                "actionType": "IsrThreatAlertAction",
                "parameters": {
                    "alertId": str(
                        uuid5(NAMESPACE_URL, f"isr:v1:{contact.track_id}:{observed_at}")
                    ),
                    "vesselId": contact.track_id,
                    "observedAt": observed_at,
                    "threatScore": float(contact.threat_score),
                    "reasonCodes": reasons,
                    "status": "PENDING_REVIEW",
                },
            }
        )
    ontology_payload: dict[str, object] = {
        "schemaVersion": "1.0.0",
        "objectType": "MaritimeVesselObject",
        "objects": vessels,
        "actions": actions,
    }
    return ontology_payload


def export_ontology(scored_tracks: pd.DataFrame, destination: Path) -> dict[str, object]:
    destination.mkdir(parents=True, exist_ok=True)
    ontology_payload = build_ontology_payload(scored_tracks)
    (destination / "ontology_payload.json").write_text(
        json.dumps(ontology_payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    parquet_records = [
        dict(vessel, lastObserved=pd.Timestamp(vessel["lastObserved"]))
        for vessel in ontology_payload["objects"]
    ]
    pq.write_table(
        pa.Table.from_pylist(parquet_records, schema=VESSEL_SCHEMA),
        destination / "maritime_vessels.parquet",
    )
    return ontology_payload

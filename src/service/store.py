"""SQLite transactions bind replay responses and proposed alerts atomically."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class ReplayConflict(ValueError):
    """A request key was reused for different observations or model settings."""


class AlertStore:
    def __init__(self, database: Path) -> None:
        self.database = database
        database.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    response TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    model_id TEXT NOT NULL,
                    alert_id TEXT NOT NULL,
                    proposal TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
                    revision INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (model_id, alert_id)
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    model_id TEXT NOT NULL,
                    alert_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    decision TEXT NOT NULL,
                    PRIMARY KEY (model_id, alert_id, revision)
                );
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def lookup(self, request_id: str, fingerprint: str) -> dict[str, object] | None:
        with self.connection() as connection:
            record = connection.execute(
                "SELECT fingerprint, response FROM requests WHERE request_id = ?", (request_id,)
            ).fetchone()
        if record is None:
            return None
        if record[0] != fingerprint:
            raise ReplayConflict("Request ID already belongs to a different scoring request")
        return json.loads(record[1])

    def commit(
        self, request_id: str, fingerprint: str, response: dict[str, object]
    ) -> dict[str, object]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT fingerprint, response FROM requests WHERE request_id = ?", (request_id,)
            ).fetchone()
            if existing is not None:
                if existing[0] != fingerprint:
                    raise ReplayConflict(
                        "Request ID already belongs to a different scoring request"
                    )
                return json.loads(existing[1])
            for proposal in response["ontology"]["actions"]:
                connection.execute(
                    "INSERT OR IGNORE INTO alerts (model_id, alert_id, proposal) VALUES (?, ?, ?)",
                    (
                        response["model_id"],
                        proposal["parameters"]["alertId"],
                        json.dumps(proposal, allow_nan=False),
                    ),
                )
            connection.execute(
                "INSERT INTO requests VALUES (?, ?, ?)",
                (request_id, fingerprint, json.dumps(response, allow_nan=False)),
            )
        return response

    def list_alerts(self, limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT model_id, proposal, status, revision FROM alerts "
                "ORDER BY model_id, alert_id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [
            {
                "model_id": model_id,
                "proposal": json.loads(proposal),
                "status": status,
                "revision": revision,
            }
            for model_id, proposal, status, revision in rows
        ]

    def review(
        self, model_id: str, alert_id: str, expected_revision: int, decision: dict[str, object]
    ) -> dict[str, object]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT status, revision FROM alerts WHERE model_id = ? AND alert_id = ?",
                (model_id, alert_id),
            ).fetchone()
            if current is None:
                raise KeyError("Alert not found")
            if current != ("PENDING_REVIEW", expected_revision):
                raise ReplayConflict("Alert has already changed; refresh before reviewing")
            revision = expected_revision + 1
            connection.execute(
                "UPDATE alerts SET status = ?, revision = ? WHERE model_id = ? AND alert_id = ?",
                (decision["disposition"], revision, model_id, alert_id),
            )
            record = {"model_id": model_id, "alert_id": alert_id, "revision": revision, **decision}
            connection.execute(
                "INSERT INTO reviews VALUES (?, ?, ?, ?)",
                (model_id, alert_id, revision, json.dumps(record)),
            )
        return record

    def review_history(self, model_id: str, alert_id: str) -> list[dict[str, object]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT decision FROM reviews WHERE model_id = ? AND alert_id = ? "
                "ORDER BY revision",
                (model_id, alert_id),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def counts(self) -> dict[str, int]:
        with self.connection() as connection:
            return {
                "requests": connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
                "alerts": connection.execute("SELECT COUNT(*) FROM alerts").fetchone()[0],
            }

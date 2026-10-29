"""Exercise a running service, including authenticated replay and persisted alerts."""

import argparse
import json
import logging
import os
import time
import urllib.error
import urllib.request
from uuid import uuid4

from src.ingest.ais_simulator import simulate_tracks

LOGGER = logging.getLogger(__name__)


def smoke_service(base_url: str, api_key: str) -> None:
    for attempt in range(30):
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as response:
                assert json.load(response)["status"] == "ready"
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 29:
                raise
            time.sleep(1)
    contacts = simulate_tracks(42, 8, 30).drop(columns=["scenario", "is_anomaly"])
    payload = json.dumps(
        {
            "request_id": f"smoke-{uuid4()}",
            "observations": json.loads(contacts.to_json(orient="records", date_format="iso")),
        }
    ).encode()
    results: list[dict[str, object]] = []
    for _ in range(2):
        request = urllib.request.Request(
            f"{base_url}/v1/score",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key,
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            results.append(json.load(response))
    assert results[0] == results[1], "Replay changed the response"
    assert len(results[0]["observations"]) == 240
    assert results[0]["ontology"]["actions"], "Expected fixture alerts"
    request = urllib.request.Request(f"{base_url}/v1/alerts", headers={"X-API-Key": api_key})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert json.load(response), "No proposals persisted"
    LOGGER.info("HTTP smoke test passed: 240 observations, identical replay, persisted proposals")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    smoke_service(arguments.url, os.environ["ISR_API_KEY"])

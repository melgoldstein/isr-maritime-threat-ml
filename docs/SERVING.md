# Inference service and analyst review

The service loads a frozen model once at startup. It does not retrain on requests.
Each request supplies a complete track window, including history for causal features.
Requests do not append to an implicit streaming feature cache.

## Run locally

Install `requirements.txt`. From an activated virtual environment in Bash:

```bash
python -m src.pipeline
export ISR_MODEL_BUNDLE="$(python -c 'import json; print(json.load(open("artifacts/run_manifest.json"))["model_bundle"])')"
export ISR_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m uvicorn src.service.api:create_app --factory --host 127.0.0.1 --port 8000
```

PowerShell, from an activated virtual environment:

```powershell
python -m src.pipeline
$env:ISR_MODEL_BUNDLE = (Get-Content artifacts/run_manifest.json | ConvertFrom-Json).model_bundle
$env:ISR_API_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"
python -m uvicorn src.service.api:create_app --factory --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the generated OpenAPI interface. Authenticated
endpoints require the `X-API-Key` header. In another terminal with the same key set,
run `python scripts/smoke_service.py`. It submits 240 observations, verifies an identical
replay response, and checks the persisted proposal list.

## Container

```bash
export ISR_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker compose up --build
```

The image trains a synthetic model in the builder stage and includes it in the runtime
image. Serving uses that frozen artifact. The final process runs as UID 10001; Compose
binds only localhost, mounts a persistent ledger volume, drops capabilities, and uses a
read-only root filesystem. CI builds the image and exercises inference over HTTP.

For repeatable production builds, pin the base image digest and resolved dependencies.
The demonstration Dockerfile follows declared version ranges; the bundle manifest
records installed versions. A new build can produce a different model.

## API contract

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Model loaded and application ready; no key required |
| `GET /v1/model` | Model identity, runtime compatibility contract and feature order |
| `POST /v1/score` | Validate and score 1-5,000 observations; persist proposals and replay response |
| `GET /v1/alerts?limit=100&offset=0` | Paginated proposals with current status and revision |
| `POST /v1/alerts/{alert_id}/review` | Confirm an anomaly or dismiss it using an expected revision |
| `GET /v1/alerts/{alert_id}/history?model_id=...` | Recorded review decisions |
| `GET /metrics` | Durable unique-request and unique-alert counters in Prometheus text format |

Score requests contain `request_id`, optional `threshold` (default 0.65), and `observations`.
Fields are defined in the [dictionary](DATA_DICTIONARY.md). Unknown fields, naive timestamps,
invalid coordinates, non-finite measurements and duplicate contact timestamps are rejected.
Scenario labels are forbidden. Each observation returns seven features, score, flag and reasons.

```json
{
  "request_id": "sector7-window-001",
  "threshold": 0.65,
  "observations": [{
    "track_id": "S7-contact-001",
    "timestamp": "2026-01-01T00:00:00Z",
    "mmsi": "900000001",
    "vessel_class": "cargo",
    "radar_latitude": 35.1,
    "radar_longitude": 24.2,
    "ais_latitude": 35.1,
    "ais_longitude": 24.2,
    "sog_knots": 12.0,
    "cog_deg": 90.0,
    "radar_rcs_dbsm": 32.0
  }]
}
```

This single-observation example validates the contract but has no historical motion evidence.
Use a complete window for meaningful kinematic scoring.

## Replay and transaction semantics

The request fingerprint includes model identity, threshold and the complete validated
payload. Repeating a request ID returns the original response, including after restart.
Reusing the ID for a changed payload or model returns HTTP 409. Observation ordering is
part of the fingerprint even though feature extraction sorts it.

SQLite commits responses and proposals in one transaction. The proposal key is
`(model_id, alert_id)`; a new request ID does not duplicate an existing model/event proposal.
Concurrent writers serialize through `BEGIN IMMEDIATE`. This deduplicates flagged
observation identity; it does not aggregate a long incident. The first proposal is retained
if later windows provide more context for that event.

The ledger does not apply Foundry actions. Exactly-once external delivery is not claimed.
A future adapter needs a durable outbox, retry policy and receiver-side idempotency.

## Analyst review

Submit `model_id`, `expected_revision: 0`, `analyst_ref`, a rationale of at least twelve
characters, and disposition `CONFIRMED_ANOMALY` or `DISMISSED`. Only `PENDING_REVIEW`
proposals can transition. Successful reviews increment revision and record UTC time in
the same transaction. A stale revision returns HTTP 409; an unknown alert returns 404.
Decisions cannot be overwritten through this API.

Confirmation means acceptance of the anomaly finding, not hostile intent. The analyst
reference is caller-supplied: a shared API key does not establish individual identity.
A deployed system should bind it to an authenticated principal. Replayed score responses
preserve their original snapshot; use the alert list for current state and history for decisions.

## Artifact integrity and rollback

Reproduce the frozen-model challenge report after generating a bundle:

```bash
python -m src.stress --bundle "$ISR_MODEL_BUNDLE" --output reports/stress
```

In PowerShell use `$env:ISR_MODEL_BUNDLE` for the bundle argument.

Bundles are stored under `artifacts/models/`. Identity covers serialized model bytes and
the feature/source/runtime contract. Loading verifies the checksum, source fingerprints,
feature order, Python minor version and dependency versions. A mismatch fails startup.
To roll back, select an earlier compatible `ISR_MODEL_BUNDLE` and restart. Proposals are
namespaced by model identity.

Joblib bundles must come from a trusted build directory. Checksums detect corruption,
not malicious replacement of both files. The API accepts no model uploads. See
[scikit-learn persistence guidance](https://scikit-learn.org/stable/model_persistence.html).

This is a single-node reference service. Public deployment still needs TLS termination,
individual identity, body-size/rate limits, backups, retention, resource limits and schema
migration procedures. `/health` confirms startup readiness, not ongoing database write health.

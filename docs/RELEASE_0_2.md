# Version 0.2: frozen inference and durable triage

- Content-addressed model artifacts with source, feature and runtime checks.
- Authenticated FastAPI inference with OpenAPI contracts and per-observation evidence.
- Transactional SQLite request replay and model/event proposal deduplication.
- Analyst confirmation/dismissal with optimistic concurrency and review history.
- Prometheus-compatible durable counters and startup health endpoint.
- Non-root container, Compose deployment and HTTP smoke test in CI.
- Six frozen-model stress scenarios and three threshold sensitivity points.

The original five-seed benchmark is retained. Stress evaluation leaves the model unchanged
and exposes failures outside that fixture: radar degradation raises false-alert burden,
fishing can be observationally ambiguous, and gradual drift is detected later than abrupt
spoofing. See [recorded results](../reports/stress/STRESS.md).

CLI invocation is unchanged. Model serialization is new; regenerate older pipeline runs
to produce bundles. Serving refuses incompatible artifacts. No live Foundry connection
is included, and local review decisions are not submitted to Foundry.

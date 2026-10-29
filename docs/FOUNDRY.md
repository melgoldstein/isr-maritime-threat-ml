# Foundry integration



These are staging contracts, not a portable Ontology deployment bundle or raw API
request body. Configure the following in your Foundry enrollment:

1. Ingest `maritime_vessels.parquet` as a backing dataset and create
   `MaritimeVesselObject`. Map `vesselId` to its string primary key, `lastObserved` to
   timestamp, `latitude`, `longitude`, `threatScore` to double, `mmsi` to nullable
   string, and `reasonCodes` to a string array.
2. Create an alert object type keyed by `alertId`, linked to the vessel through
   `vesselId`. Configure `IsrThreatAlertAction` with the parameter names below and
   rules to create/update the alert with `PENDING_REVIEW` status. Resolve actual API
   names and object-reference parameter encodings from the configured Ontology.
3. Have an authenticated integration consume the action envelopes, validate permissions
   and submission criteria, and apply the configured action using its `parameters`.
   Keep enrollment hostname, Ontology identifier and credentials outside the repository.
4. Use AIP Logic to retrieve the linked evidence and propose an analyst summary. Require
   a reviewer for disposition; keep score, reasons, model version and review decisions
   in the audit record. This repository exports proposals and performs no live action.

Foundry object and action definitions are deployment-specific. See the official
[type reference](https://www.palantir.com/docs/foundry/object-link-types/type-reference),
[action overview](https://www.palantir.com/docs/foundry/action-types/overview/), and
[action rules](https://www.palantir.com/docs/foundry/action-types/rules).

Illustrative JSON excerpt; numerical values depend on the run:

```json
{
  "schemaVersion": "1.0.0",
  "objectType": "MaritimeVesselObject",
  "objects": [{
    "vesselId": "S7-42-0001",
    "mmsi": null,
    "lastObserved": "2026-01-01T01:29:00+00:00",
    "latitude": 28.4,
    "longitude": -80.5,
    "threatScore": 0.99,
    "reasonCodes": ["DARK_LOITERING"]
  }],
  "actions": [{
    "actionType": "IsrThreatAlertAction",
    "parameters": {
      "alertId": "6ff65fc1-d475-5bb8-a027-1da30d19f826",
      "vesselId": "S7-42-0001",
      "observedAt": "2026-01-01T01:29:00+00:00",
      "threatScore": 0.99,
      "reasonCodes": ["DARK_LOITERING"],
      "status": "PENDING_REVIEW"
    }
  }]
}
```

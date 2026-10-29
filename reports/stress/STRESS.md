# Frozen-model stress evaluation

Model is fixed before challenge generation. No test-time recalibration.

| Scenario | False episodes / benign vessel-hour | Event recall | Median delay (min) |
| --- | ---: | ---: | ---: |
| normal_transit | 0.056 | n/a | n/a |
| ais_outage_during_transit | 0.389 | n/a | n/a |
| degraded_radar | 11.019 | n/a | n/a |
| benign_rcs_aspect_change | 4.111 | n/a | n/a |
| legitimate_fishing_without_ais | 0.667 | n/a | n/a |
| gradual_position_drift | 0.167 | 1.000 | 46.0 |

Reported operating point: 0.65. CSV includes 0.3 and 0.9 sensitivity checks.
A long false alarm counts as one episode; inspect flagged-observation fraction
in the CSV to assess persistent alert burden. Delay excludes undetected events.

Legitimate fishing deliberately reuses dark-loitering sensor patterns with
a benign interpretation. The available features cannot distinguish intent.
The RCS shift represents omitted aspect effects; radar degradation increases
position noise to roughly 100 metres.
These are synthetic challenges, not field trials.

The gradual drift starts at minute 30 and grows by 0.0001 latitude degrees
per minute. An event is one affected contact; exposure assumes one-minute cadence.

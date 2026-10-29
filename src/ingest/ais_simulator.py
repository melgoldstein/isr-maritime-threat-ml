"""Generate fused radar tracks with nullable AIS observations and scenario truth."""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
EXPECTED_RCS_DB = {"cargo": 32.0, "tanker": 38.0, "fishing": 17.0}


def simulate_tracks(seed: int = 42, vessels: int = 48, observations: int = 90) -> pd.DataFrame:
    if vessels < 8 or observations < 30:
        raise ValueError("Simulation requires at least 8 vessels and 30 observations")
    generator = np.random.default_rng(seed)
    track_rows: list[dict[str, object]] = []
    for vessel_index in range(vessels):
        vessel_class = str(generator.choice(list(EXPECTED_RCS_DB)))
        scenario = ("spoofing", "dark_loitering", "rcs_mismatch", "benign")[
            vessel_index % 12 if vessel_index % 12 < 3 else 3
        ]
        latitude = 35.0 + generator.uniform(-0.4, 0.4)
        longitude = 24.0 + generator.uniform(-0.4, 0.4)
        course = generator.uniform(0, 360)
        cruise_speed = generator.uniform(8, 18)
        for observation_index in range(observations):
            maneuver_active = observation_index >= observations // 3
            dark_contact = scenario == "dark_loitering" and maneuver_active
            course = (course + (22 if dark_contact else generator.normal(0, 1.2))) % 360
            speed_knots = 1.3 if dark_contact else cruise_speed + generator.normal(0, 0.15)
            latitude += speed_knots / 60 / 60 * np.cos(np.radians(course))
            longitude += (
                speed_knots / 60 / 60 * np.sin(np.radians(course)) / np.cos(np.radians(latitude))
            )
            radar_latitude = latitude + generator.normal(0, 0.00003)
            radar_longitude = longitude + generator.normal(0, 0.00003)
            spoof_offset = 0.08 if scenario == "spoofing" and maneuver_active else 0.0
            # RCS is dB relative to one square metre, not received power in dBm.
            rcs_dbsm = EXPECTED_RCS_DB[vessel_class] + generator.normal(0, 1.5)
            if scenario == "rcs_mismatch" and maneuver_active:
                rcs_dbsm -= 18
            track_rows.append(
                {
                    "track_id": f"S7-{seed}-{vessel_index:04d}",
                    "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc)
                    + timedelta(minutes=observation_index),
                    "mmsi": None if dark_contact else str(900000000 + vessel_index),
                    "vessel_class": vessel_class,
                    "radar_latitude": radar_latitude,
                    "radar_longitude": radar_longitude,
                    "ais_latitude": np.nan if dark_contact else latitude + spoof_offset,
                    "ais_longitude": np.nan if dark_contact else longitude,
                    "sog_knots": np.nan if dark_contact else speed_knots,
                    "cog_deg": np.nan if dark_contact else course,
                    "radar_rcs_dbsm": rcs_dbsm,
                    "scenario": scenario,
                    "is_anomaly": scenario != "benign" and maneuver_active,
                }
            )
    return pd.DataFrame(track_rows)


def write_tracks(destination: Path, seed: int = 42) -> pd.DataFrame:
    ais_track_df = simulate_tracks(seed)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ais_track_df.to_csv(destination, index=False)
    LOGGER.info("Wrote %d synthetic observations to %s", len(ais_track_df), destination)
    return ais_track_df

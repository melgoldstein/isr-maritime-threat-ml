"""Causal per-track evidence; all rolling windows end at the current observation."""

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from src.ingest.ais_simulator import EXPECTED_RCS_DB

FEATURE_COLUMNS = [
    "implied_speed_knots",
    "sog_delta_knots",
    "turn_rate_deg_min",
    "sensor_separation_m",
    "rcs_residual_db",
    "dark_minutes",
    "loitering_flag",
]


def haversine_m(
    latitude_a: NDArray[np.float64],
    longitude_a: NDArray[np.float64],
    latitude_b: NDArray[np.float64],
    longitude_b: NDArray[np.float64],
) -> NDArray[np.float64]:
    phi_a, phi_b = np.radians(latitude_a), np.radians(latitude_b)
    delta_phi = phi_b - phi_a
    delta_lambda = np.radians(longitude_b - longitude_a)
    arc = np.sin(delta_phi / 2) ** 2 + np.cos(phi_a) * np.cos(phi_b) * np.sin(delta_lambda / 2) ** 2
    return 6371008.8 * 2 * np.arcsin(np.sqrt(np.clip(arc, 0, 1)))


def engineer_features(ais_track_df: pd.DataFrame) -> pd.DataFrame:
    required = {
        "track_id",
        "timestamp",
        "mmsi",
        "vessel_class",
        "radar_latitude",
        "radar_longitude",
        "ais_latitude",
        "ais_longitude",
        "sog_knots",
        "cog_deg",
        "radar_rcs_dbsm",
    }
    if missing := required - set(ais_track_df.columns):
        raise ValueError(f"Missing sensor columns: {sorted(missing)}")
    tracks = ais_track_df.copy()
    tracks["timestamp"] = pd.to_datetime(tracks["timestamp"], utc=True, errors="raise")
    if tracks.empty or tracks[["track_id", "timestamp"]].isna().any().any():
        raise ValueError("Track identity and timestamps must be present")
    if tracks.duplicated(["track_id", "timestamp"]).any():
        raise ValueError("Duplicate track timestamps are not permitted")
    for column, bound in [
        ("radar_latitude", 90),
        ("radar_longitude", 180),
        ("ais_latitude", 90),
        ("ais_longitude", 180),
    ]:
        valid = tracks[column].dropna()
        if not np.isfinite(valid).all() or (valid.abs() > bound).any():
            raise ValueError(f"Invalid coordinates: {column}")
    if tracks[["radar_latitude", "radar_longitude", "radar_rcs_dbsm"]].isna().any().any():
        raise ValueError("Radar observations must be complete")
    if not tracks["vessel_class"].isin(EXPECTED_RCS_DB).all():
        raise ValueError("Unsupported vessel class")
    tracks = tracks.sort_values(["track_id", "timestamp"]).reset_index(drop=True)
    enriched_tracks: list[pd.DataFrame] = []
    for _, contact in tracks.groupby("track_id", sort=False):
        contact = contact.copy()
        elapsed_minutes = contact["timestamp"].diff().dt.total_seconds() / 60
        latitude = contact["radar_latitude"].to_numpy(dtype=float)
        longitude = contact["radar_longitude"].to_numpy(dtype=float)
        radar_distance = haversine_m(
            latitude, longitude, np.roll(latitude, 1), np.roll(longitude, 1)
        )
        contact["implied_speed_knots"] = radar_distance / (elapsed_minutes * 60) / 0.514444
        ais_distance = haversine_m(
            contact["ais_latitude"].to_numpy(float),
            contact["ais_longitude"].to_numpy(float),
            contact["ais_latitude"].shift().to_numpy(float),
            contact["ais_longitude"].shift().to_numpy(float),
        )
        contact["sog_delta_knots"] = (
            ais_distance / (elapsed_minutes * 60) / 0.514444 - contact["sog_knots"]
        ).abs()
        north_delta = contact["radar_latitude"].diff()
        east_delta = contact["radar_longitude"].diff() * np.cos(np.radians(latitude))
        radar_course = np.degrees(np.arctan2(east_delta, north_delta)) % 360
        contact["turn_rate_deg_min"] = (
            (radar_course.diff() + 180) % 360 - 180
        ).abs() / elapsed_minutes
        contact["sensor_separation_m"] = haversine_m(
            latitude,
            longitude,
            contact["ais_latitude"].to_numpy(float),
            contact["ais_longitude"].to_numpy(float),
        )
        contact["rcs_residual_db"] = (
            contact["radar_rcs_dbsm"] - contact["vessel_class"].map(EXPECTED_RCS_DB)
        ).abs()
        contact["rcs_mismatch_flag"] = contact["rcs_residual_db"] > 10
        ais_missing = contact[["mmsi", "ais_latitude", "ais_longitude"]].isna().any(axis=1)
        dark_segments = (~ais_missing).cumsum()
        contact["dark_minutes"] = (
            elapsed_minutes.fillna(0).where(ais_missing, 0).groupby(dark_segments).cumsum()
        )
        contact["loitering_flag"] = (
            contact["implied_speed_knots"].rolling(10, min_periods=10).mean().lt(3)
            & contact["turn_rate_deg_min"].rolling(10, min_periods=10).mean().gt(8)
        ).astype(float)
        contact["history_ready"] = elapsed_minutes.notna()
        contact[FEATURE_COLUMNS] = contact[FEATURE_COLUMNS].fillna(0)
        if not np.isfinite(contact[FEATURE_COLUMNS].to_numpy(float)).all():
            raise ValueError("Non-finite kinematic features")
        enriched_tracks.append(contact)
    return pd.concat(enriched_tracks, ignore_index=True)

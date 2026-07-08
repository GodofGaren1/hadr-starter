"""Normalize source payloads to the common event schema (FR-5).

All times are stored as UTC ISO-8601 strings; Singapore time exists only at
render time.
"""

from datetime import datetime, timezone
from typing import Optional


def _iso_from_epoch_ms(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def usgs_feature(feature: dict) -> Optional[dict]:
    """USGS GeoJSON feature -> normalized event, or None if not usable."""
    props = feature.get("properties") or {}
    if props.get("type") != "earthquake":  # quarry blasts, ice quakes, etc.
        return None
    coords = (feature.get("geometry") or {}).get("coordinates") or [None, None, None]
    # `ids` is the alias list; the preferred `id` can change between polls,
    # so identity is the whole set, never the single id (FR-6).
    alias_ids = [part for part in (props.get("ids") or "").split(",") if part]
    if not alias_ids:
        alias_ids = [feature.get("id")]
    return {
        "source": "usgs",
        "stable_key": feature.get("id"),
        "alias_ids": alias_ids,
        "hazard": "earthquake",
        "occurred_at": _iso_from_epoch_ms(props.get("time")),
        "updated_at": _iso_from_epoch_ms(props.get("updated")),
        "geo": {"lon": coords[0], "lat": coords[1], "depth_km": coords[2]},
        "title": props.get("title"),
        "place": props.get("place"),
        "magnitude": props.get("mag"),
        "mag_type": props.get("magType"),
        "impact": {
            "pager_alert": props.get("alert"),  # green/yellow/orange/red or None
            "mmi": props.get("mmi"),
            "felt": props.get("felt"),
            "sig": props.get("sig"),
        },
        "review_status": props.get("status"),  # automatic | reviewed | deleted
        "url": props.get("url"),
    }

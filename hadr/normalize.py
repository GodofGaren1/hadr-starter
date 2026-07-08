"""Normalize source payloads to the common event schema (FR-5).

All times are stored as UTC ISO-8601 strings; Singapore time exists only at
render time. Every normalized event carries:
  alert_level         — unified impact signal (green/yellow/orange/red or None);
                        USGS PAGER has yellow, GDACS does not — triage applies
                        per-source thresholds, but the rank order is shared.
  revision_signature  — changes when the source revised the event materially
                        without changing its alert level.
"""

from datetime import datetime, timezone
from typing import Optional

GDACS_HAZARDS = {
    "EQ": "earthquake", "TS": "tsunami", "TC": "tropical_cyclone",
    "FL": "flood", "VO": "volcano", "DR": "drought", "WF": "wildfire",
}


def _iso_from_epoch_ms(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _iso_from_gdacs(value: Optional[str]) -> Optional[str]:
    # GDACS timestamps arrive timezone-naive; they are UTC by convention.
    if not value:
        return None
    return value if "+" in value or value.endswith("Z") else value + "+00:00"


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
        "alert_level": props.get("alert"),
        "revision_signature": "{}|{}".format(props.get("mag"), props.get("status")),
        "occurred_at": _iso_from_epoch_ms(props.get("time")),
        "updated_at": _iso_from_epoch_ms(props.get("updated")),
        "geo": {"lon": coords[0], "lat": coords[1], "depth_km": coords[2]},
        "title": props.get("title"),
        "place": props.get("place"),
        "magnitude": props.get("mag"),
        "mag_type": props.get("magType"),
        "glide": None,
        "iso3": None,
        "impact": {
            "pager_alert": props.get("alert"),  # green/yellow/orange/red or None
            "mmi": props.get("mmi"),
            "felt": props.get("felt"),
            "sig": props.get("sig"),
        },
        "review_status": props.get("status"),  # automatic | reviewed | deleted
        "url": props.get("url"),
    }


def gdacs_feature(feature: dict) -> Optional[dict]:
    """GDACS EVENTS4APP feature -> normalized event, or None if not usable."""
    props = feature.get("properties") or {}
    eventtype = props.get("eventtype")
    hazard = GDACS_HAZARDS.get(eventtype)
    if not hazard or props.get("eventid") is None:
        return None
    coords = (feature.get("geometry") or {}).get("coordinates") or [None, None]
    key = "gdacs:{}:{}".format(eventtype, props["eventid"])
    severity = props.get("severitydata") or {}
    alert = (props.get("alertlevel") or "").lower() or None
    urls = props.get("url") or {}
    return {
        "source": "gdacs",
        "stable_key": key,
        "alias_ids": [key],  # eventid is stable per eventtype (FR-7)
        "hazard": hazard,
        "alert_level": alert,
        "revision_signature": "{}|{}".format(props.get("episodeid"), props.get("alertscore")),
        "occurred_at": _iso_from_gdacs(props.get("fromdate")),
        "updated_at": _iso_from_gdacs(props.get("datemodified")),
        "geo": {"lon": coords[0], "lat": coords[1], "depth_km": None},
        "title": props.get("htmldescription") or props.get("name"),
        "place": props.get("country"),
        "magnitude": severity.get("severity") if eventtype == "EQ" else None,
        "mag_type": None,
        "glide": props.get("glide") or None,  # frequently empty; re-checked every run (FR-9)
        "iso3": props.get("iso3") or None,
        "impact": {
            "gdacs_alert": alert,
            "alertscore": props.get("alertscore"),
            "episode_alert": (props.get("episodealertlevel") or "").lower() or None,
            "severity_text": severity.get("severitytext"),
        },
        "episode_id": props.get("episodeid"),
        # Empty in list payloads; populated from the detail payload for
        # Orange+ earthquakes, where it is the USGS event id (FR-9).
        "usgs_ref": (props.get("sourceid") or None) if props.get("source") == "NEIC" else None,
        "review_status": "current" if props.get("iscurrent") == "true" else "not_current",
        "url": urls.get("report"),
    }

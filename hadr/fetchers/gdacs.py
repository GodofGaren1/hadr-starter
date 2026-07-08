"""GDACS multi-hazard fetcher (FR-2).

EVENTS4APP returns the latest ~100 events across all hazards for roughly the
last 4 days (droughts excepted) — wide enough that a daily run misses nothing.
The list payload carries `sourceid` as a key but its value is only populated
in the per-event detail payload (for EQ it is the USGS event id), so the
GDACS-to-USGS bridge (FR-9) needs fetch_detail — called lazily, Orange+ only.
"""

from typing import Optional

from hadr.fetchers import FetchResult, get_json

EVENTS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP"
DETAIL_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventdata?eventtype={}&eventid={}"


def fetch() -> FetchResult:
    try:
        payload = get_json(EVENTS_URL)
        return FetchResult(ok=True, features=payload.get("features", []))
    except Exception as exc:
        return FetchResult(ok=False, error="{}: {}".format(type(exc).__name__, exc))


def fetch_detail(eventtype: str, eventid) -> Optional[dict]:
    """Per-event detail properties, or None on failure (enrichment is
    best-effort; the fuzzy correlation pass covers a miss)."""
    try:
        payload = get_json(DETAIL_URL.format(eventtype, eventid))
        return payload.get("properties") or payload
    except Exception:
        return None

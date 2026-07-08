"""USGS earthquake fetcher (FR-1, FR-4).

Uses the FDSN event service with an `updatedafter` cursor rather than the
rolling summary feeds: one call returns both new events and revisions to old
ones, and a delayed cron run cannot fall off a window edge.
"""

import urllib.parse

from hadr.fetchers import FetchResult, get_json, resolve_url

FDSN_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"


def _url() -> str:
    return resolve_url("HADR_USGS_URL", FDSN_URL)

# M4.5 is the reliable global detection floor; below it international
# coverage is too spotty to diff meaningfully.
MIN_MAGNITUDE = 4.5


def fetch(updated_after_iso: str) -> FetchResult:
    """Return every M4.5+ event created or revised since the cursor."""
    params = {
        "format": "geojson",
        "updatedafter": updated_after_iso,
        "minmagnitude": str(MIN_MAGNITUDE),
        "orderby": "time-asc",
        "eventtype": "earthquake",
    }
    try:
        payload = get_json(_url() + "?" + urllib.parse.urlencode(params))
        return FetchResult(ok=True, features=payload.get("features", []))
    except Exception as exc:
        return FetchResult(ok=False, error="{}: {}".format(type(exc).__name__, exc))


def fetch_event_status(alias_ids: list) -> str:
    """'deleted', 'exists', or 'unknown' for a previously seen event (FR-8).

    Deleted events silently vanish from normal queries with no tombstone;
    includedeleted=true is the only way to see them. Tried against every
    alias because the preferred id may have changed since we stored it.
    'unknown' (network trouble, all aliases 404) must never be treated as
    deleted - a retraction needs positive evidence.
    """
    for alias in alias_ids:
        params = {"format": "geojson", "eventid": alias, "includedeleted": "true"}
        try:
            payload = get_json(_url() + "?" + urllib.parse.urlencode(params))
        except Exception:
            continue
        properties = payload.get("properties") or {}
        status = (properties.get("status") or "").lower()
        return "deleted" if status == "deleted" else "exists"
    return "unknown"

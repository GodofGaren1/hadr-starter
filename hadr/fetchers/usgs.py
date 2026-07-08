"""USGS earthquake fetcher (FR-1, FR-4).

Uses the FDSN event service with an `updatedafter` cursor rather than the
rolling summary feeds: one call returns both new events and revisions to old
ones, and a delayed cron run cannot fall off a window edge.
"""

import urllib.parse

from hadr.fetchers import FetchResult, get_json

FDSN_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

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
        payload = get_json(FDSN_URL + "?" + urllib.parse.urlencode(params))
        return FetchResult(ok=True, features=payload.get("features", []))
    except Exception as exc:
        return FetchResult(ok=False, error="{}: {}".format(type(exc).__name__, exc))

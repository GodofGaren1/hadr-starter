"""USGS earthquake fetcher (FR-1, FR-4).

Uses the FDSN event service with an `updatedafter` cursor rather than the
rolling summary feeds: one call returns both new events and revisions to old
ones, and a delayed cron run cannot fall off a window edge.
"""

import json
import urllib.parse
import urllib.request
from typing import Optional

FDSN_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
USER_AGENT = "hadr-monitor/0.1 (course project; wilsonlimwj@gmail.com)"

# M4.5 is the reliable global detection floor; below it international
# coverage is too spotty to diff meaningfully.
MIN_MAGNITUDE = 4.5
TIMEOUT_SECONDS = 30


class FetchResult:
    def __init__(self, ok: bool, features: Optional[list] = None, error: Optional[str] = None):
        self.ok = ok
        self.features = features or []
        self.error = error


def fetch(updated_after_iso: str) -> FetchResult:
    """Return every M4.5+ event created or revised since the cursor."""
    params = {
        "format": "geojson",
        "updatedafter": updated_after_iso,
        "minmagnitude": str(MIN_MAGNITUDE),
        "orderby": "time-asc",
        "eventtype": "earthquake",
    }
    url = FDSN_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.load(response)
        return FetchResult(ok=True, features=payload.get("features", []))
    except Exception as exc:  # a source failure must never fail the run (FR-4)
        return FetchResult(ok=False, error="{}: {}".format(type(exc).__name__, exc))

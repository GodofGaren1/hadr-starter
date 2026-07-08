"""Source fetchers. Each returns a FetchResult; a failure is data, never an
exception, so one source going down cannot fail the run (FR-4)."""

import json
import urllib.request
from typing import Optional

USER_AGENT = "hadr-monitor/0.1 (course project; wilsonlimwj@gmail.com)"
TIMEOUT_SECONDS = 30


class FetchResult:
    def __init__(self, ok: bool, features: Optional[list] = None, error: Optional[str] = None):
        self.ok = ok
        self.features = features or []
        self.error = error


def get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.load(response)

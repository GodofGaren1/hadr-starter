"""Source fetchers. Each returns a FetchResult; a failure is data, never an
exception, so one source going down cannot fail the run (FR-4)."""

import json
import os
import time
import urllib.request
from typing import Optional

USER_AGENT = "hadr-monitor/0.1 (course project; wilsonlimwj@gmail.com)"
TIMEOUT_SECONDS = 30
ATTEMPTS = 2
BACKOFF_SECONDS = 5  # one polite retry, not a hammer


class FetchResult:
    def __init__(self, ok: bool, features: Optional[list] = None, error: Optional[str] = None):
        self.ok = ok
        self.features = features or []
        self.error = error


def resolve_url(env_var: str, default: str) -> str:
    """Feed URLs are env-overridable (HADR_*_URL) for degraded-run drills
    and tests; production never sets these."""
    return os.environ.get(env_var) or default


def get_json(url: str) -> dict:
    last_error = None
    for attempt in range(ATTEMPTS):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < ATTEMPTS:
                time.sleep(BACKOFF_SECONDS)
    raise last_error


def get_bytes(url: str) -> bytes:
    last_error = None
    for attempt in range(ATTEMPTS):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt + 1 < ATTEMPTS:
                time.sleep(BACKOFF_SECONDS)
    raise last_error

"""Cross-source correlation into incidents (FR-9).

Passes, strongest first: shared GLIDE number (late-binding — re-checked
every run because GDACS often fills it days late), the GDACS-to-USGS id
bridge for earthquakes, a fuzzy match (same hazard, different sources,
within 48 hours and 300 km), and a country-based pass for ReliefWeb records,
which carry no coordinates (same hazard, affected country named in the other
record's place, within 96 hours — day-precision dates plus editorial lag).
Correlation links records; it never merges their identities — each source
keeps its own view.

Recomputed from scratch each run: the passes are deterministic and incident
ids derive from member keys, so ids stay stable without a counter.
"""

import math

FUZZY_MAX_HOURS = 48
FUZZY_MAX_KM = 300
COUNTRY_PASS_MAX_HOURS = 96


def _haversine_km(a: dict, b: dict) -> float:
    if None in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon")):
        return float("inf")
    lat1, lon1, lat2, lon2 = map(math.radians, [a["lat"], a["lon"], b["lat"], b["lon"]])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(h))


def _hours_apart(iso_a: str, iso_b: str) -> float:
    from datetime import datetime
    if not iso_a or not iso_b:
        return float("inf")
    a = datetime.fromisoformat(iso_a)
    b = datetime.fromisoformat(iso_b)
    return abs((a - b).total_seconds()) / 3600.0


class _UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, item):
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def build_incidents(state: dict) -> None:
    """Rebuild state['incidents'] and stamp each event record's incident id."""
    events = {key: record["latest"] for key, record in state["events"].items()}
    uf = _UnionFind()
    methods = {}  # frozenset of a linked pair -> method name

    def link(key_a, key_b, method):
        uf.union(key_a, key_b)
        methods[frozenset((key_a, key_b))] = method

    # Pass 1 — shared GLIDE
    by_glide = {}
    for key, event in events.items():
        if event.get("glide"):
            by_glide.setdefault(event["glide"], []).append(key)
    for keys in by_glide.values():
        for other in keys[1:]:
            link(keys[0], other, "glide")

    # Pass 2 — GDACS sourceid -> USGS alias set
    usgs_by_alias = {}
    for key, record in state["events"].items():
        if record["latest"]["source"] == "usgs":
            for alias in record["alias_ids"]:
                usgs_by_alias[alias] = key
    for key, event in events.items():
        ref = event.get("usgs_ref")
        if event["source"] == "gdacs" and ref and ref in usgs_by_alias:
            link(key, usgs_by_alias[ref], "usgs_id_bridge")

    # Pass 3 — fuzzy, cross-source only
    keys = sorted(events)
    for i, key_a in enumerate(keys):
        a = events[key_a]
        for key_b in keys[i + 1:]:
            b = events[key_b]
            if (a["source"] != b["source"]
                    and a["hazard"] == b["hazard"]
                    and uf.find(key_a) != uf.find(key_b)
                    and _hours_apart(a["occurred_at"], b["occurred_at"]) <= FUZZY_MAX_HOURS
                    and _haversine_km(a["geo"], b["geo"]) <= FUZZY_MAX_KM):
                link(key_a, key_b, "fuzzy")

    # Pass 4 — ReliefWeb country match (no coordinates on that side)
    def country_match(rw_event, other):
        if rw_event.get("iso3") and other.get("iso3"):
            return rw_event["iso3"] == other["iso3"]
        haystack = (other.get("place") or "").lower()
        return any(c.lower() in haystack for c in rw_event.get("countries", []) if c)

    for key_a in keys:
        a = events[key_a]
        if a["source"] != "reliefweb":
            continue
        for key_b in keys:
            b = events[key_b]
            if (b["source"] not in ("usgs", "gdacs")
                    or a["hazard"] != b["hazard"]
                    or uf.find(key_a) == uf.find(key_b)):
                continue
            if (_hours_apart(a["occurred_at"], b["occurred_at"]) <= COUNTRY_PASS_MAX_HOURS
                    and country_match(a, b)):
                link(key_a, key_b, "country")

    groups = {}
    for key in events:
        groups.setdefault(uf.find(key), []).append(key)

    state["incidents"] = {}
    for members in groups.values():
        members = sorted(members)
        incident_id = None
        if len(members) > 1:
            incident_id = "inc:" + min(members)
            state["incidents"][incident_id] = {
                "members": members,
                "methods": sorted({m for pair, m in methods.items()
                                   if pair <= set(members)}),
            }
        for key in members:
            state["events"][key]["incident"] = incident_id

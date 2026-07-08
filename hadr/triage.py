"""Impact-based triage (FR-10, PRD section 6).

Physical severity alone never triggers a report; the signals are USGS PAGER
(yellow+) and the GDACS alert level (orange+ — GDACS has no yellow tier).

Significance is judged by scanning every tracked incident against the
reporting ledger — what the reader was last told — NOT against this run's
diff. An incident that fired while a sitrep failed (or was never published)
re-surfaces on every run until mark_reported.py records it. Droughts are
exempt from daily "new" logic (slow-onset; they get a periodic status line
instead).
"""

from hadr.store import ALERT_RANK

REPORT_THRESHOLD = {"usgs": ALERT_RANK["yellow"], "gdacs": ALERT_RANK["orange"]}
DOWNGRADE_FLOOR = min(REPORT_THRESHOLD.values())


def _reportable_units(state: dict) -> list:
    """Group event keys into incidents; uncorrelated events stand alone."""
    seen = set()
    units = []
    for incident_id, incident in state["incidents"].items():
        units.append((incident_id, incident["members"]))
        seen.update(incident["members"])
    for key in state["events"]:
        if key not in seen:
            units.append((None, [key]))
    return units


def _member_view(state: dict, key: str) -> dict:
    event = state["events"][key]["latest"]
    return {
        "key": key,
        "source": event["source"],
        "alert_level": event["alert_level"],
        "title": event["title"],
        "url": event["url"],
    }


def build_facts(state: dict, changes: list, stale_transitions: list, now_iso: str) -> dict:
    changes_by_key = {c["key"]: c for c in changes}
    significant = []

    for incident_id, members in _reportable_units(state):
        report_rank = 0      # highest level that clears its own source threshold
        current_rank = 0     # highest level regardless of threshold
        reported_rank = 0    # highest level the reader has been told
        lead_key = None
        for key in members:
            event = state["events"][key]["latest"]
            if event["hazard"] == "drought":
                continue
            rank = ALERT_RANK.get(event["alert_level"], 0)
            current_rank = max(current_rank, rank)
            if rank >= REPORT_THRESHOLD[event["source"]] and rank > report_rank:
                report_rank = rank
                lead_key = key
            entry = state["ledger"].get(key)
            if entry:
                reported_rank = max(reported_rank, ALERT_RANK.get(entry["reported_level"], 0))

        reason = None
        if report_rank > reported_rank:
            reason = "escalation" if reported_rank else "new_incident"
        elif reported_rank >= DOWNGRADE_FLOOR and current_rank < reported_rank:
            reason = "downgrade"
            lead_key = max(
                (k for k in members if k in state["ledger"]),
                key=lambda k: ALERT_RANK.get(state["ledger"][k]["reported_level"], 0),
            )

        if reason:
            significant.append({
                "key": lead_key,
                "reason": reason,
                "change": changes_by_key.get(lead_key),  # this-run context, may be None
                "event": state["events"][lead_key]["latest"],
                "incident": {
                    "id": incident_id,
                    "members": [_member_view(state, k) for k in members],
                },
                "previously_reported_level": (
                    (state["ledger"].get(lead_key) or {}).get("reported_level")
                ),
            })

    # Current status of everything already reported, so the sitrep can write
    # an honest "changes since yesterday" section without touching state.
    previously_reported = []
    for key, entry in state["ledger"].items():
        record = state["events"].get(key)
        if record:
            previously_reported.append({
                "key": key,
                "title": record["latest"]["title"],
                "reported_level": entry["reported_level"],
                "current_level": record["latest"]["alert_level"],
            })

    source_notes = []
    for source, status in state["sources"].items():
        if status["consecutive_failures"] > 0:
            source_notes.append({
                "source": source,
                "stale_since": status["last_success"],
                "error": status["last_error"],
            })

    tracked_by_source = {}
    for record in state["events"].values():
        source = record["latest"]["source"]
        tracked_by_source[source] = tracked_by_source.get(source, 0) + 1

    quiet = not significant and not stale_transitions
    return {
        "generated_at": now_iso,
        "quiet": quiet,
        "significant": significant,
        "previously_reported": previously_reported,
        "source_notes": source_notes,
        "stale_transitions": stale_transitions,
        "counts": {
            "events_tracked": len(state["events"]),
            "tracked_by_source": tracked_by_source,
            "correlated_incidents": len(state["incidents"]),
            "changes_this_run": len(changes),
        },
    }

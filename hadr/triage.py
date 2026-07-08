"""Impact-based triage (FR-10, PRD section 6).

Magnitude alone never triggers a report; the signal is PAGER (`alert`).
Significance is judged against the reporting ledger — what the reader was
last told — not against the previous poll.
"""

from hadr.store import ALERT_RANK

REPORT_THRESHOLD = ALERT_RANK["yellow"]


def _reported_rank(state: dict, key: str) -> int:
    entry = state["ledger"].get(key)
    return ALERT_RANK.get(entry["reported_level"], 0) if entry else 0


def build_facts(state: dict, changes: list, stale_transitions: list, now_iso: str) -> dict:
    significant = []
    for change in changes:
        record = state["events"][change["key"]]
        event = record["latest"]
        current_rank = ALERT_RANK.get(event["impact"]["pager_alert"], 0)
        reported = _reported_rank(state, change["key"])

        reason = None
        if change["type"] in ("NEW", "UPGRADED", "REVISED") and current_rank >= REPORT_THRESHOLD:
            if current_rank > reported:
                reason = "escalation" if reported else "new_incident"
        elif change["type"] == "DOWNGRADED" and reported >= REPORT_THRESHOLD:
            reason = "downgrade"

        if reason:
            significant.append({
                "key": change["key"],
                "reason": reason,
                "change": change,
                "event": event,
                "previously_reported_level": (
                    state["ledger"].get(change["key"], {}).get("reported_level")
                ),
            })

    source_notes = []
    for source, status in state["sources"].items():
        if status["consecutive_failures"] > 0:
            source_notes.append({
                "source": source,
                "stale_since": status["last_success"],
                "error": status["last_error"],
            })

    quiet = not significant and not stale_transitions
    return {
        "generated_at": now_iso,
        "quiet": quiet,
        "significant": significant,
        "source_notes": source_notes,
        "stale_transitions": stale_transitions,
        "counts": {
            "events_tracked": len(state["events"]),
            "changes_this_run": len(changes),
        },
    }

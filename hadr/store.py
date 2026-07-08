"""State store and reconciliation (FR-6, FR-7 groundwork).

State is a single committed JSON file. Reconcile diffs freshly fetched events
against it and emits typed changes; "changed" downstream always means changed
relative to the reporting ledger, which only mark_reported.py may write.
"""

import json
from pathlib import Path

STATE_VERSION = 1

ALERT_RANK = {None: 0, "": 0, "green": 1, "yellow": 2, "orange": 3, "red": 4}


def empty_state() -> dict:
    return {
        "version": STATE_VERSION,
        "cursors": {},          # source -> ISO timestamp for updatedafter-style fetching
        "sources": {},          # source -> {last_success, last_error, consecutive_failures}
        "events": {},           # canonical key -> record
        "ledger": {},           # canonical key -> {reported_level, reported_at}
    }


def load_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save_state(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(state, handle, indent=1, sort_keys=True)
        handle.write("\n")


def _find_existing_key(state: dict, event: dict) -> str:
    """Match by alias-set intersection (FR-6); '' if unseen."""
    incoming = set(event["alias_ids"])
    for key, record in state["events"].items():
        if incoming & set(record["alias_ids"]):
            return key
    return ""


def reconcile(state: dict, events: list, now_iso: str) -> list:
    """Fold fetched events into state; return typed change dicts."""
    changes = []
    for event in events:
        key = _find_existing_key(state, event)
        if not key:
            key = event["stable_key"]
            state["events"][key] = {
                "alias_ids": event["alias_ids"],
                "latest": event,
                "first_seen": now_iso,
                "level_history": [{"at": now_iso, "level": event["impact"]["pager_alert"]}],
            }
            changes.append({"type": "NEW", "key": key})
            continue

        record = state["events"][key]
        record["alias_ids"] = sorted(set(record["alias_ids"]) | set(event["alias_ids"]))
        previous = record["latest"]
        old_rank = ALERT_RANK.get(previous["impact"]["pager_alert"], 0)
        new_rank = ALERT_RANK.get(event["impact"]["pager_alert"], 0)
        record["latest"] = event

        if new_rank != old_rank:
            record["level_history"].append(
                {"at": now_iso, "level": event["impact"]["pager_alert"]}
            )
            kind = "UPGRADED" if new_rank > old_rank else "DOWNGRADED"
            changes.append({
                "type": kind, "key": key,
                "from_level": previous["impact"]["pager_alert"],
                "to_level": event["impact"]["pager_alert"],
            })
        elif (event["magnitude"] != previous["magnitude"]
              or event["review_status"] != previous["review_status"]):
            changes.append({"type": "REVISED", "key": key})
    return changes


def record_source_status(state: dict, source: str, ok: bool, error: str, now_iso: str) -> bool:
    """Update source health; return True when the source newly went stale."""
    status = state["sources"].setdefault(
        source, {"last_success": None, "last_error": None, "consecutive_failures": 0}
    )
    was_healthy = status["consecutive_failures"] == 0
    if ok:
        status.update({"last_success": now_iso, "last_error": None, "consecutive_failures": 0})
        return False
    status["last_error"] = "{} at {}".format(error, now_iso)
    status["consecutive_failures"] += 1
    return was_healthy

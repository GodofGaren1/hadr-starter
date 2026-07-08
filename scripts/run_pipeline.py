"""Run pipeline stages 1-5: fetch, normalize, reconcile, correlate, triage.

Writes data/state.json and data/facts.json. Never calls a model (the model
boundary lives between this script and the /sitrep step). Exit 0 even when a
source is down — only a bug in the pipeline itself is a failure.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hadr import correlate, normalize, store, triage
from hadr.fetchers import gdacs, usgs

STATE_PATH = REPO_ROOT / "data" / "state.json"
FACTS_PATH = REPO_ROOT / "data" / "facts.json"

FIRST_RUN_LOOKBACK = timedelta(days=7)
CURSOR_OVERLAP = timedelta(minutes=10)  # re-fetch a sliver so a clock skew can't drop events


def enrich_gdacs_details(state) -> None:
    """Lazy detail fetch, Orange+ only (FR-2): fills usgs_ref (the id bridge,
    FR-9) and late-arriving GLIDE numbers. Best-effort - a miss just leaves
    correlation to the fuzzy pass."""
    for key, record in state["events"].items():
        event = record["latest"]
        if (event["source"] != "gdacs"
                or store.ALERT_RANK.get(event["alert_level"], 0) < store.ALERT_RANK["orange"]):
            continue
        wants_bridge = event["hazard"] == "earthquake" and not event.get("usgs_ref")
        if not wants_bridge and event.get("glide"):
            continue
        eventtype = key.split(":")[1]
        detail = gdacs.fetch_detail(eventtype, key.split(":")[2])
        if not detail:
            continue
        if not event.get("usgs_ref") and detail.get("source") == "NEIC":
            event["usgs_ref"] = detail.get("sourceid") or None
        if not event.get("glide"):
            event["glide"] = detail.get("glide") or None


def main() -> int:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    state = store.load_state(STATE_PATH)

    stale_transitions = []
    changes = []

    def ingest(source: str, result, normalizer):
        if result.ok:
            events = [e for e in map(normalizer, result.features) if e]
            source_changes = store.reconcile(state, events, now_iso)
            changes.extend(source_changes)
            store.record_source_status(state, source, True, "", now_iso)
            print("{}: fetched {} features, {} changes".format(
                source, len(result.features), len(source_changes)))
        else:
            if store.record_source_status(state, source, False, result.error, now_iso):
                stale_transitions.append({"source": source, "error": result.error})
            print("{}: FETCH FAILED ({}); continuing degraded".format(source, result.error))

    cursor = state["cursors"].get("usgs") or (now - FIRST_RUN_LOOKBACK).isoformat()
    usgs_result = usgs.fetch(cursor)
    ingest("usgs", usgs_result, normalize.usgs_feature)
    if usgs_result.ok:
        state["cursors"]["usgs"] = (now - CURSOR_OVERLAP).isoformat()

    # GDACS has no cursor: EVENTS4APP is a rolling ~4-day window and
    # reconcile makes re-ingesting the same events idempotent.
    ingest("gdacs", gdacs.fetch(), normalize.gdacs_feature)

    enrich_gdacs_details(state)
    correlate.build_incidents(state)

    facts = triage.build_facts(state, changes, stale_transitions, now_iso)
    store.save_state(state, STATE_PATH)
    with open(FACTS_PATH, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(facts, handle, indent=1, sort_keys=True)
        handle.write("\n")

    print("facts: quiet={} significant={} tracked={} incidents={}".format(
        facts["quiet"], len(facts["significant"]),
        facts["counts"]["events_tracked"], facts["counts"]["correlated_incidents"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

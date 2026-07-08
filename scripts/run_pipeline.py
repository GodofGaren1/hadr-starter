"""Run pipeline stages 1-5: fetch, normalize, reconcile, triage, emit facts.

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

from hadr import normalize, store, triage
from hadr.fetchers import usgs

STATE_PATH = REPO_ROOT / "data" / "state.json"
FACTS_PATH = REPO_ROOT / "data" / "facts.json"

FIRST_RUN_LOOKBACK = timedelta(days=7)
CURSOR_OVERLAP = timedelta(minutes=10)  # re-fetch a sliver so a clock skew can't drop events


def main() -> int:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    state = store.load_state(STATE_PATH)

    cursor = state["cursors"].get("usgs") or (now - FIRST_RUN_LOOKBACK).isoformat()
    result = usgs.fetch(cursor)

    stale_transitions = []
    changes = []
    if result.ok:
        events = [e for e in map(normalize.usgs_feature, result.features) if e]
        changes = store.reconcile(state, events, now_iso)
        state["cursors"]["usgs"] = (now - CURSOR_OVERLAP).isoformat()
        store.record_source_status(state, "usgs", True, "", now_iso)
        print("usgs: fetched {} features, {} changes".format(len(result.features), len(changes)))
    else:
        newly_stale = store.record_source_status(state, "usgs", False, result.error, now_iso)
        if newly_stale:
            stale_transitions.append({"source": "usgs", "error": result.error})
        print("usgs: FETCH FAILED ({}); continuing degraded".format(result.error))

    facts = triage.build_facts(state, changes, stale_transitions, now_iso)
    store.save_state(state, STATE_PATH)
    with open(FACTS_PATH, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(facts, handle, indent=1, sort_keys=True)
        handle.write("\n")

    print("facts: quiet={} significant={} tracked={}".format(
        facts["quiet"], len(facts["significant"]), facts["counts"]["events_tracked"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

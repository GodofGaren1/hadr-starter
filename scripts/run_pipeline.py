"""Run pipeline stages 1-5: fetch, normalize, reconcile, correlate, triage.

Writes data/state.json and data/facts.json. Never calls a model (the model
boundary lives between this script and the /sitrep step). Exit 0 even when a
source is down — only a bug in the pipeline itself is a failure.

--replay <snapshot-dir>: re-run from an archived snapshot with no network at
all (no fetches, no deletion checks, no detail enrichment). For backtesting
triage against a past day, point it at a data/snapshots/<stamp>/ directory —
and copy data/state.json aside first if you don't want the replay folded in.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hadr import correlate, normalize, snapshots, store, triage
from hadr.fetchers import FetchResult, gdacs, reliefweb_rss, usgs

STATE_PATH = REPO_ROOT / "data" / "state.json"
FACTS_PATH = REPO_ROOT / "data" / "facts.json"
SNAPSHOT_ROOT = REPO_ROOT / "data" / "snapshots"

FIRST_RUN_LOOKBACK = timedelta(days=7)
CURSOR_OVERLAP = timedelta(minutes=10)  # re-fetch a sliver so a clock skew can't drop events


def check_deletions(state, now_iso) -> list:
    """FR-8: only previously REPORTED USGS events are re-checked — those are
    the ones whose disappearance the reader must hear about. A handful of
    queries per run, and only positive evidence retracts."""
    deletion_changes = []
    for key in list(state["ledger"]):
        record = state["events"].get(key)
        if (not record
                or record["latest"]["source"] != "usgs"
                or record["latest"]["review_status"] == "deleted"
                or (state["ledger"][key] or {}).get("retraction_reported")):
            continue
        status = usgs.fetch_event_status(record["alias_ids"])
        if status == "deleted":
            deletion_changes.append(store.apply_deletion(state, key, now_iso))
            print("usgs: {} deleted at source - retraction queued".format(key))
    return deletion_changes


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", metavar="SNAPSHOT_DIR",
                        help="re-run offline from an archived snapshot directory")
    args = parser.parse_args()
    replay_dir = Path(args.replay) if args.replay else None

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    state = store.load_state(STATE_PATH)

    stale_transitions = []
    changes = []

    def ingest(source: str, result, normalizer):
        if result.ok:
            if not replay_dir:
                snapshots.save(SNAPSHOT_ROOT, stamp, source, result.features)
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

    def replayed(source: str) -> FetchResult:
        features = snapshots.load(replay_dir, source)
        if features is None:
            return FetchResult(ok=False, error="no {} snapshot in {}".format(source, replay_dir))
        return FetchResult(ok=True, features=features)

    if replay_dir:
        ingest("usgs", replayed("usgs"), normalize.usgs_feature)
    else:
        cursor = state["cursors"].get("usgs") or (now - FIRST_RUN_LOOKBACK).isoformat()
        usgs_result = usgs.fetch(cursor)
        ingest("usgs", usgs_result, normalize.usgs_feature)
        if usgs_result.ok:
            state["cursors"]["usgs"] = (now - CURSOR_OVERLAP).isoformat()

    # GDACS has no cursor: EVENTS4APP is a rolling ~4-day window and
    # reconcile makes re-ingesting the same events idempotent.
    ingest("gdacs", replayed("gdacs") if replay_dir else gdacs.fetch(),
           normalize.gdacs_feature)

    # ReliefWeb RSS: the 20 most recent editorial disaster records.
    ingest("reliefweb", replayed("reliefweb") if replay_dir else reliefweb_rss.fetch(),
           normalize.reliefweb_item)

    if not replay_dir:  # replay is strictly offline
        changes.extend(check_deletions(state, now_iso))
        enrich_gdacs_details(state)
        snapshots.prune(SNAPSHOT_ROOT)
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

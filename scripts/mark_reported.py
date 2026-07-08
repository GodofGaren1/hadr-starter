"""Update the reporting ledger after a sitrep is actually published (FR-13).

Kept separate from run_pipeline.py so the ledger only ever reflects what the
reader was shown: if the sitrep step fails, the next run re-surfaces the same
incidents instead of losing them.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hadr import store

STATE_PATH = REPO_ROOT / "data" / "state.json"
FACTS_PATH = REPO_ROOT / "data" / "facts.json"


def main() -> int:
    with open(FACTS_PATH, encoding="utf-8") as handle:
        facts = json.load(handle)
    state = store.load_state(STATE_PATH)

    marked = 0
    for item in facts["significant"]:
        # The reader was shown the whole incident, so every member is
        # reported at its own current level - a corroborating source view
        # arriving later must not re-alert.
        for member in item["incident"]["members"]:
            state["ledger"][member["key"]] = {
                "reported_level": member["alert_level"],
                "reported_at": facts["generated_at"],
            }
            marked += 1
    store.save_state(state, STATE_PATH)
    print("ledger: marked {} event record(s) across {} incident(s)".format(
        marked, len(facts["significant"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The deterministic gate (FR-11). No model call, no network.

Reads data/facts.json and reports whether the sitrep step should run.
Emits `changed=true|false` on stdout and into $GITHUB_OUTPUT when present,
so the workflow branches on an output variable rather than a failing exit
code (a nonzero exit would mark the Actions step failed). Exit 0 on any
successful decision; exit 2 only when the pipeline never produced facts.
"""

import json
import os
import sys
from pathlib import Path

FACTS_PATH = Path(__file__).resolve().parents[1] / "data" / "facts.json"


def main() -> int:
    if not FACTS_PATH.exists():
        print("error: data/facts.json missing - run scripts/run_pipeline.py first", file=sys.stderr)
        return 2
    with open(FACTS_PATH, encoding="utf-8") as handle:
        facts = json.load(handle)

    changed = not facts.get("quiet", True)
    line = "changed={}".format(str(changed).lower())
    print(line)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

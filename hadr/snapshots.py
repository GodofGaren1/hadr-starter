"""Raw payload snapshots for replay and backtesting (FR-14).

Each pipeline run writes the normalized-input features it fetched to
data/snapshots/<stamp>/<source>.json. Snapshots are NOT committed (they would
bloat the repo); locally they are pruned to the newest KEEP runs, and in CI
the workflow uploads them as a build artifact. `run_pipeline.py --replay
<dir>` re-runs the pipeline from a snapshot with no network access.
"""

import json
import shutil
from pathlib import Path

KEEP = 14


def save(root: Path, stamp: str, source: str, features: list) -> None:
    run_dir = root / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / (source + ".json"), "w", encoding="utf-8", newline="\n") as handle:
        json.dump(features, handle)


def load(run_dir: Path, source: str) -> list:
    """Features for one source, or None when the snapshot lacks that source."""
    path = Path(run_dir) / (source + ".json")
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def prune(root: Path, keep: int = KEEP) -> None:
    if not root.exists():
        return
    runs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name)
    for stale in runs[:-keep]:
        shutil.rmtree(stale, ignore_errors=True)

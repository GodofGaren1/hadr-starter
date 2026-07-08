# Implementation notes

Kept by the agent, reviewed by you. One entry per working block.

## Decisions

- **2026-07-08 — prd.html drafted (v0.1).** Architecture: once-daily batch pipeline on GitHub Actions (00:20 UTC), state committed to the repo as `data/state.json`, deterministic change gate before any model call (per sitrep.yml). USGS fetched via FDSN `updatedafter` cursor (not rolling-window summary feeds) so revisions and delayed runs are handled; USGS identity via `ids` alias sets; GDACS episodes stored as versions; ReliefWeb starts on the no-approval RSS feed with the API v2 client as a drop-in swap once the appname is approved. Triage is impact-based (GDACS Orange+, PAGER yellow+, any new ReliefWeb disaster record); droughts exempt from daily "new" logic. Open decisions listed in prd.html §11.

## Open questions

- Geographic scope: global vs. region-weighted triage thresholds (PRD §11, defaulting to global).
- Quiet-day dashboard behaviour: leave untouched vs. stamp "no significant change" (defaulting to untouched).
- ReliefWeb appname approval pending — submitted when? (Confirm the form actually went in; RSS fallback works meanwhile.)

- **2026-07-08 — Slice 1 built and verified end-to-end (USGS only).** `hadr/` package (fetcher, normalize, store, triage) + `scripts/run_pipeline.py`, `check_changes.py`, `mark_reported.py`. Live run: 313 M4.5+ events fetched via FDSN `updatedafter` cursor, 6 met the PAGER yellow+ threshold (incl. the Venezuela red doublet), gate returned `changed=true`; sitrep hand-written to `dashboard.html` from `facts.json`; after `mark_reported.py`, a second full run returned `changed=false`. Ledger updates are a separate script so a failed sitrep re-surfaces incidents next run instead of losing them. Stdlib only, Python 3.9 compatible.

- **2026-07-08 — Slice 2 built and verified end-to-end (GDACS + correlation).** New `hadr/fetchers/gdacs.py` (EVENTS4APP + lazy Orange+-only detail fetch), `hadr/correlate.py` (GLIDE → USGS-id bridge → fuzzy passes over union-find; correlation links records, never merges identities), GDACS normalization with unified `alert_level`/`revision_signature` fields, per-source triage thresholds (USGS PAGER yellow+, GDACS orange+), drought exemption. State migrated v1→v2 in place (ledger preserved). Live verification: 100 GDACS events ingested; 3 significant (Red typhoon BAVI-26, Orange China flood, Orange France wildfires); 11 GDACS↔USGS earthquake incidents correlated; after publish + mark_reported, full re-run quiet.
  - **Bug found and fixed during verification:** triage originally judged only this-run changes, so a significant incident that fired while no sitrep was published would be silently lost on the next run. Triage now scans every tracked incident against the reporting ledger each run — unpublished incidents re-surface until marked, which is what makes the separate `mark_reported.py` step actually safe.
  - **Live API finding:** GDACS `sourceid` (the USGS event id for NEIC earthquakes) is present as a key but *empty* in EVENTS4APP list payloads — it is only populated in per-event detail. The id bridge therefore rides on the lazy Orange+ detail fetch (FR-2); green earthquakes correlate via the fuzzy pass, verified working on all 11 current pairs.

## Deviations

- **Gate signalling (PRD §5 diagram said "exit quiet / exit changed").** `check_changes.py` always exits 0 on a successful decision and emits `changed=true|false` on stdout and into `$GITHUB_OUTPUT`; exit 2 only when facts.json is missing. Reason: a nonzero exit marks the Actions step failed, which would conflate "changes found" with "pipeline broken" — output-variable branching keeps NFR-3 (failures must be loud, and only failures) intact. PRD FR-11 acceptance is otherwise unchanged.

<!-- Anything built that departs from the PRD or CLAUDE.md is recorded here,
     with the reason. An undocumented deviation is a bug. -->

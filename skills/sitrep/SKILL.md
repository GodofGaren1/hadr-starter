---
name: sitrep
description: Write the morning HADR situation report into dashboard.html from data/facts.json. Run only after scripts/check_changes.py reports changed=true; the deterministic pipeline decides whether to wake up, never this skill.
---

# /sitrep — morning situation report

Model hint: Sonnet-class or better (prose quality matters; no tool-heavy work).

## The model boundary (non-negotiable)

- Read `data/facts.json`. **Every statement you write must derive from a field
  in it.** No memory of previous reports, no outside knowledge of events, no
  fetching feeds, no running the pipeline.
- If `quiet` is `true`, write nothing and stop — the gate should have
  prevented this invocation.
- Do not run `scripts/mark_reported.py`; the workflow does that after you
  finish, so a failed report re-surfaces its incidents tomorrow.

## What to write

Rewrite `dashboard.html` in full (self-contained HTML, no external resources,
styled for both light and dark via `prefers-color-scheme` — keep the existing
file's look). Structure, in order:

1. **Header** — "HADR situation report", generation time rendered in
   Singapore time (SGT = UTC+8) with the UTC original alongside, and a
   per-source health line from `source_notes` (✅ healthy, ⚠️ stale since X).
2. **Staleness banner** — if `source_notes` or `stale_transitions` is
   non-empty, a prominent warning naming the source and its last success:
   absence of news from a stale source is not evidence of quiet.
3. **Lead summary** — 2–3 sentences: how many significant items, the most
   severe first.
4. **Incidents by severity** — one card per item in `significant`, red before
   orange before yellow, then editorial items. For each: title, level badge,
   what happened (from `event` fields only), the `reason` in plain words
   (new incident / escalation from X / downgrade from X / now confirmed by a
   ReliefWeb disaster record), all member source views with links
   (`incident.members`), GLIDE if present, and occurrence time in SGT.
5. **Changes since last report** — from `previously_reported`: every entry
   whose `current_level` differs from `reported_level` gets its own line
   (upgrades loudest); if none differ, one quiet sentence saying all N
   previously reported incidents are unchanged, naming their levels.
6. **Everything else** — counts from `counts`: events tracked per source,
   correlated incidents. One sentence.
7. **Footer** — slice/source coverage note, the facts.json generation
   timestamp, and the caveat that alert levels are PAGER/GDACS impact
   estimates, not observations.

## Tone

Analyst-to-analyst: plain sentences, no drama, numbers where facts.json has
them. Downgrades and retractions are stated as corrections, never silently
dropped. When a field is null, say nothing rather than guessing.

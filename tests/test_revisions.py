"""Slice 4 revision-handling tests: upgrades, downgrades, deletions, ledger.

No network — events are handed straight to reconcile/correlate/triage.
Run: python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hadr import correlate, store, triage

NOW = "2026-07-08T00:00:00+00:00"
LATER = "2026-07-08T12:00:00+00:00"


def usgs_event(key, alert=None, mag=6.0, aliases=None, lat=10.0, lon=-68.0,
               occurred="2026-07-07T22:00:00+00:00", status="reviewed"):
    return {
        "source": "usgs", "stable_key": key, "alias_ids": aliases or [key],
        "hazard": "earthquake", "alert_level": alert,
        "revision_signature": "{}|{}".format(mag, status),
        "occurred_at": occurred, "updated_at": occurred,
        "geo": {"lon": lon, "lat": lat, "depth_km": 10.0},
        "title": "M {} - test event {}".format(mag, key), "place": "Testland",
        "magnitude": mag, "mag_type": "mww", "glide": None, "iso3": None,
        "impact": {"pager_alert": alert}, "review_status": status,
        "url": "https://example.test/" + key,
    }


def gdacs_event(key, alert="green", hazard="earthquake", lat=10.0, lon=-68.0,
                occurred="2026-07-07T22:00:00+00:00"):
    return {
        "source": "gdacs", "stable_key": key, "alias_ids": [key],
        "hazard": hazard, "alert_level": alert,
        "revision_signature": "1|1", "occurred_at": occurred, "updated_at": occurred,
        "geo": {"lon": lon, "lat": lat, "depth_km": None},
        "title": "GDACS test event " + key, "place": "Testland",
        "magnitude": None, "mag_type": None, "glide": None, "iso3": "TST",
        "impact": {"gdacs_alert": alert}, "episode_id": 1,
        "usgs_ref": None, "review_status": "current",
        "url": "https://example.test/" + key,
    }


def facts_for(state, changes=None):
    return triage.build_facts(state, changes or [], [], LATER)


class AliasIdentityTests(unittest.TestCase):
    def test_preferred_id_change_is_not_a_new_event(self):
        state = store.empty_state()
        store.reconcile(state, [usgs_event("ci111", aliases=["ci111", "us222"])], NOW)
        changes = store.reconcile(
            state, [usgs_event("us222", aliases=["us222", "us333"])], LATER)
        self.assertEqual(len(state["events"]), 1)
        self.assertNotIn("NEW", [c["type"] for c in changes])
        self.assertEqual(sorted(state["events"]["ci111"]["alias_ids"]),
                         ["ci111", "us222", "us333"])


class EscalationTests(unittest.TestCase):
    def test_pager_upgrade_produces_escalation_lead(self):
        """The PRD slice 4 demo: yellow reported yesterday, red today."""
        state = store.empty_state()
        store.reconcile(state, [usgs_event("us1", alert="yellow")], NOW)
        correlate.build_incidents(state)
        state["ledger"]["us1"] = {"reported_level": "yellow", "reported_at": NOW}

        changes = store.reconcile(state, [usgs_event("us1", alert="red")], LATER)
        correlate.build_incidents(state)
        facts = facts_for(state, changes)

        self.assertEqual([c["type"] for c in changes], ["UPGRADED"])
        self.assertEqual(len(facts["significant"]), 1)
        item = facts["significant"][0]
        self.assertEqual(item["reason"], "escalation")
        self.assertEqual(item["key"], "us1")
        self.assertFalse(facts["quiet"])

    def test_downgrade_of_reported_incident_is_significant(self):
        state = store.empty_state()
        store.reconcile(state, [usgs_event("us1", alert="orange")], NOW)
        correlate.build_incidents(state)
        state["ledger"]["us1"] = {"reported_level": "orange", "reported_at": NOW}
        changes = store.reconcile(state, [usgs_event("us1", alert="green")], LATER)
        facts = facts_for(state, changes)
        self.assertEqual(facts["significant"][0]["reason"], "downgrade")

    def test_reported_level_unchanged_is_quiet(self):
        state = store.empty_state()
        store.reconcile(state, [usgs_event("us1", alert="red")], NOW)
        correlate.build_incidents(state)
        state["ledger"]["us1"] = {"reported_level": "red", "reported_at": NOW}
        facts = facts_for(state)
        self.assertTrue(facts["quiet"])


class LedgerTests(unittest.TestCase):
    def test_unpublished_incident_resurfaces_every_run(self):
        state = store.empty_state()
        store.reconcile(state, [usgs_event("us1", alert="red")], NOW)
        correlate.build_incidents(state)
        # facts built twice with no intervening changes and no mark_reported
        self.assertEqual(len(facts_for(state)["significant"]), 1)
        self.assertEqual(len(facts_for(state)["significant"]), 1)

    def test_corroborating_source_view_does_not_realert(self):
        state = store.empty_state()
        store.reconcile(state, [usgs_event("us1", alert="red")], NOW)
        state["ledger"]["us1"] = {"reported_level": "red", "reported_at": NOW}
        # GDACS view of the same quake arrives later: same place, same hour
        store.reconcile(state, [gdacs_event("gdacs:EQ:9", alert="red")], LATER)
        correlate.build_incidents(state)
        incident_ids = {r.get("incident") for r in state["events"].values()}
        self.assertEqual(len(incident_ids), 1, "events should share one incident")
        self.assertTrue(facts_for(state)["quiet"])


class RetractionTests(unittest.TestCase):
    def _reported_then_deleted(self):
        state = store.empty_state()
        store.reconcile(state, [usgs_event("us1", alert="red")], NOW)
        correlate.build_incidents(state)
        state["ledger"]["us1"] = {"reported_level": "red", "reported_at": NOW}
        change = store.apply_deletion(state, "us1", LATER)
        return state, [change]

    def test_deleted_reported_event_fires_retraction(self):
        state, changes = self._reported_then_deleted()
        facts = facts_for(state, changes)
        item = facts["significant"][0]
        self.assertEqual(item["reason"], "retraction")
        self.assertEqual(item["key"], "us1")

    def test_retraction_fires_once(self):
        state, changes = self._reported_then_deleted()
        facts_for(state, changes)  # published...
        state["ledger"]["us1"]["retraction_reported"] = True  # ...and marked
        self.assertTrue(facts_for(state)["quiet"])

    def test_unreported_deleted_event_stays_quiet(self):
        state = store.empty_state()
        store.reconcile(state, [usgs_event("us1", alert=None)], NOW)
        correlate.build_incidents(state)
        change = store.apply_deletion(state, "us1", LATER)
        self.assertTrue(facts_for(state, [change])["quiet"])


class TriagePolicyTests(unittest.TestCase):
    def test_magnitude_alone_never_triggers(self):
        state = store.empty_state()
        store.reconcile(state, [usgs_event("us1", alert=None, mag=7.9)], NOW)
        correlate.build_incidents(state)
        self.assertTrue(facts_for(state)["quiet"])

    def test_drought_exempt_from_daily_logic(self):
        state = store.empty_state()
        store.reconcile(
            state, [gdacs_event("gdacs:DR:1", alert="orange", hazard="drought")], NOW)
        correlate.build_incidents(state)
        self.assertTrue(facts_for(state)["quiet"])


if __name__ == "__main__":
    unittest.main()

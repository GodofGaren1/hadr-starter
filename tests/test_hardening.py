"""Slice 5 hardening tests: retries, staleness accounting, snapshots, env
overrides. Offline — network calls are mocked where exercised at all.

Run: python -m unittest discover -s tests
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hadr.fetchers as fetchers
from hadr import snapshots, store

NOW = "2026-07-08T00:00:00+00:00"
LATER = "2026-07-08T12:00:00+00:00"


class RetryTests(unittest.TestCase):
    @mock.patch("hadr.fetchers.time.sleep")
    @mock.patch("hadr.fetchers.urllib.request.urlopen")
    def test_get_json_retries_once_then_succeeds(self, urlopen, sleep):
        good = mock.MagicMock()
        good.__enter__.return_value.read.return_value = b'{"ok": 1}'
        urlopen.side_effect = [OSError("connection reset"), good]
        with mock.patch("hadr.fetchers.json.load", return_value={"ok": 1}):
            self.assertEqual(fetchers.get_json("https://example.test"), {"ok": 1})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    @mock.patch("hadr.fetchers.time.sleep")
    @mock.patch("hadr.fetchers.urllib.request.urlopen")
    def test_get_json_raises_after_final_attempt(self, urlopen, sleep):
        urlopen.side_effect = OSError("unreachable")
        with self.assertRaises(OSError):
            fetchers.get_json("https://example.test")
        self.assertEqual(urlopen.call_count, fetchers.ATTEMPTS)


class StalenessTests(unittest.TestCase):
    def test_only_the_first_failure_is_a_transition(self):
        state = store.empty_state()
        self.assertTrue(store.record_source_status(state, "gdacs", False, "boom", NOW))
        self.assertFalse(store.record_source_status(state, "gdacs", False, "boom", LATER))
        self.assertEqual(state["sources"]["gdacs"]["consecutive_failures"], 2)

    def test_recovery_resets_and_is_not_a_transition(self):
        state = store.empty_state()
        store.record_source_status(state, "gdacs", False, "boom", NOW)
        self.assertFalse(store.record_source_status(state, "gdacs", True, "", LATER))
        self.assertEqual(state["sources"]["gdacs"]["consecutive_failures"], 0)
        self.assertEqual(state["sources"]["gdacs"]["last_success"], LATER)


class SnapshotTests(unittest.TestCase):
    def test_roundtrip_and_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            features = [{"id": "us1", "properties": {"mag": 5.0}}]
            for stamp in ("20260701T000000Z", "20260702T000000Z", "20260703T000000Z"):
                snapshots.save(root, stamp, "usgs", features)
            self.assertEqual(snapshots.load(root / "20260702T000000Z", "usgs"), features)
            self.assertIsNone(snapshots.load(root / "20260702T000000Z", "gdacs"))
            snapshots.prune(root, keep=2)
            remaining = sorted(d.name for d in root.iterdir())
            self.assertEqual(remaining, ["20260702T000000Z", "20260703T000000Z"])


class EnvOverrideTests(unittest.TestCase):
    def test_env_var_wins_and_absence_falls_back(self):
        with mock.patch.dict(os.environ, {"HADR_GDACS_URL": "https://blocked.test"}):
            self.assertEqual(
                fetchers.resolve_url("HADR_GDACS_URL", "https://real.test"),
                "https://blocked.test")
        os.environ.pop("HADR_GDACS_URL", None)
        self.assertEqual(
            fetchers.resolve_url("HADR_GDACS_URL", "https://real.test"),
            "https://real.test")


if __name__ == "__main__":
    unittest.main()

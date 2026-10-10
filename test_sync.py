import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sync_public_site as mirror


def fixture(dates=("2026-10-09",)):
    data = json.dumps({"id": mirror.ARTIFACT, "buildStatus": "complete", "queries": {"reports": {"rows": [{"review_date": d} for d in dates]}}}).encode()
    html = (f'<meta name="data-app-sites-project" content="{mirror.PROJECT}">'
            f'<meta name="data-app-snapshot-sha256" content="{mirror.digest(data)}">'
            '<meta name="data-app-snapshot-storage" content="external-v1">'
            '<script type="application/json" id="data-app-reviewed-snapshot">{}</script>'
            '<script>const chunks="script[data-app-snapshot-chunk]";</script>').encode()
    return {"/": html, "/api/snapshot": data}


class SyncGuardTests(unittest.TestCase):
    def test_offline_page_contains_complete_data_and_unchanged_application(self):
        source = fixture()
        output = mirror.make_portable(source["/"], source["/api/snapshot"])
        self.assertIn(b"2026-10-09", output)
        self.assertNotIn(b'<meta name="data-app-snapshot-storage"', output)
        self.assertTrue(output.endswith(b'<script>const chunks="script[data-app-snapshot-chunk]";</script>'))

    def test_edge_request_ids_do_not_create_false_report_updates(self):
        base = fixture()["/"]
        a = base + b'<script>window.__CF$cv$params={r:"request-a"};var path="/cdn-cgi/challenge-platform/scripts/jsd/main.js";</script>'
        b = base + b'<script>window.__CF$cv$params={r:"request-b"};var path="/cdn-cgi/challenge-platform/scripts/jsd/main.js";</script>'
        self.assertEqual(mirror.normalize_source_html(a), base)
        self.assertEqual(mirror.normalize_source_html(b), base)
        self.assertEqual(mirror.normalize_source_html(base), base)

    def test_same_day_revision_preserves_original_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "docs"
            mirror.sync(destination, fixture().__getitem__)
            previous = {p.name: p.read_bytes() for p in (destination / "history").glob("*.json")}
            source = fixture()
            data = json.loads(source["/api/snapshot"])
            data["generatedAt"] = "a newer same-day revision"
            revised = json.dumps(data).encode()
            source["/"] = source["/"].replace(mirror.digest(source["/api/snapshot"]).encode(), mirror.digest(revised).encode())
            source["/api/snapshot"] = revised
            self.assertTrue(mirror.sync(destination, source.__getitem__))
            self.assertEqual(len(list((destination / "history").glob("*.json"))), 2)
            for name, original in previous.items():
                self.assertEqual((destination / "history" / name).read_bytes(), original)

    def test_inconsistent_pair_is_retried(self):
        source = fixture()
        calls = []
        def fetch(path):
            calls.append(path)
            if len(calls) == 2:
                return fixture(("2026-10-08",))[path]
            return source[path]
        with patch.object(mirror.time, "sleep"):
            result = mirror.read_verified_pair(fetch)
        self.assertEqual(result[1], source["/api/snapshot"])
        self.assertEqual(len(calls), 4)

    def test_network_failure_keeps_previous_files(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "docs"
            mirror.sync(destination, fixture().__getitem__)
            before = (destination / "index.html").read_bytes()
            with patch.object(mirror.time, "sleep"):
                with self.assertRaises(RuntimeError):
                    mirror.sync(destination, lambda path: (_ for _ in ()).throw(OSError("offline")))
            self.assertEqual((destination / "index.html").read_bytes(), before)

    def test_dropped_history_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "docs"
            mirror.sync(destination, fixture(("2026-10-08", "2026-10-09")).__getitem__)
            before = (destination / "index.html").read_bytes()
            with self.assertRaises(ValueError):
                mirror.sync(destination, fixture().__getitem__)
            self.assertEqual((destination / "index.html").read_bytes(), before)

    def test_repeated_sync_is_idempotent_and_new_day_preserves_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "docs"
            self.assertTrue(mirror.sync(destination, fixture().__getitem__))
            self.assertFalse(mirror.sync(destination, fixture().__getitem__))
            self.assertTrue(mirror.sync(destination, fixture(("2026-10-09", "2026-10-12")).__getitem__))
            self.assertEqual(len(list((destination / "history").glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import sync_public_site as mirror
import verify_publication as publish


def prepared(folder):
    data = json.dumps({'id': mirror.ARTIFACT, 'buildStatus': 'complete',
        'generatedAt': '2026-10-10T17:44:29+08:00',
        'queries': {'reports': {'rows': [{'review_date': '2026-10-09', 'value': 5.24}]}}}).encode()
    html = (f'<meta name="data-app-sites-project" content="{mirror.PROJECT}">'
        f'<meta name="data-app-snapshot-sha256" content="{mirror.digest(data)}">'
        '<script type="application/json" id="data-app-reviewed-snapshot">{}</script>'
        '<script>const chunks="script[data-app-snapshot-chunk]";</script>').encode()
    docs = Path(folder) / 'docs'
    mirror.sync(docs, {'/': html, '/api/snapshot': data}.__getitem__)
    return docs


class PublicationTests(unittest.TestCase):
    def test_failed_deploy_is_retried_even_if_repository_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            docs = prepared(folder)
            old = json.loads((docs / 'mirror-manifest.json').read_bytes())
            old['snapshotSha256'] = '0' * 64
            result = publish.plan(docs, lambda path: json.dumps(old).encode())
            self.assertTrue(result['needs_deploy'])

    def test_matching_manifest_but_bad_html_requires_deployment(self):
        with tempfile.TemporaryDirectory() as folder:
            docs = prepared(folder)
            def fetch(path):
                return b'broken HTML' if path == 'index.html' else (docs / path).read_bytes()
            self.assertTrue(publish.plan(docs, fetch)['needs_deploy'])

    def test_matching_manifest_but_missing_archive_requires_deployment(self):
        with tempfile.TemporaryDirectory() as folder:
            docs = prepared(folder)
            def fetch(path):
                if path.startswith('history/'):
                    raise OSError('archive unavailable')
                return (docs / path).read_bytes()
            self.assertTrue(publish.plan(docs, fetch)['needs_deploy'])

    def test_complete_live_copy_skips_deployment_and_verifies_history(self):
        with tempfile.TemporaryDirectory() as folder:
            docs = prepared(folder)
            fetch = lambda path: (docs / path).read_bytes()
            self.assertFalse(publish.plan(docs, fetch)['needs_deploy'])
            self.assertTrue(publish.verify(docs, 1, 0, fetch)['historyVerified'])

    def test_temporary_publication_delay_is_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            docs = prepared(folder)
            calls = []
            def fetch(path):
                calls.append(path)
                if len(calls) == 1:
                    raise OSError('transient CDN failure')
                return (docs / path).read_bytes()
            with patch.object(publish.time, 'sleep'):
                self.assertTrue(publish.verify(docs, 2, 0, fetch)['matches'])

    def test_persistent_failure_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as folder:
            docs = prepared(folder)
            with self.assertRaises(RuntimeError):
                publish.verify(docs, 1, 0, lambda path: b'{}')

    def test_corrupt_local_files_stop_before_deploy(self):
        with tempfile.TemporaryDirectory() as folder:
            docs = prepared(folder)
            (docs / 'snapshot.json').write_text('{}')
            with self.assertRaises(ValueError):
                publish.plan(docs)


if __name__ == '__main__':
    unittest.main()

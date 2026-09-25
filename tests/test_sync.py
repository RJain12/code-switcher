import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_code import load, ROOT


class Sync(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.client = load(os.path.join(ROOT, 'codespace'), tmp.name)
        self.client.private_json_write(self.client.CONFIG, {'sync_uri': 'gs://fixture/machines'})
        self.before = [{'version': 1, 'machine': 'cached'}]
        self.client.private_json_write(self.client.CATALOG_CACHE, self.before)

    def test_failed_listing_preserves_cache(self):
        with patch.object(self.client.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, stdout='')):
            with self.assertRaisesRegex(ValueError, 'preserved'):
                self.client.sync(['status'], quiet=True)
        self.assertEqual(json.loads(self.client.CATALOG_CACHE.read_text()), self.before)

    def test_partial_read_preserves_whole_snapshot(self):
        responses = [subprocess.CompletedProcess([], 0, stdout='gs://fixture/machines/a.json\ngs://fixture/machines/b.json\n'),
                     subprocess.CompletedProcess([], 0, stdout=json.dumps({'version': 1, 'machine': 'new'})),
                     subprocess.CalledProcessError(1, 'cat')]
        with patch.object(self.client.subprocess, 'run', side_effect=responses):
            with self.assertRaisesRegex(ValueError, 'preserved'):
                self.client.sync(['status'], quiet=True)
        self.assertEqual(json.loads(self.client.CATALOG_CACHE.read_text()), self.before)

    def test_complete_snapshot_replaces_cache_privately(self):
        record = {'version': 1, 'machine': 'new'}
        responses = [subprocess.CompletedProcess([], 0, stdout='gs://fixture/machines/a.json\n'),
                     subprocess.CompletedProcess([], 0, stdout=json.dumps(record))]
        with patch.object(self.client.subprocess, 'run', side_effect=responses):
            self.client.sync(['status'], quiet=True)
        self.assertEqual(json.loads(self.client.CATALOG_CACHE.read_text()), [record])
        self.assertEqual(self.client.CATALOG_CACHE.stat().st_mode & 0o777, 0o600)

    def test_sync_failure_does_not_prevent_update(self):
        with patch.object(self.client, 'renew_t3_connection', return_value={'status': 'current'}), patch.object(self.client, 'sync', side_effect=ValueError('offline')), patch.object(self.client, 'update', return_value=0) as update, patch('builtins.print'):
            self.assertEqual(self.client.maintenance(), 1)
            update.assert_called_once()

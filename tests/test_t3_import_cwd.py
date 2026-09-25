import os
import tempfile
import unittest
from unittest.mock import patch
from test_code import load, ROOT

class ImportCwd(unittest.TestCase):
    def test_existing_project_is_reused_and_root_is_guarded(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            client = load(os.path.join(ROOT, 'codespace'), tmp)
            cwd = os.path.realpath(tmp)
            with patch.object(client, 't3_http', return_value={'projects': [{'id': 'existing', 'workspaceRoot': cwd}]}) as http, patch.object(client, 't3_rpc_value', side_effect=[{}, {'importedCount': 1, 'skippedCount': 0}]) as rpc:
                result = client.t3_import_cwd(tmp, 'http://localhost', 'fixture')
                self.assertEqual(result['projectId'], 'existing')
                self.assertEqual(http.call_count, 1)
                self.assertEqual(rpc.call_args.args[-1], {'projectId': 'existing', 'expectedWorkspaceRoot': cwd})

    def test_new_project_created_before_import_without_starting_turn(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            client = load(os.path.join(ROOT, 'codespace'), tmp)
            with patch.object(client, 't3_http', side_effect=[{'projects': []}, {}]) as http, patch.object(client, 't3_rpc_value', side_effect=[{}, {'importedCount': 0, 'skippedCount': 0}]):
                result = client.t3_import_cwd(tmp, 'http://localhost', 'fixture')
                command = http.call_args.args[-1]
                self.assertEqual(command['type'], 'project.create')
                self.assertEqual(command['projectId'], result['projectId'])

    def test_shared_history_is_detected_across_distinct_account_homes(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            client = load(os.path.join(ROOT, 'codespace'), tmp)
            first, second = Path(tmp)/'one', Path(tmp)/'two'
            (first/'sessions').mkdir(parents=True)
            second.mkdir()
            (second/'sessions').symlink_to(first/'sessions')
            settings = {'providerInstances': {name: {'driver': 'codex', 'config': {'homePath': str(home)}} for name, home in [('first', first), ('second', second)]}}
            self.assertEqual(client.shared_t3_history(settings), [['first', 'second']])
            with patch.object(client, 't3_rpc_value', return_value=settings), patch.object(client, 't3_http') as http:
                with self.assertRaisesRegex(ValueError, 'share transcript'):
                    client.t3_import_cwd(tmp, 'http://localhost', 'fixture')
                http.assert_not_called()

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from test_code import load, ROOT


class ConnectionHealth(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = load(os.path.join(ROOT, 'codespace'), self.tmp.name)
        os.environ['CODESPACE_T3_TOKEN'] = 'fixture-token'

    def test_local_check_authenticates_without_contacting_peers_or_cloud(self):
        with patch.object(self.app, 'config', return_value={'hosts': {'mini': 'fixture'}, 'sync_uri': 'gs://fixture/machines'}), patch.object(self.app, 'verify_t3_token') as verify, patch.object(self.app.subprocess, 'run') as run:
            report = self.app.connection_report(local_only=True)
            self.assertEqual(set(report['checks']), {'t3'})
            self.assertEqual(report['checks']['t3']['status'], 'authenticated')
            verify.assert_called_once_with('http://127.0.0.1:3773', 'fixture-token')
            run.assert_not_called()

    def test_reachable_peer_can_have_a_rejected_t3_connection(self):
        remote = {'version': 1, 'machine': 'mini', 'checks': {'t3': {'status': 'rejected'}}}
        result = subprocess.CompletedProcess([], 1, json.dumps(remote), '')
        with patch.object(self.app, 'config', return_value={'hosts': {'mini': 'fixture'}}), patch.object(self.app, 'verify_t3_token'), patch.object(self.app.subprocess, 'run', return_value=result) as run:
            peer = self.app.connection_report()['checks']['peer:mini']
            self.assertEqual(peer['status'], 'reachable')
            self.assertEqual(peer['t3']['status'], 'rejected')
            self.assertIn('BatchMode=yes', run.call_args.args[0])
            self.assertIn('StrictHostKeyChecking=yes', run.call_args.args[0])

    def test_errors_do_not_expose_credentials(self):
        with patch.object(self.app, 'config', return_value={}), patch.object(self.app, 'verify_t3_token', side_effect=ValueError('private token and URL')):
            report = self.app.connection_report(local_only=True)
            self.assertEqual(report['checks']['t3']['status'], 'unavailable')
            self.assertNotIn('private token', json.dumps(report))

    def test_expired_or_revoked_token_is_reported_as_rejected(self):
        error = urllib.error.HTTPError('http://localhost', 401, 'unauthorized', {}, None)
        with patch.object(self.app, 'config', return_value={}), patch.object(self.app, 'verify_t3_token', side_effect=error):
            self.assertEqual(self.app.connection_report(local_only=True)['checks']['t3']['status'], 'rejected')

    def test_invalid_host_and_plaintext_remote_token_target_are_rejected(self):
        settings = {'hosts': {'mini': '-oProxyCommand=bad'}, 't3_url': 'http://remote.test'}
        with patch.object(self.app, 'config', return_value=settings), patch.object(self.app, 'verify_t3_token') as verify, patch.object(self.app.subprocess, 'run') as run:
            report = self.app.connection_report()
            self.assertEqual(report['checks']['t3']['status'], 'invalid-config')
            self.assertEqual(report['checks']['peer:mini']['status'], 'invalid-config')
            run.assert_not_called()
            verify.assert_not_called()

    def test_unreachable_lan_name_falls_back_to_next_address(self):
        settings = {'hosts': {'mini': ['me@mini.local', 'me@mini.tail.ts.net']}}
        attempts = []

        def connect(address, timeout):
            attempts.append(address[0])
            if address[0] == 'mini.local':
                raise OSError('nodename nor servname provided')
            return unittest.mock.MagicMock()

        with patch.object(self.app.socket, 'create_connection', side_effect=connect):
            self.assertEqual(self.app.reachable_host('mini', settings), 'me@mini.tail.ts.net')
        self.assertEqual(attempts, ['mini.local', 'mini.tail.ts.net'])

    def test_candidates_merge_config_and_catalog_without_duplicates_or_unsafe_hosts(self):
        Path(self.app.CATALOG_CACHE).parent.mkdir(parents=True, exist_ok=True)
        Path(self.app.CATALOG_CACHE).write_text(json.dumps([
            {'alias': 'mini', 'ssh_host': 'me@a', 'ssh_hosts': ['me@a', 'me@b', '-oProxyCommand=x']},
            {'alias': 'other', 'ssh_host': 'me@z'}]))
        self.assertEqual(self.app.host_candidates('mini', {'hosts': {'mini': 'me@a'}}), ['me@a', 'me@b'])
        self.assertEqual(self.app.host_candidates('other', {}), ['me@z'])
        self.assertEqual(self.app.host_candidates('plain.example', {}), ['plain.example'])

    def test_peer_report_names_the_address_used(self):
        remote = {'version': 1, 'machine': 'mini', 'checks': {'t3': {'status': 'authenticated'}}}
        with patch.object(self.app, 'config', return_value={'hosts': {'mini': ['me@down', 'me@up']}}), \
                patch.object(self.app, 'verify_t3_token'), \
                patch.object(self.app, 'reachable_host', return_value='me@up'), \
                patch.object(self.app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(remote), '')) as run:
            peer = self.app.connection_report()['checks']['peer:mini']
        self.assertEqual(peer['via'], 'me@up')
        self.assertEqual(run.call_args.args[0][-2], 'me@up')

    def test_bridge_tunnel_tries_each_address_in_order(self):
        log = Path(self.tmp.name) / 'ssh.log'
        fake = Path(self.tmp.name) / 'fake ssh'
        fake.write_text(f'#!/bin/sh\nfor last; do :; done\necho "$last" >> "{log}"\nexit 255\n')
        fake.chmod(0o755)
        command = self.app.bridge_tunnel_command(['me@first', "me@it's-second"], 42322, ssh=str(fake))
        self.assertNotEqual(subprocess.run(command, timeout=10).returncode, 0)
        self.assertEqual(log.read_text().splitlines(), ['me@first', "me@it's-second"])
        self.assertIn('ExitOnForwardFailure=yes', command[2])

    def test_cloud_catalog_probe_is_read_only(self):
        with patch.object(self.app, 'config', return_value={'sync_uri': 'gs://fixture/machines'}), patch.object(self.app, 'verify_t3_token'), patch.object(self.app, 'require', return_value='gcloud'), patch.object(self.app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            self.assertEqual(self.app.connection_report()['checks']['cloudCatalog']['status'], 'accessible')
            self.assertEqual(run.call_args.args[0], ['gcloud', 'storage', 'ls', 'gs://fixture/machines/'])


if __name__ == '__main__':
    unittest.main()

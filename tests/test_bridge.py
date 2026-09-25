import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_code import load, ROOT


class Bridge(unittest.TestCase):
    def test_peer_setup_is_idempotent_and_preserves_existing_ssh_configuration(self):
        with tempfile.TemporaryDirectory(prefix="codespace-peer-test-") as tmp, patch.dict(os.environ):
            client = load(os.path.join(ROOT, "codespace"), tmp)
            ssh = Path(tmp) / '.ssh'
            ssh.mkdir()
            original = 'Host existing\n  HostName example.invalid\n'
            (ssh / 'config').write_text(original)
            request = {'action': 'configure', 'alias': 'test-mac', 'hostKey': 'ssh-ed25519 fixture-public-key', 'port': 42322, 'user': 'testuser'}
            for _ in range(2):
                result = subprocess.run([sys.executable, '-c', client.BRIDGE_PEER_SCRIPT], input=json.dumps(request), text=True, capture_output=True, check=True, env=dict(os.environ, HOME=tmp))
                self.assertTrue(json.loads(result.stdout)['publicKey'].startswith('ssh-ed25519 '))
            config = (ssh / 'config').read_text()
            self.assertIn(original, config)
            self.assertEqual(config.count('Include ~/.ssh/codespace.conf'), 1)
            managed = (ssh / 'codespace.conf').read_text()
            self.assertEqual(managed.count('Host codespace-test-mac'), 1)
            self.assertIn('StrictHostKeyChecking yes', managed)
            self.assertIn('HostName 127.0.0.1', managed)
            key = Path(tmp) / '.config/codespace/bridge/test-mac/client_ed25519'
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            settings = json.loads((Path(tmp) / '.config/codespace/config.json').read_text())
            self.assertEqual(settings['hosts']['test-mac'], 'codespace-test-mac')


if __name__ == '__main__':
    unittest.main()

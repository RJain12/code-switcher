import os
import tempfile
import unittest
from unittest.mock import patch
from test_code import load


class CodeSpace(unittest.TestCase):
    def test_forwarding_preserves_arguments_exit_code_and_skips_account_loading(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            client = load(home=tmp)
            for command, prefix in [('space', []), ('dispatch', ['t3', 'start'])]:
                args = ['--prompt', 'literal $(touch /tmp/not-executed)\nsecond line', '--cwd', '/tmp/path with spaces']
                with self.subTest(command=command), patch.object(client.sys, 'argv', ['code', command, *args]), patch.object(client.subprocess, 'call', return_value=7) as call, patch.object(client, 'load_db') as db:
                    with self.assertRaises(SystemExit) as raised:
                        client.main()
                    self.assertEqual(raised.exception.code, 7)
                    self.assertEqual(call.call_args.args[0][2:], prefix + args)
                    db.assert_not_called()

    def test_missing_companion_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            client = load(home=tmp)
            with patch.object(client.sys, 'argv', ['code', 'space']), patch.object(client.os.path, 'isfile', return_value=False):
                with self.assertRaisesRegex(SystemExit, 'reinstall the paired'):
                    client.main()

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_code import load

class Adopt(unittest.TestCase):
    def test_adopts_in_place_deduplicates_and_removes_only_registration(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            code = load(home=tmp)
            home = Path(code.DATA) / 'existing'
            home.mkdir(parents=True)
            credential = home / 'auth.json'
            credential.write_text('original opaque content')
            db = {'accounts': []}
            with patch('builtins.print'):
                code.adopt_account(db, ['codex', 'existing', '--home', str(home)])
                code.adopt_account(db, ['codex', 'another-name', '--home', str(home)])
            self.assertEqual(len(db['accounts']), 1)
            self.assertTrue(db['accounts'][0]['external_home'])
            self.assertEqual(db['accounts'][0]['home'], str(home.resolve()))
            code.remove_account(db, db['accounts'][0])
            self.assertEqual(db['accounts'], [])
            self.assertEqual(credential.read_text(), 'original opaque content')

    def test_adopted_claude_home_keeps_its_own_mcp_settings(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            code = load(home=tmp)
            home = Path(tmp) / 'existing'
            home.mkdir()
            (Path(tmp)/'.claude.json').write_text('{"mcpServers":{"shared":{}}}')
            settings = home / '.claude.json'
            settings.write_text('{"mcpServers":{"own":{}}}')
            db = {'accounts': []}
            with patch('builtins.print'):
                code.adopt_account(db, ['claude', 'existing', '--home', str(home)])
            code.sync_claude_mcp(db['accounts'][0])
            self.assertEqual(settings.read_text(), '{"mcpServers":{"own":{}}}')

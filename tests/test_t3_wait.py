import os
import tempfile
import unittest
from unittest.mock import patch
from test_code import load, ROOT


class Wait(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.client = load(os.path.join(ROOT, 'codespace'), tmp.name)

    def test_terminal_outcomes(self):
        for state, expected in [('completed', 0), ('error', 1), ('interrupted', 1)]:
            with self.subTest(state=state), patch.object(self.client, 't3_http', return_value={'thread': {'latestTurn': {'state': state}}}), patch('builtins.print'):
                self.assertEqual(self.client.t3_wait(['test'], 'http://localhost', 'fixture'), expected)

    def test_running_turn_is_polled_until_complete(self):
        snapshots = [{'thread': {'latestTurn': {'state': state}}} for state in ['running', 'completed']]
        with patch.object(self.client, 't3_http', side_effect=snapshots) as http, patch.object(self.client.time, 'sleep'), patch('builtins.print'):
            self.assertEqual(self.client.t3_wait(['test'], 'http://localhost', 'fixture'), 0)
            self.assertEqual(http.call_count, 2)
            self.assertTrue(all(len(call.args) == 3 for call in http.call_args_list))

    def test_timeout_does_not_stop_or_restart_task(self):
        with patch.object(self.client, 't3_http', return_value={'thread': {'latestTurn': {'state': 'running'}}}) as http, patch.object(self.client.time, 'monotonic', side_effect=[0, 5]), patch('builtins.print'):
            self.assertEqual(self.client.t3_wait(['test', '--timeout', '1'], 'http://localhost', 'fixture'), 124)
            http.assert_called_once_with('http://localhost', 'fixture', '/api/orchestration/threads/test')

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_code import load


class AutoImport(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = load(home=self.tmp.name)
        self.account = {'id': 'codex-work', 'provider': 'codex', 'home': self.tmp.name}
        self.db = {'accounts': [self.account]}
        self.path = Path(self.tmp.name) / 'session.jsonl'
        self.path.write_text('native history')
        self.session = {'account': self.account['id'], 'provider': 'codex', 'home': self.tmp.name,
                        'session_id': 'session', 'cwd': self.tmp.name, 'path': str(self.path)}
        self.app.record_completed_session(self.account, self.session)

    def result(self, count=1):
        return subprocess.CompletedProcess([], 0, json.dumps({'importedCount': count, 'projectId': 'project'}), '')

    def test_success_is_durable_and_new_completion_is_imported_again(self):
        with patch.object(self.app.subprocess, 'run', return_value=self.result()) as run:
            first = self.app.sync_completed_threads(self.db)
            self.assertEqual(first['sessions'][0]['status'], 'imported')
            self.app.sync_completed_threads(self.db)
            self.assertEqual(run.call_count, 1)
            self.path.write_text('native history with another turn')
            self.app.record_completed_session(self.account, self.session)
            self.app.sync_completed_threads(self.db)
            self.assertEqual(run.call_count, 2)
            payload = json.loads(run.call_args.kwargs['input'])
            self.assertEqual(payload['sessionId'], 'session')
            self.assertNotIn('native history', run.call_args.kwargs['input'])

    def test_offline_retry_retains_same_session_and_redacts_provider_output(self):
        failed = subprocess.CompletedProcess([], 1, '', 'secret token must not be stored')
        with patch.object(self.app.subprocess, 'run', side_effect=[failed, self.result()]) as run:
            state = self.app.sync_completed_threads(self.db)['sessions'][0]
            self.assertEqual(state['status'], 'pending')
            self.assertNotIn('secret token', json.dumps(state))
            self.app.sync_completed_threads(self.db)
            self.assertEqual(run.call_count, 1)
            with patch.object(self.app.time, 'time', return_value=state['retryAfter'] + 1):
                self.assertEqual(self.app.sync_completed_threads(self.db)['sessions'][0]['status'], 'imported')
            self.assertEqual(run.call_args_list[0].kwargs['input'], run.call_args_list[1].kwargs['input'])

    def test_active_account_and_changed_transcript_are_not_imported(self):
        with patch.object(self.app.subprocess, 'run') as run:
            with self.app.account_session_lock(self.account):
                state = self.app.sync_completed_threads(self.db)['sessions'][0]
                self.assertEqual(state['status'], 'pending')
            self.path.write_text('changed outside supervision')
            with patch.object(self.app.time, 'time', return_value=state['retryAfter'] + 1):
                state = self.app.sync_completed_threads(self.db)['sessions'][0]
                self.assertIn('session changed', state['error'])
            run.assert_not_called()

    def test_status_and_disabled_automatic_mode_do_not_contact_t3(self):
        with patch.object(self.app.subprocess, 'run') as run:
            self.assertEqual(self.app.sync_completed_threads(self.db, status_only=True)['sessions'][0]['status'], 'pending')
            self.assertEqual(self.app.sync_completed_threads(self.db, automatic=True)['sessions'], [])
            run.assert_not_called()

    def test_unconfirmed_import_stays_pending(self):
        with patch.object(self.app.subprocess, 'run', return_value=self.result(0)):
            self.assertEqual(self.app.sync_completed_threads(self.db)['sessions'][0]['status'], 'pending')

    def test_schedule_happens_after_supervisor_releases_account_lease(self):
        result = (0, None, self.session)
        def schedule():
            with self.app.account_session_lock(self.account, importing=True):
                pass
        with patch.object(self.app, 'supervise_locked', return_value=result), patch.object(self.app, 'schedule_t3_sync', side_effect=schedule) as enqueue:
            self.assertEqual(self.app.supervise(self.db, self.account, []), result)
            enqueue.assert_called_once()

    def test_automatic_configuration_and_detached_launch(self):
        config = Path(self.tmp.name) / '.config/codespace/config.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'t3_auto_import': True}))
        with patch.object(self.app.subprocess, 'Popen') as launch:
            self.app.schedule_t3_sync()
            self.assertEqual(launch.call_args.args[0][-2:], ['thread-sync', '--auto'])
            self.assertTrue(launch.call_args.kwargs['start_new_session'])
            config.write_text(json.dumps({'t3_auto_import': False}))
            self.app.schedule_t3_sync()
            self.assertEqual(launch.call_count, 1)

    def test_batch_limit_does_not_starve_later_sessions(self):
        self.app.record_completed_session(self.account, dict(self.session, session_id='second'))
        with patch.object(self.app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')) as run:
            first = self.app.sync_completed_threads(self.db, limit=1)
            next_retry = max(row.get('retryAfter', 0) for row in first['sessions'])
            with patch.object(self.app.time, 'time', return_value=next_retry + 1):
                self.app.sync_completed_threads(self.db, limit=1)
            ids = [json.loads(call.kwargs['input'])['sessionId'] for call in run.call_args_list]
            self.assertEqual(len(set(ids)), 2)


if __name__ == '__main__':
    unittest.main()

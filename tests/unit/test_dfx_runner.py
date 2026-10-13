"""Fault injection for host DFX: no ADB, network, credentials or real account."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/device'))
spec = importlib.util.spec_from_file_location('daily_runner', ROOT / 'scripts/device/run-daily.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def log_for(status='done', reason='completed', summary='dungeon_done=true daily_done=false placeholders=shimen,zhuagui,rewards'):
    return ('[daily][fake][account] current\n'
            '[task_result] shimen status=not_implemented reason=placeholder\n'
            '[task_result] zhuagui status=not_implemented reason=placeholder\n'
            f'[task_result] dungeon status={status} reason={reason}\n'
            '[task_result] rewards status=not_implemented reason=placeholder\n'
            f'[summary] {summary}\n[finished] script_exited_normally\n')


class RuntimeResultTest(unittest.TestCase):
    def test_host_transport_rejects_ui_commands_before_adb_runs(self):
        from dfx_device import Device
        device=Device('offline')
        with patch('dfx_device.command') as command:
            for args in [('shell','input','tap','10','20'),('shell','input swipe 1 2 3 4'),('shell','am','force-stop','app'),('shell','monkey','-p','app','1')]:
                with self.assertRaises(RuntimeError):device.adb_call(*args)
            command.assert_not_called()
            device.adb_call('shell','sha256sum','/storage/emulated/0/TouchSprite/lua/main.lua')
            command.assert_called_once()

    def test_single_role_regression_cannot_claim_whole_roster_complete(self):
        text='[account] current\n[task_result] zhuagui status=done reason=done\n[task_result] dungeon status=done reason=done\n[summary] scope=selected_roles roles_expected=1 roles_completed=1 all_roles_done=false selected_done=true daily_done=false\n[finished] script_exited_normally'
        result=runner.runtime_result(text,'run','daily','dungeon',[{'alias':'current'}],['zhuagui','dungeon'])
        self.assertTrue(result['expectation_met'])
        self.assertTrue(result['selected_complete'])
        self.assertFalse(result['daily_complete'])
        self.assertFalse(runner.runtime_result(text,'run','daily','dungeon',[{'alias':'current'},{'alias':'other'}],['zhuagui','dungeon'])['expectation_met'])

    def test_selected_completion_requires_both_roles_and_every_task(self):
        text=''
        for alias in ('first','second'):
            text+=f'[account] {alias}\n[task_result] zhuagui status=done reason=done\n[task_result] dungeon status=done reason=done\n'
        text+='[summary] scope=roles roles_expected=2 roles_completed=2 all_roles_done=true selected_done=true daily_done=false\n[finished] script_exited_normally'
        accounts=[{'alias':'first'},{'alias':'second'}]
        result=runner.runtime_result(text,'run','daily','dungeon',accounts,['zhuagui','dungeon'])
        self.assertTrue(result['expectation_met'])
        self.assertTrue(result['selected_complete'])
        self.assertFalse(result['daily_complete'])
        partial=text.replace('[task_result] zhuagui status=done reason=done\n','',1)
        self.assertFalse(runner.runtime_result(partial,'run','daily','dungeon',accounts,['zhuagui','dungeon'])['expectation_met'])
        extra=text.replace('[account] second','[account] third')
        self.assertFalse(runner.runtime_result(extra,'run','daily','dungeon',accounts,['zhuagui','dungeon'])['expectation_met'])

    def test_daily_placeholders_remain_incomplete(self):
        result = runner.runtime_result(log_for(), 'run', 'daily')
        self.assertTrue(result['expectation_met'])
        self.assertEqual(result['business_status'], 'incomplete')
        self.assertFalse(result['daily_complete'])
        self.assertEqual(result['tasks'][0]['account'], 'current')

    def test_daily_pause_is_not_success(self):
        result = runner.runtime_result(log_for('paused', 'stable_unknown_state_no_actions', 'daily_done=false reason=dungeon_paused'), 'run', 'daily')
        self.assertFalse(result['expectation_met'])
        self.assertEqual(result['business_status'], 'paused')

    def test_only_expected_development_pause_is_accepted(self):
        for reason, expected in [('battle_completed', True), ('stable_unknown_state_no_actions', False)]:
            with self.subTest(reason=reason):
                self.assertEqual(runner.runtime_result(log_for('paused', reason), 'run', 'advance')['expectation_met'], expected)

    def test_shimen_advance_accepts_only_normal_completion_pauses(self):
        cases = [
            ('paused', 'one_task_completed', 'script_exited_normally', True),
            ('paused', 'one_minigame_completed', 'script_exited_normally', True),
            ('paused', 'shimen_completion_count_mismatch', 'script_exited_normally', False),
            ('paused', 'find_icon_not_found', 'script_exited_normally', False),
            ('paused', 'battle_completed', 'script_exited_normally', False),
            ('blocked', 'one_task_completed', 'script_exited_normally', False),
            ('failed', 'one_task_completed', 'script_exited_normally', False),
            ('paused', 'one_task_completed', 'script_failed', False),
            ('paused', 'one_task_completed', None, False),
        ]
        for status, reason, finished, expected in cases:
            with self.subTest(status=status, reason=reason, finished=finished):
                prefix = '[daily][20261013_120000]'
                text = (f'{prefix}[account] current\n'
                        f'{prefix}[task_result] shimen status={status} reason={reason}\n'
                        f'{prefix}[summary] daily_done=false reason=shimen_{status}\n')
                if finished:
                    text += f'{prefix}[finished] {finished}\n'
                result = runner.runtime_result(text, 'run', 'advance', 'shimen')
                self.assertEqual(result['expectation_met'], expected)
                self.assertFalse(result['daily_complete'])
                self.assertEqual(result['tasks'][0]['account'], 'current')

    def test_legacy_summary_only_navigation_failure_is_rejected(self):
        result = runner.runtime_result(log_for(summary='daily_done=false reason=return_home_not_verified'), 'run', 'daily')
        self.assertFalse(result['expectation_met'])
        self.assertEqual(result['termination_reason'], 'return_home_not_verified')

    def test_normal_exit_without_business_evidence_is_rejected(self):
        self.assertFalse(runner.runtime_result('[finished] script_exited_normally', 'run', 'daily')['expectation_met'])

    def test_isolated_zhuagui_entry_checks_selected_task(self):
        text = '[task_result] zhuagui status=running reason=entered_ready_cost_three_no_task_accepted\n[summary] scope=zhuagui daily_done=false\n[finished] script_exited_normally'
        self.assertTrue(runner.runtime_result(text, 'run', 'enter', 'zhuagui')['expectation_met'])
        self.assertFalse(runner.runtime_result(text, 'run', 'enter', 'dungeon')['expectation_met'])

    def test_zhuagui_observation_is_read_only_result(self):
        text = '[zhuagui_observe] state=ready_cost_three no_actions=true\n[finished] script_exited_normally'
        result = runner.runtime_result(text, 'observe', 'observe', 'zhuagui')
        self.assertTrue(result['expectation_met'])
        self.assertEqual(result['business_status'], 'observed')


class RunnerFaultTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        dist = self.root / 'dist'
        dist.mkdir()
        self.bundle = dist / 'main.lua'
        self.bundle.write_text('return true', encoding='utf-8')
        (dist / 'manifest.json').write_text('{}', encoding='utf-8')
        self.archive = self.root / 'debug-runs/20261009_230000'
        self.args = SimpleNamespace(device='fake', mode='run', step='complete', dungeon='wuji')
        self.statuses = ['f00', 'f00']
        self.start_error = None
        self.collect_error = None
        self.cleanup_error = None
        self.text = log_for()
        self.calls = []
        test = self

        class FakeDevice:
            adb = 'fake-adb'
            auth = 'fake-secret-not-for-archive'

            def __init__(self, device):
                self.files = {}

            def authorize(self):
                pass

            def status(self):
                item = test.statuses.pop(0) if len(test.statuses) > 1 else test.statuses[0]
                if isinstance(item, Exception):
                    raise item
                return item

            def adb_call(self, *args):
                if args[0] == 'push':
                    self.files[args[2]] = Path(args[1]).read_bytes()
                elif args[:2] == ('shell', 'sha256sum'):
                    return hashlib.sha256(self.files[args[2]]).hexdigest() + ' fake'
                return ''

            def close(self):
                if test.cleanup_error:
                    raise test.cleanup_error

        self.patches = [patch.object(runner, 'ROOT', self.root), patch.object(runner, 'build', return_value=self.bundle),
                        patch.object(runner, 'Device', FakeDevice), patch.object(runner, 'command', side_effect=self.command),
                        patch.object(runner.time, 'sleep'), patch.object(runner.time, 'monotonic', side_effect=[0, 2])]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def command(self, args, **kwargs):
        self.calls.append(args)
        if any('ts-cli.ps1' in str(arg) for arg in args):
            if self.start_error:
                raise self.start_error
            return 'accepted'
        if self.collect_error:
            raise self.collect_error
        folder = self.archive / 'log'
        folder.mkdir(exist_ok=True)
        (folder / 'daily_20261009_230000.log').write_text(self.text, encoding='utf-8')
        return 'collected'

    def invoke(self, expected_error=None, expected_launches=1):
        with contextlib.redirect_stdout(io.StringIO()):
            if expected_error:
                with self.assertRaises(expected_error) as caught:
                    runner.run_once(self.args, [{'alias': 'current'}], 1, '20261009_230000', self.archive)
                self.caught = caught.exception
            else:
                runner.run_once(self.args, [{'alias': 'current'}], 1, '20261009_230000', self.archive)
        raw = (self.archive / 'result.json').read_text(encoding='utf-8')
        self.assertNotIn('fake-secret-not-for-archive', raw)
        self.assertEqual(sum('ts-cli.ps1' in str(call) for call in self.calls), expected_launches)
        return json.loads(raw)

    def test_normal_partial_scope_and_config_are_archived(self):
        result = self.invoke()
        self.assertEqual(result['host_status'], 'completed')
        self.assertEqual(result['collection_status'], 'complete')
        self.assertEqual(result['script_status'], 'succeeded')
        self.assertFalse(result['daily_complete'])
        self.assertTrue((self.archive / 'run-config.lua').exists())

    def test_launch_response_lost_still_collects_and_never_relaunches(self):
        self.start_error = subprocess.TimeoutExpired(['fake-command'], 45)
        result = self.invoke(subprocess.TimeoutExpired)
        self.assertEqual(result['host_status'], 'launch_unknown')
        self.assertEqual(result['launch_status'], 'unknown')
        self.assertEqual(result['collection_status'], 'complete')
        self.assertEqual(result['script_status'], 'succeeded')

    def test_timeout_records_potentially_running_device(self):
        self.statuses = ['f00', 'f01', 'f01']
        result = self.invoke(runner.WaitExpired)
        self.assertEqual(result['host_status'], 'timed_out')
        self.assertTrue(result['may_still_be_running'])
        self.assertEqual(result['last_device_status'], 'f01')
        self.assertEqual(result['collection_status'], 'complete')

    def test_secondary_collection_timeout_preserves_first_failure(self):
        self.start_error = RuntimeError('first fault')
        self.collect_error = subprocess.TimeoutExpired(['fake-collector'], 45)
        result = self.invoke(RuntimeError)
        self.assertEqual(str(self.caught), 'first fault')
        self.assertEqual(result['collection_error_type'], 'TimeoutExpired')
        self.assertEqual(result['host_status'], 'launch_unknown')

    def test_transport_failure_does_not_become_business_success(self):
        self.statuses = ['f00', RuntimeError('offline'), RuntimeError('offline')]
        result = self.invoke(RuntimeError)
        self.assertEqual(result['host_status'], 'transport_failed')
        self.assertTrue(result['may_still_be_running'])
        self.assertEqual(result['script_status'], 'succeeded')

    def test_business_pause_is_archived_and_rejected(self):
        self.text = log_for('paused', 'stable_unknown_state_no_actions', 'daily_done=false reason=dungeon_paused')
        result = self.invoke(RuntimeError)
        self.assertEqual(result['host_status'], 'business_unverified')
        self.assertEqual(result['business_status'], 'paused')

    def test_cleanup_failure_does_not_replace_original_fault(self):
        self.start_error = RuntimeError('first fault')
        self.cleanup_error = RuntimeError('cleanup fault')
        result = self.invoke(RuntimeError)
        self.assertEqual(str(self.caught), 'first fault')
        self.assertEqual(result['cleanup_error_type'], 'RuntimeError')

    def test_build_failure_is_archived_without_attempting_launch(self):
        with patch.object(runner, 'build', side_effect=RuntimeError('build fault')):
            result = self.invoke(RuntimeError, expected_launches=0)
        self.assertEqual(result['phase'], 'build')
        self.assertEqual(result['launch_status'], 'not_attempted')
        self.assertEqual(result['collection_status'], 'not_attempted')

    def test_busy_preflight_never_launches_or_collects_other_run(self):
        self.statuses = ['f01']
        result = self.invoke(RuntimeError, expected_launches=0)
        self.assertEqual(result['launch_status'], 'not_attempted')
        self.assertEqual(result['collection_status'], 'not_attempted')
        self.assertTrue(result['may_still_be_running'])
        self.assertEqual(self.calls, [])

    def test_missing_device_log_is_unknown_not_success(self):
        with patch.object(runner, 'command', return_value='accepted but no evidence'):
            result = self.invoke(RuntimeError, expected_launches=0)
        self.assertEqual(result['host_status'], 'business_unverified')
        self.assertEqual(result['script_status'], 'unknown')


if __name__ == '__main__':
    unittest.main()

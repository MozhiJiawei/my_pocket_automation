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
    def test_ledger_retry_cli_options_are_removed(self):
        for option in ('--find-retry-attempt','--puzzle-retry-attempt'):
            with self.subTest(option=option),patch.object(sys,'argv',['run-daily.py','--device','fake',option,'14']),patch.object(runner,'run_once') as run,contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):runner.main()
                run.assert_not_called()

    def test_prior_ledger_date_is_not_a_runtime_option(self):
        with patch.object(sys,'argv',['run-daily.py','--device','fake','--shimen-resume-date','20261010']),patch.object(runner,'run_once') as run,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):runner.main()
            run.assert_not_called()

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


    def test_rewards_debug_accepts_only_step_specific_pauses(self):
        allowed={'enter':{'rewards_inventory_observed'},'browse':{'rewards_inventory_observed'},
                 'advance':{'opened_one_gourd','discarded_one_special'},'complete':set()}
        for step,reasons in allowed.items():
            for reason in ('rewards_inventory_observed','opened_one_gourd','discarded_one_special',
                           'battle_completed','carousel_observation_only','energy_budget_exhausted'):
                for status in ('paused','blocked','failed'):
                    with self.subTest(step=step,reason=reason,status=status):
                        text=f'[account] current\n[task_result] rewards status={status} reason={reason}\n[summary] scope=rewards daily_done=false\n[finished] script_exited_normally'
                        result=runner.runtime_result(text,'run',step,'rewards',[{'alias':'current'}])
                        self.assertEqual(result['expectation_met'],status=='paused' and reason in reasons)
                        self.assertFalse(result['daily_complete'])

    def test_rewards_complete_requires_one_done_result_for_selected_role(self):
        text='[account] current\n[task_result] rewards status=done reason=all_gourds_opened\n[summary] scope=rewards daily_done=false\n[finished] script_exited_normally'
        self.assertTrue(runner.runtime_result(text,'run','complete','rewards',[{'alias':'current'}])['expectation_met'])
        for changed in (text.replace('current','other'),text.replace('rewards status','dungeon status'),
                        text.replace('status=done','status=running'),text.replace('script_exited_normally','script_failed'),
                        text.replace('[summary]','[task_result] rewards status=done reason=duplicate\n[summary]')):
            with self.subTest(text=changed):
                self.assertFalse(runner.runtime_result(changed,'run','complete','rewards',[{'alias':'current'}])['expectation_met'])

    def test_rewards_debug_pause_requires_task_evidence_and_normal_exit(self):
        text='[account] current\n[task_result] rewards status=paused reason=rewards_inventory_observed\n[summary] scope=rewards daily_done=false\n[finished] script_exited_normally'
        for changed in (text.replace('rewards status','dungeon status'),text.replace('current','other'),
                        text.replace('[finished] script_exited_normally',''),
                        text.replace('script_exited_normally','script_failed')):
            with self.subTest(text=changed):
                self.assertFalse(runner.runtime_result(changed,'run','enter','rewards',[{'alias':'current'}])['expectation_met'])
        summary_only='[summary] reason=rewards_inventory_observed\n[finished] script_exited_normally'
        self.assertFalse(runner.runtime_result(summary_only,'run','browse','rewards')['expectation_met'])


class RewardsRunnerOptionsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.accounts=Path(self.temp.name)/'accounts.json'
        self.accounts.write_text(json.dumps([{'alias':'first'},{'alias':'second'}]),encoding='utf-8')
        self.base=['run-daily.py','--device','fake','--accounts',str(self.accounts)]

    def parse(self,options):
        with patch.object(sys,'argv',self.base+options),patch.object(runner,'run_once') as run:
            runner.main()
        run.assert_called_once()
        return run.call_args.args

    def test_default_daily_tasks_include_rewards(self):
        args,accounts,*_=self.parse(['--mode','run','--step','daily'])
        self.assertEqual(args.tasks,['shimen','zhuagui','dungeon','rewards'])
        self.assertFalse(args.rewards_debug_after_shimen)
        self.assertEqual(args.rewards_inspect_category,'task')
        self.assertEqual([account['alias'] for account in accounts],['first','second'])

    def test_daily_tasks_follow_fixed_order_including_subsets(self):
        for tasks,expected in [('rewards,dungeon,zhuagui,shimen',['shimen','zhuagui','dungeon','rewards']),
                               ('rewards,shimen',['shimen','rewards']),('dungeon,zhuagui',['zhuagui','dungeon'])]:
            with self.subTest(tasks=tasks):
                args,*_=self.parse(['--mode','run','--step','daily','--tasks',tasks])
                self.assertEqual(args.tasks,expected)

    def test_explicit_after_shimen_debug_is_bounded_to_one_role(self):
        for step in ('enter','complete','advance','browse'):
            with self.subTest(step=step):
                args,accounts,*_=self.parse(['--task','rewards','--mode','run','--step',step,'--account','second',
                                             '--rewards-debug-after-shimen'])
                self.assertTrue(args.rewards_debug_after_shimen)
                self.assertEqual([account['alias'] for account in accounts],['second'])

    def test_rewards_debug_rejects_other_scopes_before_launch(self):
        base=['--task','rewards','--mode','run','--step','enter','--account','first','--rewards-debug-after-shimen']
        invalid=(['--task','dungeon'],['--task','shimen'],['--mode','observe'],['--step','daily'],
                 ['--step','start'],['--step','finish'],['--step','switch'],['--step','back'],['--step','observe'],
                 ['--select-accounts','first','second'])
        for change in invalid:
            with self.subTest(change=change),patch.object(sys,'argv',self.base+base+change),patch.object(runner,'run_once') as run:
                with self.assertRaises(ValueError):runner.main()
                run.assert_not_called()
        for options in (['--task','rewards','--mode','run','--step','enter'],
                        ['--mode','run','--step','enter','--account','first','--rewards-debug-after-shimen']):
            with self.subTest(options=options),patch.object(sys,'argv',self.base+options),patch.object(runner,'run_once') as run:
                with self.assertRaises(ValueError):runner.main()
                run.assert_not_called()

    def test_rewards_category_inspection_accepts_only_authorized_read_only_steps(self):
        for category in ('dungeon','special'):
            for step in ('enter','browse'):
                with self.subTest(category=category,step=step):
                    args,accounts,*_=self.parse(['--task','rewards','--mode','run','--step',step,'--account','second',
                                                 '--rewards-debug-after-shimen','--rewards-inspect-category',category])
                    self.assertEqual(args.rewards_inspect_category,category)
                    self.assertTrue(args.rewards_debug_after_shimen)
                    self.assertEqual([account['alias'] for account in accounts],['second'])

    def test_rewards_category_inspection_rejects_other_scopes_before_launch(self):
        base=['--task','rewards','--mode','run','--step','enter','--account','first','--rewards-debug-after-shimen']
        for category in ('dungeon','special'):
            for change in (['--step','advance'],['--step','complete'],['--step','daily'],['--step','observe'],
                           ['--task','dungeon'],['--mode','observe'],['--select-accounts','first']):
                with self.subTest(category=category,change=change),patch.object(sys,'argv',self.base+base+['--rewards-inspect-category',category]+change),patch.object(runner,'run_once') as run:
                    with self.assertRaises(ValueError):runner.main()
                    run.assert_not_called()
            options=['--task','rewards','--mode','run','--step','enter','--account','first','--rewards-inspect-category',category]
            with self.subTest(category=category,debug=False),patch.object(sys,'argv',self.base+options),patch.object(runner,'run_once') as run:
                with self.assertRaises(ValueError):runner.main()
                run.assert_not_called()
        with patch.object(sys,'argv',self.base+base+['--rewards-inspect-category','other']),patch.object(runner,'run_once') as run,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):runner.main()
            run.assert_not_called()


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
        self.device_calls = []
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
                test.device_calls.append(args)
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
        self.assertFalse(result['rewards_debug_after_shimen'])
        self.assertEqual(result['rewards_inspect_category'],'task')
        config=(self.archive/'run-config.lua').read_text(encoding='utf-8')
        self.assertIn('rewards_debug_after_shimen=false',config)
        self.assertIn('rewards_inspect_category="task"',config)

    def test_rewards_debug_publishes_selected_identity_and_archives_authorization(self):
        self.args.task='rewards';self.args.account='current';self.args.step='enter'
        self.args.rewards_debug_after_shimen=True
        self.args.rewards_inspect_category='dungeon'
        self.text='[account] current\n[task_result] rewards status=paused reason=rewards_inventory_observed\n[summary] scope=rewards daily_done=false\n[finished] script_exited_normally\n'
        home=self.root/'fake-home'
        identities=home/'.my_pocket_automation/accounts/current'
        identities.mkdir(parents=True)
        for name in ('role.lua','selector.lua'):(identities/name).write_text('return {}',encoding='utf-8')
        with patch.object(runner.Path,'home',return_value=home):result=self.invoke()
        self.assertTrue(result['rewards_debug_after_shimen'])
        self.assertEqual(result['rewards_inspect_category'],'dungeon')
        self.assertFalse(result['daily_complete'])
        config=(self.archive/'run-config.lua').read_text(encoding='utf-8')
        self.assertIn('verify_role=true',config)
        self.assertIn('rewards_debug_after_shimen=true',config)
        self.assertIn('rewards_inspect_category="dungeon"',config)
        self.assertIn('accounts={{alias="current"',config)
        published=[call[2] for call in self.device_calls if call[0]=='push']
        self.assertIn('/storage/emulated/0/TouchSprite/res/daily_identity_current.lua.pending',published)
        self.assertIn('/storage/emulated/0/TouchSprite/res/daily_selector_current.lua.pending',published)

    def test_rewards_direct_run_also_restricts_accounts_and_publishes_both_resources(self):
        self.args.task='rewards';self.args.account='current';self.args.step='complete'
        self.text='[account] current\n[task_result] rewards status=done reason=all_gourds_opened\n[summary] scope=rewards daily_done=false\n[finished] script_exited_normally\n'
        home=self.root/'fake-home'
        identities=home/'.my_pocket_automation/accounts/current'
        identities.mkdir(parents=True)
        for name in ('role.lua','selector.lua'):(identities/name).write_text('return {}',encoding='utf-8')
        with patch.object(runner.Path,'home',return_value=home),contextlib.redirect_stdout(io.StringIO()):
            runner.run_once(self.args,[{'alias':'current'},{'alias':'other'}],1,'20261009_230000',self.archive)
        config=(self.archive/'run-config.lua').read_text(encoding='utf-8')
        self.assertIn('verify_role=true',config)
        self.assertNotIn('alias="other"',config)
        self.assertFalse(json.loads((self.archive/'result.json').read_text(encoding='utf-8'))['rewards_debug_after_shimen'])
        published=[call[2] for call in self.device_calls if call[0]=='push']
        self.assertEqual(published,['/storage/emulated/0/TouchSprite/res/daily_identity_current.lua.pending',
                                    '/storage/emulated/0/TouchSprite/res/daily_selector_current.lua.pending',
                                    '/storage/emulated/0/TouchSprite/res/daily_config.lua.pending'])

    def test_rewards_missing_identity_never_launches(self):
        self.args.task='rewards';self.args.account='current';self.args.step='browse'
        with patch.object(runner.Path,'home',return_value=self.root/'missing-home'):
            result=self.invoke(RuntimeError,expected_launches=0)
        self.assertEqual(result['launch_status'],'not_attempted')
        self.assertEqual(result['phase'],'publish_config')

    def test_rewards_direct_debug_cannot_be_used_as_daily(self):
        self.args.task='rewards';self.args.account='current';self.args.step='daily'
        self.args.rewards_debug_after_shimen=True
        with self.assertRaises(ValueError):
            runner.run_once(self.args,[{'alias':'current'}],1,'20261009_230000',self.archive)
        self.assertFalse(self.archive.exists())
        self.assertEqual(self.calls,[])

    def test_rewards_direct_category_inspection_rejects_consuming_steps(self):
        self.args.task='rewards';self.args.account='current';self.args.rewards_debug_after_shimen=True
        self.args.rewards_inspect_category='special'
        for step in ('complete','advance','daily'):
            with self.subTest(step=step):
                self.args.step=step
                with self.assertRaises(ValueError):
                    runner.run_once(self.args,[{'alias':'current'}],1,'20261009_230000',self.archive)
        self.assertFalse(self.archive.exists())
        self.assertEqual(self.calls,[])

    def test_collection_authorization_is_passed_only_in_environment(self):
        with patch.object(runner, 'command', side_effect=self.command) as execute:
            self.invoke()
        calls = [call for call in execute.call_args_list
                 if any('collect-debug.ps1' in str(arg) for arg in call.args[0])]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs['env']['TOUCHSPRITE_AUTH'], 'fake-secret-not-for-archive')
        self.assertNotIn('fake-secret-not-for-archive', str(calls[0].args))

    def test_run_config_does_not_include_prior_game_state(self):
        self.args.task='shimen';self.args.account='current'
        self.text='[account] current\n[task_result] shimen status=done reason=completion_card_verified\n[summary] scope=shimen daily_done=false\n[finished] script_exited_normally\n'
        home=self.root/'fake-home'
        identities=home/'.my_pocket_automation/accounts/current'
        identities.mkdir(parents=True)
        for name in ('role.lua','selector.lua'):(identities/name).write_text('return {}',encoding='utf-8')
        with patch.object(runner.Path,'home',return_value=home):result=self.invoke()
        config=(self.archive/'run-config.lua').read_text(encoding='utf-8')
        for name in ('shimen_resume_date','find_retry_attempt','puzzle_retry_attempt'):
            self.assertNotIn(name,config)
            self.assertNotIn(name,result)
        self.assertIn('business_date="'+runner.datetime.now().strftime('%Y%m%d')+'"',config)

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

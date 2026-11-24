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
    def test_shimen_capture_is_observation_only_not_daily_completion(self):
        text='[account] current\n[task_result] shimen status=paused reason=find_catalog_observation_only\n[summary] daily_done=false\n[finished] script_exited_normally'
        result=runner.runtime_result(text,'run','browse','shimen',[{'alias':'current'}])
        self.assertTrue(result['expectation_met'])
        self.assertFalse(result['daily_complete'])

    def test_long_run_refreshes_expiring_transport_authorization(self):
        from dfx_device import Device
        device=Device('offline');device.port='123';device.auth='fixture';device.auth_deadline=10
        with patch('dfx_device.time.monotonic',return_value=20),patch.object(device,'authorize') as renew, \
                patch.object(device,'request',return_value='f01'):
            self.assertEqual(device.status(),'f01')
            renew.assert_called_once_with()

    def test_valid_transport_authorization_is_reused(self):
        from dfx_device import Device
        device=Device('offline');device.port='123';device.auth='fixture';device.auth_deadline=30
        with patch('dfx_device.time.monotonic',return_value=20),patch.object(device,'authorize') as renew, \
                patch.object(device,'request',return_value='f01'):
            self.assertEqual(device.status(),'f01')
            renew.assert_not_called()

    def test_authorization_refresh_keeps_existing_forwarding_port(self):
        from dfx_device import Device
        device=Device('offline');device.port='123'
        with patch.object(device,'adb_call') as adb,patch.object(Path,'read_text',return_value='fixture'), \
                patch.object(device,'request',side_effect=['abcdefghijklmnop','{"status":200,"auth":"renewed"}']), \
                patch('dfx_device.time.monotonic',return_value=20):
            device.authorize()
            adb.assert_not_called()
            self.assertEqual(device.port,'123')
            self.assertEqual(device.auth_deadline,3560)

    def test_ledger_retry_cli_options_are_removed(self):
        for option in ('--find-retry-attempt','--puzzle-retry-attempt'):
            with self.subTest(option=option),patch.object(sys,'argv',['run-daily.py','--vm-index','5','--device','fake',option,'14']),patch.object(runner,'run_once') as run,contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):runner.main()
                run.assert_not_called()

    def test_prior_ledger_date_is_not_a_runtime_option(self):
        with patch.object(sys,'argv',['run-daily.py','--vm-index','5','--device','fake','--shimen-resume-date','20261010']),patch.object(runner,'run_once') as run,contextlib.redirect_stderr(io.StringIO()):
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

    def test_secondary_screenshot_failure_preserves_first_task_failure_reason(self):
        for status in ('failed', 'blocked', 'paused'):
            with self.subTest(status=status):
                text = (f'[account] current\n[task_result] shimen status={status} reason=puzzle_tiles_unrecognized\n'
                        '[task_result] navigation status=blocked reason=secondary_navigation_failure\n'
                        '[failed] screenshot error\n[finished] script_failed\n')
                result = runner.runtime_result(text, 'run', 'daily', accounts=[{'alias': 'current'}],
                                               selected_tasks=['shimen'])
                self.assertEqual(result['script_status'], 'failed')
                self.assertEqual(result['termination_reason'], 'puzzle_tiles_unrecognized')
                self.assertEqual(result['tasks'][0]['status'], status)
                self.assertFalse(result['expectation_met'])

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
        self.base=['run-daily.py','--vm-index','5','--accounts',str(self.accounts)]

    def parse(self,options):
        args=runner.create_parser().parse_args(self.base[1:]+options)
        with patch.object(runner,'execute',side_effect=AssertionError('validation performed device work')):
            accounts,seconds=runner.prepare(args)
        return args,accounts,seconds

    def test_default_daily_tasks_include_rewards(self):
        args,accounts,seconds=self.parse(['--mode','run','--step','daily'])
        self.assertEqual(args.tasks,['shimen','zhuagui','dungeon','rewards'])
        self.assertIsNone(args.dungeons)
        self.assertEqual(seconds,18000)
        self.assertFalse(args.rewards_debug_after_shimen)
        self.assertEqual(args.rewards_inspect_category,'task')
        self.assertEqual([account['alias'] for account in accounts],['first','second'])

    def test_explicit_dungeons_preserve_order_and_reject_duplicates(self):
        options=['--mode','run','--step','daily','--dungeons']
        args,_,seconds=self.parse(options+['pingding,chechi,shuilu,heifeng,wuji'])
        self.assertEqual(args.dungeons,['pingding','chechi','shuilu','heifeng','wuji'])
        self.assertEqual(seconds,10800)
        with self.assertRaisesRegex(ValueError,'Invalid selected dungeons'):
            self.parse(options+['pingding,pingding'])

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
        self.args = SimpleNamespace(device='fake', vm_index=5, mumu_dir=self.root / 'mumu', adb='fake-adb',
                                    mode='run', step='complete', dungeon='wuji')
        self.statuses = ['f00', 'f00']
        self.start_error = None
        self.collect_error = None
        self.cleanup_error = None
        self.authorize_action = None
        self.before_push = None
        self.text = log_for()
        self.calls = []
        self.device_calls = []
        test = self

        class FakeDevice:
            adb = 'fake-adb'
            auth = 'fake-secret-not-for-archive'

            def __init__(self, device, adb='fake-adb'):
                self.adb = adb
                self.files = {}

            def authorize(self):
                if test.authorize_action:
                    test.authorize_action()

            def status(self):
                item = test.statuses.pop(0) if len(test.statuses) > 1 else test.statuses[0]
                if isinstance(item, Exception):
                    raise item
                return item

            def adb_call(self, *args):
                test.device_calls.append(args)
                if args[0] == 'push':
                    if test.before_push:
                        test.before_push(Path(args[1]))
                    self.files[args[2]] = Path(args[1]).read_bytes()
                elif args[:2] == ('shell', 'sha256sum'):
                    return hashlib.sha256(self.files[args[2]]).hexdigest() + ' fake'
                return ''

            def close(self):
                if test.cleanup_error:
                    raise test.cleanup_error

        self.patches = [patch.object(runner, 'ROOT', self.root), patch.object(runner, 'build', return_value=self.bundle),
                        patch.object(runner.Path, 'home', return_value=self.root / 'empty-home'),
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
        self.assertEqual(result['vm_index'], 5)
        self.assertEqual(result['device'], 'fake')
        self.assertEqual(result['adb'], 'fake-adb')
        self.assertEqual(result['mumu_dir'], str(self.args.mumu_dir))
        self.assertEqual(result['archive'], str(self.archive))
        self.assertEqual(result['run_config_sha256'], hashlib.sha256((self.archive / 'run-config.lua').read_bytes()).hexdigest())
        self.assertEqual(result['bundle_sha256'], hashlib.sha256((self.archive / 'script-source.lua').read_bytes()).hexdigest())
        for key in ('failure_domain', 'failure_boundary', 'recovery_events', 'recovery_attempt_token'):
            self.assertNotIn(key, result)

    def test_build_and_published_source_are_isolated_to_this_archive(self):
        with patch.object(runner, 'build', return_value=self.bundle) as build:
            self.invoke()
        build.assert_called_once_with(output=self.archive / 'build')
        launch = next(call for call in self.calls if any('ts-cli.ps1' in str(arg) for arg in call))
        self.assertEqual(launch[launch.index('-SourcePath') + 1], str(self.archive / 'script-source.lua'))

    def test_account_config_and_device_tool_hashes_are_archived_with_environment_link(self):
        self.args.accounts_source = self.root / 'external-accounts.json'
        self.args.accounts_source.write_text('[{"alias":"current"}]', encoding='utf-8')
        self.args.environment_run_id = '20261009_225959'
        self.args.environment_archive = str(self.root / 'debug-runs/20261009_225959')
        tools = self.root / 'scripts/device'
        tools.mkdir(parents=True)
        for name, content in (('run-daily.py', 'runner source'), ('ts-cli.ps1', 'transport source'),
                              ('README.md', 'instructions')):
            (tools / name).write_text(content, encoding='utf-8')
        result = self.invoke()
        self.assertEqual(result['accounts_sha256'], hashlib.sha256(self.args.accounts_source.read_bytes()).hexdigest())
        self.assertEqual(result['device_tools_sha256'], {
            'scripts/device/' + name: hashlib.sha256((tools / name).read_bytes()).hexdigest()
            for name in ('run-daily.py', 'ts-cli.ps1')})
        self.assertEqual(result['environment_run_id'], self.args.environment_run_id)
        self.assertEqual(result['environment_archive'], self.args.environment_archive)
        self.assertNotIn('runner source', json.dumps(result))

    def test_archive_collision_preserves_previous_evidence_without_launch(self):
        self.archive.mkdir(parents=True)
        result_path = self.archive / 'result.json'
        result_path.write_text('{"prior":true}', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            runner.run_once(self.args, [{'alias': 'current'}], 1, '20261009_230000', self.archive)
        self.assertEqual(result_path.read_text(encoding='utf-8'), '{"prior":true}')
        self.assertEqual(self.device_calls, [])
        self.assertEqual(self.calls, [])

    def configure_input_files(self):
        self.args.task = 'shimen'
        self.args.account = 'current'
        identities = self.root / 'empty-home/.my_pocket_automation/accounts/current'
        identities.mkdir(parents=True)
        for name in ('role.lua', 'selector.lua'):
            (identities / name).write_text('return {original=true}', encoding='utf-8')
        source = self.root / 'src/main.lua'
        source.parent.mkdir()
        source.write_text('return "original source"', encoding='utf-8')
        self.args.accounts_source = self.root / 'external-accounts.json'
        self.args.accounts_source.write_text('[{"alias":"current"}]', encoding='utf-8')
        self.args.accounts_source_sha256 = hashlib.sha256(self.args.accounts_source.read_bytes()).hexdigest()
        self.args.input_evidence = runner.input_evidence(self.args, [{'alias': 'current'}], 1)
        return {'role.lua': identities / 'role.lua', 'selector.lua': identities / 'selector.lua', 'source': source}

    def assert_authorization_drift_is_rejected(self, name):
        paths = self.configure_input_files()
        original = self.args.input_evidence
        self.authorize_action = lambda: paths[name].write_text('changed while authorizing', encoding='utf-8')
        result = self.invoke(RuntimeError, expected_launches=0)
        self.assertEqual(result['phase'], 'authorize')
        self.assertEqual(result['launch_status'], 'not_attempted')
        self.assertEqual(result['collection_status'], 'not_attempted')
        for key in ('requested_scope', 'accounts_sha256', 'account_resources_sha256', 'source_sha256'):
            self.assertEqual(result[key], original[key])
        self.assertEqual(result['requested_scope']['accounts'], [{'alias': 'current', 'claim_dungeon_rewards': False}])
        config = (self.archive / 'run-config.lua').read_text(encoding='utf-8')
        self.assertIn('identity_binding="' + original['account_resources_sha256']['current']['role.lua'] + '"', config)
        self.assertEqual(self.device_calls, [])
        self.assertEqual(self.calls, [])

    def test_role_change_during_authorization_does_not_publish_or_rebind(self):
        self.assert_authorization_drift_is_rejected('role.lua')

    def test_selector_change_during_authorization_does_not_publish(self):
        self.assert_authorization_drift_is_rejected('selector.lua')

    def test_source_change_during_authorization_does_not_publish(self):
        self.assert_authorization_drift_is_rejected('source')

    def test_identity_changed_during_push_cannot_self_validate_against_live_file(self):
        paths = self.configure_input_files()
        original_hash = self.args.input_evidence['account_resources_sha256']['current']['role.lua']

        def replace_identity(path):
            if path == paths['role.lua']:
                path.write_text('changed immediately before push', encoding='utf-8')

        self.before_push = replace_identity
        result = self.invoke(RuntimeError, expected_launches=0)
        self.assertEqual(result['phase'], 'publish_config')
        self.assertEqual(result['account_resources_sha256']['current']['role.lua'], original_hash)
        self.assertNotEqual(hashlib.sha256(paths['role.lua'].read_bytes()).hexdigest(), original_hash)
        self.assertEqual(result['launch_status'], 'not_attempted')
        self.assertFalse(any(call[:2] == ('shell', 'mv') for call in self.device_calls))
        self.assertFalse(any('daily_config.lua.pending' in str(call) for call in self.device_calls))
        self.assertEqual(self.calls, [])

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
        expected = hashlib.sha256((identities / 'role.lua').read_bytes()).hexdigest()
        self.assertIn('identity_binding="' + expected + '"', config)
        self.assertEqual(result['account_resources_sha256'], {'current': {
            name: hashlib.sha256((identities / name).read_bytes()).hexdigest()
            for name in ('role.lua', 'selector.lua')}})
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

    def test_unknown_preflight_state_never_publishes_launches_or_collects(self):
        self.statuses = ['unrecognized-status']
        result = self.invoke(RuntimeError, expected_launches=0)
        self.assertEqual(result['launch_status'], 'not_attempted')
        self.assertEqual(result['collection_status'], 'not_attempted')
        self.assertTrue(result['may_still_be_running'])
        self.assertEqual(self.device_calls, [])
        self.assertEqual(self.calls, [])

    def test_preflight_transport_failure_never_launches_or_collects(self):
        self.statuses = [RuntimeError('auth MUST_NOT_LEAK')]
        result = self.invoke(RuntimeError, expected_launches=0)
        self.assertEqual(result['launch_status'], 'not_attempted')
        self.assertEqual(result['collection_status'], 'not_attempted')
        self.assertEqual(result['error_type'], 'RuntimeError')
        self.assertNotIn('MUST_NOT_LEAK', json.dumps(result))
        self.assertEqual(self.device_calls, [])
        self.assertEqual(self.calls, [])

    def test_missing_device_log_is_unknown_not_success(self):
        with patch.object(runner, 'command', return_value='accepted but no evidence'):
            result = self.invoke(RuntimeError, expected_launches=0)
        self.assertEqual(result['host_status'], 'business_unverified')
        self.assertEqual(result['script_status'], 'unknown')


if __name__ == '__main__':
    unittest.main()

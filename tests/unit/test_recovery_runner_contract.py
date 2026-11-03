"""A run command validates its scope, holds one VM lock, and launches once."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tests.unit import test_dfx_runner as existing


runner = existing.runner


class AtomicRunnerOptionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.accounts = self.root / 'accounts.json'
        self.configured = [{'alias': 'one'}, {'alias': 'two', 'claim_dungeon_rewards': True}]
        self.accounts.write_text(json.dumps(self.configured), encoding='utf-8')
        self.base = ['--vm-index', '5', '--accounts', str(self.accounts)]

    def prepare(self, options=()):
        args = runner.create_parser().parse_args([*self.base, *options])
        with patch.object(runner, 'Device', side_effect=AssertionError('device I/O during validation')), \
                patch.object(runner, 'command', side_effect=AssertionError('host I/O during validation')):
            accounts, seconds = runner.prepare(args)
        return args, accounts, seconds

    def test_exact_vm_is_required_even_when_endpoint_is_supplied(self):
        for options in ([], ['--device', '127.0.0.1:16544']):
            with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    runner.create_parser().parse_args(options)
        args = runner.create_parser().parse_args(['--vm-index', '0'])
        self.assertEqual(args.vm_index, 0)
        self.assertIsNone(args.device)

    def test_old_recovery_controls_are_rejected_by_the_parser(self):
        for options in (['--recover'], ['--recovery-state', 'state.json'],
                        ['--recovery-delay', '1'], ['--reset-recovery']):
            with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    runner.create_parser().parse_args([*self.base, *options])

    def test_daily_preparation_keeps_full_roster_and_selected_task_order(self):
        args, accounts, seconds = self.prepare([
            '--mode', 'run', '--step', 'daily', '--select-accounts', 'two',
            '--tasks', 'rewards,dungeon,shimen', '--dungeons', 'chechi,wuji',
            '--max-seconds', '111', '--shimen-needed', '7',
            '--routine-screenshots', '--verbose-logs'])
        self.assertEqual(accounts, self.configured)
        self.assertEqual(args.select_accounts, ['two'])
        self.assertEqual(args.tasks, ['shimen', 'dungeon', 'rewards'])
        self.assertEqual(args.dungeons, ['chechi', 'wuji'])
        self.assertEqual(seconds, 111)
        self.assertEqual(args.shimen_needed, 7)
        self.assertTrue(args.routine_screenshots)
        self.assertTrue(args.verbose_logs)
        self.assertEqual(args.accounts_source, self.accounts)
        self.assertEqual(args.accounts_source_sha256, hashlib.sha256(self.accounts.read_bytes()).hexdigest())
        self.assertIsNone(args.device)

    def test_selected_rewards_preparation_preserves_claim_policy_and_debug_authorization(self):
        args, accounts, seconds = self.prepare([
            '--mode', 'run', '--step', 'browse', '--task', 'rewards', '--account', 'two',
            '--rewards-debug-after-shimen', '--rewards-inspect-category', 'special'])
        self.assertEqual(accounts, [self.configured[1]])
        self.assertEqual(args.account, 'two')
        self.assertEqual(args.rewards_inspect_category, 'special')
        self.assertTrue(args.rewards_debug_after_shimen)
        self.assertEqual(seconds, 90)

    def test_observation_and_bounded_sampling_options_survive_preparation(self):
        args, accounts, seconds = self.prepare([
            '--mode', 'run', '--step', 'browse', '--task', 'zhuagui', '--account', 'one',
            '--browse-rounds', '10', '--browse-until-no-new-topics'])
        self.assertEqual((args.browse_rounds, args.browse_until_no_new_topics), (10, True))
        self.assertEqual(accounts, [self.configured[0]])
        self.assertEqual(seconds, 60 * 65 + 30)
        args, accounts, seconds = self.prepare([
            '--mode', 'observe', '--step', 'observe', '--task', 'shimen', '--account', 'two'])
        self.assertEqual((args.mode, args.step, args.task), ('observe', 'observe', 'shimen'))
        self.assertEqual(accounts, [self.configured[1]])
        self.assertEqual(seconds, 90)

    def test_one_visible_shimen_puzzle_family_is_preserved(self):
        args, accounts, seconds = self.prepare([
            '--mode', 'run', '--step', 'advance', '--task', 'shimen', '--account', 'one',
            '--shimen-puzzle-family', '八仙'])
        self.assertEqual(args.shimen_puzzle_family, '八仙')
        self.assertEqual(accounts, [self.configured[0]])
        self.assertEqual(seconds, 3900)

    def test_launch_game_needs_no_accounts_or_identity_file(self):
        args = runner.create_parser().parse_args(['--vm-index', '5', '--mode', 'run', '--step', 'launch-game'])
        with patch.object(Path, 'read_text', side_effect=AssertionError('account read')):
            self.assertEqual(runner.prepare(args), ([], 150))

    def test_accounts_changed_after_preparation_prevent_all_execution(self):
        original_hash = hashlib.sha256(self.accounts.read_bytes()).hexdigest()

        @contextlib.contextmanager
        def lock(*_args):
            self.accounts.write_text('[{"alias":"replacement"}]', encoding='utf-8')
            yield

        with patch.object(runner, 'instance_lock', side_effect=lock), \
                patch.object(runner, 'prepare', wraps=runner.prepare) as prepare, \
                patch.object(runner, 'execute') as execute, patch.object(runner, 'Device') as device, \
                patch.object(runner, 'command') as command:
            with self.assertRaisesRegex(RuntimeError, 'configuration changed'):
                runner.main([*self.base, '--mode', 'run', '--step', 'daily'])
        self.assertEqual(prepare.call_args.args[0].accounts_source_sha256, original_hash)
        execute.assert_not_called()
        device.assert_not_called()
        command.assert_not_called()

    def test_invalid_scope_is_rejected_before_lock_or_device_io(self):
        invalid = (
            ['--vm-index', '-1'], ['--max-seconds', '0'], ['--max-seconds', '-1'],
            ['--shimen-needed', '0'], ['--tasks', 'shimen,shimen'], ['--tasks', 'unknown'],
            ['--dungeons', 'wuji,wuji'], ['--browse-rounds', '61'],
            ['--browse-rounds', '2'], ['--browse-until-no-new-topics'],
            ['--shimen-puzzle-family', '八仙'], ['--task', 'rewards', '--mode', 'run'],
            ['--select-accounts', 'missing', '--step', 'daily'],
            ['--select-accounts', 'one', 'one', '--step', 'daily'],
        )
        for options in invalid:
            with self.subTest(options=options), patch.object(runner, 'instance_lock') as lock, \
                    patch.object(runner, 'execute') as execute, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises((ValueError, SystemExit)):
                    runner.main([*self.base, *options])
                lock.assert_not_called()
                execute.assert_not_called()


class AtomicRunnerExecutionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = SimpleNamespace(vm_index=5, mumu_dir=self.root / 'mumu', device=None)
        self.accounts = [{'alias': 'one', 'claim_dungeon_rewards': True}]
        self.launcher = SimpleNamespace(validate_vm=Mock(return_value={'device': '127.0.0.1:16385'}),
                                        start=Mock(side_effect=AssertionError('automatic VM recovery')),
                                        start_apps=Mock(side_effect=AssertionError('automatic app recovery')))
        for item in (patch.object(runner, 'ROOT', self.root),
                     patch.object(runner.Path, 'home', return_value=self.root / 'empty-home'),
                     patch.object(runner, '_load_emulator', return_value=self.launcher)):
            item.start()
            self.addCleanup(item.stop)

    def test_execute_resolves_current_endpoint_and_uses_selected_installation_adb(self):
        with patch.object(runner, 'run_once', return_value={'expectation_met': True}) as run:
            result = runner.execute(self.args, self.accounts, 121)
        self.launcher.validate_vm.assert_called_once_with(self.args.mumu_dir, 5, None)
        run.assert_called_once()
        args, accounts, seconds, run_id, archive = run.call_args.args
        self.assertIs(args, self.args)
        self.assertEqual(args.device, '127.0.0.1:16385')
        self.assertEqual(args.adb, str(self.args.mumu_dir / 'adb.exe'))
        self.assertEqual((accounts, seconds), (self.accounts, 121))
        self.assertRegex(run_id, r'^\d{8}_\d{6}$')
        self.assertEqual(archive, self.root / 'debug-runs' / run_id)
        self.assertEqual(args.lua_run_id, run_id)
        self.assertEqual(Path(args.lua_archive), archive)
        self.assertTrue(result['expectation_met'])

    def test_supplied_endpoint_is_only_an_exact_vm_check(self):
        self.args.device = '127.0.0.1:16384'
        self.launcher.validate_vm.side_effect = ValueError('Selected VM and connected device do not match')
        with patch.object(runner, 'run_once') as run:
            with self.assertRaises(ValueError):
                runner.execute(self.args, self.accounts, 121)
        self.launcher.validate_vm.assert_called_once_with(self.args.mumu_dir, 5, '127.0.0.1:16384')
        run.assert_not_called()
        self.assertFalse((self.root / 'debug-runs').exists())

    def test_repeated_commands_reserve_distinct_run_ids(self):
        with patch.object(runner, 'run_once', return_value={}) as run:
            runner.execute(self.args, self.accounts, 121)
            self.args.device = None
            self.launcher.validate_vm.return_value = {'device': '127.0.0.1:16386'}
            runner.execute(self.args, self.accounts, 121)
        calls = run.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0].args[3], calls[1].args[3])
        self.assertNotEqual(calls[0].args[4], calls[1].args[4])
        self.assertEqual(self.args.device, '127.0.0.1:16386')

    def test_single_attempt_failure_is_propagated_without_stop_or_restart(self):
        failure = TimeoutError('launch outcome unknown')
        with patch.object(runner, 'run_once', side_effect=failure) as run, patch.object(runner, 'Device') as device:
            with self.assertRaises(TimeoutError) as raised:
                runner.execute(self.args, self.accounts, 121)
        self.assertIs(raised.exception, failure)
        run.assert_called_once()
        device.assert_not_called()
        self.launcher.start.assert_not_called()
        self.launcher.start_apps.assert_not_called()


class AtomicRunnerCliTest(unittest.TestCase):
    def test_main_prepares_before_lock_and_executes_once_inside_it(self):
        events = []
        accounts = [{'alias': 'current'}]

        def prepare(args):
            events.append('prepare')
            self.assertEqual(args.vm_index, 5)
            return accounts, 150

        @contextlib.contextmanager
        def lock(root, mumu_dir, vm_index):
            self.assertEqual((root, mumu_dir, vm_index), (runner.ROOT, Path('D:/mumu'), 5))
            events.append('locked')
            try:
                yield
            finally:
                events.append('released')

        def execute(args, prepared, seconds):
            self.assertEqual(events, ['prepare', 'locked'])
            self.assertEqual((prepared, seconds), (accounts, 150))
            events.append('execute')

        def capture_evidence(args, prepared, seconds):
            self.assertEqual(events, ['prepare', 'locked'])
            self.assertEqual((prepared, seconds), (accounts, 150))
            return {'requested_scope': 'fixture'}

        with patch.object(runner, 'prepare', side_effect=prepare), patch.object(runner, 'instance_lock', side_effect=lock), \
                patch.object(runner, 'input_evidence', side_effect=capture_evidence) as evidence, \
                patch.object(runner, 'execute', side_effect=execute) as run:
            runner.main(['--vm-index', '5', '--mumu-dir', 'D:/mumu'])
        run.assert_called_once()
        evidence.assert_called_once_with(run.call_args.args[0], accounts, 150)
        self.assertEqual(run.call_args.args[0].input_evidence, {'requested_scope': 'fixture'})
        self.assertEqual(events, ['prepare', 'locked', 'execute', 'released'])

    def test_busy_lock_prevents_all_execution(self):
        with patch.object(runner, 'prepare', return_value=([], 150)), \
                patch.object(runner, 'instance_lock', side_effect=RuntimeError('selected VM busy')), \
                patch.object(runner, 'execute') as execute:
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                runner.main(['--vm-index', '5'])
        execute.assert_not_called()

    def test_cli_failure_is_machine_readable_without_exception_details(self):
        for failure in (RuntimeError('auth MUST_NOT_LEAK'), FileNotFoundError('private credential path'),
                        TimeoutError('auth MUST_NOT_LEAK')):
            output = io.StringIO()
            with self.subTest(error_type=type(failure).__name__), patch.object(runner, 'main', side_effect=failure) as main, \
                    contextlib.redirect_stdout(output):
                self.assertEqual(runner.cli(['--vm-index', '5']), 1)
            main.assert_called_once_with(['--vm-index', '5'])
            result = json.loads(output.getvalue())
            self.assertEqual(result['error_type'], type(failure).__name__)
            self.assertNotIn('MUST_NOT_LEAK', output.getvalue())
            self.assertNotIn('private credential', output.getvalue())

    def test_cli_success_calls_main_once(self):
        with patch.object(runner, 'main') as main:
            self.assertEqual(runner.cli(['--vm-index', '5']), 0)
        main.assert_called_once_with(['--vm-index', '5'])

    def test_old_recovery_fields_are_not_returned_in_normal_result(self):
        text = ('[account] current\n[recovery_failure] domain=puzzle task=shimen account=current reason=failed\n'
                '[roster_verified] roles=1\n[account_verified] current\n'
                '[task_result] shimen status=paused reason=puzzle_tiles_unrecognized\n'
                '[home_verified] account=current task=shimen\n[finished] script_exited_normally\n')
        result = runner.runtime_result(text, 'run', 'daily', accounts=[{'alias': 'current'}], selected_tasks=['shimen'])
        self.assertEqual(result['tasks'][0]['reason'], 'puzzle_tiles_unrecognized')
        self.assertEqual(result['termination_reason'], 'puzzle_tiles_unrecognized')
        self.assertFalse(result['expectation_met'])
        for key in ('failure_domain', 'failure_boundary', 'recovery_events', 'recovery_attempt_token'):
            self.assertNotIn(key, result)


if __name__ == '__main__':
    unittest.main()

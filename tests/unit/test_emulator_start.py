"""Emulator bootstrap validates the selected VM and never operates apps."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/device'))
spec = importlib.util.spec_from_file_location('start_emulator', ROOT / 'scripts/device/start-emulator.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def vm(running=True, android=True, port=16544, index='5', pid=1000):
    result = dict(index=index, error_code=0, name='fixture', android_version='12.0',
                  is_process_started=running, is_android_started=android, pid=pid)
    if port is not None:
        result['adb_port'] = port
    return result


class EmulatorStartTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        for name in ('MuMuManager.exe', 'adb.exe'):
            (self.folder / name).touch()
        self.report = self.folder / 'archive/emulator-start.json'
        self.clock = 0
        self.infos = [vm()]
        self.calls = []
        self.boot = '1'
        self.android = '12'
        self.package = 'package:/system/framework/framework-res.apk'
        self.launch_lost = False
        self.restart_lost = False
        self.on_restart = None
        self.adb_states = ['device']
        self.offline_until_disconnect = False

    def command(self, args, timeout):
        self.calls.append(args)
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 10)
        if args[1] == 'version':
            return '{"version":"6.8.7.0"}'
        if args[1] == 'info':
            self.assertEqual(args[2:], ['--vmindex', '5'])
            result = self.infos.pop(0) if len(self.infos) > 1 else self.infos[0]
            return json.dumps(result)
        if args[1] == 'control':
            self.assertEqual(args[2:4], ['--vmindex', '5'])
            self.assertIn(args[4], ('launch', 'restart'))
            if args[4] == 'restart' and self.on_restart:
                self.on_restart()
            if (args[4] == 'launch' and self.launch_lost) or (args[4] == 'restart' and self.restart_lost):
                raise subprocess.TimeoutExpired(args, timeout)
            return '{}'
        if args[1] == 'connect':
            return 'connected'
        if args[1] == 'disconnect':
            self.assertEqual(len(args), 3, 'Never disconnect all transports')
            self.offline_until_disconnect = False
            return 'disconnected'
        self.assertEqual(args[1], '-s')
        self.assertRegex(args[2], r'^127\.0\.0\.1:\d+$')
        operation = args[3:]
        if operation == ['get-state']:
            if self.offline_until_disconnect:
                raise RuntimeError('ADB offline')
            state = self.adb_states.pop(0) if len(self.adb_states) > 1 else self.adb_states[0]
            if isinstance(state, Exception):
                raise state
            return state
        if operation == ['shell', 'getprop', 'sys.boot_completed']:
            return self.boot
        if operation == ['shell', 'getprop', 'ro.build.version.release']:
            return self.android
        self.assertEqual(operation, ['shell', 'pm', 'path', 'android'])
        return self.package

    def sleep(self, seconds):
        self.assertLessEqual(seconds, 2)
        self.clock += seconds

    def run_start(self, timeout=5, max_restarts=0):
        with patch.object(launcher, 'command', side_effect=self.command), \
                patch.object(launcher.time, 'monotonic', side_effect=lambda: self.clock), \
                patch.object(launcher.time, 'sleep', side_effect=self.sleep), contextlib.redirect_stdout(io.StringIO()):
            options = {} if max_restarts is None else {'max_restarts': max_restarts}
            return launcher.start(self.folder, 5, timeout, self.report, **options)

    def launches(self):
        return [args for args in self.calls if args[1] == 'control' and args[-1] == 'launch']

    def restarts(self):
        return [args for args in self.calls if args[1] == 'control' and args[-1] == 'restart']

    def test_cold_start_launches_only_selected_vm_then_waits_for_boot(self):
        self.infos = [vm(False, False, None), vm(True, False, None), vm()]
        result = self.run_start()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['device'], '127.0.0.1:16544')
        self.assertEqual(result['elapsed_seconds'], 2)
        self.assertTrue(result['package_manager_ready'])
        self.assertEqual(len(self.launches()), 1)
        self.assertEqual(list(self.report.parent.glob('*.png')), [])

    def test_running_vm_is_reused_and_dynamic_endpoint_is_selected_explicitly(self):
        result = self.run_start()
        self.assertEqual(result['launch_status'], 'reused')
        self.assertEqual(self.launches(), [])
        self.assertFalse(any(args[1] == 'devices' for args in self.calls))
        self.assertIn([str(self.folder / 'adb.exe'), 'connect', '127.0.0.1:16544'], self.calls)

    def test_wrong_vm_identity_prevents_launch(self):
        self.infos = [vm(index='6')]
        with self.assertRaises(ValueError):
            self.run_start()
        self.assertEqual(self.launches(), [])
        self.assertEqual(json.loads(self.report.read_text())['status'], 'failed')

    def test_invalid_or_unbounded_deadlines_do_not_start_any_process(self):
        for seconds in (0, -1, float('nan'), float('inf')):
            with self.subTest(timeout=seconds), patch.object(launcher, 'command') as command:
                with self.assertRaises(ValueError):
                    launcher.start(self.folder, 5, seconds, self.report)
                command.assert_not_called()
                self.assertFalse(self.report.exists())

    def test_adb_device_state_without_android_boot_is_not_ready(self):
        self.infos = [vm(False, False, None), vm()]
        self.boot = '0'
        with self.assertRaises(TimeoutError):
            self.run_start()
        record = json.loads(self.report.read_text())
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['boot_completed'], '0')
        self.assertEqual(len(self.launches()), 1)
        self.assertEqual(self.clock, 5)

    def test_lost_launch_reply_is_observed_without_a_second_launch(self):
        self.infos = [vm(False, False, None), vm()]
        self.launch_lost = True
        result = self.run_start()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['launch_status'], 'unknown')
        self.assertEqual(len(self.launches()), 1)

    def test_missing_vm_port_never_falls_back_to_another_adb_device(self):
        self.infos = [vm(False, False, None), vm(True, True, None)]
        with self.assertRaises(TimeoutError):
            self.run_start()
        self.assertFalse(any(args[1] in ('connect', '-s', 'devices') for args in self.calls))

    def test_package_manager_and_android_version_must_also_match(self):
        for android, package in [('15', self.package), ('12', '')]:
            with self.subTest(android=android, package=package):
                self.report.unlink(missing_ok=True)
                self.clock = 0
                self.android, self.package = android, package
                with self.assertRaises(TimeoutError):
                    self.run_start()
                self.assertEqual(json.loads(self.report.read_text())['status'], 'failed')

    def test_offline_adb_is_not_ready_until_selected_transport_recovers(self):
        self.offline_until_disconnect = True
        result = self.run_start(timeout=15, max_restarts=3)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['elapsed_seconds'], 10)
        self.assertEqual(result['attempts'][0]['connect_requests'], 2)
        self.assertEqual(self.restarts(), [])
        self.assertIn([str(self.folder / 'adb.exe'), 'disconnect', '127.0.0.1:16544'], self.calls)
        self.assertFalse(any(args[1] == 'kill-server' for args in self.calls))

    def test_timeout_restarts_only_selected_vm_then_uses_its_new_port(self):
        self.adb_states = [RuntimeError('ADB offline')]

        def recover():
            self.infos = [vm(port=16600, pid=2000)]
            self.adb_states = ['device']

        self.on_restart = recover
        result = self.run_start(max_restarts=3)
        self.assertEqual(result['device'], '127.0.0.1:16600')
        self.assertEqual(result['restart_count'], 1)
        self.assertEqual([attempt['status'] for attempt in result['attempts']], ['timed_out', 'ready'])
        self.assertEqual(len(self.restarts()), 1)
        self.assertIn([str(self.folder / 'adb.exe'), '-s', '127.0.0.1:16600', 'get-state'], self.calls)

    def test_connect_acknowledgement_does_not_replace_device_state_probe(self):
        self.adb_states = ['offline', 'unauthorized', 'device']
        result = self.run_start()
        self.assertEqual(result['elapsed_seconds'], 4)
        self.assertEqual(result['adb_state'], 'device')
        self.assertEqual(len([args for args in self.calls if args[-1] == 'get-state']), 3)
        self.assertEqual(len([args for args in self.calls if args[-2:] == ['getprop', 'sys.boot_completed']]), 1)

    def test_third_restart_can_succeed_without_sending_a_fourth_request(self):
        self.boot = '0'
        restarted = 0

        def recover():
            nonlocal restarted
            restarted += 1
            self.infos = [vm(pid=1000 + restarted)]
            self.boot = '1' if restarted == 3 else '0'

        self.on_restart = recover
        result = self.run_start(max_restarts=3)
        self.assertEqual(result['restart_count'], 3)
        self.assertEqual(result['elapsed_seconds'], 15)
        self.assertEqual(len(result['attempts']), 4)
        self.assertEqual(len(self.restarts()), 3)

    def test_default_budget_stops_after_initial_attempt_and_three_restarts(self):
        self.infos = [vm(False, False, None), vm()]
        self.boot = '0'
        with self.assertRaises(TimeoutError):
            self.run_start(max_restarts=None)
        report = json.loads(self.report.read_text())
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['restart_count'], 3)
        self.assertEqual(len(report['attempts']), 4)
        self.assertTrue(all(attempt['status'] == 'timed_out' for attempt in report['attempts']))
        self.assertEqual(len(self.launches()), 1)
        self.assertEqual(len(self.restarts()), 3)
        self.assertEqual(self.clock, 20)

    def test_restart_reply_loss_is_observed_without_repeating_the_request(self):
        self.boot = '0'
        self.restart_lost = True

        def recover():
            self.infos = [vm(pid=2000)]
            self.boot = '1'

        self.on_restart = recover
        result = self.run_start(max_restarts=3)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['attempts'][1]['request_status'], 'unknown')
        self.assertEqual(len(self.restarts()), 1)

    def test_old_online_process_is_not_accepted_while_restart_is_pending(self):
        self.boot = '0'
        self.on_restart = lambda: setattr(self, 'boot', '1')
        with self.assertRaises(TimeoutError):
            self.run_start(max_restarts=1)
        report = json.loads(self.report.read_text())
        self.assertFalse(report['attempts'][1]['restart_observed'])
        self.assertNotIn('package_manager_ready', report)
        self.assertEqual(len(self.restarts()), 1)

    def test_observed_shutdown_allows_restarted_vm_even_without_pid(self):
        self.boot = '0'

        def recover():
            self.infos = [vm(False, False, None, pid=None), vm(pid=None)]
            self.boot = '1'

        self.on_restart = recover
        self.assertEqual(self.run_start(max_restarts=1)['status'], 'ready')
        self.assertEqual(len(self.restarts()), 1)

    def test_restart_limit_cannot_be_negative_noninteger_or_above_three(self):
        for budget in (-1, 4, 1.5, True):
            with self.subTest(max_restarts=budget), patch.object(launcher, 'command') as command:
                with self.assertRaises(ValueError):
                    launcher.start(self.folder, 5, 5, self.report, max_restarts=budget)
                command.assert_not_called()
                self.assertFalse(self.report.exists())

    def test_failed_adb_startup_never_continues_to_application_launch(self):
        arguments = ['start-emulator.py', '--vm-index', '5', '--mumu-dir', str(self.folder),
                     '--timeout', '7', '--max-restarts', '2', '--apps']
        with patch.object(sys, 'argv', arguments), patch.object(launcher, 'ROOT', self.folder), \
                patch.object(launcher, 'start', side_effect=TimeoutError) as start, \
                patch.object(launcher, 'start_apps') as apps, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(), 1)
        self.assertEqual(start.call_args.args[:3], (self.folder, 5, 7))
        self.assertEqual(start.call_args.kwargs, {'max_restarts': 2})
        apps.assert_not_called()


if __name__ == '__main__':
    unittest.main()

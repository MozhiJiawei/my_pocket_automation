"""A single emulator preparation never adds an automatic restart."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/device'))
spec = importlib.util.spec_from_file_location('start_emulator', ROOT / 'scripts/device/start-emulator.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def vm(running=True, android=True, port=16544, index='5', pid=1000):
    return dict(index=index, error_code=0, name='fixture', android_version='12.0',
                is_process_started=running, is_android_started=android, pid=pid, adb_port=port)


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
        self.control_lost = False
        self.adb_states = ['device']
        self.offline_until_disconnect = False
        self.device = Mock()
        self.device.status.return_value = 'f00'

    def command(self, args, timeout):
        self.calls.append(args)
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 10)
        if args[1] == 'version':
            return '{"version":"6.8.7.0"}'
        if args[1] == 'info':
            self.assertEqual(args[2:], ['--vmindex', '5'])
            return json.dumps(self.infos.pop(0) if len(self.infos) > 1 else self.infos[0])
        if args[1] == 'control':
            self.assertEqual(args[2:4], ['--vmindex', '5'])
            self.assertIn(args[4], ('launch', 'restart'))
            if self.control_lost:
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

    def run_start(self, timeout=5, force_restart=False):
        with patch.object(launcher, 'command', side_effect=self.command), \
                patch.object(launcher, 'Device', return_value=self.device), \
                patch.object(launcher.time, 'monotonic', side_effect=lambda: self.clock), \
                patch.object(launcher.time, 'sleep', side_effect=self.sleep), \
                contextlib.redirect_stdout(io.StringIO()):
            return launcher.start(self.folder, 5, timeout, self.report, force_restart=force_restart)

    def controls(self):
        return [args for args in self.calls if args[1] == 'control']

    def test_cold_start_launches_only_selected_vm_then_waits_for_boot(self):
        self.infos = [vm(False, False, None), vm(True, False, None), vm()]
        result = self.run_start()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['device'], '127.0.0.1:16544')
        self.assertEqual(result['elapsed_seconds'], 2)
        self.assertTrue(result['package_manager_ready'])
        self.assertEqual([args[-1] for args in self.controls()], ['launch'])
        self.device.authorize.assert_not_called()

    def test_running_vm_is_reused_with_dynamic_endpoint_and_no_control_request(self):
        result = self.run_start()
        self.assertEqual(result['launch_status'], 'reused')
        self.assertEqual(self.controls(), [])
        self.assertFalse(any(args[1] == 'devices' for args in self.calls))
        self.assertIn([str(self.folder / 'adb.exe'), 'connect', '127.0.0.1:16544'], self.calls)

    def test_wrong_or_unknown_vm_state_prevents_any_control_request(self):
        for value in (vm(index='6'), vm(running=None), vm(running=1)):
            with self.subTest(value=value):
                self.report.unlink(missing_ok=True)
                self.infos = [value]
                with self.assertRaises((ValueError, RuntimeError)):
                    self.run_start()
                self.assertEqual(self.controls(), [])
                self.assertEqual(json.loads(self.report.read_text())['status'], 'failed')

    def test_invalid_or_unbounded_deadlines_do_not_start_any_process(self):
        for seconds in (0, -1, float('nan'), float('inf')):
            with self.subTest(timeout=seconds), patch.object(launcher, 'command') as command:
                with self.assertRaises(ValueError):
                    launcher.start(self.folder, 5, seconds, self.report)
                command.assert_not_called()
                self.assertFalse(self.report.exists())

    def test_timeout_never_restarts_or_repeats_a_cold_launch(self):
        self.infos = [vm(False, False, None), vm()]
        self.boot = '0'
        with self.assertRaises(TimeoutError):
            self.run_start()
        record = json.loads(self.report.read_text())
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['boot_completed'], '0')
        self.assertEqual([args[-1] for args in self.controls()], ['launch'])
        self.assertEqual(self.clock, 5)

    def test_lost_launch_reply_is_observed_without_a_second_launch(self):
        self.infos = [vm(False, False, None), vm()]
        self.control_lost = True
        result = self.run_start()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['launch_status'], 'unknown')
        self.assertEqual(len(self.controls()), 1)

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
                self.assertEqual(self.controls(), [])

    def test_offline_adb_reconnects_only_selected_transport_without_vm_restart(self):
        self.offline_until_disconnect = True
        result = self.run_start(timeout=15)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['elapsed_seconds'], 10)
        self.assertEqual(result['connect_requests'], 2)
        self.assertEqual(self.controls(), [])
        self.assertIn([str(self.folder / 'adb.exe'), 'disconnect', '127.0.0.1:16544'], self.calls)
        self.assertFalse(any(args[1] == 'kill-server' for args in self.calls))

    def test_connect_acknowledgement_does_not_replace_device_state_probe(self):
        self.adb_states = ['offline', 'unauthorized', 'device']
        result = self.run_start()
        self.assertEqual(result['elapsed_seconds'], 4)
        self.assertEqual(result['adb_state'], 'device')
        self.assertEqual(len([args for args in self.calls if args[-1] == 'get-state']), 3)

    def test_explicit_restart_requires_idle_then_follows_new_pid_and_port(self):
        self.infos = [vm(), vm(pid=2000, port=16600)]
        result = self.run_start(force_restart=True)
        self.assertEqual(result['device'], '127.0.0.1:16600')
        self.assertEqual([args[-1] for args in self.controls()], ['restart'])
        self.assertEqual(result['touchsprite_status_before_restart'], 'f00')
        self.device.authorize.assert_called_once_with()
        self.device.status.assert_called_once_with()
        self.device.close.assert_called_once_with()

    def test_busy_recording_unknown_and_unreachable_lua_block_explicit_restart(self):
        for state in ('f01', 'f02', 'unrecognized', None, RuntimeError('private fixture')):
            with self.subTest(state=state):
                self.report.unlink(missing_ok=True)
                self.device.reset_mock()
                self.device.status.side_effect = state if isinstance(state, Exception) else None
                self.device.status.return_value = state
                with self.assertRaises(RuntimeError):
                    self.run_start(force_restart=True)
                self.assertEqual(self.controls(), [])
                self.assertNotIn('private fixture', self.report.read_text())

    def test_authorization_failure_blocks_explicit_restart(self):
        self.device.authorize.side_effect = RuntimeError('unreachable')
        with self.assertRaises(RuntimeError):
            self.run_start(force_restart=True)
        self.assertEqual(self.controls(), [])
        self.device.close.assert_called_once_with()

    def test_old_online_process_is_not_accepted_while_restart_is_pending(self):
        with self.assertRaises(TimeoutError):
            self.run_start(force_restart=True)
        record = json.loads(self.report.read_text())
        self.assertFalse(record['restart_observed'])
        self.assertNotIn('package_manager_ready', record)
        self.assertEqual([args[-1] for args in self.controls()], ['restart'])
        self.assertFalse(any(args[1] == 'connect' for args in self.calls))

    def test_observed_shutdown_allows_restarted_vm_with_same_pid(self):
        self.infos = [vm(), vm(android=False), vm(port=16600)]
        self.assertEqual(self.run_start(force_restart=True)['device'], '127.0.0.1:16600')
        self.assertEqual(self.clock, 2)
        self.assertEqual(len(self.controls()), 1)

    def test_lost_restart_reply_is_observed_without_resending(self):
        self.infos = [vm(), vm(pid=2000, port=16600)]
        self.control_lost = True
        result = self.run_start(force_restart=True)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['launch_status'], 'unknown')
        self.assertEqual(len(self.controls()), 1)

    def test_force_restart_on_stopped_vm_launches_once_without_idle_probe(self):
        self.infos = [vm(False, False, None), vm()]
        self.assertEqual(self.run_start(force_restart=True)['status'], 'ready')
        self.assertEqual([args[-1] for args in self.controls()], ['launch'])
        self.device.authorize.assert_not_called()


if __name__ == '__main__':
    unittest.main()

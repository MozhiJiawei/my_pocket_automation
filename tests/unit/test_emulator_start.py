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


def vm(running=True, android=True, port=16544, index='5'):
    result = dict(index=index, error_code=0, name='fixture', android_version='12.0',
                  is_process_started=running, is_android_started=android)
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
            self.assertEqual(args[2:], ['--vmindex', '5', 'launch'])
            if self.launch_lost:
                raise subprocess.TimeoutExpired(args, timeout)
            return '{}'
        if args[1] == 'connect':
            return 'connected'
        self.assertEqual(args[1:3], ['-s', '127.0.0.1:16544'])
        operation = args[3:]
        if operation == ['get-state']:
            return 'device'
        if operation == ['shell', 'getprop', 'sys.boot_completed']:
            return self.boot
        if operation == ['shell', 'getprop', 'ro.build.version.release']:
            return self.android
        self.assertEqual(operation, ['shell', 'pm', 'path', 'android'])
        return self.package

    def sleep(self, seconds):
        self.assertLessEqual(seconds, 2)
        self.clock += seconds

    def run_start(self, timeout=5):
        with patch.object(launcher, 'command', side_effect=self.command), \
                patch.object(launcher.time, 'monotonic', side_effect=lambda: self.clock), \
                patch.object(launcher.time, 'sleep', side_effect=self.sleep), contextlib.redirect_stdout(io.StringIO()):
            return launcher.start(self.folder, 5, timeout, self.report)

    def launches(self):
        return [args for args in self.calls if args[1] == 'control']

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


if __name__ == '__main__':
    unittest.main()

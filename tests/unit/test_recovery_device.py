"""Atomic device commands share a lock, unique evidence IDs and read-only probes."""
import contextlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/device'))
import dfx_device
from dfx_device import Device, allocate_run_id, instance_lock

spec = importlib.util.spec_from_file_location('atomic_emulator', ROOT / 'scripts/device/start-emulator.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def vm(port=16544, index='5', running=True):
    return dict(error_code=0, index=index, android_version='12.0', is_process_started=running,
                is_android_started=running, adb_port=port, pid=1000)


class DeviceCoordinationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.installation = self.folder / 'MuMu'

    def test_same_installation_and_vm_are_locked_across_both_commands(self):
        with instance_lock(self.folder, self.installation, 5):
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                with instance_lock(self.folder, self.installation / '..' / 'MuMu', 5):
                    self.fail('same target acquired twice')
            with instance_lock(self.folder, self.installation, 6):
                pass
            with instance_lock(self.folder, self.folder / 'OtherMuMu', 5):
                pass
        with instance_lock(self.folder, self.installation, 5):
            pass

    def test_exception_releases_lock_and_invalid_target_never_allocates_it(self):
        with self.assertRaisesRegex(RuntimeError, 'fixture'):
            with instance_lock(self.folder, self.installation, 5):
                raise RuntimeError('fixture')
        with instance_lock(self.folder, self.installation, 5):
            pass
        for installation, index in ((Path('relative'), 5), (self.installation, -1), (self.installation, True)):
            with self.subTest(installation=installation, index=index), self.assertRaises(ValueError):
                with instance_lock(self.folder, installation, index):
                    self.fail('invalid target acquired')

    def test_parallel_same_second_allocations_are_unique_strict_and_never_reuse_archives(self):
        stamp = datetime(2026, 11, 3, 12, 30, 0)
        existing = self.folder / 'debug-runs/20261103_123000'
        existing.mkdir(parents=True)
        with patch.object(dfx_device, 'datetime') as clock:
            clock.now.return_value = stamp
            with ThreadPoolExecutor(max_workers=8) as pool:
                ids = list(pool.map(lambda _: allocate_run_id(self.folder), range(16)))
            later = allocate_run_id(self.folder)
        self.assertEqual(len(set(ids + [later])), 17)
        self.assertNotIn(existing.name, ids)
        for run_id in ids + [later]:
            self.assertRegex(run_id, r'^\d{8}_\d{6}$')
            self.assertEqual(datetime.strptime(run_id, '%Y%m%d_%H%M%S').strftime('%Y%m%d_%H%M%S'), run_id)


class VMTargetValidationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_explicit_index_and_current_endpoint_must_match(self):
        with patch.object(launcher, 'command', return_value=json.dumps(vm())) as command:
            self.assertEqual(launcher.validate_vm(self.folder, 5)['device'], '127.0.0.1:16544')
            for endpoint in ('127.0.0.1:16600', 'emulator-5562', 'localhost:16544'):
                with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                    launcher.validate_vm(self.folder, 5, endpoint)
            self.assertTrue(all(call.args[0][1:] == ['info', '--vmindex', '5']
                                for call in command.call_args_list))

    def test_wrong_identity_and_invalid_ports_never_become_targets(self):
        for value in (vm(index='6'), vm(port=None), vm(port=True), vm(port=0), vm(port=65536)):
            with self.subTest(value=value), patch.object(launcher, 'command', return_value=json.dumps(value)):
                with self.assertRaises(ValueError):
                    launcher.validate_vm(self.folder, 5)

    def test_stopped_instance_can_be_identified_without_an_endpoint(self):
        with patch.object(launcher, 'command', return_value=json.dumps(vm(port=None, running=False))):
            self.assertEqual(launcher.validate_vm(self.folder, 5, require_endpoint=False)['index'], '5')
            with self.assertRaises(ValueError):
                launcher.validate_vm(self.folder, 5, '127.0.0.1:16544', require_endpoint=False)

    def test_relative_path_and_noninteger_instance_fail_before_any_command(self):
        with patch.object(launcher, 'command') as command:
            for folder, index in ((Path('relative'), 5), (self.folder, None), (self.folder, True), (self.folder, -1)):
                with self.subTest(folder=folder, index=index), self.assertRaises(ValueError):
                    launcher.validate_vm(folder, index)
            with self.assertRaises(ValueError):
                launcher.start(self.folder, 5, 5, Path('relative.json'), force_restart=True)
            command.assert_not_called()


class EnvironmentCommandTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.runner = launcher._load_runner()
        self.events = []
        self.lua_fail = False
        self.apps_fail = False
        self.evidence_fail = False
        self.prepared = ([{'alias': 'first'}], 10800)
        self.snapshot = dict(vm_index=5, mumu_dir=str(self.folder),
                             requested_scope=dict(mode='observe', step='observe', accounts=['first']),
                             source_sha256={'src/main.lua': 'source-fixture'},
                             device_tools_sha256={'scripts/device/start-emulator.py': 'tool-fixture'},
                             accounts_sha256='accounts-fixture', account_resources_sha256={})

    def assert_locked(self):
        with self.assertRaisesRegex(RuntimeError, 'busy'):
            with instance_lock(self.folder, self.folder, 5):
                self.fail('device stage was outside instance lock')

    def prepare(self, args):
        self.events.append('prepare')
        with instance_lock(self.folder, self.folder, 5):
            pass
        return self.prepared

    def environment(self, *args, **kwargs):
        self.assert_locked()
        self.events.append('environment')
        snapshot = args[3].parent / 'requested-scope.json'
        self.assertEqual(json.loads(snapshot.read_text()), self.snapshot)
        self.assertEqual(kwargs, {'force_restart': self.force})
        return dict(status='ready', vm_index=5, device='127.0.0.1:16600', elapsed_seconds=1)

    def apps(self, *args):
        self.assert_locked()
        self.events.append('touchsprite')
        self.assertEqual(args[2], '127.0.0.1:16600')
        if self.apps_fail:
            raise RuntimeError('fixture-only TouchSprite failure')

    def input_evidence(self, args, accounts, max_seconds):
        self.assert_locked()
        self.events.append('snapshot')
        self.assertEqual((accounts, max_seconds), self.prepared)
        if self.evidence_fail:
            raise RuntimeError('fixture-only changed inputs')
        return self.snapshot

    def execute(self, args, accounts, max_seconds):
        self.assert_locked()
        self.events.append('lua')
        self.seen_args = args
        self.assertEqual(accounts, self.prepared[0])
        self.assertEqual(max_seconds, 10800)
        self.assertIs(args.input_evidence, self.snapshot)
        args.lua_run_id = allocate_run_id(self.folder)
        args.lua_archive = str(self.folder / 'debug-runs' / args.lua_run_id)
        if self.lua_fail:
            raise RuntimeError('fixture-only Lua failure')
        return dict(run_id=args.lua_run_id, archive=args.lua_archive)

    def run_main(self, options=()):
        self.force = '--force-restart' in options
        with patch.object(launcher, 'ROOT', self.folder), \
                patch.object(launcher, '_load_runner', return_value=self.runner), \
                patch.object(self.runner, 'prepare', side_effect=self.prepare), \
                patch.object(self.runner, 'input_evidence', side_effect=self.input_evidence), \
                patch.object(self.runner, 'execute', side_effect=self.execute) as execute, \
                patch.object(launcher, 'start', side_effect=self.environment) as start, \
                patch.object(launcher, 'start_apps', side_effect=self.apps) as apps, \
                patch.object(launcher, 'validate_vm', return_value=vm()) as validate, \
                contextlib.redirect_stdout(io.StringIO()):
            result = launcher.main(['--vm-index', '5', '--mumu-dir', str(self.folder), *options])
        return result, start, apps, execute, validate

    def test_default_prepares_environment_then_executes_observe_once_under_same_lock(self):
        result, start, apps, execute, validate = self.run_main()
        self.assertEqual(result, 0)
        self.assertEqual(self.events, ['prepare', 'snapshot', 'environment', 'touchsprite', 'lua'])
        self.assertEqual((start.call_count, apps.call_count, execute.call_count), (1, 1, 1))
        self.assertEqual((self.seen_args.mode, self.seen_args.step), ('observe', 'observe'))
        self.assertEqual(self.seen_args.device, '127.0.0.1:16600')
        self.assertEqual(start.call_args.args[2], 180)
        validate.assert_not_called()
        self.assertNotEqual(self.seen_args.environment_run_id, self.seen_args.lua_run_id)
        report = Path(self.seen_args.environment_archive) / 'emulator-start.json'
        record = json.loads(report.read_text())
        self.assertEqual(record['lua_run_id'], self.seen_args.lua_run_id)
        self.assertEqual(record['lua_status'], 'completed')

    def test_explicit_scope_passes_unchanged_and_old_device_is_only_checked_before_start(self):
        result, _, _, execute, validate = self.run_main([
            '--device', '127.0.0.1:16544', '--force-restart', '--mode', 'run', '--step', 'daily',
            '--tasks', 'zhuagui,dungeon', '--select-accounts', 'first', 'second'])
        self.assertEqual(result, 0)
        validate.assert_called_once_with(self.folder, 5, '127.0.0.1:16544', require_endpoint=False)
        self.assertEqual((self.seen_args.mode, self.seen_args.step), ('run', 'daily'))
        self.assertEqual(self.seen_args.tasks, 'zhuagui,dungeon')
        self.assertEqual(self.seen_args.select_accounts, ['first', 'second'])
        execute.assert_called_once()

    def test_lua_failure_is_reported_with_its_allocated_link_without_retry(self):
        self.lua_fail = True
        result, start, apps, execute, _ = self.run_main()
        self.assertEqual(result, 1)
        self.assertEqual((start.call_count, apps.call_count, execute.call_count), (1, 1, 1))
        report = Path(self.seen_args.environment_archive) / 'emulator-start.json'
        record = json.loads(report.read_text())
        self.assertEqual(record['lua_status'], 'failed')
        self.assertEqual(record['lua_run_id'], self.seen_args.lua_run_id)
        self.assertNotIn('fixture-only', report.read_text())

    def test_invalid_scope_fails_before_any_device_stage_or_evidence_allocation(self):
        with patch.object(launcher, '_load_runner', return_value=self.runner), \
                patch.object(self.runner, 'prepare', side_effect=ValueError('invalid scope')), \
                patch.object(launcher, 'start') as start, \
                patch.object(launcher, 'instance_lock') as lock, \
                patch.object(launcher, 'allocate_run_id') as allocate:
            with self.assertRaises(ValueError):
                launcher.main(['--vm-index', '5'])
        start.assert_not_called()
        lock.assert_not_called()
        allocate.assert_not_called()

    def test_failed_environment_never_continues_to_touchsprite_or_lua(self):
        with patch.object(launcher, 'ROOT', self.folder), \
                patch.object(launcher, '_load_runner', return_value=self.runner), \
                patch.object(self.runner, 'prepare', return_value=self.prepared), \
                patch.object(self.runner, 'input_evidence', return_value=self.snapshot), \
                patch.object(launcher, 'start', side_effect=TimeoutError) as start, \
                patch.object(launcher, 'start_apps') as apps, \
                patch.object(self.runner, 'execute') as execute, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(['--vm-index', '5', '--mumu-dir', str(self.folder)]), 1)
        start.assert_called_once()
        apps.assert_not_called()
        execute.assert_not_called()
        snapshot = start.call_args.args[3].parent / 'requested-scope.json'
        self.assertEqual(json.loads(snapshot.read_text()), self.snapshot)

    def test_touchsprite_failure_preserves_requested_scope_and_input_hashes(self):
        self.apps_fail = True
        result, start, apps, execute, _ = self.run_main()
        self.assertEqual(result, 1)
        start.assert_called_once()
        apps.assert_called_once()
        execute.assert_not_called()
        snapshot = start.call_args.args[3].parent / 'requested-scope.json'
        self.assertEqual(json.loads(snapshot.read_text()), self.snapshot)

    def test_input_evidence_failure_prevents_all_device_calls(self):
        self.evidence_fail = True
        result, start, apps, execute, validate = self.run_main(['--device', '127.0.0.1:16544'])
        self.assertEqual(result, 1)
        self.assertEqual(self.events, ['prepare', 'snapshot'])
        start.assert_not_called()
        apps.assert_not_called()
        execute.assert_not_called()
        validate.assert_not_called()

    def test_removed_recovery_and_apps_options_are_rejected_by_parser(self):
        for option in ('--max-restarts', '--apps', '--recover'):
            with self.subTest(option=option), patch.object(launcher, '_load_runner', return_value=self.runner), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                launcher.main(['--vm-index', '5', option])


class DeviceTransportTest(unittest.TestCase):
    def test_loopback_status_uses_authenticated_read_only_endpoint(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append((self.path, self.headers.get('auth')))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'f00')

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        try:
            device = Device('fixture-only')
            device.port = str(server.server_address[1])
            device.auth = 'fixture-secret'
            device.auth_deadline = time.monotonic() + 10
            self.assertEqual(device.status(), 'f00')
            self.assertEqual(requests, [('/status', 'fixture-secret')])
            self.assertFalse(hasattr(device, 'stop_lua'))
        finally:
            server.shutdown()
            server.server_close()

    def test_transport_redacts_authorization_errors_and_blocks_external_ui_operations(self):
        device = Device('fixture-only')
        with patch.object(device.http, 'open', side_effect=OSError('private-token')):
            with self.assertRaises(RuntimeError) as caught:
                device.request('http://127.0.0.1:1/status', authenticated=True)
            self.assertNotIn('private-token', str(caught.exception))
        with patch.object(dfx_device, 'command') as command:
            for operation in (('input', 'tap', '1', '2'), ('am', 'start', 'game'), ('monkey', '-p', 'game')):
                with self.subTest(operation=operation), self.assertRaises(RuntimeError):
                    device.adb_call('shell', *operation)
            command.assert_not_called()


if __name__ == '__main__':
    unittest.main()

"""Prepare one existing MuMu instance, then execute the requested Lua scope once."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time

from dfx_device import Device, allocate_run_id, command, instance_lock

ROOT = Path(__file__).resolve().parents[2]
TOUCHSPRITE = 'com.touchsprite.android'


def _mumu_paths(mumu_dir, vm_index):
    if type(vm_index) is not int or vm_index < 0:
        raise ValueError('A nonnegative integer VM index is required')
    folder = Path(mumu_dir)
    if not folder.is_absolute():
        raise ValueError('An absolute MuMu installation path is required')
    return folder / 'MuMuManager.exe', folder / 'adb.exe'


def _verified_vm(value, vm_index, endpoint=None, require_endpoint=True):
    if not isinstance(value, dict) or value.get('error_code') != 0 or str(value.get('index')) != str(vm_index):
        raise ValueError('Requested VM was not found or its identity was not verified')
    vm = {key: value[key] for key in ('index', 'name', 'android_version', 'is_process_started',
                                     'is_android_started', 'adb_port', 'pid') if key in value}
    port = vm.get('adb_port')
    if port is not None:
        if isinstance(port, bool) or not re.fullmatch(r'[0-9]+', str(port)) or not 1 <= int(port) <= 65535:
            raise ValueError('Invalid VM ADB port')
        target = f'127.0.0.1:{int(port)}'
        if endpoint is not None and endpoint != target:
            raise ValueError('Selected VM and connected device do not match')
        vm['device'] = target
    elif require_endpoint or endpoint is not None:
        raise ValueError('Selected VM has no verifiable ADB endpoint')
    return vm


def validate_vm(mumu_dir, vm_index, endpoint=None, require_endpoint=True):
    """Resolve only the explicit MuMu index; never infer it from an ADB device."""
    if type(require_endpoint) is not bool:
        raise ValueError('require_endpoint must be boolean')
    manager, _ = _mumu_paths(mumu_dir, vm_index)
    value = json.loads(command([str(manager), 'info', '--vmindex', str(vm_index)], timeout=10))
    return _verified_vm(value, vm_index, endpoint, require_endpoint=require_endpoint)


def _write_report(report, record):
    pending = report.with_suffix('.json.pending')
    pending.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    pending.replace(report)


def _idle_for_restart(endpoint, adb):
    """A live VM may be restarted only after an authenticated idle response."""
    client = Device(endpoint, adb=str(adb))
    try:
        client.authorize()
        state = client.status()
        if state != 'f00':
            raise RuntimeError('TouchSprite is busy or unknown; VM restart was not requested')
        return state
    finally:
        client.close()


def start(mumu_dir, vm_index, timeout, report, force_restart=False):
    """Launch, reuse or explicitly restart one VM; never retry a control request."""
    manager, adb = _mumu_paths(mumu_dir, vm_index)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('A positive finite timeout is required')
    if type(force_restart) is not bool:
        raise ValueError('force_restart must be boolean')
    report = Path(report)
    if not report.is_absolute():
        raise ValueError('An absolute startup evidence path is required')
    if report.exists():
        raise ValueError('Startup evidence already exists')
    report.parent.mkdir(parents=True, exist_ok=True)
    source = Path(__file__)
    shutil.copyfile(source, report.parent / 'start-emulator-source.py')
    started = time.monotonic()
    deadline = started + timeout
    record = dict(status='starting', phase='preflight', vm_index=vm_index,
                  launch_status='not_requested', timeout_seconds=timeout,
                  force_restart=force_restart, connect_requests=0,
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())

    def persist():
        record['elapsed_seconds'] = round(time.monotonic() - started, 2)
        _write_report(report, record)

    def call(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Emulator startup deadline reached')
        return command([str(part) for part in args], timeout=min(10, remaining))

    def info():
        return _verified_vm(json.loads(call([manager, 'info', '--vmindex', vm_index])), vm_index,
                            require_endpoint=False)

    try:
        persist()
        if not manager.is_file() or not adb.is_file():
            raise FileNotFoundError('MuMuManager.exe and adb.exe are required in --mumu-dir')
        record['mumu_version'] = json.loads(call([manager, 'version']))['version']
        before = record['before'] = info()
        if type(before.get('is_process_started')) is not bool:
            raise RuntimeError('Selected VM process state is unknown; no control request sent')
        action = 'reuse'
        if not before['is_process_started']:
            action = 'launch'
        elif force_restart:
            record['phase'] = 'verify_idle_before_restart'
            persist()
            if not before.get('device'):
                raise RuntimeError('Selected VM endpoint is unknown; no restart request sent')
            record['touchsprite_status_before_restart'] = _idle_for_restart(before['device'], adb)
            action = 'restart'
        record['action'] = action
        if action != 'reuse':
            record.update(phase=action, launch_status='requested')
            persist()  # The single request may take effect even if its response is lost.
            print(f'[emulator] {action} VM {vm_index}', flush=True)
            try:
                call([manager, 'control', '--vmindex', vm_index, action])
                record['launch_status'] = 'returned'
            except (RuntimeError, subprocess.TimeoutExpired, TimeoutError) as exc:
                record.update(launch_status='unknown', request_error_type=type(exc).__name__)
        else:
            record['launch_status'] = 'reused'
        record['phase'] = 'waiting_android_adb'
        persist()
        print(f'[emulator] Waiting for VM {vm_index} Android/ADB', flush=True)
        endpoint, next_connect, connected = None, 0, False
        restart_observed = action != 'restart'
        while time.monotonic() < deadline:
            try:
                vm = record['after'] = info()
                if vm.get('is_process_started') is False or vm.get('is_android_started') is False:
                    restart_observed = True
                elif before.get('pid') and vm.get('pid') and before['pid'] != vm['pid']:
                    restart_observed = True
                record['restart_observed'] = restart_observed
                if (restart_observed and vm.get('is_process_started') is True
                        and vm.get('is_android_started') is True and vm.get('device')):
                    target = vm['device']
                    if target != endpoint:
                        endpoint, next_connect, connected = target, 0, False
                    record['device'] = endpoint
                    if not connected and time.monotonic() >= next_connect:
                        next_connect = time.monotonic() + 10
                        if record['connect_requests']:
                            try:
                                call([adb, 'disconnect', endpoint])
                            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                                record['disconnect_error_type'] = type(exc).__name__
                        record['connect_requests'] += 1
                        call([adb, 'connect', endpoint])
                    try:
                        state = call([adb, '-s', endpoint, 'get-state'])
                    except (RuntimeError, subprocess.TimeoutExpired):
                        connected = False
                        record['adb_state'] = 'unavailable'
                        raise
                    connected = state == 'device'
                    record['adb_state'] = state
                    if connected:
                        boot = call([adb, '-s', endpoint, 'shell', 'getprop', 'sys.boot_completed'])
                        record['boot_completed'] = boot
                        if boot == '1':
                            android = call([adb, '-s', endpoint, 'shell', 'getprop', 'ro.build.version.release'])
                            package = call([adb, '-s', endpoint, 'shell', 'pm', 'path', 'android'])
                            if android.split('.')[0] != str(vm.get('android_version', '')).split('.')[0]:
                                raise ValueError('Connected Android version differs from selected VM')
                            if package.startswith('package:'):
                                record.update(status='ready', phase='ready', android_version=android,
                                              package_manager_ready=True)
                                persist()
                                return record
            except (RuntimeError, subprocess.TimeoutExpired, TimeoutError, ValueError) as exc:
                record['last_wait_error_type'] = type(exc).__name__
            persist()
            time.sleep(max(0, min(2, deadline - time.monotonic())))
        raise TimeoutError('Selected VM did not reach Android/ADB readiness; no automatic restart requested')
    except Exception as exc:
        record.update(status='failed', error_type=type(exc).__name__)
        persist()
        raise


def _touchsprite_running(client):
    """Process existence alone does not establish application initialization."""
    rows = client.adb_call('shell', 'ps', '-A').splitlines()
    header = rows[0].split() if rows else []
    name_columns = [column for column in ('NAME', 'CMD', 'COMMAND', 'CMDLINE', 'ARGS') if column in header]
    if len(rows) < 2 or 'PID' not in header or not name_columns:
        raise RuntimeError('TouchSprite process state is unknown; no launch request sent')
    name_index, pid_index = header.index(name_columns[0]), header.index('PID')
    processes = []
    for row in rows[1:]:
        fields = row.split()
        if len(fields) <= max(name_index, pid_index) or not fields[pid_index].isdigit():
            raise RuntimeError('TouchSprite process state is unknown; no launch request sent')
        processes.append(fields[name_index])
    return any(name == TOUCHSPRITE or name.startswith(TOUCHSPRITE + ':') for name in processes)


def _touchsprite_uninitialized(client, record):
    """Recognize the boot receiver process without an activity, service or API.

    Opening that app once initializes it; never stop/relaunch an existing
    activity or service merely because its HTTP endpoint is unavailable.
    Keep raw dumps out of the report, since they can contain private extras.
    """
    activities = client.adb_call('shell', 'dumpsys', 'activity', 'activities')
    services = client.adb_call('shell', 'dumpsys', 'activity', 'services', TOUCHSPRITE)
    listeners = client.adb_call('shell', 'ss', '-ltn')
    rows = listeners.splitlines()
    if (not activities.startswith('ACTIVITY MANAGER ACTIVITIES')
            or not services.startswith('ACTIVITY MANAGER SERVICES')
            or not rows or rows[0].split()[:1] != ['State']
            or any(len(row.split()) < 5 or row.split()[0] != 'LISTEN' for row in rows[1:])):
        raise RuntimeError('TouchSprite initialization state is unknown; no launch request sent')
    record['touchsprite_activity_present'] = TOUCHSPRITE in activities
    record['touchsprite_service_present'] = TOUCHSPRITE in services
    record['touchsprite_api_listening'] = any(row.split()[3].rsplit(':', 1)[-1] == '50005'
                                             for row in rows[1:])
    return not any(record[key] for key in ('touchsprite_activity_present',
                                          'touchsprite_service_present', 'touchsprite_api_listening'))


def start_apps(mumu_dir, vm_index, endpoint, report):
    """Prepare only TouchSprite; the caller runs the requested Lua scope once."""
    report = Path(report)
    manager, adb = _mumu_paths(mumu_dir, vm_index)
    if not report.is_absolute():
        raise ValueError('An absolute application evidence path is required')
    if report.exists():
        raise ValueError('Application startup evidence already exists')
    report.parent.mkdir(parents=True, exist_ok=True)
    record = dict(status='starting', vm_index=vm_index, device=endpoint, phase='preflight',
                  touchsprite_launch='not_requested', touchsprite_ready=False,
                  touchsprite_api_checks=0, http_proxy_policy='direct',
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    started = time.monotonic()
    deadline = started + 90
    client = Device(endpoint, adb=str(adb))

    def persist():
        record['elapsed_seconds'] = round(time.monotonic() - started, 2)
        _write_report(report, record)

    def api_ready():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        record['touchsprite_api_checks'] += 1
        try:
            with client.http.open(f'http://127.0.0.1:{client.port}/deviceid', timeout=min(2, remaining)) as response:
                valid = bool(re.fullmatch(r'[\w-]{16,64}', response.read(256).decode().strip()))
                record['touchsprite_api_probe'] = 'ready' if valid else 'invalid_identity'
                return valid
        except Exception as exc:
            record['touchsprite_api_probe'] = type(exc).__name__
            return False

    try:
        persist()
        vm = validate_vm(mumu_dir, vm_index, endpoint)
        if vm.get('is_android_started') is not True or vm.get('is_process_started') is not True:
            raise ValueError('Selected VM and connected device do not match')
        if not client.adb_call('shell', 'pm', 'path', TOUCHSPRITE).startswith('package:'):
            raise RuntimeError('TouchSprite is not installed')
        client.port = client.adb_call('forward', 'tcp:0', 'tcp:50005')
        if not client.port.isdigit():
            raise RuntimeError('Invalid forwarded port')
        if not api_ready():
            record['phase'] = 'inspect_touchsprite_initialization'
            persist()
            record['touchsprite_process_running'] = _touchsprite_running(client)
            initialize = (not record['touchsprite_process_running']
                          or _touchsprite_uninitialized(client, record))
            # The boot receiver can create the process before MainActivity and
            # its HTTP service. Recheck the API before the one initialization
            # request, in case startup completed during the read-only probes.
            if initialize and not api_ready():
                record['touchsprite_launch_reason'] = ('process_absent' if not record['touchsprite_process_running']
                                                       else 'process_without_activity_service_or_api')
                record.update(phase='launch_touchsprite', touchsprite_launch='requested')
                persist()
                print('[apps] Starting TouchSprite', flush=True)
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('TouchSprite readiness deadline reached')
                    reply = json.loads(command([str(manager), 'control', '--vmindex', str(vm_index),
                                                'app', 'launch', '--package', TOUCHSPRITE],
                                               timeout=min(15, remaining)))
                    if reply.get('errcode') != 0:
                        raise RuntimeError('TouchSprite launch rejected')
                    record['touchsprite_launch'] = 'returned'
                except (RuntimeError, subprocess.TimeoutExpired, TimeoutError, json.JSONDecodeError) as exc:
                    record.update(touchsprite_launch='unknown', launch_error_type=type(exc).__name__)
            else:
                record['touchsprite_launch'] = 'reused'
            record['phase'] = 'wait_touchsprite'
            persist()
            while not api_ready():
                if time.monotonic() >= deadline:
                    raise TimeoutError('TouchSprite API did not become available; no repeated launch or restart requested')
                persist()
                time.sleep(max(0, min(1, deadline - time.monotonic())))
        else:
            record['touchsprite_launch'] = 'reused'
        record['phase'] = 'authorize_idle'
        record['touchsprite_api_ready_seconds'] = round(time.monotonic() - started, 2)
        persist()
        authorization_started = time.monotonic()
        try:
            client.authorize()
        finally:
            record['authorization_seconds'] = round(time.monotonic() - authorization_started, 2)
        record['touchsprite_status'] = client.status()
        if record['touchsprite_status'] != 'f00':
            raise RuntimeError('TouchSprite is busy or unknown; no Lua files published')
        record.update(status='ready', phase='ready', touchsprite_ready=True)
    except Exception as exc:
        record.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        try:
            client.close()
        finally:
            persist()
    return record


def _load_runner():
    spec = importlib.util.spec_from_file_location('environment_daily_runner', Path(__file__).with_name('run-daily.py'))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def main(argv=None):
    runner = _load_runner()
    parser = runner.create_parser()
    parser.description = __doc__
    parser.add_argument('--timeout', type=float, default=180, help='Android/ADB readiness deadline in seconds')
    parser.add_argument('--force-restart', action='store_true', help='Explicitly restart a running VM once after confirming TouchSprite idle')
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('Timeout must be finite and positive')
    accounts, max_seconds = runner.prepare(args)
    report = None
    try:
        with instance_lock(ROOT, args.mumu_dir, args.vm_index):
            run_id = allocate_run_id(ROOT)
            archive = ROOT / 'debug-runs' / run_id
            archive.mkdir(parents=True)
            report = archive / 'emulator-start.json'
            args.input_evidence = runner.input_evidence(args, accounts, max_seconds)
            _write_report(archive / 'requested-scope.json', args.input_evidence)
            if args.device is not None:
                validate_vm(args.mumu_dir, args.vm_index, args.device, require_endpoint=False)
            result = start(args.mumu_dir, args.vm_index, args.timeout, report,
                           force_restart=args.force_restart)
            start_apps(args.mumu_dir, args.vm_index, result['device'], archive / 'apps-start.json')
            args.device = result['device']
            args.environment_run_id = run_id
            args.environment_archive = str(archive)
            result.update(environment_run_id=run_id, lua_status='starting')
            _write_report(report, result)
            try:
                lua = runner.execute(args, accounts, max_seconds)
                result.update(lua_status='completed', lua_run_id=lua.get('run_id'), lua_archive=lua.get('archive'))
            except Exception as exc:
                result.update(lua_status='failed', lua_error_type=type(exc).__name__)
                raise
            finally:
                for field in ('lua_run_id', 'lua_archive'):
                    if getattr(args, field, None) is not None:
                        result[field] = str(getattr(args, field))
                _write_report(report, result)
        print(json.dumps(dict(status='completed', vm_index=args.vm_index, device=args.device,
                              environment_run_id=run_id, lua_run_id=result['lua_run_id'])), flush=True)
        print(f'[emulator] Evidence: {report}', flush=True)
        return 0
    except Exception as exc:
        print(json.dumps(dict(status='failed', error_type=type(exc).__name__,
                              report=str(report) if report else None)), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

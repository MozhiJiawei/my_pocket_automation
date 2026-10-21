"""Start one existing MuMu VM with bounded ADB recovery and optional Lua startup."""
import argparse
from datetime import datetime
import hashlib
import json
import importlib.util
import math
from pathlib import Path
import shutil
import subprocess
import time
from types import SimpleNamespace
import re

from dfx_device import ADB, Device, command

ROOT = Path(__file__).resolve().parents[2]


def start(mumu_dir, vm_index, timeout, report, max_restarts=3):
    if vm_index < 0 or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('A nonnegative VM index and positive timeout are required')
    if type(max_restarts) is not int or not 0 <= max_restarts <= 3:
        raise ValueError('At most three emulator restarts are allowed')
    report = Path(report)
    if report.exists():
        raise ValueError('Startup evidence already exists')
    report.parent.mkdir(parents=True, exist_ok=True)
    source = Path(__file__)
    shutil.copyfile(source, report.parent / 'start-emulator-source.py')
    started = time.monotonic()
    deadline = started + timeout
    manager = Path(mumu_dir) / 'MuMuManager.exe'
    adb = Path(mumu_dir) / 'adb.exe'
    record = dict(status='starting', phase='preflight', vm_index=vm_index, launch_status='not_requested',
                  timeout_seconds=timeout, max_restarts=max_restarts, restart_count=0, attempts=[],
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())

    def persist():
        record['elapsed_seconds'] = round(time.monotonic() - started, 2)
        pending = report.with_suffix('.json.pending')
        pending.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        pending.replace(report)

    def call(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Emulator startup deadline reached')
        return command([str(part) for part in args], timeout=min(10, remaining))

    def info():
        vm = json.loads(call([manager, 'info', '--vmindex', vm_index]))
        if vm.get('error_code') != 0 or str(vm.get('index')) != str(vm_index):
            raise ValueError('Requested VM was not found or its identity was not verified')
        return {key: vm[key] for key in ('index', 'name', 'android_version', 'is_process_started',
                                        'is_android_started', 'adb_port', 'pid') if key in vm}

    try:
        persist()
        if not manager.is_file() or not adb.is_file():
            raise FileNotFoundError('MuMuManager.exe and adb.exe are required in --mumu-dir')
        record['mumu_version'] = json.loads(call([manager, 'version']))['version']
        record['before'] = info()
        for restart in range(max_restarts + 1):
            attempt_started = time.monotonic() if restart else started
            deadline = attempt_started + timeout
            before = info() if restart else record['before']
            attempt = dict(number=restart + 1, before=before, status='starting', connect_requests=0)
            record['attempts'].append(attempt)
            for key in ('device', 'boot_completed', 'adb_state', 'package_manager_ready', 'android_version'):
                record.pop(key, None)
            action = None
            if restart:
                action = 'restart'
            elif not before.get('is_process_started'):
                action = 'launch'
            record['restart_count'] = restart
            if action:
                record.update(phase='restarting' if restart else 'launching', launch_status='requested')
                attempt.update(action=action, request_status='requested')
                persist()  # One request per timeout window, even when its reply is lost.
                print(f'[emulator] {action} VM {vm_index}; restart {restart}/{max_restarts}', flush=True)
                try:
                    call([manager, 'control', '--vmindex', vm_index, action])
                    record['launch_status'] = attempt['request_status'] = 'returned'
                except (RuntimeError, subprocess.TimeoutExpired, TimeoutError) as exc:
                    record['launch_status'] = attempt['request_status'] = 'unknown'
                    attempt['request_error_type'] = type(exc).__name__
            else:
                record['launch_status'] = 'reused'
                attempt.update(action='reuse', request_status='not_requested')
            record['phase'] = 'waiting_android_adb'
            persist()
            print(f'[emulator] Waiting for VM {vm_index} Android/ADB (attempt {restart + 1})', flush=True)
            endpoint, next_connect, connected = None, 0, False
            restart_observed = restart == 0
            while time.monotonic() < deadline:
                try:
                    vm = info()
                    record['after'] = attempt['after'] = vm
                    # A restart request can return while the old VM is still online.
                    # Wait for shutdown or a new process before trusting its ADB.
                    if not vm.get('is_process_started') or not vm.get('is_android_started'):
                        restart_observed = True
                    elif before.get('pid') and vm.get('pid') and before['pid'] != vm['pid']:
                        restart_observed = True
                    attempt['restart_observed'] = restart_observed
                    port = vm.get('adb_port')
                    if restart_observed and vm.get('is_process_started') and vm.get('is_android_started') and port:
                        port = int(port)
                        if not 1 <= port <= 65535:
                            raise ValueError('Invalid VM ADB port')
                        target = f'127.0.0.1:{port}'
                        if target != endpoint:
                            endpoint, next_connect, connected = target, 0, False
                        record['device'] = attempt['device'] = endpoint
                        if not connected and time.monotonic() >= next_connect:
                            next_connect = time.monotonic() + 10
                            if attempt['connect_requests']:
                                # Reset only this transport; never kill the shared ADB server.
                                try:
                                    call([adb, 'disconnect', endpoint])
                                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                                    attempt['disconnect_error_type'] = type(exc).__name__
                            attempt['connect_requests'] += 1
                            call([adb, 'connect', endpoint])
                        try:
                            state = call([adb, '-s', endpoint, 'get-state'])
                        except (RuntimeError, subprocess.TimeoutExpired):
                            connected = False
                            record['adb_state'] = attempt['adb_state'] = 'unavailable'
                            raise
                        connected = state == 'device'
                        record['adb_state'] = attempt['adb_state'] = state
                        if connected:
                            boot = call([adb, '-s', endpoint, 'shell', 'getprop', 'sys.boot_completed'])
                            record['boot_completed'] = attempt['boot_completed'] = boot
                            if boot == '1':
                                android = call([adb, '-s', endpoint, 'shell', 'getprop', 'ro.build.version.release'])
                                package = call([adb, '-s', endpoint, 'shell', 'pm', 'path', 'android'])
                                if android.split('.')[0] != vm['android_version'].split('.')[0]:
                                    raise ValueError('Connected Android version differs from selected VM')
                                if package.startswith('package:'):
                                    attempt.update(status='ready', elapsed_seconds=round(time.monotonic() - attempt_started, 2))
                                    record.update(status='ready', phase='ready', android_version=android,
                                                  package_manager_ready=True)
                                    persist()
                                    return record
                except (RuntimeError, subprocess.TimeoutExpired, TimeoutError, ValueError) as exc:
                    record['last_wait_error_type'] = attempt['last_wait_error_type'] = type(exc).__name__
                persist()
                time.sleep(max(0, min(2, deadline - time.monotonic())))
            attempt.update(status='timed_out', elapsed_seconds=round(time.monotonic() - attempt_started, 2))
            persist()
        raise TimeoutError(f'Selected VM did not reach Android/ADB readiness after {max_restarts} restart(s)')
    except Exception as exc:
        record.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        persist()
        raise


def start_apps(mumu_dir, vm_index, endpoint, report):
    """Bootstrap TouchSprite infrastructure; game operations remain in Lua."""
    report=Path(report)
    if report.exists():
        raise ValueError('Application startup evidence already exists')
    record=dict(status='starting',vm_index=vm_index,device=endpoint,phase='preflight',
                touchsprite_launch='not_requested',source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    started=time.monotonic()
    client=Device(endpoint,adb=str(Path(mumu_dir)/'adb.exe'))

    def persist():
        record['elapsed_seconds']=round(time.monotonic()-started,2)
        pending=report.with_suffix('.json.pending')
        pending.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        pending.replace(report)

    def api_ready():
        try:
            with client.http.open(f'http://127.0.0.1:{client.port}/deviceid',timeout=2) as response:
                return bool(re.fullmatch(r'[\w-]{16,64}',response.read(256).decode().strip()))
        except Exception:
            return False

    try:
        persist()
        manager=str(Path(mumu_dir)/'MuMuManager.exe')
        vm=json.loads(command([manager,'info','--vmindex',str(vm_index)],timeout=10))
        if (vm.get('error_code')!=0 or str(vm.get('index'))!=str(vm_index)
                or not vm.get('is_android_started') or not vm.get('is_process_started')
                or endpoint!=f"127.0.0.1:{vm.get('adb_port')}"):
            raise ValueError('Selected VM and connected device do not match')
        for package in ('com.touchsprite.android','com.netease.mhxyhtb'):
            if not client.adb_call('shell','pm','path',package).startswith('package:'):
                raise RuntimeError('Required application is not installed')
        client.port=client.adb_call('forward','tcp:0','tcp:50005')
        if not client.port.isdigit():
            raise RuntimeError('Invalid forwarded port')
        if not api_ready():
            record.update(phase='launch_touchsprite',touchsprite_launch='requested')
            persist()
            print('[apps] Starting TouchSprite',flush=True)
            try:
                reply=json.loads(command([manager,'control','--vmindex',str(vm_index),
                                          'app','launch','--package','com.touchsprite.android'],timeout=15))
                if reply.get('errcode')!=0:
                    raise RuntimeError('TouchSprite launch rejected')
                record['touchsprite_launch']='returned'
            except (RuntimeError,subprocess.TimeoutExpired,json.JSONDecodeError) as exc:
                record.update(touchsprite_launch='unknown',launch_error_type=type(exc).__name__)
            record['phase']='wait_touchsprite'
            deadline=time.monotonic()+90
            while not api_ready():
                if time.monotonic()>=deadline:
                    raise TimeoutError('TouchSprite API did not become available; launch was not repeated')
                time.sleep(1)
        else:
            record['touchsprite_launch']='reused'
        record['phase']='authorize_idle'
        client.authorize()
        record['touchsprite_status']=client.status()
        if record['touchsprite_status']!='f00':
            raise RuntimeError('TouchSprite is busy; no Lua files published')
        client.close()
        client=None
        record['phase']='lua_game_start'
        # The existing collector uses a timestamp run ID and its own archive folder.
        for _ in range(20):
            run_id=datetime.now().strftime('%Y%m%d_%H%M%S')
            archive=ROOT/'debug-runs'/run_id
            if not archive.exists():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError('No unused startup run ID available')
        record.update(lua_run_id=run_id,lua_archive=str(archive))
        persist()
        spec=importlib.util.spec_from_file_location('application_daily_runner',Path(__file__).with_name('run-daily.py'))
        runner=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        print('[apps] Starting game with Lua; waiting for a verified entry',flush=True)
        args=SimpleNamespace(device=endpoint,adb=str(Path(mumu_dir)/'adb.exe'),
                             mode='run',step='launch-game',task='dungeon',dungeon='wuji')
        runner.run_once(args,[],150,run_id,archive)
        record.update(status='ready',phase='ready',game_entry_verified=True)
    except Exception as exc:
        record.update(status='failed',error_type=type(exc).__name__) # Never persist authorization-bearing exceptions.
        raise
    finally:
        try:
            if client:
                client.close()
        finally:
            persist()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-index', type=int, required=True, help='Existing MuMu VM index; never creates a VM')
    parser.add_argument('--mumu-dir', type=Path, default=Path(ADB).parent)
    parser.add_argument('--timeout', type=float, default=180, help='Android/ADB deadline per attempt in seconds')
    parser.add_argument('--max-restarts', type=int, choices=range(4), default=3,
                        help='Restart the selected VM after timeout, at most 3 times (default: 3)')
    parser.add_argument('--apps',action='store_true',help='Also start TouchSprite and launch/verify the game through Lua')
    args = parser.parse_args()
    if args.vm_index < 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('VM index must be nonnegative and timeout must be positive')
    archive = ROOT / 'debug-runs' / datetime.now().strftime('%Y%m%d_%H%M%S')
    archive.mkdir(parents=True)  # Refuse to overwrite a previous run.
    report = archive / 'emulator-start.json'
    try:
        result = start(args.mumu_dir, args.vm_index, args.timeout, report, max_restarts=args.max_restarts)
        if args.apps:
            report=archive/'apps-start.json'
            apps=start_apps(args.mumu_dir,args.vm_index,result['device'],report)
            result['applications_ready']=apps['game_entry_verified']
        print(json.dumps({key: result[key] for key in ('status', 'vm_index', 'device', 'elapsed_seconds')}))
        if args.apps:
            print(json.dumps(dict(applications_ready=True,lua_run_id=apps['lua_run_id'])))
    except Exception as exc:
        print(json.dumps(dict(status='failed', error_type=type(exc).__name__, report=str(report))))
        return 1
    print(f'[emulator] Evidence: {report}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

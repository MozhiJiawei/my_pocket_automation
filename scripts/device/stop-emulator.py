"""Stop one MuMu instance and verify its underlying VM process has exited."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

from dfx_device import allocate_run_id, command, instance_lock

ROOT = Path(__file__).resolve().parents[2]


def matches_vm(process, index, version):
    """Require an exact engine name and exact MuMu instance comment."""
    return (process.get('Name', '').lower() == 'mumuvmmheadless.exe'
            and re.search(r'(?:^|\s)--comment\s+"?MuMuPlayer-'
                          + re.escape(version) + '-' + str(index)
                          + r'"?(?=\s|$)', process.get('CommandLine') or '') is not None)


def processes():
    raw = command(['powershell', '-NoProfile', '-Command',
                   "ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | "
                   "Where-Object { $_.Name -eq 'MuMuVMMHeadless.exe' } | "
                   "Select-Object Name,ProcessId,CommandLine,@{Name='CreationDate';"
                   "Expression={$_.CreationDate.Ticks.ToString()}})"], timeout=15)
    return json.loads(raw)


def stop(folder, index):
    manager = folder / 'MuMuManager.exe'
    report = ROOT / 'debug-runs' / allocate_run_id(ROOT) / 'emulator-stop.json'
    report.parent.mkdir(parents=True)
    record = dict(vm_index=index, mumu_dir=str(folder), status='failed', killed=[])
    try:
        before = json.loads(command([str(manager), 'info', '-v', str(index)], timeout=10))
        if before.get('error_code') != 0 or str(before.get('index')) != str(index):
            raise RuntimeError('Instance identity unavailable')
        version = before['android_version']
        record['before'] = before
        record['shutdown_reply'] = command([str(manager), 'control', '-v', str(index), 'shutdown'], timeout=15)
        # Management state alone is insufficient: stale headless processes survive it.
        for attempt in range(10):
            remaining = [p for p in processes() if matches_vm(p, index, version)]
            if not remaining:
                break
            if attempt >= 2:
                for process in remaining:
                    pid = int(process['ProcessId'])
                    # Revalidate identity and creation time inside the terminating command.
                    creation = str(process['CreationDate']).replace("'", "''")
                    script = (f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; "
                              f"if ($p -and $p.CreationDate.Ticks.ToString() -eq '{creation}' "
                              "-and $p.Name -eq 'MuMuVMMHeadless.exe') { "
                              f"Stop-Process -Id {pid} -Force -ErrorAction Stop }}")
                    command(['powershell', '-NoProfile', '-Command', script], timeout=10)
                    record['killed'].append(pid)
            time.sleep(1)
        remaining = [p for p in processes() if matches_vm(p, index, version)]
        after = json.loads(command([str(manager), 'info', '-v', str(index)], timeout=10))
        record.update(after=after, remaining=remaining)
        if remaining or after.get('is_process_started') is not False or after.get('is_android_started') is not False:
            raise RuntimeError('Instance shutdown verification failed')
        record['main_close_reply'] = command([str(manager), 'main', 'close'], timeout=15)
        record['status'] = 'stopped'
    except Exception as exc:
        record['error'] = str(exc)
        raise
    finally:
        report.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        print(report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-index', type=int, required=True)
    parser.add_argument('--mumu-dir', type=Path, default=Path('D:/Program Files/Netease/MuMu/nx_main'))
    args = parser.parse_args()
    if args.vm_index < 0 or not args.mumu_dir.is_absolute():
        parser.error('Require nonnegative instance index and absolute installation directory')
    with instance_lock(ROOT, args.mumu_dir, args.vm_index):
        stop(args.mumu_dir, args.vm_index)

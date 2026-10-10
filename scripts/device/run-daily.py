"""Build, publish, run and collect a bounded TouchSprite daily/debug invocation."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import re

from build import ROOT, build
from dfx_device import Device, command


class WaitExpired(RuntimeError):
    pass


def runtime_result(text, mode, step, task='dungeon'):
    """Interpret device evidence independently of transport/host exit status."""
    tasks = []
    account = None
    summary = {}
    for line in text.splitlines():
        account_match = re.search(r'\[account\] ([A-Za-z0-9_-]+)$', line)
        if account_match:
            account = account_match[1]
        match = re.search(r'\[task_result\] (\w+) status=(\w+) reason=(.*)$', line)
        if match:
            tasks.append(dict(account=account, task=match[1], status=match[2], reason=match[3]))
        if '[summary] ' in line:
            summary = dict(re.findall(r'(\w+)=([^\s]+)', line.split('[summary] ', 1)[1]))
    script = 'failed' if '[failed]' in text or '[finished] script_failed' in text else (
        'succeeded' if '[finished] script_exited_normally' in text else 'unknown')
    business, reason = 'unknown', 'runtime_evidence_missing'
    if script == 'failed':
        business, reason = 'failed', 'device_script_failed'
    elif script == 'succeeded':
        problem = next((item for item in tasks if item['status'] in ('failed', 'blocked', 'paused')), None)
        if problem:
            business, reason = problem['status'], problem['reason']
        elif summary.get('reason'):
            business, reason = 'blocked', summary['reason']
        elif mode == 'observe' and '[' + task + '_observe]' in text:
            business, reason = 'observed', 'observation_only'
        elif summary and tasks:
            if any(item['status'] == 'running' for item in tasks):
                business, reason = 'running', 'start_or_entry_verified'
            elif any(item['status'] == 'not_implemented' for item in tasks):
                business, reason = 'incomplete', 'tasks_not_implemented'
            else:
                business, reason = 'done', 'task_results_verified'
    pause_reasons = {'observe': 'observation_only', 'advance': 'battle_completed',
                     'browse': 'carousel_observation_only', 'select': 'card_selection_only',
                     'switch': 'switched_without_claiming_reward', 'back': 'returned_without_claiming_reward'}
    expected_pause = mode == 'run' and pause_reasons.get(step) == reason
    if task=='zhuagui' and step=='advance' and reason=='one_task_completed':
        expected_pause=mode=='run'
    if task=='zhuagui' and step=='browse' and reason=='find_catalog_observation_only':
        expected_pause=mode=='run'
    acceptable = script == 'succeeded' and (
        business in ('observed', 'incomplete', 'done', 'running') or
        (business == 'paused' and expected_pause))
    if mode == 'run' and step in ('daily', 'complete', 'finish', 'start', 'enter'):
        expected = 'running' if step in ('start', 'enter') else 'done'
        dungeons = [item for item in tasks if item['task'] == task]
        acceptable = acceptable and bool(dungeons) and all(item['status'] == expected for item in dungeons)
        if step == 'daily':
            acceptable = acceptable and summary.get('dungeon_done') == 'true'
    return {'script_status': script, 'business_status': business, 'termination_reason': reason,
            'tasks': tasks, 'device_summary': summary, 'daily_complete': False,
            'expectation_met': acceptable}


def run_once(args, accounts, max_seconds, run_id, archive):
    """A single attempt; never retry a launch, even when its response is lost."""
    archive.mkdir(parents=True)  # A collision must not overwrite previous evidence.
    record = {'run_id': run_id, 'mode': args.mode, 'step': args.step,
              'task': getattr(args, 'task', 'dungeon'),
              'reward_claim_allowed': False, 'daily_complete': False,
              'host_status': 'running', 'phase': 'build', 'launch_status': 'not_attempted',
              'last_device_status': None, 'may_still_be_running': False,
              'collection_status': 'not_attempted', 'script_status': 'unknown',
              'business_status': 'unknown', 'termination_reason': 'not_finished', 'tasks': []}
    result_path = archive / 'result.json'

    def persist():
        pending = result_path.with_suffix('.json.pending')
        pending.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        pending.replace(result_path)

    shell = shutil.which('pwsh') or 'powershell'
    device = Device(args.device)
    failure = None
    persist()

    def observe_status():
        state = device.status()
        record['last_device_status'] = state
        record['may_still_be_running'] = state != 'f00'
        return state

    def collect():
        record['collection_status'] = 'attempted'
        try:
            print(command([shell, '-NoProfile', '-File', str(ROOT / 'scripts/device/collect-debug.ps1'),
                           '-AdbPath', device.adb, '-Device', args.device, '-RunId', run_id], timeout=600), flush=True)
            record['collection_status'] = 'complete'
        except Exception as exc:
            record['collection_status'] = 'failed'
            record['collection_error_type'] = type(exc).__name__
            raise

    def read_evidence():
        log = archive / 'log' / f'daily_{run_id}.log'
        if log.exists():
            text = log.read_text(encoding='utf-8')
            record.update(runtime_result(text, args.mode, args.step, getattr(args, 'task', 'dungeon')))
            return text
        return ''

    try:
        bundle = build()
        shutil.copyfile(bundle, archive / 'script-source.lua')
        shutil.copyfile(ROOT / 'dist/manifest.json', archive / 'manifest.json')
        record['bundle_sha256'] = hashlib.sha256(bundle.read_bytes()).hexdigest()
        config = ROOT / 'dist/daily_config.lua'
        account_lua = ','.join('{alias="%s"}' % item['alias'] for item in accounts)
        config.write_text('return {run_id="%s", business_date="%s", mode="%s", step="%s", task="%s", dungeon="%s", zhuagui_budget=%d, browse_rounds=%d, allow_reward_claim=false, accounts={%s}}\n' %
                          (run_id, datetime.now().strftime('%Y%m%d'), args.mode, args.step, getattr(args, 'task', 'dungeon'), args.dungeon,
                           getattr(args, 'zhuagui_budget', 0), getattr(args,'browse_rounds',1), account_lua), encoding='utf-8')
        shutil.copyfile(config, archive / 'run-config.lua')
        record['phase'] = 'authorize'
        device.authorize()
        if observe_status() != 'f00':
            raise RuntimeError('Device is not idle; no files published')
        record['phase'] = 'publish_config'
        if args.step == 'daily' or (getattr(args, 'task', 'dungeon')=='zhuagui' and args.mode=='run' and args.step in ('enter','start','complete')):
            for item in accounts:
                alias = item['alias']
                for local_name, remote_kind in [('role.lua', 'identity'), ('selector.lua', 'selector')]:
                    identity = Path.home() / '.my_pocket_automation/accounts' / alias / local_name
                    if not identity.exists():
                        raise RuntimeError('Calibrate configured saved-role resources outside repository first')
                    remote = f'/storage/emulated/0/TouchSprite/res/daily_{remote_kind}_{alias}.lua'
                    device.adb_call('push', str(identity), remote + '.pending')
                    if device.adb_call('shell', 'sha256sum', remote + '.pending').split()[0] != hashlib.sha256(identity.read_bytes()).hexdigest():
                        raise RuntimeError('Saved-role resource hash mismatch')
                    device.adb_call('shell', 'mv', remote + '.pending', remote)
        remote_config = '/storage/emulated/0/TouchSprite/res/daily_config.lua'
        device.adb_call('push', str(config), remote_config + '.pending')
        if device.adb_call('shell', 'sha256sum', remote_config + '.pending').split()[0] != hashlib.sha256(config.read_bytes()).hexdigest():
            raise RuntimeError('Configuration hash mismatch')
        device.adb_call('shell', 'mv', remote_config + '.pending', remote_config)
        env = os.environ.copy()
        env['TOUCHSPRITE_AUTH'] = device.auth
        record.update(phase='start', launch_status='unknown', may_still_be_running=True)
        persist()  # The next call may launch successfully without returning a response.
        print(command([shell, '-NoProfile', '-File', str(ROOT / 'scripts/device/ts-cli.ps1'), 'run',
                       '-AdbPath', device.adb, '-Device', args.device, '-SourcePath', str(bundle)], env=env), flush=True)
        record.update(phase='wait', launch_status='accepted')
        deadline = time.monotonic() + max_seconds
        time.sleep(1)
        while observe_status() != 'f00':
            if time.monotonic() > deadline:
                raise WaitExpired('Bounded wait expired; script may still be running; do not redeploy')
            time.sleep(1)
        record['phase'] = 'collect'
        collect()
        record['phase'] = 'evaluate'
        print(read_evidence(), flush=True)
        if not record.get('expectation_met', False):
            raise RuntimeError('Runtime evidence does not meet this step; inspect result.json')
        record['host_status'] = 'completed'
    except Exception as exc:
        failure = exc
        record['host_status'] = (
            'launch_unknown' if record['phase'] == 'start' else
            'timed_out' if isinstance(exc, WaitExpired) else
            'business_unverified' if record['phase'] == 'evaluate' else
            'transport_failed' if record['phase'] in ('wait', 'collect', 'authorize') else 'failed')
        record['error_type'] = type(exc).__name__  # Never archive authorization-bearing exceptions.
        if record['launch_status'] != 'not_attempted':
            try:
                observe_status()
            except Exception as status_exc:
                record['status_error_type'] = type(status_exc).__name__
                record['may_still_be_running'] = True
            if record['collection_status'] != 'complete':
                try:
                    collect()
                except Exception:
                    pass  # Preserve the first failure, including subprocess timeouts.
            try:
                read_evidence()
            except Exception as evidence_exc:
                record['evidence_error_type'] = type(evidence_exc).__name__
    finally:
        try:
            device.close()
        except Exception as cleanup_exc:
            record['cleanup_error_type'] = type(cleanup_exc).__name__
            if failure is None:
                failure = cleanup_exc
                record['host_status'] = 'cleanup_failed'
        persist()
    if failure is not None:
        raise failure
    print(json.dumps({'run_id': run_id, 'archive': str(archive)}), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--device', required=True)
    p.add_argument('--mode', choices=['observe', 'run'], default='observe')
    p.add_argument('--max-seconds', type=int)
    p.add_argument('--dungeon', choices=['wuji', 'chechi'], default='wuji')
    p.add_argument('--task', choices=['dungeon', 'zhuagui'], default='dungeon')
    p.add_argument('--zhuagui-budget', type=int, default=0, help='Explicit daily energy cap for ZhuaGui; defaults to zero')
    p.add_argument('--browse-rounds',type=int,default=1,help='Observation-only retries of the existing find task (1–60)')
    p.add_argument('--accounts', type=Path, help='External JSON list of configured saved-role aliases')
    p.add_argument('--step', choices=['enter', 'start', 'advance', 'complete', 'finish', 'back', 'browse', 'select', 'switch', 'observe', 'daily'], default='observe')
    args = p.parse_args()
    if not 1<=args.browse_rounds<=60:
        raise ValueError('Browse rounds must be between 1 and 60')
    if args.browse_rounds!=1 and (args.task!='zhuagui' or args.step!='browse' or args.mode!='run'):
        raise ValueError('Multiple browse rounds require ZhuaGui observation-only browse mode')
    if not 0 <= args.zhuagui_budget <= 75 or args.zhuagui_budget % 3:
        raise ValueError('ZhuaGui energy cap must be a multiple of 3 between 0 and 75')
    accounts_path=args.accounts or Path.home() / '.my_pocket_automation/daily-accounts.json'
    if not accounts_path.exists() and not args.accounts:
        accounts_path.parent.mkdir(parents=True,exist_ok=True)
        accounts_path.write_text(json.dumps([{'alias':'current'}],indent=2),encoding='utf-8')
    if accounts_path.resolve().is_relative_to(ROOT):
        raise ValueError('Saved-role configuration belongs outside the repository')
    accounts=json.loads(accounts_path.read_text(encoding='utf-8'))
    if not isinstance(accounts,list) or not accounts:
        raise ValueError('Accounts must be a nonempty list')
    aliases=[item['alias'] for item in accounts]
    if len(set(aliases))!=len(aliases) or not all(re.fullmatch(r'[A-Za-z0-9_-]+',name) for name in aliases):
        raise ValueError('Aliases must be unique and contain only ASCII letters, digits, underscore or hyphen')
    if args.step!='daily' and aliases!=['current']:
        raise ValueError('Development steps are limited to the inspected current account')
    max_seconds = args.max_seconds or (3900 if args.step=='daily' else 2000 if args.step in ['advance','complete'] else 90)
    if args.task=='zhuagui' and args.step=='browse' and not args.max_seconds:
        max_seconds=max(max_seconds,args.browse_rounds*65+30)
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    archive = ROOT / 'debug-runs' / run_id
    if max_seconds <= 0:
        raise ValueError('Wait limit must be positive')
    run_once(args, accounts, max_seconds, run_id, archive)


if __name__ == '__main__':
    main()

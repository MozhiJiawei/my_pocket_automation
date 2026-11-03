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
import sys

from build import ROOT, build
from dfx_device import ADB, Device, allocate_run_id, command, instance_lock


class WaitExpired(RuntimeError):
    pass


DAILY_TASK_ORDER = ('shimen', 'zhuagui', 'dungeon', 'rewards')


def input_evidence(args, accounts, max_seconds):
    """Describe the exact requested scope and input hashes without credentials."""
    accounts_source = getattr(args, 'accounts_source', None)
    accounts_hash = hashlib.sha256(accounts_source.read_bytes()).hexdigest() if accounts_source else None
    if hasattr(args, 'accounts_source_sha256') and accounts_hash != args.accounts_source_sha256:
        raise RuntimeError('Account configuration changed after validation; no launch requested')
    names = ('mode', 'step', 'task', 'account', 'select_accounts', 'tasks', 'dungeon', 'dungeons',
             'shimen_needed', 'shimen_puzzle_family', 'browse_rounds', 'browse_until_no_new_topics',
             'rewards_debug_after_shimen', 'rewards_inspect_category', 'routine_screenshots', 'verbose_logs')
    scope = {name: getattr(args, name, None) for name in names}
    scope.update(accounts=[{'alias': item['alias'], 'claim_dungeon_rewards': item.get('claim_dungeon_rewards', False)}
                           for item in accounts], max_seconds=max_seconds)
    resources = {}
    for item in accounts:
        folder = Path.home() / '.my_pocket_automation/accounts' / item['alias']
        resources[item['alias']] = {
            name: hashlib.sha256((folder / name).read_bytes()).hexdigest() if (folder / name).is_file() else None
            for name in ('role.lua', 'selector.lua')}
    return {'vm_index': getattr(args, 'vm_index', None),
            'mumu_dir': str(getattr(args, 'mumu_dir', Path(ADB).parent)),
            'requested_scope': scope, 'accounts_sha256': accounts_hash,
            'account_resources_sha256': resources,
            'source_sha256': {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sorted((ROOT / 'src').rglob('*.lua'))},
            'device_tools_sha256': {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in sorted((ROOT / 'scripts/device').glob('*'))
                                    if path.is_file() and path.suffix in ('.py', '.ps1')}}


def validate_rewards_options(args):
    if getattr(args, 'rewards_debug_after_shimen', False):
        if (getattr(args, 'task', None) != 'rewards' or args.mode != 'run'
                or not getattr(args, 'account', None) or getattr(args, 'select_accounts', None)
                or args.step not in ('enter', 'complete', 'advance', 'browse')):
            raise ValueError('After-Shimen debug requires one selected rewards run at enter, complete, advance or browse')
    if getattr(args, 'task', None) == 'rewards' and args.mode == 'run' and not getattr(args, 'account', None):
        raise ValueError('Rewards runs require one explicitly selected account')
    category = getattr(args, 'rewards_inspect_category', 'task')
    if category not in ('task', 'dungeon', 'special'):
        raise ValueError('Unsupported rewards inspection category')
    if category != 'task' and (getattr(args, 'task', None) != 'rewards' or args.mode != 'run'
            or args.step not in ('enter', 'browse') or not getattr(args, 'account', None)
            or not getattr(args, 'rewards_debug_after_shimen', False) or getattr(args, 'select_accounts', None)):
        raise ValueError('Category inspection requires one after-Shimen rewards debug run at enter or browse')


def runtime_result(text, mode, step, task='dungeon', accounts=None, selected_tasks=None):
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
    problem = next((item for item in tasks if item['status'] in ('failed', 'blocked', 'paused')), None)
    if script == 'failed':
        business, reason = 'failed', problem['reason'] if problem else 'device_script_failed'
    elif script == 'succeeded':
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
    if task=='zhuagui' and step=='browse' and reason in ('find_catalog_observation_only','find_catalog_no_new_topics'):
        expected_pause=mode=='run'
    if task=='shimen' and step=='advance':
        expected_pause=mode=='run' and reason in ('one_minigame_completed','one_task_completed')
    if task=='shimen' and step=='browse':
        expected_pause=mode=='run' and reason=='find_catalog_observation_only'
    if task=='rewards':
        expected_pause=mode=='run' and reason in {
            'enter': ('rewards_inventory_observed',),
            'browse': ('rewards_inventory_observed',),
            'advance': ('opened_one_gourd', 'discarded_one_special'),
        }.get(step, ())
    acceptable = script == 'succeeded' and (
        business in ('observed', 'incomplete', 'done', 'running') or
        (business == 'paused' and expected_pause))
    if mode == 'run' and step in ('daily', 'complete', 'finish', 'start', 'enter') and not (task=='rewards' and step=='enter'):
        expected = 'running' if step in ('start', 'enter') else 'done'
        dungeons = [item for item in tasks if item['task'] == task]
        acceptable = acceptable and bool(dungeons) and all(item['status'] == expected for item in dungeons)
        if step == 'daily' and summary.get('scope')!='roles':
            acceptable = acceptable and summary.get('dungeon_done') == 'true'
    if mode=='run' and task=='rewards' and step!='daily':
        rewards=[item for item in tasks if item['task']=='rewards']
        verified=len(rewards)==1 and len(tasks)==1
        if accounts is not None:
            verified=verified and len(accounts)==1 and rewards[0]['account']==accounts[0]['alias']
        if step in ('enter','browse'):
            verified=verified and rewards[0]['status']=='paused' and expected_pause
        elif step=='advance':
            verified=verified and (rewards[0]['status']=='done' or (rewards[0]['status']=='paused' and expected_pause))
        elif step=='complete':
            verified=verified and rewards[0]['status']=='done'
        else:
            verified=False
        acceptable=acceptable and verified
    selected_complete=False
    if step=='daily' and summary.get('scope') in ('roles','selected_roles'):
        expected_aliases=[item['alias'] for item in accounts or []]
        required=selected_tasks or []
        verified=bool(expected_aliases and required)
        for alias in expected_aliases:
            for name in required:
                evidence=[item for item in tasks if item['account']==alias and item['task']==name]
                verified=verified and len(evidence)==1 and evidence[0]['status']=='done'
        verified=verified and all(item['account'] in expected_aliases for item in tasks)
        selected_complete=bool(verified and (summary.get('scope')=='selected_roles' or summary.get('all_roles_done')=='true') and summary.get('selected_done')=='true'
                               and summary.get('roles_expected')==str(len(expected_aliases))
                               and summary.get('roles_completed')==str(len(expected_aliases)))
        acceptable=script=='succeeded' and selected_complete and not any(item['status']!='done' for item in tasks)
        if not acceptable and business=='done': business,reason='incomplete','all_roles_not_verified'
    if step=='launch-game':
        acceptable = (mode=='run' and script=='succeeded' and business=='done' and len(tasks)==1
                      and tasks[0]==dict(account=None,task='startup',status='done',reason='game_entry_verified')
                      and summary.get('scope')=='application_startup' and summary.get('daily_done')=='false')
        if not acceptable and business=='done':
            business,reason='incomplete','application_entry_not_verified'
    return {'script_status': script, 'business_status': business, 'termination_reason': reason,
            'tasks': tasks, 'device_summary': summary, 'selected_complete':selected_complete,
            'daily_complete': bool(selected_complete and summary.get('daily_done')=='true'),
            'expectation_met': acceptable}


def run_once(args, accounts, max_seconds, run_id, archive):
    """A single attempt; never retry a launch, even when its response is lost."""
    if args.step=='launch-game' and (args.mode!='run' or getattr(args,'task','dungeon')!='dungeon'
            or accounts or getattr(args,'account',None) or getattr(args,'select_accounts',None)):
        raise ValueError('Application startup requires run mode without role or task selection')
    validate_rewards_options(args)
    if getattr(args, 'task', None)=='rewards' and args.mode=='run':
        selected=[item for item in accounts if item['alias']==args.account]
        if len(selected)!=1:
            raise ValueError('Selected rewards role is not configured')
        if args.step!='daily':
            accounts=selected
    archive.mkdir(parents=True)  # A collision must not overwrite previous evidence.
    record = {'run_id': run_id, 'archive': str(archive), 'mode': args.mode, 'step': args.step,
              'device': args.device, 'vm_index': getattr(args, 'vm_index', None),
              'adb': str(getattr(args, 'adb', None) or ADB),
              'mumu_dir': str(getattr(args, 'mumu_dir', Path(ADB).parent)),
              'environment_run_id': getattr(args, 'environment_run_id', None),
              'environment_archive': getattr(args, 'environment_archive', None),
              'task': getattr(args, 'task', 'dungeon'),
              'selected_account':getattr(args,'account',None),
              'rewards_debug_after_shimen':bool(getattr(args,'rewards_debug_after_shimen',False)),
              'rewards_inspect_category':getattr(args,'rewards_inspect_category','task'),
              'reward_claim_allowed': any(item.get('claim_dungeon_rewards') is True for item in accounts
                                          if not getattr(args,'account',None) or item['alias']==args.account),
              'reward_policies': {item['alias']: {'claim_dungeon_rewards':item.get('claim_dungeon_rewards',False)} for item in accounts},
              'daily_complete': False,
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
    device = Device(args.device, adb=args.adb) if getattr(args, 'adb', None) else Device(args.device)
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
            env = os.environ.copy()
            if device.auth:
                env['TOUCHSPRITE_AUTH'] = device.auth
            print(command([shell, '-NoProfile', '-File', str(ROOT / 'scripts/device/collect-debug.ps1'),
                           '-AdbPath', device.adb, '-Device', args.device, '-RunId', run_id], timeout=600, env=env), flush=True)
            record['collection_status'] = 'complete'
            # Diagnostic assembly cannot change the game's completion evidence.
            try:
                if str(ROOT) not in sys.path:
                    sys.path.insert(0, str(ROOT))
                from scripts.perception.lib.failure_materials import assemble
                record['recognition_materials'] = assemble(archive)
            except Exception as exc:
                record['material_assembly_error_type'] = type(exc).__name__
        except Exception as exc:
            record['collection_status'] = 'failed'
            record['collection_error_type'] = type(exc).__name__
            raise

    def read_evidence():
        log = archive / 'log' / f'daily_{run_id}.log'
        if log.exists():
            text = log.read_text(encoding='utf-8')
            selected=getattr(args,'select_accounts',None) or ([args.account] if getattr(args,'account',None) else None)
            expected_accounts=[item for item in accounts if not selected or item['alias'] in selected]
            record.update(runtime_result(text, args.mode, args.step, getattr(args, 'task', 'dungeon'),expected_accounts,
                                         getattr(args,'tasks',None)))
            return text
        return ''

    try:
        expected_inputs = getattr(args, 'input_evidence', None) or input_evidence(args, accounts, max_seconds)
        record.update(expected_inputs)
        persist()
        if input_evidence(args, accounts, max_seconds) != expected_inputs:
            raise RuntimeError('Run inputs changed before build; no launch requested')
        bundle = build(output=archive / 'build')
        shutil.copyfile(bundle, archive / 'script-source.lua')
        manifest = bundle.parent / 'manifest.json'
        shutil.copyfile(manifest, archive / 'manifest.json')
        bundle = archive / 'script-source.lua'
        record['bundle_sha256'] = hashlib.sha256(bundle.read_bytes()).hexdigest()
        config = archive / 'run-config.lua'
        def binding(item):
            return record['account_resources_sha256'][item['alias']]['role.lua'] or ''
        account_lua = ','.join('{alias="%s",claim_dungeon_rewards=%s,identity_binding="%s"}' %
                              (item['alias'],'true' if item.get('claim_dungeon_rewards') is True else 'false',binding(item)) for item in accounts)
        config.write_text('return {run_id="%s", business_date="%s", mode="%s", step="%s", task="%s", dungeon="%s", browse_rounds=%d, allow_reward_claim=false, accounts={%s}}\n' %
                          (run_id, datetime.now().strftime('%Y%m%d'), args.mode, args.step, getattr(args, 'task', 'dungeon'), args.dungeon,
                           getattr(args,'browse_rounds',1), account_lua), encoding='utf-8')
        if args.step=='daily' and getattr(args,'tasks',None):
            text=config.read_text(encoding='utf-8').rstrip()
            text=text[:-1]+',tasks={'+','.join('"'+name+'"' for name in args.tasks)+'}}\n'
            config.write_text(text,encoding='utf-8')
        if getattr(args,'select_accounts',None):
            text=config.read_text(encoding='utf-8').rstrip()
            config.write_text(text[:-1]+',selected_accounts={'+','.join(json.dumps(alias) for alias in args.select_accounts)+'},verify_role=true}\n',encoding='utf-8')
        text=config.read_text(encoding='utf-8').rstrip()
        extra=',profile=true,completion_ledger_path="/storage/emulated/0/TouchSprite/res/daily_completion.tsv"'
        extra+=',shimen_needed='+str(getattr(args,'shimen_needed',2))
        extra+=',rewards_debug_after_shimen='+str(record['rewards_debug_after_shimen']).lower()
        extra+=',rewards_inspect_category='+json.dumps(record['rewards_inspect_category'])
        if getattr(args,'shimen_puzzle_family',None):
            extra+=',shimen_puzzle_family='+json.dumps(args.shimen_puzzle_family,ensure_ascii=False)
        extra+=',routine_screenshots='+str(getattr(args,'routine_screenshots',False)).lower()
        extra+=',browse_until_no_new_topics='+str(getattr(args,'browse_until_no_new_topics',False)).lower()
        extra+=',verbose_logs='+str(getattr(args,'verbose_logs',False)).lower()
        extra+=',dungeons={'+','.join('"'+name+'"' for name in getattr(args,'dungeons',['wuji','chechi']))+'}'
        config.write_text(text[:-1]+extra+'}\n',encoding='utf-8')
        record['dungeons']=getattr(args,'dungeons',['wuji','chechi'])
        if args.step=='daily' or (getattr(args,'task',None)=='zhuagui' and args.step=='complete'):
            text=config.read_text(encoding='utf-8').rstrip()
            config.write_text(text[:-1]+',zhuagui_timeout='+str(max_seconds)+'}\n',encoding='utf-8')
        if getattr(args,'account',None):
            text=config.read_text(encoding='utf-8').rstrip()
            selection=',selected_account="'+args.account+'"' if args.step=='daily' else ''
            config.write_text(text[:-1]+',verify_role=true'+selection+'}\n',encoding='utf-8')
        record['run_config_sha256'] = hashlib.sha256(config.read_bytes()).hexdigest()
        record['phase'] = 'authorize'
        device.authorize()
        if observe_status() != 'f00':
            raise RuntimeError('Device is not idle; no files published')
        if input_evidence(args, accounts, max_seconds) != expected_inputs:
            raise RuntimeError('Run inputs changed before publication; no launch requested')
        record['phase'] = 'publish_config'
        if args.step == 'daily' or getattr(args,'account',None) or (getattr(args, 'task', 'dungeon')=='zhuagui' and args.mode=='run' and args.step in ('enter','start','complete')):
            for item in accounts:
                alias = item['alias']
                for local_name, remote_kind in [('role.lua', 'identity'), ('selector.lua', 'selector')]:
                    if args.step=='select-role' and local_name=='role.lua':
                        continue
                    identity = Path.home() / '.my_pocket_automation/accounts' / alias / local_name
                    if not identity.exists():
                        raise RuntimeError('Calibrate configured saved-role resources outside repository first')
                    expected_hash = record['account_resources_sha256'][alias][local_name]
                    if hashlib.sha256(identity.read_bytes()).hexdigest() != expected_hash:
                        raise RuntimeError('Saved-role resource changed; no launch requested')
                    remote = f'/storage/emulated/0/TouchSprite/res/daily_{remote_kind}_{alias}.lua'
                    device.adb_call('push', str(identity), remote + '.pending')
                    if device.adb_call('shell', 'sha256sum', remote + '.pending').split()[0] != expected_hash:
                        raise RuntimeError('Saved-role resource hash mismatch')
                    device.adb_call('shell', 'mv', remote + '.pending', remote)
        remote_config = '/storage/emulated/0/TouchSprite/res/daily_config.lua'
        device.adb_call('push', str(config), remote_config + '.pending')
        if device.adb_call('shell', 'sha256sum', remote_config + '.pending').split()[0] != hashlib.sha256(config.read_bytes()).hexdigest():
            raise RuntimeError('Configuration hash mismatch')
        device.adb_call('shell', 'mv', remote_config + '.pending', remote_config)
        if input_evidence(args, accounts, max_seconds) != expected_inputs:
            raise RuntimeError('Run inputs changed before Lua launch; no launch requested')
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
    return record


def _load_emulator():
    import importlib.util
    spec = importlib.util.spec_from_file_location('single_run_emulator', Path(__file__).with_name('start-emulator.py'))
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    return launcher


def execute(args, accounts, max_seconds):
    """Execute one validated scope; the caller holds the instance lock."""
    launcher = _load_emulator()
    args.device = launcher.validate_vm(args.mumu_dir, args.vm_index, args.device)['device']
    args.adb = str(args.mumu_dir / 'adb.exe')
    if getattr(args, 'input_evidence', None) is None:
        args.input_evidence = input_evidence(args, accounts, max_seconds)
    run_id = allocate_run_id(ROOT)
    args.lua_run_id = run_id
    args.lua_archive = str(ROOT / 'debug-runs' / run_id)
    return run_once(args, accounts, max_seconds, run_id, Path(args.lua_archive))


def create_parser():
    p = argparse.ArgumentParser()
    p.add_argument('--device', help='Optional exact endpoint check against the selected VM')
    p.add_argument('--vm-index', type=int, required=True, help='Explicit existing MuMu instance')
    p.add_argument('--mumu-dir', type=Path, default=Path(ADB).parent)
    p.add_argument('--mode', choices=['observe', 'run'], default='observe')
    p.add_argument('--max-seconds', type=int)
    p.add_argument('--dungeon', choices=['wuji', 'chechi'], default='wuji')
    p.add_argument('--task', choices=['dungeon', 'zhuagui','shimen','rewards'], default='dungeon')
    p.add_argument('--rewards-debug-after-shimen',action='store_true',help='One selected rewards debug run after Lua verifies the Shimen completion card')
    p.add_argument('--rewards-inspect-category',choices=['task','dungeon','special'],default='task',help='Read-only inventory category for an after-Shimen enter or browse debug run')
    p.add_argument('--shimen-needed',type=int,default=2)
    p.add_argument('--shimen-puzzle-family',help='Explicit family for one visible legacy-puzzle attempt; no new task or automatic retry')
    p.add_argument('--routine-screenshots',action='store_true',help='Archive before/after frames for device debugging')
    p.add_argument('--verbose-logs',action='store_true',help='Include DEBUG state, recognition and individual input logs')
    p.add_argument('--dungeons',default='wuji,chechi',help='Selected daily dungeons, comma-separated')
    p.add_argument('--browse-rounds',type=int,default=1,help='Observation-only retries of the existing find task (1–60)')
    p.add_argument('--browse-until-no-new-topics',action='store_true',help='Collect wine-only 10-round cycles until one cycle has no new question topics (maximum 60 rounds)')
    p.add_argument('--accounts', type=Path, help='External JSON list of configured saved-role aliases')
    p.add_argument('--account', help='One configured role for bounded recovery; full daily runs still verify the roster')
    p.add_argument('--select-accounts',nargs='+',help='Configured roles to run in daily mode; verify the full saved roster first')
    p.add_argument('--tasks', default=','.join(DAILY_TASK_ORDER), help='Daily selected task modules, comma-separated; run in Shimen, ZhuaGui, dungeon, rewards order')
    p.add_argument('--step', choices=['launch-game', 'select-role', 'enter', 'start', 'advance', 'complete', 'finish', 'back', 'browse', 'select', 'switch', 'observe', 'daily'], default='observe')
    return p


def prepare(args):
    """Validate options and external configuration without contacting a device."""
    if type(args.vm_index) is not int or args.vm_index < 0:
        raise ValueError('VM index must be a nonnegative integer')
    if not args.mumu_dir.is_absolute():
        raise ValueError('An absolute MuMu installation path is required')
    validate_rewards_options(args)
    if not 1<=args.shimen_needed<=10:raise ValueError('Invalid Shimen item count')
    if args.shimen_puzzle_family and (args.task!='shimen' or args.step!='advance' or args.mode!='run' or not re.fullmatch(r'[\w\u4e00-\u9fff]{1,20}',args.shimen_puzzle_family)):
        raise ValueError('Puzzle family requires one Shimen advance run')
    args.tasks=args.tasks.split(',')
    if len(set(args.tasks))!=len(args.tasks) or not set(args.tasks)<=set(DAILY_TASK_ORDER):
        raise ValueError('Tasks must be a unique list of supported modules')
    args.tasks=[name for name in DAILY_TASK_ORDER if name in args.tasks]
    args.dungeons=args.dungeons.split(',')
    if not args.dungeons or len(set(args.dungeons))!=len(args.dungeons) or any(name not in ('wuji','chechi') for name in args.dungeons):
        raise ValueError('Invalid selected dungeons')
    if len(set(args.tasks))!=len(args.tasks) or any(name not in ('shimen','zhuagui','dungeon','rewards') for name in args.tasks):
        raise ValueError('Invalid selected tasks')
    if not 1<=args.browse_rounds<=60:
        raise ValueError('Browse rounds must be between 1 and 60')
    if args.browse_rounds!=1 and (args.task!='zhuagui' or args.step!='browse' or args.mode!='run'):
        raise ValueError('Multiple browse rounds require ZhuaGui observation-only browse mode')
    if args.browse_until_no_new_topics and (args.task!='zhuagui' or args.step!='browse' or args.mode!='run' or args.browse_rounds!=10):
        raise ValueError('Topic cycles require wine sampling in 10-round ZhuaGui browse mode')
    if args.step=='launch-game':
        if args.mode!='run' or args.task!='dungeon' or args.accounts or args.account or args.select_accounts:
            raise ValueError('Application startup requires run mode without role or task selection')
        max_seconds=args.max_seconds if args.max_seconds is not None else 150
        if max_seconds<=0:
            raise ValueError('Wait limit must be positive')
        return [], max_seconds
    accounts_path=args.accounts or Path.home() / '.my_pocket_automation/daily-accounts.json'
    if not accounts_path.exists() and not args.accounts:
        accounts_path.parent.mkdir(parents=True,exist_ok=True)
        accounts_path.write_text(json.dumps([{'alias':'current'}],indent=2),encoding='utf-8')
    if accounts_path.resolve().is_relative_to(ROOT):
        raise ValueError('Saved-role configuration belongs outside the repository')
    args.accounts_source = accounts_path
    accounts_bytes = accounts_path.read_bytes()
    args.accounts_source_sha256 = hashlib.sha256(accounts_bytes).hexdigest()
    accounts=json.loads(accounts_bytes.decode('utf-8'))
    if not isinstance(accounts,list) or not accounts:
        raise ValueError('Accounts must be a nonempty list')
    aliases=[item['alias'] for item in accounts]
    if args.select_accounts and (args.step!='daily' or args.account or len(set(args.select_accounts))!=len(args.select_accounts) or not set(args.select_accounts)<=set(aliases)):
        raise ValueError('Selected accounts require daily mode, configured unique aliases and no single-account option')
    for item in accounts:
        if not isinstance(item.get('claim_dungeon_rewards',False),bool):
            raise ValueError('Reward policy must be boolean')
    if len(set(aliases))!=len(aliases) or not all(re.fullmatch(r'[A-Za-z0-9_-]+',name) for name in aliases):
        raise ValueError('Aliases must be unique and contain only ASCII letters, digits, underscore or hyphen')
    if args.account:
        selected=[item for item in accounts if item['alias']==args.account]
        if len(selected)!=1: raise ValueError('Selected role is not configured')
        if args.step!='daily':
            accounts=selected
            aliases=[args.account]
    if args.step!='daily' and aliases!=['current'] and not args.account:
        raise ValueError('Development steps are limited to the inspected current account')
    max_seconds = args.max_seconds if args.max_seconds is not None else (10800 if args.step=='daily' else 3900 if args.step in ['advance','complete'] else 90)
    if args.task=='zhuagui' and args.step=='browse' and not args.max_seconds:
        max_seconds=max(max_seconds,(60 if args.browse_until_no_new_topics else args.browse_rounds)*65+30)
    if max_seconds <= 0:
        raise ValueError('Wait limit must be positive')
    return accounts, max_seconds


def main(argv=None):
    args = create_parser().parse_args(argv)
    accounts, max_seconds = prepare(args)
    with instance_lock(ROOT, args.mumu_dir, args.vm_index):
        args.input_evidence = input_evidence(args, accounts, max_seconds)
        return execute(args, accounts, max_seconds)


def cli(argv=None):
    try:
        main(argv)
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(cli())

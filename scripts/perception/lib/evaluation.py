"""One evaluator for unittest and algorithm experiments; predictions never edit labels."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import cv2
from scripts.perception.lib.corpus import VERIFIED, audit, image_path, validate
from tests.support.lua_runtime import ROOT, Runtime
from tests.support.touchsprite_adapter import CONTRACT, Screen
from scripts.perception.lib.round_truth import evaluate_rounds


def evaluate_case(case):
    screen=Screen.read(validate(case))
    if list(reversed(screen.frame.shape[:2]))!=case['capture']['size']:
        raise ValueError('Frame dimensions changed')
    runtime=Runtime(screen,planning=True)
    checks=[]
    predicted={}
    plan = None
    for name in case['expected']['checks']:
        field=case['truth'][name]
        if field['status'] not in VERIFIED:
            checks.append({'field':name,'status':'unscored','reason':field['status']})
            continue
        value=field['value']
        if name in ('page','forbidden_page'):
            actual=runtime.page(case['task'])
            passed=actual!=value if name=='forbidden_page' else actual!='find' if value=='not_find' else actual==value
        elif name=='question':
            actual=runtime.question() or 'unknown'
            passed=actual==value['target']
        elif name=='count':
            actual=runtime.count()
            actual='unknown' if actual is None else actual
            passed=actual==value
        elif name in ('target_regions', 'negative_regions'):
            if plan is None:
                plan=runtime.locate()
            result=plan
            taps=[a['point'] for a in runtime.actions if a['kind']=='tap']
            actual={'planned_taps':taps,'solver_result':list(result) if isinstance(result,tuple) else result}
            hits=lambda x,y:any(x1<=x<x2 and y1<=y<y2 for x1,y1,x2,y2 in value)
            passed=(bool(taps) and all(hits(x,y) for x,y in taps)) if name=='target_regions' else not any(hits(x,y) for x,y in taps)
            actual['diagnosis']='valid_selection' if passed and taps else 'abstained' if not taps else 'wrong_selection'
            if name == 'target_regions' and taps and not passed and case['truth'].get('target_regions_complete',{}).get('value') is False:
                negatives=case['truth'].get('negative_regions',{}).get('value') or []
                rejected=any(x1<=x<x2 and y1<=y<y2 for x,y in taps for x1,y1,x2,y2 in negatives)
                if not rejected:
                    predicted[name]=actual
                    checks.append({'field':name,'expected':value,'actual':actual,'status':'unscored',
                                   'reason':'tap_outside_partial_truth'})
                    continue
        elif name=='forbidden_actions':
            runtime.locate()
            actual=[a['kind'] for a in runtime.actions]
            passed=not set(actual).intersection(value)
        else:
            raise ValueError(f'Unsupported assertion: {name}')
        predicted[name]=actual
        checks.append({'field':name,'expected':value,'actual':actual,'status':'passed' if passed else 'failed'})
    return {'id':case['id'],'task':case['task'],'image':str(image_path(case)),
            'group':case['capture']['group'],'split':case['capture']['split'],
            'checks':checks,'predictions':predicted,'actions':runtime.actions,
            'known_negative_regions':case['truth'].get('negative_regions',{}).get('value') or [],
            'trace':runtime.logs,'matches':screen.matches,
            'status':'failed' if any(c['status']=='failed' for c in checks) else 'passed' if any(c['status']=='passed' for c in checks) else 'unscored'}


def write_report(cases, results, output, baseline=None):
    output.mkdir(parents=True,exist_ok=True)
    source=hashlib.sha256()
    for path in sorted((ROOT/'src').rglob('*.lua')):
        source.update(path.relative_to(ROOT).as_posix().encode()); source.update(path.read_bytes())
    dataset=hashlib.sha256(json.dumps(cases,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    revision=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True)
    summary={'source_sha256':source.hexdigest(),'git_revision':revision.stdout.strip() if revision.returncode==0 else None,
             'dataset_sha256':dataset,'backend':CONTRACT,'annotation_audit':audit(cases),
             'frames':len(results),'failed_frames':sum(r['status']=='failed' for r in results),
             'checks':{status:sum(c['status']==status for r in results for c in r['checks'])
                       for status in ('passed','failed','unscored')}}
    harness=hashlib.sha256()
    for path in sorted([*(ROOT/'tests/support').glob('*.py'), *(ROOT/'scripts/perception/lib').glob('*.py')]):
        harness.update(path.relative_to(ROOT).as_posix().encode()); harness.update(path.read_bytes())
    summary['harness_sha256']=harness.hexdigest()
    summary['environment']={'python':sys.version.split()[0],'opencv':cv2.__version__}
    summary['full_question_text_evaluated']=False
    summary['game_postconditions_simulated']=False
    round_file=ROOT/'testdata/zhuagui/rounds.json'
    round_cases=[]
    if round_file.exists():
        selected_ids={c['id'] for c in cases}
        round_document=json.loads(round_file.read_text(encoding='utf-8'))
        round_cases=[r for r in round_document['rounds'] if {c['case_id'] for c in r['captures']}.issubset(selected_ids)]
        summary['round_truth_sha256']=hashlib.sha256(round_file.read_bytes()).hexdigest()
    round_results=evaluate_rounds(round_cases,results)
    summary['rounds']={'count':len(round_results),
                       'status':{state:sum(r['status']==state for r in round_results) for state in ('passed','failed','unscored')},
                       'approved_answer_instances':sum(len(r['expected_answers']) for r in round_results),
                       'selected_answer_instances':sum(len(r['selected_answers']) for r in round_results)}
    targets={c['id']:(c['truth'].get('question',{}).get('value') or {}).get('target') for c in cases}
    summary['by_target']={}
    for target in sorted({v for v in targets.values() if v}):
        group=[r for r in results if targets[r['id']]==target]
        summary['by_target'][target]={'frames':len(group),'capture_groups':len({r['group'] for r in group}),
            'checks':{field:{state:sum(c['field']==field and c['status']==state for r in group for c in r['checks'])
                             for state in ('passed','failed','unscored')}
                      for field in sorted({c['field'] for r in group for c in r['checks']})}}
    summary['by_round_target']={target:{state:sum(r['topic']==target and r['status']==state for r in round_results)
                                      for state in ('passed','failed','unscored')}
                               for target in sorted({r['topic'] for r in round_results})}
    if baseline:
        previous=json.loads(Path(baseline).read_text(encoding='utf-8'))
        old={(r['id'],c['field']):c for r in previous['results'] for c in r['checks']}
        changes=[]
        for result in results:
            for check in result['checks']:
                before=old.get((result['id'],check['field']))
                kind='new_check' if before is None else 'annotation_changed' if before.get('expected')!=check.get('expected') else 'regressed' if before['status']=='passed' and check['status']=='failed' else 'fixed' if before['status']=='failed' and check['status']=='passed' else None
                if kind: changes.append({'id':result['id'],'field':check['field'],'kind':kind})
        summary['baseline_comparison']=changes
    (output/'results.json').write_text(json.dumps({'summary':summary,'results':results,'round_results':round_results},ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 离线识别评测','',f"画面 {len(results)}；失败 {summary['failed_frames']}；断言统计 {summary['checks']}。",
           '', '未标注项不参与通过率；电脑颜色匹配是近似后端，不能证明设备完成。','']
    lines.extend([f'整轮选答案评测：{summary["rounds"]}。', '',
                  '选中任一正确答案表示本轮具备可用选择；未选中其他正确答案不计作检测召回率。只评测当前所选原始帧齐全的轮次；部分采集不宣称覆盖整题。', '',
                  '|轮次|类别|已标答案数|选中答案数|结果|', '|---|---|---|---|---|'])
    for item in round_results:
        lines.append(f'|{item["id"]}|{item["topic"]}|{len(item["expected_answers"])}|{len(item["selected_answers"])}|{item["status"]}|')
    lines.append('')
    lookup={c['id']:c for c in cases}
    for result in results:
        if result['status']!='failed': continue
        case=lookup[result['id']]
        frame=Screen.read(image_path(case)).frame
        for x1,y1,x2,y2 in case['truth'].get('target_regions',{}).get('value') or []:
            cv2.rectangle(frame,(x1,y1),(x2,y2),(0,200,0),3)
        for x1,y1,x2,y2 in result['known_negative_regions']:
            cv2.rectangle(frame,(x1,y1),(x2,y2),(255,100,0),3)
        for action in result['actions']:
            if action['kind']=='tap': cv2.circle(frame,tuple(action['point']),10,(0,0,255),3)
        target=output/f"{result['id']}.png"
        cv2.imencode('.png',frame)[1].tofile(target)
        lines.append(f"- [{result['id']}](</{target.as_posix()}>): " + ', '.join(c['field'] for c in result['checks'] if c['status']=='failed'))
    (output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return summary

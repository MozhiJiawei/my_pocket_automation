"""One evaluator for unittest and algorithm experiments; predictions never edit labels."""
import json
import sys
import os
import shutil
import time
from contextlib import nullcontext
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import cv2
import numpy as np
from scripts.perception.lib.corpus import VERIFIED, audit, image_path, validate, load_rounds, crop_sources, iter_variants
from tests.support.lua_runtime import ROOT, Runtime, freeze_module_versions
from tests.support.touchsprite_adapter import CONTRACT, Screen
from scripts.perception.lib.round_truth import evaluate_rounds

if os.environ.get('POCKET_TEST_GPU','auto')!='off':
    try:
        from tests.support.opencl_colors import GpuScreen
        if GpuScreen.available():Screen=GpuScreen
        elif os.environ.get('POCKET_TEST_GPU')=='required':raise RuntimeError('No OpenCL GPU available')
    except (ImportError,RuntimeError):
        if os.environ.get('POCKET_TEST_GPU')=='required':raise


def _evaluate_input(job):
    case,crops,origin=job
    frame=Screen.read(image_path(case)).frame
    cases=[];results=[]
    inventory=case['task']=='shimen' and case['truth'].get('page',{}).get('value')=='find'
    pixels=np.empty((8,*frame.shape),dtype=frame.dtype) if inventory and origin!='device' and hasattr(Screen,'configure_catalog') else None
    variants=list(iter_variants(case,crops,frame,persist=False,canvases=pixels)) if inventory and origin!='device' else None
    identity_variant=bool(variants and np.array_equal(variants[0][1],frame))
    if pixels is not None and not identity_variant:raise ValueError('Identity enhancement changed the original')
    batch={'pixels':pixels,'results':{}} if pixels is not None else None
    original_screen=Screen(frame)
    if batch:original_screen.frame_batch=batch;original_screen.batch_index=0
    if not origin or case['capture']['origin']==origin:
        cases.append(case);results.append(evaluate_case(case,screen=original_screen))
    header_cache={}
    if case['task']=='shimen':
        for query,result in original_screen.cache.items():
            offsets=[int(p.split('|')[1]) for p in query[1].split(',') if p]
            if query[6]+max([0,*offsets])<535:header_cache[query]=result
    if origin!='device':
        for index,(derived,pixels) in enumerate(variants if variants is not None else iter_variants(case,crops,frame,persist=False),1):
            screen=Screen(pixels)
            if batch:screen.frame_batch=batch;screen.batch_index=index-int(identity_variant)
            if case['task']=='shimen' and np.array_equal(pixels[:535],frame[:535]):
                # Reuse exact color queries only when every possible sampled
                # pixel is inside the byte-identical header, never item results.
                screen.cache.update(header_cache)
            cases.append(derived);results.append(evaluate_case(derived,screen=screen))
            if results[-1]['status']=='failed':
                path=image_path(derived);path.parent.mkdir(parents=True,exist_ok=True)
                cv2.imencode('.png',pixels,[cv2.IMWRITE_PNG_COMPRESSION,1])[1].tofile(path)
    return cases,results


def evaluate_inputs(inputs,origin=None,workers=None,*,executor=None):
    """Each worker reads one original and evaluates its eight pixel transforms.

    Only failures need PNG output; scoring still executes production Lua and
    validates every transformed image, without PNG encode/decode round trips.
    """
    crops=crop_sources(inputs)
    jobs=[(c,crops.get(c['id'],[]),origin) for c in inputs]
    cases=[];results=[]
    context=nullcontext(executor) if executor is not None else ProcessPoolExecutor(
        max_workers=workers or min(12,max(1,(os.cpu_count() or 1)-4)),initializer=freeze_module_versions)
    with context as pool:
        for batch,predictions in pool.map(_evaluate_input,jobs):
            cases.extend(batch);results.extend(predictions)
    return cases,results


def evaluate_case(case, frame=None,screen=None):
    started=time.perf_counter()
    screen=screen or (Screen.read(image_path(case)) if frame is None else Screen(frame))
    if case['task']=='shimen':screen.trace_matches=False
    validate(case,screen.frame)
    if list(reversed(screen.frame.shape[:2]))!=case['capture']['size']:
        raise ValueError('Frame dimensions changed')
    runtime=Runtime(screen,planning=True)
    try:
        result=_evaluate_runtime(case,screen,runtime)
        result['elapsed_seconds']=time.perf_counter()-started
        return result
    finally:runtime.close()


def _evaluate_runtime(case,screen,runtime):
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
            actual=runtime.question(case['task']) or 'unknown'
            passed=actual==value['target']
        elif name=='count':
            actual=runtime.count()
            actual='unknown' if actual is None else actual
            passed=actual==value
        elif name=='puzzle_locations' and case['task']=='shimen':
            source=case.get('augmentation',{}).get('parent',case['image'])
            locations,reason=runtime.require('tasks.shimen.puzzle').read(Path(source).parent.name)
            actual=list(locations.values()) if locations else None
            passed=actual==value
        elif name in ('puzzle_family','puzzle_order'):
            family,locations=runtime.require('tasks.zhuagui.puzzle').read()
            actual=family if name=='puzzle_family' else ''.join(chr(64+int(i)) for i in locations.values()) if locations else None
            passed=actual==value
        elif name in ('target_regions', 'negative_regions'):
            if plan is None:
                plan=runtime.locate(case['task'])
            result=plan
            taps=[a['point'] for a in runtime.actions if a['kind']=='tap']
            actual={'planned_taps':taps,'solver_result':list(result) if isinstance(result,tuple) else result}
            hits=lambda x,y:any(x1<=x<x2 and y1<=y<y2 for x1,y1,x2,y2 in value)
            passed=(bool(taps) and all(hits(x,y) for x,y in taps)) if name=='target_regions' else not any(hits(x,y) for x,y in taps)
            if name=='target_regions' and case['task']=='shimen':
                passed=all(any(x1<=x<x2 and y1<=y<y2 for x,y in taps) for x1,y1,x2,y2 in value)
            actual['diagnosis']='valid_selection' if passed and taps else 'abstained' if not taps else 'wrong_selection'
            if case['task']!='shimen' and name == 'target_regions' and taps and not passed and case['truth'].get('target_regions_complete',{}).get('value') is False:
                negatives=case['truth'].get('negative_regions',{}).get('value') or []
                rejected=any(x1<=x<x2 and y1<=y<y2 for x,y in taps for x1,y1,x2,y2 in negatives)
                if not rejected:
                    predicted[name]=actual
                    checks.append({'field':name,'expected':value,'actual':actual,'status':'unscored',
                                   'reason':'tap_outside_partial_truth'})
                    continue
        elif name=='forbidden_actions':
            runtime.locate(case['task'])
            actual=[a['kind'] for a in runtime.actions]
            passed=not set(actual).intersection(value)
        else:
            raise ValueError(f'Unsupported assertion: {name}')
        predicted[name]=actual
        checks.append({'field':name,'expected':value,'actual':actual,'status':'passed' if passed else 'failed'})
    result={'id':case['id'],'task':case['task'],'image':str(image_path(case)),
            'group':case['capture']['group'],'split':case['capture']['split'],
            'checks':checks,'predictions':predicted,'actions':runtime.actions,
            'known_negative_regions':case['truth'].get('negative_regions',{}).get('value') or [],
            'trace':runtime.logs,'matches':screen.matches,
            'status':'failed' if any(c['status']=='failed' for c in checks) else 'passed' if any(c['status']=='passed' for c in checks) else 'unscored'}
    return result


def write_report(cases, results, output, baseline=None):
    output.mkdir(parents=True,exist_ok=True)
    summary={'backend':CONTRACT,'annotation_audit':audit(cases),
             'frames':len(results),'failed_frames':sum(r['status']=='failed' for r in results),
             'checks':{status:sum(c['status']==status for r in results for c in r['checks'])
                       for status in ('passed','failed','unscored')}}
    derived=[c for c in cases if c.get('augmentation')]
    summary['input_cases']=len({c['augmentation']['parent'] if c.get('augmentation') else c['id'] for c in cases})
    summary['augmentation_sources']=len({(c['augmentation']['parent'],tuple(c['augmentation']['crop'])) for c in derived})
    summary['generated_images']=len(derived)
    summary['environment']={'python':sys.version.split()[0],'opencv':cv2.__version__}
    summary['full_question_text_evaluated']=False
    origins={c['id']:c['capture']['origin'] for c in cases}
    summary['by_origin']={origin:{'frames':sum(origins[r['id']]==origin for r in results),
        'failed_frames':sum(origins[r['id']]==origin and r['status']=='failed' for r in results)}
        for origin in sorted(set(origins.values()))}
    summary['game_postconditions_simulated']=False
    selected_ids={c['id'] for c in cases}
    round_cases=[r for r in load_rounds(None) if set(r['frames']).issubset(selected_ids)]
    round_results=evaluate_rounds(round_cases,results)
    summary['rounds']={'count':len(round_results),
                       'status':{state:sum(r['status']==state for r in round_results) for state in ('passed','failed','unscored')},
                       'approved_answer_instances':sum(r['approved_count'] for r in round_results),
                       'selected_answer_instances':sum(r['selected_count'] for r in round_results)}
    targets={c['id']:(c['truth'].get('question',{}).get('value') or {}).get('target') for c in cases}
    summary['by_target']={}
    for target in sorted({v for v in targets.values() if v}):
        group=[r for r in results if targets[r['id']]==target]
        summary['by_target'][target]={'frames':len(group),'capture_groups':len({r['group'] for r in group}),
            'worker_seconds':sum(r.get('elapsed_seconds',0) for r in group),
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
    lines=['# 离线识别评测','',f"输入用例 {summary['input_cases']}；增强裁图来源 {summary['augmentation_sources']}；执行时生成图片 {summary['generated_images']}。",
           '',f"实际识别画面 {len(results)}；失败 {summary['failed_frames']}；断言统计 {summary['checks']}。",
           '', f"来源分别统计：{summary['by_origin']}。增强帧不增加真实采集轮数。",
           '', '未标注项不参与通过率；电脑颜色匹配是近似后端，不能证明设备完成。','']
    lines.extend([f'整轮选答案评测：{summary["rounds"]}。', '',
                  '抓鬼按选中任一已批准答案评分；师门要求全部已批准区域得到定位，且不得命中已标反例。未知区域不作为反例。只评测原始帧齐全的轮次。', '',
                  '|轮次|类别|已标答案数|选中答案数|结果|', '|---|---|---|---|---|'])
    for item in round_results:
        lines.append(f'|{item["id"]}|{item["topic"]}|{item["approved_count"]}|{item["selected_count"]}|{item["status"]}|')
    lookup={c['id']:c for c in cases}
    lines.extend(['','逐类区域统计包含原图及全部增强；耗时为各工作进程识别时间之和，不是总墙钟时间。','',
                  '|类别|画面|批准正例区域|漏定位|命中反例|未知区域定位|工作进程秒数|','|---|---|---|---|---|---|---|'])
    for target,stats in summary['by_target'].items():
        positive=missed=negative=unknown=0
        for result in results:
            if targets[result['id']]!=target:continue
            truth=lookup[result['id']]['truth']
            approved=truth.get('target_regions',{}).get('value') or []
            rejected=truth.get('negative_regions',{}).get('value') or []
            points=[a['point'] for a in result['actions'] if a['kind']=='tap']
            def contains(boxes,point):
                x,y=point
                return any(x1<=x<x2 and y1<=y<y2 for x1,y1,x2,y2 in boxes)
            positive+=len(approved)
            missed+=sum(not any(contains([box],point) for point in points) for box in approved)
            negative+=sum(contains(rejected,point) for point in points)
            unknown+=sum(not contains(approved+rejected,point) for point in points)
        stats.update(approved_regions=positive,missed_regions=missed,negative_hits=negative,unknown_locations=unknown)
        lines.append(f'|{target}|{stats["frames"]}|{positive}|{missed}|{negative}|{unknown}|{stats["worker_seconds"]:.3f}|')
    lines.append('')
    for result in results:
        if result['status']!='failed': continue
        case=lookup[result['id']]
        if case['task']=='shimen' and case.get('augmentation'):
            target=output/'failures'/result['id'];target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(image_path(case),target)
            lines.append(f"- [{result['id']}](</{target.as_posix()}>): "+', '.join(c['field'] for c in result['checks'] if c['status']=='failed')+f"；定位：{result['actions']}")
            continue
        frame=Screen.read(image_path(case)).frame
        for x1,y1,x2,y2 in case['truth'].get('target_regions',{}).get('value') or []:
            cv2.rectangle(frame,(x1,y1),(x2,y2),(0,200,0),3)
        for x1,y1,x2,y2 in result['known_negative_regions']:
            cv2.rectangle(frame,(x1,y1),(x2,y2),(255,100,0),3)
        for action in result['actions']:
            if action['kind']=='tap': cv2.circle(frame,tuple(action['point']),10,(0,0,255),3)
        target=output/"failures"/result["id"]
        target.parent.mkdir(parents=True,exist_ok=True)
        cv2.imencode('.png',frame)[1].tofile(target)
        lines.append(f"- [{result['id']}](</{target.as_posix()}>): " + ', '.join(c['field'] for c in result['checks'] if c['status']=='failed'))
    (output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (output/'results.json').write_text(json.dumps({'summary':summary,'results':results,'round_results':round_results},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    return summary

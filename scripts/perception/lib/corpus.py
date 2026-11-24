"""Discover named image cases. Directory names and local answers are the only truth."""
import json
import struct
import itertools
from pathlib import Path
from copy import deepcopy
from functools import lru_cache
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3] / 'testdata'
VERIFIED = {'reviewed', 'device_verified', 'user_verified'}
TASKS = {'zhuagui':'抓鬼', 'dungeon':'副本', 'shimen':'师门'}
PAGES = {'任务列表':'task_list','开始任务消耗三精力':'ready_cost_three','玩法规则':'rules',
         '出发':'depart','战斗':'battle','今日次数已满对话':'quota_dialogue',
         '今日完成任务卡片':'quota_completed_card','进行中未校准页面':'active_uncalibrated',
         '非寻物页面':'not_find','获得葫芦提示禁止操作':'unknown'}
DUNGEON_IDS = {'乌鸡国':'wuji', '车迟国':'chechi', '黑风山':'heifeng', '水陆大会':'shuilu', '平顶山':'pingding'}
DUNGEON_CARD_FIELDS = tuple(f'{dungeon}_card' for dungeon in DUNGEON_IDS.values())
DUNGEON_STATES = {'副本列表':'list_{id}', '准备开始':'{id}_ready', '继续战斗':'{id}_active',
                  '领奖确认':'{id}_claim_confirm', '领取成功':'{id}_claim_receipt',
                  '葫芦已领取':'list_{id}', '今日已完成':'{id}_done', '葫芦未领取':'{id}_reward_sealed'}
DUNGEON = {f'{name}/{scene}': state.format(id=identifier)
           for name, identifier in DUNGEON_IDS.items() for scene, state in DUNGEON_STATES.items()}
DUNGEON.update({'战斗':'battle', '副本切换/乌鸡国切换车迟国':'switch_wuji_chechi',
                '副本切换/车迟国切换乌鸡国':'switch_chechi_wuji',
                '副本切换/黑风山切换水陆大会':'switch_heifeng_shuilu',
                '副本切换/水陆大会切换平顶山':'switch_shuilu_pingding', '异常画面/未知页面':'unknown'})


def regions(value):
    """A historical answer may retain two independently approved boundary boxes."""
    return [value] if value and type(value[0]) is int else value


def read_answers(folder):
    path=folder/'答案.json'
    document=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if set(document)-{'正确','反例','预期'}:raise ValueError(f'Unknown answer sections: {path}')
    for section in ('正确','反例'):
        for locations in document.get(section,{}).values():
            for name,box in locations.items():
                if Path(name).name!=name or not (folder/name).is_file():raise ValueError(f'Missing answer image: {path}/{name}')
                for rectangle in regions(box):
                    if len(rectangle)!=4 or any(type(v) is not int for v in rectangle):raise ValueError('Region needs four integer coordinates')
    for name in document.get('预期',{}):
        if Path(name).name!=name or not (folder/name).is_file():raise ValueError(f'Missing expected image: {name}')
    return document


def annotation(value, status='reviewed', source='独立审核真值'):
    return {'value':value, 'status':status, 'source':source}


def directory_truth(relative):
    parts=relative.parts
    if parts[0]=='师门' and parts[1]=='拼图':return {'page':'puzzle'}
    if parts[0]=='师门' and parts[1]=='寻物':
        return {'page':'find','question':{'target':parts[2],'text':None},'target_regions':None}
    if parts[0]=='抓鬼':
        if parts[1] in ('寻物','找鬼'):
            target={'上好的兵器':'兵器','未知题目':'unknown'}.get(parts[2],parts[2])
            return {'page':'find','question':{'target':target,'text':None},'target_regions':None}
        if parts[1]=='页面':return {'page':PAGES[parts[2]]}
        if parts[1]=='拼图':return {'page':'puzzle','puzzle_family':parts[2]}
        if parts[1]=='次数识别':return {'count':int(parts[2][3:-1])}
    if parts[0]=='副本':
        page=DUNGEON.get('/'.join(parts[1:-1]))
        return {'page':page} if page else {}
    return {}


def load_cases(task=None):
    cases=[];documents={}
    for key,name in TASKS.items():
        if task and task not in (key,name):continue
        for image in sorted((ROOT/name).rglob('*.png')):
            relative=image.relative_to(ROOT)
            if '审核依据' in relative.parts or '连续帧' in relative.parts:continue
            if relative.parts[1] in ('寻物','找鬼','拼图') and not (image.parent/'答案.json').is_file():
                raise ValueError(f'Recognition input has no approved answer file; move it to the annotation queue: {relative}')
            if image.parent not in documents:documents[image.parent]=read_answers(image.parent)
            document=documents[image.parent]
            extra=document.get('预期',{}).get(image.name,{})
            values=directory_truth(relative.parent)
            values.update({k:v for k,v in extra.items() if k not in ('不检查','用途','合成')})
            for section,field in [('正确','target_regions'),('反例','negative_regions')]:
                boxes=[box for loc in document.get(section,{}).values() if image.name in loc for box in regions(loc[image.name])]
                if boxes:values[field]=sorted(map(list,{tuple(b) for b in boxes}))
            if 'target_regions' in values and values['target_regions'] is not None:
                values.setdefault('target_regions_complete',False)
            with image.open('rb') as stream:header=stream.read(24)
            if header[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError(f'Invalid PNG: {relative}')
            size=list(struct.unpack('>II',header[16:24]))
            truth={k:annotation(v,'pending' if v is None else 'reviewed',relative.parent.as_posix()) for k,v in values.items()}
            checks=[k for k in truth if k not in ('target_regions_complete',*DUNGEON_CARD_FIELDS)
                    and k not in extra.get('不检查',[])]
            cases.append({'id':relative.as_posix(),'task':key,'image':relative.as_posix(),
                'capture':{'size':size,'group':relative.parent.as_posix(),
                           'split':extra.get('用途','calibration'),'origin':'synthetic' if extra.get('合成') else 'device'},
                'truth':truth,'expected':{'checks':checks}})
    return cases


def image_path(case):
    return resolved_image(case['image'],bool(case.get('augmentation')))


@lru_cache(maxsize=16384)
def resolved_image(image,augmented):
    base=resolved_base(ROOT.parent/'.tmp/perception/augmentation' if augmented else ROOT)
    path=(base/image).resolve()
    if not path.is_relative_to(base):raise ValueError('Image path escapes the corpus')
    return path


@lru_cache(maxsize=4)
def resolved_base(base):
    return base.resolve()


def validate(case, frame=None):
    path=image_path(case)
    if frame is None:frame=cv2.imdecode(np.fromfile(path,dtype=np.uint8),1)
    if frame is None:raise ValueError(f'Unreadable image: {case["id"]}')
    height,width=frame.shape[:2]
    if [width,height]!=case['capture']['size']:raise ValueError('Frame dimensions differ from truth')
    validate_truth(case,width,height)
    return path


def validate_truth(case,width,height):
    """Metadata checks can use the PNG header; evaluation checks decoded pixels."""
    for field in case['truth'].values():
        if field['status'] not in VERIFIED|{'pending','proposed'}:raise ValueError('Unknown annotation status')
        if field['status'] in VERIFIED and (field['value'] is None or not field['source']):
            raise ValueError('Approved truth needs a value and evidence')
    if not set(case['expected']['checks']).issubset(case['truth']):raise ValueError('Missing independent truth')
    for name in ('target_regions','negative_regions',*DUNGEON_CARD_FIELDS):
        boxes=case['truth'].get(name,{}).get('value') or []
        if name.endswith('_card') and boxes:boxes=[boxes]
        for x1,y1,x2,y2 in boxes:
            if not 0<=x1<x2<=width or not 0<=y1<y2<=height:raise ValueError('Region outside image')


def load_rounds(task='zhuagui'):
    rounds=[]
    names=('抓鬼','师门') if task is None else (TASKS.get(task,task),)
    folders=[p for name in names for p in (ROOT/name/'寻物').glob('*/第*轮')]
    for folder in sorted(folders):
        doc=read_answers(folder)
        rounds.append({'id':folder.relative_to(ROOT).as_posix(),
            'topic':{'上好的兵器':'兵器'}.get(folder.parent.name,folder.parent.name),
            'frames':[p.relative_to(ROOT).as_posix() for p in sorted(folder.glob('*.png'))],
            'answers':doc.get('正确',{})})
    return rounds


def crop_sources(cases):
    """One representative per approved answer, not a separate seed registry."""
    available={c['id']:c for c in cases};selected={};visited=set()
    for case in cases:
        if case['task']=='shimen':
            for field,positive in [('target_regions',True),('negative_regions',False)]:
                if case['truth'].get(field,{}).get('status') not in VERIFIED:continue
                for box in case['truth'].get(field,{}).get('value') or []:
                    selected.setdefault(case['id'],[]).append({'label':field,'region':box,'positive':positive})
            continue
        folder=ROOT/Path(case['image']).parent
        if folder in visited or case.get('augmentation'):continue
        visited.add(folder)
        for section,positive in [('正确',True),('反例',False)]:
            for label,locations in read_answers(folder).get(section,{}).items():
                if not locations:continue
                name,boxes=next(iter(locations.items()));box=regions(boxes)[0]
                identity=(folder/name).relative_to(ROOT).as_posix()
                if identity in available and available[identity]['truth'].get('page',{}).get('value')=='find':
                    field='target_regions' if positive else 'negative_regions'
                    if available[identity]['truth'].get(field,{}).get('status') not in VERIFIED:continue
                    selected.setdefault(identity,[]).append({'label':label,'region':box,'positive':positive})
    return selected


def transform(tile,mirror,turn):
    return np.rot90(tile[:,::-1] if mirror else tile,-turn)


def iter_variants(case,crops,original=None,persist=True,canvases=None):
    if original is None:original=cv2.imdecode(np.fromfile(image_path(case),dtype=np.uint8),1)
    validate(case,original)
    if case['task']=='shimen' and case['truth'].get('page',{}).get('value')=='find':
        if canvases is not None and (canvases.shape!=(8,*original.shape) or canvases.dtype!=original.dtype):
            raise ValueError('Eight canvases must have the original shape and dtype')
        # Transform every approved icon together: eight frames, not eight
        # full-screen copies per object. Every positive and negative is scored.
        for mirror in (False,True):
            for turn in range(4):
                canvas=original.copy() if canvases is None else canvases[int(mirror)*4+turn]
                if canvases is not None:canvas[:]=original
                for crop in crops:
                    x1,y1,x2,y2=crop['region'];tile=transform(original[y1:y2,x1:x2],mirror,turn)
                    if tile.shape[:2]!=(y2-y1,x2-x1):raise ValueError('Inventory crop must be square')
                    canvas[y1:y2,x1:x2]=tile
                relative=Path(case['id']).with_suffix('')/f'全部物品_{int(mirror)}_{turn*90}度.png'
                derived={**case,'id':relative.as_posix(),'image':relative.as_posix(),
                    'capture':{**case['capture'],'origin':'synthetic'},'truth':deepcopy(case['truth']),
                    'augmentation':{'parent':case['id'],'crop':[63,535,829,1410],
                                    'mirror':mirror,'turn':turn,'regions':[c['region'] for c in crops]}}
                if persist:
                    path=image_path(derived);path.parent.mkdir(parents=True,exist_ok=True)
                    cv2.imencode('.png',canvas)[1].tofile(path);yield derived
                else:yield derived,canvas
        return
    for index,crop in enumerate(crops,1):
        x1,y1,x2,y2=crop['region'];tile=original[y1:y2,x1:x2]
        for mirror in (False,True):
            for turn in range(4):
                rotated=transform(tile,mirror,turn);height,width=rotated.shape[:2]
                x,y=((100,650),(360,900),(650,1150))[(turn+2*int(mirror))%3]
                canvas=original.copy();canvas[535:1435,15:887]=(215,204,185)
                canvas[y:y+height,x:x+width]=rotated
                name=f'{index:02d}_{crop["label"]}_{"镜像" if mirror else "原向"}_{turn*90}度.png'
                relative=Path(case['id']).with_suffix('')/name
                derived={'id':relative.as_posix(),'task':case['task'],'image':relative.as_posix(),
                    'capture':{**case['capture'],'origin':'synthetic'},
                    'truth':{k:deepcopy(case['truth'][k]) for k in ('page','question')},
                    'augmentation':{'parent':case['id'],'crop':crop['region'],'label':crop['label'],
                                    'mirror':mirror,'turn':turn,'destination':[x,y,x+width,y+height]}}
                field='target_regions' if crop['positive'] else 'negative_regions'
                derived['truth'][field]=annotation([[x,y,x+width,y+height]])
                if crop['positive']:derived['truth']['target_regions_complete']=annotation(True)
                else:derived['truth']['forbidden_actions']=annotation(['tap'])
                derived['expected']={'checks':['page','question',field]+([] if crop['positive'] else ['forbidden_actions'])}
                if persist:
                    path=image_path(derived);path.parent.mkdir(parents=True,exist_ok=True)
                    data=cv2.imencode('.png',canvas,[cv2.IMWRITE_PNG_COMPRESSION,1])[1].tobytes()
                    if not path.exists() or path.read_bytes()!=data:path.write_bytes(data)
                    yield derived
                else:
                    yield derived,canvas
    field_name='puzzle_locations' if case['task']=='shimen' else 'puzzle_order'
    field=case['truth'].get(field_name,{})
    if field.get('status') not in VERIFIED:return
    cells=json.loads((ROOT/TASKS[case['task']]/'拼图/格位.json').read_text(encoding='utf-8'))
    tiles=[original[y1:y2,x1:x2].copy() for x1,y1,x2,y2 in cells]
    for permutation in itertools.permutations(range(4)):
        if permutation==(0,1,2,3):continue  # The original is evaluated once.
        canvas=original.copy()
        for cell,source in zip(cells,permutation):
            x1,y1,x2,y2=cell;canvas[y1:y2,x1:x2]=tiles[source]
        order=([permutation.index(cell-1)+1 for cell in field['value']] if field_name=='puzzle_locations'
               else ''.join(chr(65+permutation.index(ord(letter)-65)) for letter in field['value']))
        relative=Path(case['id']).with_suffix('')/('四格_'+''.join(chr(65+i) for i in permutation)+'.png')
        derived={'id':relative.as_posix(),'task':case['task'],'image':relative.as_posix(),
                 'capture':{**case['capture'],'origin':'synthetic'},
                 'truth':deepcopy(case['truth']),'expected':deepcopy(case['expected']),
                 'augmentation':{'parent':case['id'],'crop':[cells[0][0],cells[0][1],cells[-1][2],cells[-1][3]],
                                 'cells':cells,'permutation':list(permutation)}}
        derived['truth'][field_name]=annotation(order)
        if persist:
            path=image_path(derived);path.parent.mkdir(parents=True,exist_ok=True)
            cv2.imencode('.png',canvas)[1].tofile(path)
            yield derived
        else:yield derived,canvas


def evaluation_cases(cases):
    crops=crop_sources(cases)
    for case in cases:
        yield case
        yield from iter_variants(case,crops.get(case['id'],[]))


def audit(cases):
    return {task:{'frames':sum(c['task']==task for c in cases)} for task in sorted({c['task'] for c in cases})}

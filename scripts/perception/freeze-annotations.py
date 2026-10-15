"""Freeze explicitly confirmed queue rounds; never consume AI proposals."""
import json
import argparse
import shutil
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from itertools import repeat
import cv2
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib import annotation_queue as queue
from scripts.perception.lib import capture_feedback
from scripts.perception.lib.corpus import read_answers,regions
from scripts.perception.lib.task_review import compose_rows
SUPPORTED={('师门','寻物'),('师门','拼图'),('抓鬼','寻物'),('抓鬼','找鬼'),('抓鬼','拼图')}
WINES={'虎骨酒','蛇胆酒','梅花酒','珍露酒'}


def prepare(identity,allow_partial=False):
    cv2.setNumThreads(1)
    task,kind=Path(identity).parts[:2]
    if (task,kind) not in SUPPORTED:raise ValueError(f'Unsupported annotation type: {identity}')
    folder=queue.resolve('confirmed',identity)
    if not (folder/'审核.md').is_file():raise ValueError(f'Missing approval: {identity}')
    feedback=capture_feedback.verify(folder,task,kind)
    if feedback['status']!='complete':
        capture_feedback.warn(identity,feedback)
        if not allow_partial:
            raise ValueError(f'采集不完整或未核验 [{identity}]: '+
                '；'.join(feedback['reasons'])+' 若仅固化已确认局部，须显式使用 --allow-partial 并保留采集反馈。')
    doc=read_answers(folder)
    files=sorted(folder.glob('第*页.png'))
    if kind=='拼图':
        from PIL import Image
        images={}
        for path in files:
            with Image.open(path) as image:images[path.name]={'size':list(image.size)}
        queue.validate_puzzle_document(doc,images,task,complete=True)
        return identity,doc,4*len(files),feedback
    _,_,_,layers=compose_rows({i:{'id':p.name,'image':p.name} for i,p in enumerate(files)},lambda c:folder/c['image'])
    output={};mapped=0
    for section in ('正确','反例'):
        groups={}
        for topic,locations in doc.get(section,{}).items():
            target={}
            for name,boxes in locations.items():
                for box in regions(boxes):
                    aliases=[{'image':name,'source':[0,0,900,1600]}]
                    origin=aliases[0]
                    for layer in layers:
                        found=next((a for a in layer['aliases'] if a['image']==name and
                            a['source'][0]<=box[0]<box[2]<=a['source'][2] and
                            a['source'][1]<=box[1]<box[3]<=a['source'][3]),None)
                        if found:origin=found;aliases=layer['aliases'];break
                    for alias in aliases:
                        dx=alias['source'][0]-origin['source'][0];dy=alias['source'][1]-origin['source'][1]
                        b=[box[0]+dx,box[1]+dy,box[2]+dx,box[3]+dy]
                        if b not in target.setdefault(alias['image'],[]):target[alias['image']].append(b)
                    mapped+=1
            groups[topic]={n:sorted(bs) for n,bs in sorted(target.items())}
        output[section]=groups
    for topic,locations in output['正确'].items():
        for name,boxes in locations.items():
            if set(map(tuple,boxes))&set(map(tuple,output['反例'].get(topic,{}).get(name,[]))):
                raise ValueError(f'Conflicting confirmed labels: {identity}/{name}')
    return identity,output,mapped,feedback


def compact(document):
    if '预期' in document:return json.dumps(document,ensure_ascii=False,indent=2)+'\n'
    lines=['{']
    for si,(section,groups) in enumerate(document.items()):
        lines.append('  '+json.dumps(section,ensure_ascii=False)+': {')
        for gi,(topic,locations) in enumerate(groups.items()):
            lines.append('    '+json.dumps(topic,ensure_ascii=False)+': {')
            for ni,(name,boxes) in enumerate(locations.items()):
                lines.append('      '+json.dumps(name,ensure_ascii=False)+': '+json.dumps(boxes,separators=(',',':'))+(',' if ni+1<len(locations) else ''))
            lines.append('    }'+(',' if gi+1<len(groups) else ''))
        lines.append('  }'+(',' if si+1<len(document) else ''))
    return '\n'.join(lines+['}'])+'\n'


def select_items(items,wine_cases=None):
    selected=[item for item in items if (item['task'],item['kind']) in SUPPORTED]
    if wine_cases is None:return selected
    result=[item for item in selected if item['topic'] not in WINES]
    for topic in sorted(WINES):
        candidates=[item for item in selected if item['topic']==topic]
        candidates.sort(key=lambda item:(-(item['capture_feedback'].get('image_height') or 0),item['id']))
        result.extend(candidates[:wine_cases])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update',action='store_true',help='Apply changed, explicitly confirmed answers to their existing rounds')
    parser.add_argument('--allow-partial',action='store_true',help='Freeze confirmed visible regions with explicit incomplete/unverified capture feedback; never claim a full round')
    parser.add_argument('--id',action='append',help='Only freeze these confirmed queue identities')
    parser.add_argument('--wine-cases',type=int,help='Keep this many confirmed rounds per named wine, preferring taller strips')
    args=parser.parse_args()
    if args.wine_cases is not None and args.wine_cases<1:parser.error('--wine-cases must be positive')
    items=select_items(queue.items('confirmed'),args.wine_cases)
    if args.id:
        found={item['id']:item for item in items}
        missing=set(args.id)-set(found)
        if missing:parser.error('Unknown supported confirmed input: '+', '.join(sorted(missing)))
        items=[found[identity] for identity in args.id]
    with ProcessPoolExecutor(max_workers=8) as pool:prepared=list(pool.map(prepare,[i['id'] for i in items],repeat(args.allow_partial)))
    counts={};existing={};report=[]
    for target in (ROOT/'testdata').glob('*/*/*/第*轮'):
        key=target.relative_to(ROOT/'testdata').parts[:3]
        counts[key]=max(counts.get(key,0),int(target.name[1:-1]))
    for history in (ROOT/'testdata').rglob('审核.md'):
        target=history.parent
        if history.is_file():
            for line in history.read_text(encoding='utf-8').splitlines():
                if line.startswith('原确认归档：'):existing[line.split('：',1)[1].split('。',1)[0]]=target
    for identity,document,mapped,feedback in prepared:
        source=queue.resolve('confirmed',identity);task,kind,topic=Path(identity).parts[:3];key=(task,kind,topic)
        target=existing.get(identity)
        if target is None:
            if kind=='拼图':target=ROOT/'testdata'/task/kind/topic
            else:
                counts[key]=counts.get(key,0)+1
                target=ROOT/'testdata'/task/kind/topic/f'第{counts[key]:02d}轮'
        if kind=='拼图' and target.exists():
            merged=read_answers(target)
            merged.setdefault('预期',{})
            planned=[];names={p.name for p in target.glob('*.png')}
            for image in sorted(source.glob('第*页.png')):
                name=image.name
                if name in names and (not (target/name).exists() or image.read_bytes()!=(target/name).read_bytes()):
                    ordinal=1
                    while f'第{ordinal:02d}页.png' in names:ordinal+=1
                    name=f'第{ordinal:02d}页.png'
                if name in merged['预期'] and merged['预期'][name]!=document['预期'][image.name]:raise ValueError('Confirmed puzzle answers conflict')
                merged['预期'][name]=document['预期'][image.name]
                names.add(name);planned.append((image,target/name))
            for image,destination in planned:
                if not destination.exists():shutil.copyfile(image,destination)
            (target/'答案.json').write_text(compact(merged),encoding='utf-8')
            if identity not in existing:
                with (target/'审核.md').open('a',encoding='utf-8') as stream:stream.write(f'\n原确认归档：{identity}。\n')
            queue.remove_frozen(identity,target)
            report.append({'source':identity,'case':target.relative_to(ROOT/'testdata').as_posix(),'approved_regions':mapped,
                'capture_status':feedback['status'],'can_use_as_complete':feedback['can_use_as_complete']})
            continue
        if target.exists():
            original_names={p.name for p in source.glob('第*页.png')}
            if original_names!={p.name for p in target.glob('第*页.png')}:
                raise ValueError(f'Original image set changed: {target}')
            for name in original_names:
                if (source/name).read_bytes()!=(target/name).read_bytes():
                    raise ValueError(f'Original image changed: {target/name}')
            if read_answers(target)!=document:
                if not args.update:raise ValueError(f'Confirmed answers changed; review and use --update: {target}')
                backup=ROOT/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'annotation-corrections'/target.relative_to(ROOT/'testdata')
                backup.mkdir(parents=True,exist_ok=True)
                for name in ('答案.json','审核.md'):shutil.copyfile(target/name,backup/name)
                (target/'答案.json').write_text(compact(document),encoding='utf-8')
                with (target/'审核.md').open('a',encoding='utf-8') as stream:
                    stream.write('\n已按用户重新确认的归档更正：\n'+(source/'审核.md').read_text(encoding='utf-8').replace('尚未写入正式测试真值','现已固化正式测试真值'))
        else:
            target.mkdir(parents=True)
            # Retain every input: scroll overlap alone is not duplicate evidence.
            for image in source.glob('第*页.png'):shutil.copyfile(image,target/image.name)
            (target/'答案.json').write_text(compact(document),encoding='utf-8')
            (target/'审核.md').write_text((source/'审核.md').read_text(encoding='utf-8').replace('尚未写入正式测试真值','现已固化正式测试真值')+
                f'\n原确认归档：{identity}。重叠页位置沿用同一物品行的原图映射；未标区域仍为未知。\n',encoding='utf-8')
        assert read_answers(target)==document
        for image in source.glob('第*页.png'):assert image.read_bytes()==(target/image.name).read_bytes()
        capture_feedback.write(target,feedback)
        report.append({'source':identity,'case':target.relative_to(ROOT/'testdata').as_posix(),'approved_regions':mapped,
            'capture_status':feedback['status'],'can_use_as_complete':feedback['can_use_as_complete'],
            'mapped_regions':sum(len(bs) for g in document.values() for loc in g.values() for bs in loc.values())})
        queue.remove_frozen(identity,target)
    output=ROOT/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'annotation-freeze';output.mkdir(parents=True)
    (output/'核对.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    topics={Path(item['source']).parts[:3] for item in report}
    print(f'Frozen {len(report)} inputs, {len(topics)} topics. Evidence: {output}')

if __name__=='__main__':main()

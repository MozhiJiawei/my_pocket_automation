"""Freeze explicitly confirmed queue rounds; never consume AI proposals."""
import json
import argparse
import shutil
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
import cv2
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib import annotation_queue as queue
from scripts.perception.lib.corpus import read_answers
from scripts.perception.lib.task_review import compose_rows


def prepare(identity):
    cv2.setNumThreads(1)
    if Path(identity).parts[:2]!=('师门','寻物'):raise ValueError(f'Unsupported annotation type: {identity}')
    folder=queue.resolve('confirmed',identity)
    if not (folder/'审核.md').is_file():raise ValueError(f'Missing approval: {identity}')
    doc=read_answers(folder)
    files=sorted(folder.glob('第*页.png'))
    _,_,_,layers=compose_rows({i:{'id':p.name,'image':p.name} for i,p in enumerate(files)},lambda c:folder/c['image'])
    output={};mapped=0
    for section in ('正确','反例'):
        groups={}
        for topic,locations in doc.get(section,{}).items():
            target={}
            for name,boxes in locations.items():
                for box in boxes:
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
    return identity,output,mapped


def compact(document):
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update',action='store_true',help='Apply changed, explicitly confirmed answers to their existing rounds')
    args=parser.parse_args()
    items=[item for item in queue.items('confirmed') if (item['task'],item['kind'])==('师门','寻物')]
    with ProcessPoolExecutor(max_workers=8) as pool:prepared=list(pool.map(prepare,[i['id'] for i in items]))
    counts={};existing={};report=[]
    for target in (ROOT/'testdata/师门/寻物').glob('*/第*轮'):
        counts[target.parent.name]=max(counts.get(target.parent.name,0),int(target.name[1:-1]))
        history=target/'审核.md'
        if history.is_file():
            for line in history.read_text(encoding='utf-8').splitlines():
                if line.startswith('原确认归档：'):existing[line.split('：',1)[1].split('。',1)[0]]=target
    for identity,document,mapped in prepared:
        source=queue.resolve('confirmed',identity);topic=source.parent.name
        target=existing.get(identity)
        if target is None:
            counts[topic]=counts.get(topic,0)+1
            target=ROOT/'testdata/师门/寻物'/topic/f'第{counts[topic]:02d}轮'
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
        report.append({'source':identity,'case':target.relative_to(ROOT/'testdata').as_posix(),'approved_regions':mapped,
            'mapped_regions':sum(len(bs) for g in document.values() for loc in g.values() for bs in loc.values())})
    output=ROOT/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'annotation-freeze';output.mkdir(parents=True)
    (output/'核对.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Frozen {len(report)} rounds, {len(counts)} topics. Evidence: {output}')

if __name__=='__main__':main()

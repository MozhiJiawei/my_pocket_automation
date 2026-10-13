"""Generate device color signatures from approved calibration answers, never predictions."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.corpus import image_path, load_cases, validate, load_rounds, regions


def sample(crop):
    hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
    foreground=(np.min(crop,axis=2)<140)|(hsv[:,:,1]>85)
    foreground[:10]=False; foreground[-10:]=False
    foreground[:,:10]=False; foreground[:,-10:]=False
    contrast=np.max(cv2.dilate(crop,np.ones((3,3),np.uint8)).astype(int)-
                    cv2.erode(crop,np.ones((3,3),np.uint8)).astype(int),axis=2)
    candidates=np.column_stack(np.where(foreground&(contrast<45)))[:,::-1]
    if len(candidates)<200:
        candidates=np.column_stack(np.where(foreground))[:,::-1]
    if len(candidates)<16:
        raise ValueError('Too little item foreground')
    colors=crop[candidates[:,1],candidates[:,0]].astype(int)
    # Rare foreground anchor reduces scanning; distributed colors encode shape.
    keys=(colors//32)@np.array([64,8,1])
    unique,counts=np.unique(keys,return_counts=True)
    frequency=dict(zip(unique,counts))
    chosen=[int(np.argmin([frequency[k] for k in keys]))]
    spatial=chroma=None
    for _ in range(23):
        distance=np.sum((candidates-candidates[chosen[-1]])**2,axis=1)
        color_distance=np.sum((colors-colors[chosen[-1]])**2,axis=1)
        spatial=distance if spatial is None else np.minimum(spatial,distance)
        chroma=color_distance if chroma is None else np.minimum(chroma,color_distance)
        score=np.where(spatial>=16,spatial+chroma*.08,-1)
        index=int(np.argmax(score))
        if score[index]<0:break
        chosen.append(index)
    points=candidates[chosen]
    if len(points)<16:raise ValueError('Insufficient distributed signature points')
    return [(int(x),int(y),int(crop[y,x,2])*65536+int(crop[y,x,1])*256+int(crop[y,x,0])) for x,y in points]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--task',choices=['zhuagui','shimen'],default='zhuagui');args=parser.parse_args()
    cv2.setNumThreads(1)
    cases={c['id']:c for c in load_cases(args.task)}
    frames={}
    groups={}; provenance=[]; seen=set()
    # Newer approved appearances get first chance within the time-limited list.
    for entry in reversed(load_rounds(args.task)):
        if not entry['frames'] or entry['frames'][0] not in cases:continue
        for label,locations in entry['answers'].items():
            sources=[(name,box) for name,boxes in locations.items() for box in regions(boxes)]
            if args.task=='zhuagui':sources=sources[:1]
            for name,box in sources:
                case=cases[entry['id']+'/'+name]
                if case['capture']['split']!='calibration':raise ValueError('Cannot train from holdout')
                if case['id'] not in frames:frames[case['id']]=cv2.imdecode(np.fromfile(validate(case),dtype=np.uint8),1)
                frame=frames[case['id']];x1,y1,x2,y2=box;crop=frame[y1:y2,x1:x2]
                digest=hashlib.sha256(crop.tobytes()).hexdigest()
                if (entry['topic'],digest) in seen:continue
                seen.add((entry['topic'],digest));points=sample(crop);ax,ay,base=points[0]
                offsets=','.join(f'{x-ax}|{y-ay}|0x{color:06x}' for x,y,color in points[1:])
                identity=f'{entry["id"]}/{label}' if args.task=='zhuagui' else f'{case["id"]}:{x1},{y1},{x2},{y2}'
                feature={'width':900,'height':1600,'base':base,'offsets':offsets,'degree':90,
                         'region':[65,535,829,1410],'tap_offset':[(x2-x1)//2-ax,(y2-y1)//2-ay],
                         'calibration_id':identity}
                if args.task=='zhuagui':feature['region']=[65,540,825,1405]
                groups.setdefault(entry['topic'],[]).append(feature)
                provenance.append({'id':identity,'case_id':case['id'],'region':box,'label':label,'split':case['capture']['split']})
    folder=ROOT/'src/tasks'/args.task/'assets';folder.mkdir(parents=True,exist_ok=True)
    lines=['-- Generated from approved calibration answers; regenerate with calibrate-reviewed-items.py.','return {']
    for topic,features in sorted(groups.items()):
        lines.append('['+json.dumps(topic,ensure_ascii=False)+']={')
        for f in features:
            lines.append('{width=900,height=1600,base=0x%06x,offsets=%s,degree=90,region={%d,%d,%d,%d},tap_offset={%d,%d},calibration_id=%s},'%(
                f['base'],json.dumps(f['offsets']),*f['region'],*f['tap_offset'],json.dumps(f['calibration_id'],ensure_ascii=False)))
        lines.append('},')
    lines.append('}')
    work=folder if args.task=='zhuagui' else ROOT/'.tmp/perception/calibration/shimen'
    work.mkdir(parents=True,exist_ok=True)
    (work/'reviewed_items.lua').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (work/'reviewed_items.json').write_text(json.dumps({
        'backend':'device_multicolor','points':24,'tolerance_offline':25,'samples':provenance},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.task=='shimen':
        from tests.support.lua_runtime import Runtime
        from tests.support.touchsprite_adapter import Screen
        title_runtime=Runtime(Screen(next(iter(frames.values()))))
        title=title_runtime.require('tasks.zhuagui.assets.find_title')
        def literal(feature):
            return '{width=900,height=1600,base=0x%06x,offsets=%s,degree=90,region={%d,%d,%d,%d},tap_offset={0,0}}'%(feature['base'],json.dumps(feature['offsets']),*feature['region'])
        title_feature={k:title[k] for k in ('base','offsets')};title_feature['region']=[int(title['region'][i]) for i in range(1,5)]
        title_runtime.close()
        questions={};question_seen=set();signature_seen=set()
        for case in cases.values():
            if case['id'] not in frames:frames[case['id']]=cv2.imdecode(np.fromfile(validate(case),dtype=np.uint8),1)
            crop=frames[case['id']][325:425,78:610];topic=case['truth']['question']['value']['target']
            key=(topic,hashlib.sha256(crop.tobytes()).digest())
            if key in question_seen:continue
            question_seen.add(key);points=sample(crop);ax,ay,base=points[0]
            feature={'base':base,'offsets':','.join(f'{x-ax}|{y-ay}|0x{color:06x}' for x,y,color in points[1:]),'region':[65,310,660,435]}
            signature=(topic,feature['base'],feature['offsets'])
            if signature in signature_seen:continue
            signature_seen.add(signature)
            questions.setdefault(topic,[]).append(feature)
        lines=['-- Generated from approved question images.','return {title='+literal(title_feature)+',topics={']
        for topic,features in sorted(questions.items()):lines.append('{name='+json.dumps(topic,ensure_ascii=False)+',features={'+','.join(literal(f) for f in features)+'}},')
        lines.append('}}');(folder/'questions.lua').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({topic:len(v) for topic,v in groups.items()},ensure_ascii=True))


if __name__=='__main__':main()

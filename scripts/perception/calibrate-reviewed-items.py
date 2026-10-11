"""Generate device color signatures from approved calibration answers, never predictions."""
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
    for _ in range(23):
        spatial=np.min(np.sum((candidates[:,None]-candidates[chosen][None,:])**2,axis=2),axis=1)
        chroma=np.min(np.sum((colors[:,None]-colors[chosen][None,:])**2,axis=2),axis=1)
        score=np.where(spatial>=16,spatial+chroma*.08,-1)
        index=int(np.argmax(score))
        if score[index]<0:break
        chosen.append(index)
    points=candidates[chosen]
    if len(points)<16:raise ValueError('Insufficient distributed signature points')
    return [(int(x),int(y),int(crop[y,x,2])*65536+int(crop[y,x,1])*256+int(crop[y,x,0])) for x,y in points]


def main():
    cases={c['id']:c for c in load_cases('zhuagui')}
    groups={}; provenance=[]; seen=set()
    # Newer approved appearances get first chance within the time-limited list.
    for entry in reversed(load_rounds()):
        for label,locations in entry['answers'].items():
            name,boxes=next(iter(locations.items()));box=regions(boxes)[0]
            case=cases[entry['id']+'/'+name]
            if case['capture']['split']!='calibration':raise ValueError('Cannot train from holdout')
            frame=cv2.imdecode(np.fromfile(validate(case),dtype=np.uint8),1)
            x1,y1,x2,y2=box;crop=frame[y1:y2,x1:x2]
            digest=hashlib.sha256(crop.tobytes()).hexdigest()
            if (entry['topic'],digest) in seen:continue
            seen.add((entry['topic'],digest))
            points=sample(crop);ax,ay,base=points[0]
            offsets=','.join(f'{x-ax}|{y-ay}|0x{color:06x}' for x,y,color in points[1:])
            feature={'width':900,'height':1600,'base':base,'offsets':offsets,'degree':90,
                     'region':[65,540,825,1405],'tap_offset':[(x2-x1)//2-ax,(y2-y1)//2-ay],
                     'calibration_id':f'{entry["id"]}/{label}'}
            groups.setdefault(entry['topic'],[]).append(feature)
            provenance.append({'id':feature['calibration_id'],'case_id':case['id'],
                               'region':box,'label':label,'split':case['capture']['split']})
    folder=ROOT/'src/tasks/zhuagui/assets'
    lines=['-- Generated from approved calibration answers; regenerate with calibrate-reviewed-items.py.','return {']
    for topic,features in sorted(groups.items()):
        lines.append('['+json.dumps(topic,ensure_ascii=False)+']={')
        for f in features:
            lines.append('{width=900,height=1600,base=0x%06x,offsets=%s,degree=90,region={65,540,825,1405},tap_offset={%d,%d},calibration_id=%s},'%(
                f['base'],json.dumps(f['offsets']),*f['tap_offset'],json.dumps(f['calibration_id'])))
        lines.append('},')
    lines.append('}')
    (folder/'reviewed_items.lua').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (folder/'reviewed_items.json').write_text(json.dumps({
        'backend':'device_multicolor','points':24,'tolerance_offline':25,'samples':provenance},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({topic:len(v) for topic,v in groups.items()},ensure_ascii=True))


if __name__=='__main__':main()

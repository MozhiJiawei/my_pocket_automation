"""Precompute and remove redundant signatures offline; never modify test truth."""
import argparse
import json
from pathlib import Path
import re
import sys
import cv2
import numpy as np
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.corpus import load_cases,validate
from tests.support.touchsprite_adapter import Screen
NAMED_WINE_KEYS={'虎骨酒':'tiger_wine','蛇胆酒':'snake_wine','梅花酒':'plum_wine','珍露酒':'dew_wine'}


def oriented(source,mirror,turn):
    def point(x,y):
        x=-x if mirror else x
        for _ in range(turn): x,y=-y,x
        return x,y
    offsets=[]
    for x,y,color in re.findall(r'(-?\d+)\|(-?\d+)\|(0x[\da-f]+)',source['offsets']):
        x,y=point(int(x),int(y)); offsets.append(f'{x}|{y}|{color}')
    return {'base':source['base'],'offsets':','.join(offsets),
            'tap_offset':point(source['tap_offset'][1],source['tap_offset'][2]),
            'rotation':turn,'mirror':mirror,'calibration_id':source['calibration_id']}


def covered(tile,features):
    screen=Screen(tile);h,w=tile.shape[:2]
    for feature in features:
        x,y=screen.find(feature['base'],feature['offsets'],90,0,0,w-1,h-1)
        if x>=0:
            dx,dy=feature['tap_offset']
            if 0<=x+dx<w and 0<=y+dy<h:return True
    return False


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--task',choices=['zhuagui','shimen'],default='zhuagui');args=parser.parse_args()
    cv2.setNumThreads(1)
    folder=ROOT/'src/tasks'/args.task/'assets'
    cases={c['id']:c for c in load_cases(args.task)}
    frames={}
    work=folder if args.task=='zhuagui' else ROOT/'.tmp/perception/calibration/shimen'
    lua=LuaRuntime()
    groups=lua.execute((work/'reviewed_items.lua').read_text(encoding='utf-8'))
    ghosts=lua.execute((folder/'reviewed_ghosts.lua').read_text(encoding='utf-8')) if args.task=='zhuagui' else lua.table()
    evidence=json.loads((work/'reviewed_items.json').read_text(encoding='utf-8'))['samples']
    index={entry['id']:entry for entry in evidence}
    ghost_evidence=json.loads((folder/'reviewed_ghosts.json').read_text(encoding='utf-8')) if args.task=='zhuagui' else []
    catalog={};audit={}
    for key,sources in list(groups.items())+list(ghosts.items()):
        key=NAMED_WINE_KEYS.get(key,key)
        selected=catalog.get(key,[]);count=audit.get(key,{}).get('expanded',0)
        for ordinal,source in sources.items():
            ref=index.get(source['calibration_id'])
            if ref is None:
                ref=[e for e in ghost_evidence if e['name']==key][int(ordinal)-1]
            case=cases[ref['case_id']]
            if case['capture']['split']!='calibration':raise ValueError('Holdout cannot compile resources')
            if case['id'] not in frames:frames[case['id']]=cv2.imdecode(np.fromfile(validate(case),dtype=np.uint8),1)
            frame=frames[case['id']]
            x1,y1,x2,y2=ref['region'];tile=frame[y1:y2,x1:x2]
            for mirror in (False,True):
                for turn in range(4):
                    count+=1
                    transformed=np.ascontiguousarray(np.rot90(tile[:,::-1] if mirror else tile,-turn))
                    if not covered(transformed,selected):selected.append(oriented(source,mirror,turn))
        catalog[key]=selected;audit[key]={'expanded':count,'retained':len(selected)}
    if args.task=='zhuagui' and 'skeleton' not in catalog:
        # Preserve the old unverified skeleton feature; do not claim new coverage.
        source=lua.execute((folder/'icon_skeleton.lua').read_text(encoding='utf-8'))
        source['calibration_id']='legacy/icon_skeleton'
        catalog['skeleton']=[oriented(source,m,t) for m in (False,True) for t in range(4)]
    lines=['-- Generated offline; run compile-find-catalog.py. No runtime transforms.','return {']
    for key,features in sorted(catalog.items()):
        lines.append('['+json.dumps(key,ensure_ascii=False)+']='+('function() return {' if args.task=='shimen' else '{'))
        for feature in features:
            if args.task=='shimen':
                lines.append('{width=900,height=1600,base=0x%06x,offsets=%s,degree=90,region={65,535,829,1410},tap_offset={%d,%d}},'%(
                    feature['base'],json.dumps(feature['offsets']),*feature['tap_offset']))
                continue
            lines.append('{width=900,height=1600,base=0x%06x,offsets=%s,degree=90,region={%d,%d,%d,%d},tap_offset={%d,%d},rotation=%d,mirror=%s,calibration_id=%s},'%(
                feature['base'],json.dumps(feature['offsets']),*([65,540,825,1405] if args.task=='zhuagui' else [65,535,829,1410]),*feature['tap_offset'],feature['rotation'],
                str(feature['mirror']).lower(),json.dumps(feature['calibration_id'],ensure_ascii=False)))
        lines.append('} end,' if args.task=='shimen' else '},')
    lines.append('}')
    (folder/'catalog.lua').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    sources=['reviewed_items.lua','reviewed_items.json']+(['reviewed_ghosts.lua','reviewed_ghosts.json','icon_skeleton.lua'] if args.task=='zhuagui' else ['questions.lua'])
    audit_folder=folder if args.task=='zhuagui' else ROOT/'debug-runs'/__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')/'catalog-build'
    audit_folder.mkdir(parents=True,exist_ok=True)
    (audit_folder/'catalog.json').write_text(json.dumps({'counts':audit,'sources':sources,
        'deduplication':'host color approximation on approved calibration crops; requires full regression and native verification'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(audit,ensure_ascii=True))


if __name__=='__main__':main()

"""Calibrate invariant 回合 strokes from the reviewed battle failure."""
import json
from pathlib import Path
import sys
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.corpus import load_cases,validate


def main():
    case=next(c for c in load_cases('dungeon') if c['id']=='副本/战斗/场景02/画面.png')
    assert case['capture']['split']=='calibration' and case['truth']['page']['value']=='battle'
    image=cv2.imdecode(np.fromfile(validate(case),dtype=np.uint8),1)
    crop=image[8:52,458:545]
    points=np.column_stack(np.where(np.min(crop,axis=2)>240))[:,::-1]
    chosen=[0]
    for _ in range(23):
        distance=np.min(np.sum((points[:,None]-points[chosen][None,:])**2,axis=2),axis=1)
        chosen.append(int(np.argmax(distance)))
    selected=points[chosen]+[458,8]
    ax,ay=map(int,selected[0])
    def color(x,y):
        b,g,r=map(int,image[y,x]);return r*65536+g*256+b
    offsets=','.join(f'{int(x)-ax}|{int(y)-ay}|0x{color(x,y):06x}' for x,y in selected[1:])
    path=ROOT/'src/common/assets/battle_title.lua'
    path.write_text('return {width=900,height=1600,base=0x%06x,offsets=%s,degree=90,region={450,0,550,60},tap_offset={0,0}}\n'%(color(ax,ay),json.dumps(offsets)),encoding='utf-8')
    path.with_suffix('.json').write_text(json.dumps({'case_id':case['id'],'region':[458,8,545,52],'excludes':'round number and tinted background'},indent=2),encoding='utf-8')


if __name__=='__main__':main()

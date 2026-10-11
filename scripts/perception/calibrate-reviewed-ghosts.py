"""Sample stable icon interiors from independently verified ghost answers."""
import importlib.util
import json
from pathlib import Path
import sys
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.corpus import load_cases,validate,VERIFIED

def main():
    spec=importlib.util.spec_from_file_location('item_sampler',Path(__file__).with_name('calibrate-reviewed-items.py'))
    sampler=importlib.util.module_from_spec(spec);spec.loader.exec_module(sampler)
    cases={c['id']:c for c in load_cases('zhuagui')}
    seeds={'horse':'抓鬼/找鬼/马面/场景01/画面.png','wild':'抓鬼/找鬼/野鬼/场景01/画面.png',
           'bull':'抓鬼/找鬼/牛头/场景01/画面.png','paper':'抓鬼/寻物/黄纸/场景01/画面.png',
           'incense':'抓鬼/寻物/香/第01轮/第03页.png','candle':'抓鬼/寻物/蜡烛/第01轮/第01页.png',
           'zombie':'抓鬼/找鬼/僵尸/场景01/画面.png','snake_wine':'抓鬼/寻物/蛇胆酒/场景01/画面.png'}
    lines=['-- Generated from verified answers; see calibrate-reviewed-ghosts.py.','return {']
    evidence=[]
    for name,cid in seeds.items():
        case=cases[cid];truth=case['truth']['target_regions']
        assert truth['status'] in VERIFIED and case['capture']['split']=='calibration'
        frame=cv2.imdecode(np.fromfile(validate(case),dtype=np.uint8),1)
        lines.append('['+json.dumps(name)+']={')
        for box in truth['value']:
            x1,y1,x2,y2=box;points=sampler.sample(frame[y1:y2,x1:x2]);ax,ay,base=points[0]
            offsets=','.join(f'{x-ax}|{y-ay}|0x{color:06x}' for x,y,color in points[1:])
            lines.append('{width=900,height=1600,base=0x%06x,offsets=%s,degree=90,region={65,540,825,1405},tap_offset={%d,%d},calibration_id=%s},'%(base,json.dumps(offsets),(x2-x1)//2-ax,(y2-y1)//2-ay,json.dumps(cid)))
            evidence.append({'name':name,'case_id':cid,'region':box,'source':truth['source']})
        lines.append('},')
    lines.append('}')
    folder=ROOT/'src/tasks/zhuagui/assets'
    (folder/'reviewed_ghosts.lua').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (folder/'reviewed_ghosts.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    # Calibrated title glyphs, not runtime OCR. Cases have explicit user approval.
    for name in ('bull','paper','incense','candle'):
        case=cases[seeds[name]]
        assert case['truth']['question']['status'] in VERIFIED
        frame=cv2.imdecode(np.fromfile(validate(case),dtype=np.uint8),1)
        box=[184,365,245,402];x1,y1,x2,y2=box
        points=sampler.sample(frame[y1:y2,x1:x2]);ax,ay,base=points[0]
        offsets=','.join(f'{x-ax}|{y-ay}|0x{color:06x}' for x,y,color in points[1:])
        (folder/f'target_{name}.lua').write_text(
            '-- Generated from an approved question; see calibrate-reviewed-ghosts.py.\n'+
            'return {width=900,height=1600,base=0x%06x,offsets=%s,degree=90,region={%d,%d,%d,%d},tap_offset={0,0}}\n'%(
                base,json.dumps(offsets),x1+ax-5,y1+ay-5,x1+ax+5,y1+ay+5),encoding='utf-8')
        (folder/f'target_{name}.json').write_text(json.dumps({'case_id':case['id'],
            'region':box,'source':case['truth']['question']['source']},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()

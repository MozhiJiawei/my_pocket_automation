"""Preserve full-width green digit variants from verified calibration counts."""
import json
from pathlib import Path
import sys
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.corpus import VERIFIED,load_cases,validate

variants={}; sources=[]
for case in load_cases('zhuagui'):
    truth=case['truth'].get('count',{})
    value=truth.get('value')
    if truth.get('status') not in VERIFIED or not isinstance(value,int):continue
    if case['capture']['split']!='calibration':raise ValueError('Cannot train from holdout')
    image=cv2.imdecode(np.fromfile(validate(case),dtype=np.uint8),1)
    # The slash begins at x=807; the old x=803 boundary clipped wider digits.
    b,g,r=cv2.split(image[208:230,740:807]);mask=(g>140)&(r<150)&(b<120)
    columns=np.any(mask,axis=0); runs=[]
    for x,on in enumerate(columns):
        if on and (x==0 or not columns[x-1]):left=x
        if on and (x==len(columns)-1 or not columns[x+1]):runs.append((left,x+1))
    if len(runs)!=len(str(value)):raise ValueError('Reviewed count and glyph components differ')
    for digit,(left,right) in zip(str(value),runs):
        rows=tuple(''.join('1' if v else '0' for v in row) for row in mask[:,left:right])
        variants.setdefault(int(digit),set()).add(rows)
    sources.append({'case_id':case['id'],'count':value})
folder=ROOT/'src/tasks/zhuagui/assets/digits'
lines=['-- Generated from reviewed count samples; full numerator ends before x=807.','return {']
for digit,items in sorted(variants.items()):
    lines.append(f'[{digit}]={{')
    for rows in sorted(items):lines.append('{'+','.join(json.dumps(row) for row in rows)+'},')
    lines.append('},')
lines.append('}')
(folder/'variants.lua').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(folder/'variants.json').write_text(json.dumps({'region':[740,208,807,230],'sources':sources},indent=2)+'\n',encoding='utf-8')
print('Verified digit variants:',{k:len(v) for k,v in variants.items()})

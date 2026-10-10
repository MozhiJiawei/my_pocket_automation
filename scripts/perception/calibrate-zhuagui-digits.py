"""Learn exact green count glyphs from an inspected, unobscured task frame."""
import argparse
from pathlib import Path
import cv2
import numpy as np

p=argparse.ArgumentParser()
p.add_argument('--image',type=Path,required=True)
p.add_argument('--count',required=True)
a=p.parse_args()
frame=cv2.imdecode(np.fromfile(a.image,dtype=np.uint8),1)
crop=frame[208:230,740:803]
b,g,r=cv2.split(crop)
mask=(g>140)&(r<150)&(b<120)
columns=np.any(mask,axis=0)
runs=[]
for x,on in enumerate(columns):
    if on and (x==0 or not columns[x-1]): start=x
    if on and (x==len(columns)-1 or not columns[x+1]): runs.append((start,x+1))
if len(runs)!=len(a.count): raise ValueError('Count and glyph components differ')
folder=Path(__file__).resolve().parents[2]/'src/tasks/zhuagui/assets/digits'
folder.mkdir(exist_ok=True)
for digit,(left,right) in zip(a.count,runs):
    rows=[''.join('1' if v else '0' for v in row) for row in mask[:,left:right]]
    (folder/f'd{digit}.lua').write_text('return {'+','.join('"'+s+'"' for s in rows)+'}\n',encoding='utf-8')
for digit,left,right in [('2',818,832),('5',837,850)]:
    if (folder/f'd{digit}.lua').exists(): continue
    tile=frame[208:230,left:right]
    b,g,r=cv2.split(tile)
    tile=(g>140)&(r<150)&(b<120)
    rows=[''.join('1' if v else '0' for v in row) for row in tile]
    (folder/f'd{digit}.lua').write_text('return {'+','.join('"'+s+'"' for s in rows)+'}\n',encoding='utf-8')
print('Count glyphs calibrated: '+a.count)

"""Group raw puzzle boards for human annotation; never generate correct answers."""
import argparse
import itertools
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[2]
CELLS=((146,556,438,926),(448,556,740,926),(146,938,438,1308),(448,938,740,1308))

def tiles(path):
    frame=cv2.imdecode(np.fromfile(path,dtype=np.uint8),1)
    if frame is None or frame.shape[:2]!=(1600,900):raise ValueError('Unreadable board')
    return [cv2.cvtColor(frame[y1:y2,x1:x2],cv2.COLOR_BGR2RGB) for x1,y1,x2,y2 in CELLS]

def signature(parts):
    return [cv2.resize(part,(40,50)).astype(np.float32) for part in parts]

def grouping(paths):
    groups=[]
    for path in paths:
        parts=tiles(path);samples=signature(parts)
        for group in groups:
            best=min((sum(float(np.mean(np.abs(samples[i]-group['signature'][perm[i]]))) for i in range(4))/4,perm)
                     for perm in itertools.permutations(range(4)))
            if best[0]<6:
                group['sources'].append({'path':str(path),'current_to_reference':[i+1 for i in best[1]],'difference':round(best[0],2)})
                break
        else:
            groups.append({'signature':samples,'parts':parts,'sources':[{'path':str(path),'current_to_reference':[1,2,3,4],'difference':0}]})
    return groups

def main():
    p=argparse.ArgumentParser()
    p.add_argument('archives',nargs='+',type=Path)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    paths=[]
    for folder in args.archives:
        paths.extend(sorted((folder/'res').glob('*puzzle_r*.png')))
        paths.extend(sorted((folder/'res').glob('*zhuagui_unknown_state.png')))
    groups=grouping(paths)
    args.output.mkdir(parents=True,exist_ok=True)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',24)
    small=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',19)
    panels=[];records=[]
    for index,group in enumerate(groups,1):
        panel=Image.new('RGB',(630,900),'#f4f6fa');draw=ImageDraw.Draw(panel)
        draw.text((16,10),f'图案{index:02d} · 当前图块 A/B/C/D',font=font,fill='black')
        draw.text((16,48),'请标出每块的正确位置，或画出正确排列',font=small,fill='#444444')
        for cell,part in enumerate(group['parts']):
            x=14+(cell%2)*308;y=115+(cell//2)*390
            draw.text((x,y-29),'ABCD'[cell],font=font,fill='#005f9c')
            panel.paste(Image.fromarray(part),(x,y))
        panel.save(args.output/f'图案{index:02d}.png')
        panels.append(panel)
        records.append({'group':index,'reference':group['sources'][0]['path'],'sources':group['sources']})
    sheet=Image.new('RGB',(1260,900*((len(panels)+1)//2)),'white')
    for i,panel in enumerate(panels):sheet.paste(panel,((i%2)*630,(i//2)*900))
    sheet.save(args.output/'拼图审核总览.png')
    proposal=ROOT/'.tmp/annotation/拼图';proposal.mkdir(parents=True,exist_ok=True)
    (proposal/'原图对应.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'raw_frames':len(paths),'pattern_groups':len(groups),
                      'unique_arrangements':sum(len({tuple(s['current_to_reference']) for s in g['sources']}) for g in groups),
                      'review':str((args.output/'拼图审核总览.png').resolve())},ensure_ascii=False))

if __name__=='__main__':main()

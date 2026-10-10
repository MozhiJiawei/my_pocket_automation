"""Index public hint/candidate frames by question; OCR never drives device input."""
import argparse
import hashlib
import json
import re
from pathlib import Path

import cv2
import numpy as np
from rapidocr import RapidOCR
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.device.dfx_device import Device

# Offline indexing shares the host with the emulator; avoid an OpenCV thread pool.
cv2.setNumThreads(1)

ROOT=Path(__file__).resolve().parents[2]
REQUIRED=['梅花酒','虎骨酒','蛇胆酒','珍露酒','黄金','黄纸','书籍','书画','香','蜡烛','野鬼','牛头','马面','僵尸']
CLUES=[('梅花','梅花酒'),('虎骨','虎骨酒'),('蛇胆','蛇胆酒'),('露水','珍露酒'),('珍露','珍露酒')]
CLUES += [(name,name) for name in REQUIRED[4:]] + [('兵器','兵器'),('骷髅','骷髅怪'),('酒','酒')]

def read(path):
    frame=cv2.imdecode(np.fromfile(path,dtype=np.uint8),1)
    if frame is None or frame.shape[:2]!=(1600,900):
        raise ValueError('Expected inspected portrait 900x1600 frame')
    return frame

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--device',help='Pull only this run’s explicit catalog pages while sampling')
    args=parser.parse_args()
    if not re.fullmatch(r'\d{8}_\d{6}',args.run_id): raise ValueError('Invalid run ID')
    archive=ROOT/'debug-runs'/args.run_id
    folder=archive/'res'
    folder.mkdir(parents=True,exist_ok=True)
    if args.device:
        device=Device(args.device)
        files=device.adb_call('shell','ls',f'/storage/emulated/0/TouchSprite/res/daily_{args.run_id}_*_catalog_r*_p*.png').splitlines()
        for remote in files:
            if not re.fullmatch(rf'/storage/emulated/0/TouchSprite/res/daily_{args.run_id}_\d+_catalog_r\d{{3}}_p\d{{2}}\.png',remote):
                raise ValueError('Unexpected catalog path')
            local=folder/Path(remote).name
            if not local.exists(): device.adb_call('pull',remote,str(local))
    rounds={}
    for path in sorted(folder.glob('*_catalog_r???_p??.png')):
        match=re.search(r'_catalog_r(\d{3})_p(\d{2})',path.name)
        rounds.setdefault(match[1],[]).append((int(match[2]),path))
    engine=RapidOCR()
    records=[]
    for number,pages in rounds.items():
        first=next((path for page,path in pages if page==1),None)
        if first is None: continue
        frame=read(first)
        hint=cv2.cvtColor(frame[340:420,65:575],cv2.COLOR_BGR2GRAY)
        hint=cv2.threshold(hint,155,255,cv2.THRESH_BINARY)[1]
        hint=cv2.copyMakeBorder(hint,40,40,20,20,cv2.BORDER_CONSTANT,value=255)
        hint=cv2.resize(hint,None,fx=2,fy=2)
        result=engine(hint)
        text=''.join(result.txts or [])
        normalized=re.sub(r'[xX×]\s*1$','',re.sub(r'\s+','',text))
        topic=next((name for clue,name in CLUES if clue in normalized),None)
        hashes=[]
        distinct=[]
        valid_pages=[]
        title=cv2.imdecode(np.fromfile(ROOT/'src/tasks/zhuagui/assets/find_title.png',dtype=np.uint8),1)
        for page,path in pages:
            original=read(path)
            visible=cv2.minMaxLoc(cv2.matchTemplate(original[245:325,200:750],title,cv2.TM_CCOEFF_NORMED))[1]>=0.9
            valid_pages.append(visible)
            masked=np.zeros_like(original)
            masked[174:1435,15:887]=original[174:1435,15:887]
            encoded=cv2.imencode('.png',masked)[1].tobytes()
            digest=hashlib.sha256(encoded).hexdigest()
            hashes.append(digest)
            # Page identity excludes changing countdown/title overlays.
            body=original[527:1405,60:830]
            if visible and not any(np.mean(np.abs(body.astype(np.int16)-old.astype(np.int16)))<1.5 for old in distinct):
                distinct.append(body)
        records.append({'run_id':args.run_id,'round':int(number),'question':normalized,
                        'ocr_text':text,'ocr_scores':[float(v) for v in (result.scores if result.scores is not None else [])],
                        'topic':topic,'reviewed':False,'pages_complete':len(pages)==7 and all(valid_pages),
                        'valid_pages':valid_pages,
                        'distinct_pages':len(distinct),'pages':[str(p.relative_to(ROOT)).replace('\\','/') for _,p in pages],
                        'sha256_redacted':hashes})
    target=archive/'catalog-index.json'
    target.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    unique={}
    for item in records:
        if item['pages_complete']: unique.setdefault(item['question'],item)
    tiles=[]
    for item in unique.values():
        frame=read(ROOT/item['pages'][0])
        tile=np.full((110,600,3),255,dtype=np.uint8)
        cv2.putText(tile,f"round {item['round']}",(10,25),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,0),1)
        tile[40:105,25:535]=frame[350:415,65:575]
        tiles.append(tile)
    if tiles:
        cv2.imencode('.png',np.vstack(tiles))[1].tofile(archive/'catalog-questions.png')
    questions={r['question'] for r in records}
    found={r['topic'] for r in records if r['pages_complete']}
    print(json.dumps({'run_id':args.run_id,'rounds':len(records),'distinct_questions':len(questions),
                      'complete_topics':sorted(found-{None}),'missing_required':[n for n in REQUIRED if n not in found]},ensure_ascii=False))

if __name__=='__main__': main()

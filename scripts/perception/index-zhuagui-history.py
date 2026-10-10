"""Recover distinct real find questions from archived runs without device input."""
import hashlib
import json
from pathlib import Path
import re
import cv2
import numpy as np
from rapidocr import RapidOCR

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'debug-runs/zhuagui-history-index.json'

def main():
    grouped={}
    for source in sorted((ROOT/'debug-runs').glob('202610*/res/*.png')):
        if not re.search(r'find|catalog|wine|target',source.stem): continue
        original=cv2.imdecode(np.fromfile(source,dtype=np.uint8),1)
        if original is None or original.shape[:2]!=(1600,900): continue
        # Exact hints share a bitmap even when candidates, timer and account change.
        hint=cv2.cvtColor(original[340:420,65:575],cv2.COLOR_BGR2GRAY)
        hint=cv2.threshold(hint,155,255,cv2.THRESH_BINARY)[1]
        key=hashlib.sha256(hint.tobytes()).hexdigest()
        grouped.setdefault(key,{'hint':hint,'sources':[]})['sources'].append(source.relative_to(ROOT).as_posix())
    cached=json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    engine=RapidOCR()
    for key,item in grouped.items():
        if key not in cached:
            hint=cv2.copyMakeBorder(item['hint'],40,40,20,20,cv2.BORDER_CONSTANT,value=255)
            result=engine(cv2.resize(hint,None,fx=2,fy=2))
            text=''.join(result.txts or [])
            cached[key]={'question':re.sub(r'[xX×]\s*1$','',re.sub(r'\s+','',text)),
                         'scores':[float(s) for s in (result.scores if result.scores is not None else [])]}
        cached[key]['sources']=item['sources']
        OUT.write_text(json.dumps(cached,ensure_ascii=False,indent=2),encoding='utf-8')
    questions=[{'question':v['question'],'sources':v['sources']} for v in cached.values() if '请找到' in v['question']]
    print(json.dumps({'distinct_hint_bitmaps':len(grouped),'questions':questions},ensure_ascii=False))

if __name__=='__main__': main()

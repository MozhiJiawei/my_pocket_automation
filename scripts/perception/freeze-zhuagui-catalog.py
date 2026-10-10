"""Freeze visually reviewed questions and redacted candidates as offline cases."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

cv2.setNumThreads(1)

ROOT=Path(__file__).resolve().parents[2]
REQUIRED=['梅花酒','虎骨酒','蛇胆酒','珍露酒','黄金','黄纸','书籍','书画','香','蜡烛','野鬼','牛头','马面','僵尸']
DEST=ROOT/'testdata/zhuagui/images/catalog'

def save_frame(source,target):
    original=cv2.imdecode(np.fromfile(source,dtype=np.uint8),1)
    if original is None or original.shape[:2]!=(1600,900): raise ValueError('Invalid source frame')
    frame=np.zeros_like(original)
    frame[174:1435,15:887]=original[174:1435,15:887]
    encoded=cv2.imencode('.png',frame)[1].tobytes()
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(encoded)
    title=cv2.imdecode(np.fromfile(ROOT/'src/tasks/zhuagui/assets/find_title.png',dtype=np.uint8),1)
    visible=cv2.minMaxLoc(cv2.matchTemplate(original[245:325,200:750],title,cv2.TM_CCOEFF_NORMED))[1]>=0.9
    return {'image':target.relative_to(DEST).as_posix(),'sha256':hashlib.sha256(encoded).hexdigest(),
            'source':source.relative_to(ROOT).as_posix(),'hint_visible':visible}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--index',type=Path,required=True)
    parser.add_argument('--review',type=Path,required=True,help='Explicit round → visually confirmed topic mapping')
    parser.add_argument('--history-review',type=Path,help='Visually reviewed archived question/source/topic records')
    parser.add_argument('--include-variants',action='store_true',help='Append reviewed layouts even when a question already has a complete catalog')
    args=parser.parse_args()
    records=json.loads(args.index.read_text(encoding='utf-8'))
    review=json.loads(args.review.read_text(encoding='utf-8'))
    DEST.mkdir(parents=True,exist_ok=True)
    manifest_path=DEST/'manifest.json'
    previous=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    cases=previous.get('cases',[])
    known={c['question']:c for c in cases}
    if args.history_review:
        for record in json.loads(args.history_review.read_text(encoding='utf-8')):
            if record['question'] in known: continue
            key=hashlib.sha256(record['question'].encode()).hexdigest()[:12]
            frames=[save_frame(ROOT/path,DEST/key/f'page_{i:02d}.png') for i,path in enumerate(record['sources'],1)]
            case={'topic':record['topic'],'question':record['question'],'reviewed':True,
                  'source_run':record['sources'][0].split('/')[1],'source_round':None,
                  'catalog_complete':record.get('catalog_complete',False),
                  'answer_verified':record.get('answer_verified',False),'frames':frames}
            cases.append(case)
            known[record['question']]=case
    for record in records:
        topic=review.get(str(record['round']))
        if topic is None: continue
        if topic!=record['topic'] or not record['question'] or not record['pages']:
            raise ValueError('Review disagrees with the indexed question')
        if record['question'] in known and known[record['question']]['catalog_complete'] and not args.include_variants: continue
        key=hashlib.sha256(record['question'].encode()).hexdigest()[:12]
        frames=[]
        bodies=[]
        existing_sources={f['source'] for f in known.get(record['question'],{}).get('frames',[])}
        for page_number,relative in enumerate(record['pages'],1):
            if relative in existing_sources: continue
            source=ROOT/relative
            original=cv2.imdecode(np.fromfile(source,dtype=np.uint8),1)
            body=original[527:1405,60:830].astype(np.int16)
            if any(np.mean(np.abs(body-old))<1.5 for old in bodies): continue
            bodies.append(body)
            frames.append(save_frame(source,DEST/key/f"{record['run_id']}_r{record['round']:03d}_page_{page_number:02d}.png"))
        if record['question'] in known:
            existing=known[record['question']]
            existing['frames'].extend(frames)
            existing['catalog_complete']=existing['catalog_complete'] or record['pages_complete']
            continue
        case={'topic':topic,'question':record['question'],'reviewed':True,
              'source_run':record['run_id'],'source_round':record['round'],
              'catalog_complete':record['pages_complete'],'answer_verified':False,'frames':frames}
        cases.append(case)
        known[record['question']]=case
    present={c['topic'] for c in cases if c['reviewed'] and c['frames']}
    for case in cases:
        for frame in case['frames']:
            if 'hint_visible' not in frame:
                source=ROOT/frame['source']
                frame.update(save_frame(source,DEST/frame['image']))
        if not all(frame['hint_visible'] for frame in case['frames']): case['catalog_complete']=False
    present={c['topic'] for c in cases if c['reviewed'] and any(f['hint_visible'] for f in c['frames'])}
    missing=[name for name in REQUIRED if name not in present]
    runs=previous.get('collection_runs',{})
    for record in records:
        if str(record['round']) not in review: continue
        run=runs.setdefault(record['run_id'],{})
        run[str(record['round'])]={'question':record['question'],'topic':record['topic'],
                                  'pages_complete':record['pages_complete'],'pages':len(record['pages'])}
    data={'required_topics':REQUIRED,'complete':not missing,'missing_topics':missing,
          'collection_runs':runs,'cases':cases}
    manifest_path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.path.insert(0,str(ROOT))
    from scripts.perception.lib.ingest import sync_catalog
    sync_catalog()
    print(json.dumps({'questions':len(cases),'required_covered':len(REQUIRED)-len(missing),
                      'required_total':len(REQUIRED),'missing':missing},ensure_ascii=False))

if __name__=='__main__': main()

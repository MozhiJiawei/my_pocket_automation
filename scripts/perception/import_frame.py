"""Import a redacted real frame as pending evidence, without invoking recognition."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.corpus import annotation


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--task',choices=['dungeon','zhuagui'],required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--group',required=True,help='Capture run or independent capture group')
    parser.add_argument('--retain',action='append',required=True,help='Public rectangle x1,y1,x2,y2; repeatable')
    args=parser.parse_args()
    if not args.source.is_absolute(): parser.error('Source must be an absolute path')
    original=cv2.imdecode(np.fromfile(args.source,dtype=np.uint8),1)
    if original is None: parser.error('Unreadable image')
    height,width=original.shape[:2]
    rectangles=[list(map(int,v.split(','))) for v in args.retain]
    frame=np.zeros_like(original)
    for box in rectangles:
        if len(box)!=4: parser.error('Rectangle needs four coordinates')
        x1,y1,x2,y2=box
        if not 0<=x1<x2<=width or not 0<=y1<y2<=height: parser.error('Invalid rectangle')
        frame[y1:y2,x1:x2]=original[y1:y2,x1:x2]
    encoded=cv2.imencode('.png',frame)[1].tobytes()
    digest=hashlib.sha256(encoded).hexdigest()
    folder=ROOT/'testdata'/args.task
    document=json.loads((folder/'cases.json').read_text(encoding='utf-8'))
    if any(c['sha256']==digest for c in document['cases']):
        print('Evidence already exists; annotations preserved'); return
    relative=Path('images/imported')/f'{digest[:16]}.png'
    target=folder/relative; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(encoded)
    truth={name:annotation(None,'pending','New evidence; not reviewed') for name in
           (['page','question','target_regions'] if args.task=='zhuagui' else ['page'])}
    splits={c['capture']['split'] for c in document['cases'] if c['capture']['group']==args.group}
    if len(splits)>1: parser.error('Existing group already leaks between splits')
    split=next(iter(splits),'holdout')
    document['cases'].append({'id':args.task+'_'+digest[:16],'task':args.task,'image':relative.as_posix(),
        'sha256':digest,'capture':{'size':[width,height],'game_version':None,'group':args.group,
        'split':split,'origin':'device','retained_rectangles':rectangles},'truth':truth,
        'expected':{'checks':list(truth),'on_unknown':'abstain'},
        'provenance':[{'source':str(args.source),'original_sha256':hashlib.sha256(args.source.read_bytes()).hexdigest()}]})
    (folder/'cases.json').write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Imported pending evidence; no truth inferred')

if __name__=='__main__': main()

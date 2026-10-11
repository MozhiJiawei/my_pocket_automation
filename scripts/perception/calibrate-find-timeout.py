"""Build an expired countdown guard from independently reviewed zero-time evidence."""
import json
from pathlib import Path
import sys
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.corpus import load_cases,validate,VERIFIED


def main():
    case=next(c for c in load_cases('zhuagui') if c['id']=='抓鬼/寻物/未知题目/场景01/画面.png')
    assert case['capture']['split']=='calibration'
    assert case['truth']['forbidden_actions']['status'] in VERIFIED
    frame=cv2.imdecode(np.fromfile(validate(case),dtype=np.uint8),1)
    # Full digit outline plus grey centre distinguishes zero from 8/9.
    coordinates=[(448,452),(444,456),(444,460),(444,465),(448,470),(451,470),
                 (455,466),(455,461),(455,456),(451,452),(450,459),(450,465),
                 (438,460),(414,459)]
    colors=[int(frame[y,x,2])*65536+int(frame[y,x,1])*256+int(frame[y,x,0]) for x,y in coordinates]
    ax,ay=coordinates[0]
    offsets=','.join(f'{x-ax}|{y-ay}|0x{color:06x}' for (x,y),color in zip(coordinates[1:],colors[1:]))
    folder=ROOT/'src/tasks/zhuagui/assets'
    (folder/'find_time_expired.lua').write_text(
        '-- Generated from independently reviewed red countdown zero; see calibrate-find-timeout.py.\n'
        f'return {{width=900,height=1600,base=0x{colors[0]:06x},offsets={json.dumps(offsets)},degree=90,region={{446,450,450,454}},tap_offset={{0,0}}}}\n',encoding='utf-8')
    (folder/'find_time_expired.json').write_text(json.dumps({'case_id':case['id'],
        'region':[436,446,461,474],'points':coordinates,'source':case['truth']['forbidden_actions']['source']},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()

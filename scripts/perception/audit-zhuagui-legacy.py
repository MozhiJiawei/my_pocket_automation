"""Check scaled legacy item features against saved frames without device actions."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import cv2
import numpy as np
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


def match(frame,feature):
    x1,y1,x2,y2=map(int,feature['region'].values())
    points=[(0,0,int(feature['base']))]+[(int(x),int(y),int(c,16))
        for x,y,c in (s.split('|') for s in feature['offsets'].split(','))]
    tolerance=round(255*(100-int(feature['degree']))/100)
    crop=frame[y1:y2+1,x1:x2+1].astype(np.int16)
    c=points[0][2]
    yy,xx=np.where(np.max(np.abs(crop-np.array([c&255,(c>>8)&255,(c>>16)&255])),axis=2)<=tolerance)
    xx,yy=xx+x1,yy+y1
    for dx,dy,c in points[1:]:
        px,py=xx+dx,yy+dy
        valid=(px>=0)&(px<frame.shape[1])&(py>=0)&(py<frame.shape[0])
        xx,yy,px,py=xx[valid],yy[valid],px[valid],py[valid]
        pixels=frame[py,px].astype(np.int16)
        valid=np.max(np.abs(pixels-np.array([c&255,(c>>8)&255,(c>>16)&255])),axis=1)<=tolerance
        xx,yy=xx[valid],yy[valid]
        if not len(xx): break
    return list(zip(xx.tolist(),yy.tolist()))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--category',default='酒')
    p.add_argument('--image',action='append',type=Path,required=True)
    a=p.parse_args()
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path; getScreenSize=function() return 900,1600 end")
    legacy=lua.eval("require('tasks.zhuagui.legacy')")[0]
    features=legacy['items'](a.category)
    results=[]
    for path in a.image:
        frame=cv2.imdecode(np.fromfile(path,dtype=np.uint8),1)
        if frame is None or frame.shape[:2]!=(1600,900): raise ValueError('Expected 900x1600 screenshot')
        matches=[]
        for feature in features.values():
            for x,y in match(frame,feature)[:10]:
                matches.append(dict(index=feature['legacy_index'],scale=feature['legacy_scale'],x=x,y=y))
        results.append(dict(image=str(path.resolve()),category=a.category,feature_variants=len(features),matches=matches))
        print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    run_id=datetime.now().strftime('%Y%m%d_%H%M%S')
    archive=ROOT/'debug-runs'/run_id
    archive.mkdir()
    (archive/'legacy-audit.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(archive)


if __name__=='__main__': main()

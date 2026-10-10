"""Make an indexed screenshot overview for human answers; retain original frames."""
import argparse
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-id',required=True)
    a=p.parse_args()
    if len(a.run_id)!=15 or not a.run_id.replace('_','').isdigit(): raise ValueError('Invalid run ID')
    archive=ROOT/'debug-runs'/a.run_id
    candidates=sorted(list((archive/'res').glob('*_zhuagui_catalog_first.png'))+
                      list((archive/'res').glob('*_zhuagui_catalog_scroll_after.png')))
    frames=[]
    for source in candidates:
        frame=cv2.imdecode(np.fromfile(source,dtype=np.uint8),1)
        body=frame[527:1405,60:830]
        if any(np.mean(np.abs(body.astype(np.int16)-old[1].astype(np.int16)))<1.5 for old in frames): continue
        frames.append((source,body,frame))
    if not frames: raise ValueError('No catalog screenshots')
    tiles=[]
    for index,(source,body,frame) in enumerate(frames,1):
        tile=np.zeros((1135,900,3),np.uint8)
        cv2.putText(tile,f'PAGE {index}',(30,45),cv2.FONT_HERSHEY_SIMPLEX,1.2,(255,255,255),2)
        tile[65:270]=frame[245:450]
        tile[270:1135]=frame[540:1405]
        tiles.append(tile)
    sheet=np.zeros((((len(tiles)+1)//2)*1135,1800,3),np.uint8)
    for i,tile in enumerate(tiles): sheet[(i//2)*1135:(i//2+1)*1135,(i%2)*900:(i%2+1)*900]=tile
    target=archive/'breakpoint_catalog.png'
    cv2.imencode('.png',sheet)[1].tofile(target)
    links='\n'.join(f'- [第 {i} 张原始截图](</{path.as_posix()}>)' for i,(path,_,_) in enumerate(frames,1))
    (archive/'BREAKPOINT.md').write_text('# 抓鬼寻物断点\n\n各页属于同一次找物品尝试；重复的底部画面已从总览中去除，原图全部保留。\n\n'
        '请指出题目对应的图标，可以说明第几页、位置或物品外观。脚本尚未选择候选。\n\n'+links+'\n\n'
        f'![候选总览](</{target.as_posix()}>)\n',encoding='utf-8')
    print(f'Saved {len(frames)} distinct catalog frames: {target}')


if __name__=='__main__': main()

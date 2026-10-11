"""Calibrate the public two-arrow button from independently reviewed evidence."""
import json
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]

def main():
    folder=ROOT/'testdata/导航/已登录角色切换按钮'
    truth=json.loads((folder/'预期.json').read_text(encoding='utf-8'))
    source=folder/'画面.png'
    image=cv2.imdecode(np.fromfile(source,dtype=np.uint8),1)
    points=np.column_stack(np.where(np.min(image[277:306,120:153],axis=2)>240))[:,::-1]+[120,277]
    chosen=[0]
    for _ in range(23):
        distances=np.min(np.sum((points[:,None]-points[chosen][None,:])**2,axis=2),axis=1)
        chosen.append(int(np.argmax(distances)))
    selected=points[chosen];ax,ay=map(int,selected[0])
    def color(x,y):
        b,g,r=map(int,image[y,x]);return r*65536+g*256+b
    offsets=','.join(f'{int(x)-ax}|{int(y)-ay}|0x{color(x,y):06x}' for x,y in selected[1:])
    target=ROOT/'src/common/assets/saved_account_switch.lua'
    target.write_text('return {width=900,height=1600,base=0x%06x,offsets=%s,degree=90,region={111,268,162,318},tap_offset={%d,%d}}\n'%(color(ax,ay),json.dumps(offsets),137-ax,291-ay),encoding='utf-8')

if __name__=='__main__':main()

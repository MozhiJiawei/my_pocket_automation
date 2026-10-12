"""Rebuild the movable ghost-entry glyph from the explicitly approved failure."""
from pathlib import Path
import json
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]

def main():
    source=ROOT/'testdata/抓鬼/页面/任务列表/推荐副本插入后抓鬼下移/画面.png'
    frame=cv2.imdecode(np.fromfile(source,dtype=np.uint8),1)
    crop=frame[935:975,275:365]
    mask=cv2.erode((np.max(crop,axis=2)<125).astype(np.uint8),np.ones((3,3),np.uint8))
    pixels=np.column_stack(np.where(mask))[:,::-1]
    assert len(pixels)>=16
    chosen=[0]
    for _ in range(15):
        distance=np.min(np.sum((pixels[:,None]-pixels[chosen][None,:])**2,axis=2),axis=1)
        chosen.append(int(np.argmax(distance)))
    selected=pixels[chosen]+[275,935]
    ax,ay=map(int,selected[0])
    def color(x,y):
        b,g,r=map(int,frame[y,x]);return r*65536+g*256+b
    offsets=','.join(f'{int(x)-ax}|{int(y)-ay}|0x{color(x,y):06x}' for x,y in selected[1:])
    feature='{{width=900,height=1600,base=0x%06x,offsets=%s,degree=90,region={40,331,760,1310},tap_offset={%d,%d}}}'%(color(ax,ay),json.dumps(offsets),450-ax,1030-ay)
    # Keep the old independently calibrated appearance as primary; one new glyph
    # appearance is sufficient, with no rotation or online feature transforms.
    original='return {width=900,height=1600,base=0x323869,offsets="5|-31|0x2a3061,38|0|0x292f60,58|-11|0xb1c2ea,68|-5|0x292f60,48|-11|0xb1c2ea,0|-23|0x424a7a,8|0|0x292f60,32|-30|0x4c5583,33|0|0x2c3263,0|-11|0x2e3465,61|-7|0xb9cbf2",degree=90,region={40,331,760,1310},tap_offset={168,79}'
    (ROOT/'src/tasks/zhuagui/assets/task_card.lua').write_text(original+',variants='+feature+'}\n',encoding='utf-8')

if __name__=='__main__':main()

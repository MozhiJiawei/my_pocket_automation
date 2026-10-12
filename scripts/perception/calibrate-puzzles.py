"""Generate static piece signatures from user-approved four-cell arrangements."""
import json
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]

def sample(crop,white=False):
    kernel=np.ones((3,3),np.uint8)
    mask=(np.min(crop,axis=2)>235) if white else (np.min(crop,axis=2)<150)
    if not white:
        gradient=np.max(cv2.dilate(crop,kernel).astype(int)-cv2.erode(crop,kernel).astype(int),axis=2)
        mask &= gradient<=25
        mask[:12]=False;mask[-12:]=False;mask[:,:12]=False;mask[:,-12:]=False
    points=np.column_stack(np.where(mask))[:,::-1]
    assert len(points)>=16,'Insufficient stable glyph/object pixels'
    chosen=[0]
    for _ in range(15):
        distances=np.min(np.sum((points[:,None]-points[chosen][None,:])**2,axis=2),axis=1)
        chosen.append(int(np.argmax(distances)))
    return points[chosen]

def feature(frame,box,region,tap=None,white=False):
    x1,y1,x2,y2=box
    points=sample(frame[y1:y2,x1:x2],white)+[x1,y1]
    ax,ay=map(int,points[0])
    def color(x,y):
        b,g,r=map(int,frame[y,x]);return r*65536+g*256+b
    offsets=','.join(f'{int(x)-ax}|{int(y)-ay}|0x{color(x,y):06x}' for x,y in points[1:])
    result='{width=900,height=1600,base=0x%06x,offsets=%s,degree=90,region={%s}'%(color(ax,ay),json.dumps(offsets),','.join(map(str,region)))
    if tap:result+=',tap_offset={%d,%d}'%(tap[0]-ax,tap[1]-ay)
    return result+'}'

def main():
    base=ROOT/'testdata/抓鬼/拼图'
    cells=json.loads((base/'格位.json').read_text(encoding='utf-8'))
    result=[];first=None
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        answer=json.loads((folder/'答案.json').read_text(encoding='utf-8'))['预期']['画面.png']['puzzle_order']
        assert sorted(answer)==list('ABCD')
        frame=cv2.imdecode(np.fromfile(folder/'画面.png',np.uint8),1)
        if first is None:first=frame
        pieces=[]
        for letter in answer:
            box=cells[ord(letter)-65]
            center=((box[0]+box[2])//2,(box[1]+box[3])//2)
            pieces.append(feature(frame,box,[146,556,740,1308],center))
        result.append('['+json.dumps(folder.name,ensure_ascii=False)+']={'+','.join(pieces)+'}')
    title=feature(first,[390,179,510,236],[380,170,530,242],white=True)
    # The separately retained free-Continue prompt is observation evidence,
    # not a puzzle answer; use only with a caller-authorized owned attempt.
    retry_frame=cv2.imdecode(np.fromfile(ROOT/'testdata/抓鬼/待审核/拼图超时对话/画面.png',np.uint8),1)
    prompt=feature(retry_frame,[705,1025,810,1074],[680,1010,822,1080])
    button=feature(retry_frame,[550,1340,644,1400],[535,1320,659,1410],(594,1368),True)
    text='return {title='+title+',retry_prompt='+prompt+',retry_button='+button+',cells='+json.dumps(cells,separators=(',',':')).replace('[','{').replace(']','}')+',families={'+','.join(result)+'}}\n'
    (ROOT/'src/tasks/zhuagui/assets/puzzle.lua').write_text(text,encoding='utf-8')

if __name__=='__main__':main()

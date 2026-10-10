"""Record a public UI crop and its multi-color signature from an inspected frame."""
import argparse
from pathlib import Path
import cv2
import numpy as np

p = argparse.ArgumentParser()
p.add_argument('--image', type=Path, required=True)
p.add_argument('--rect', nargs=4, type=int, required=True)
p.add_argument('--tap', nargs=2, type=int, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--foreground-white', action='store_true', help='Use white glyph interiors, excluding animated backgrounds')
p.add_argument('--interior', action='store_true', help='Sample flat colored interiors instead of antialiased edges')
p.add_argument('--foreground-ink', action='store_true', help='Sample dark hint glyphs plus surrounding background for shape discrimination')
a = p.parse_args()
frame = cv2.imdecode(np.fromfile(a.image, dtype=np.uint8), cv2.IMREAD_COLOR)
if frame is None:
    raise ValueError('Unreadable frame')
x1, y1, x2, y2 = a.rect
crop = frame[y1:y2, x1:x2]
gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
corners = cv2.goodFeaturesToTrack(gray, 16, 0.08, 5)
points = [] if corners is None else [(int(x), int(y)) for x, y in corners[:, 0]][:12]
if len(points) < 12:
    ys, xs = np.where(cv2.Canny(gray, 40, 120) > 0)
    for x, y in zip(xs, ys):
        if all((int(x)-px)**2 + (int(y)-py)**2 >= 64 for px, py in points):
            points.append((int(x), int(y)))
        if len(points) >= 12:
            break
if len(points) < 8:
    raise ValueError('Insufficient nonuniform feature points')
if a.foreground_white:
    points=[]
    ys,xs=np.where(np.min(crop,axis=2)>=225)
    for x,y in zip(xs,ys):
        if all((int(x)-px)**2+(int(y)-py)**2>=25 for px,py in points):
            points.append((int(x),int(y)))
        if len(points)>=12: break
    if len(points)<8: raise ValueError('Insufficient white foreground points')
ax, ay = points[0]
if a.interior:
    local_max=cv2.dilate(crop,np.ones((3,3),np.uint8)).astype(int)
    local_min=cv2.erode(crop,np.ones((3,3),np.uint8)).astype(int)
    flat=np.max(local_max-local_min,axis=2)
    candidates=np.argsort(flat.ravel())
    points=[]
    for index in candidates:
        y,x=divmod(int(index),crop.shape[1])
        if x<2 or y<2 or x>=crop.shape[1]-2 or y>=crop.shape[0]-2: continue
        if all((x-px)**2+(y-py)**2>=64 and np.max(np.abs(crop[y,x].astype(int)-crop[py,px].astype(int)))>=25 for px,py in points):
            points.append((x,y))
        if len(points)>=8: break
    if len(points)<5: raise ValueError('Insufficient distinct interior colors')
    ax,ay=points[0]
if a.foreground_ink:
    ink=(crop[:,:,1]<145)&(crop[:,:,0]<205)
    solid=cv2.erode(ink.astype(np.uint8),np.ones((2,2),np.uint8))>0
    background=cv2.erode((~ink).astype(np.uint8),np.ones((3,3),np.uint8))>0
    points=[]
    for mask,limit in ((solid,24),(background,12)):
        ys,xs=np.where(mask)
        candidates=np.column_stack((xs,ys)).astype(int)
        for _ in range(limit):
            if not len(candidates): break
            distances=np.min(np.sum((candidates[:,None,:]-np.array(points)[None,:,:])**2,axis=2),axis=1) if points else np.ones(len(candidates))*16
            index=int(np.argmax(distances))
            if distances[index]<16: break
            points.append(tuple(map(int,candidates[index])))
            candidates=np.delete(candidates,index,axis=0)
    if len(points)<16: raise ValueError('Insufficient ink shape points')
    ax,ay=points[0]
def rgb(x, y):
    b, g, r = map(int, crop[y, x])
    return (r << 16) | (g << 8) | b
offsets = ','.join(f'{x-ax}|{y-ay}|0x{rgb(x,y):06x}' for x, y in points[1:])
anchor = (x1 + ax, y1 + ay)
a.output.parent.mkdir(parents=True, exist_ok=True)
cv2.imencode('.png', crop)[1].tofile(a.output.with_suffix('.png'))
region = [max(0, anchor[0]-15), max(0, anchor[1]-15),
          min(frame.shape[1]-1, anchor[0]+15), min(frame.shape[0]-1, anchor[1]+15)]
a.output.write_text(
    'return {width=%d,height=%d,base=0x%06x,offsets="%s",degree=90,region={%s},tap_offset={%d,%d}}\n' %
    (frame.shape[1], frame.shape[0], rgb(ax,ay), offsets, ','.join(map(str,region)),
     a.tap[0]-anchor[0], a.tap[1]-anchor[1]), encoding='utf-8')
print(a.output)

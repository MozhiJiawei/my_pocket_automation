"""Save a reviewed role name signature outside Git; no inferred role identity."""
import argparse
import hashlib
import json
from pathlib import Path
import re

import cv2
import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--alias', required=True)
    p.add_argument('--kind', choices=['role', 'selector'], required=True)
    p.add_argument('--region', required=True, help='Reviewed name rectangle x1,y1,x2,y2')
    p.add_argument('--tap', required=True, help='Safe target center x,y')
    p.add_argument('--append-variant',action='store_true',help='Preserve existing selector and add another reviewed selected/unselected appearance')
    args = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.alias):
        p.error('Invalid stable alias')
    frame = cv2.imdecode(np.fromfile(args.source, dtype=np.uint8), 1)
    x1,y1,x2,y2 = map(int,args.region.split(','))
    tx,ty = map(int,args.tap.split(','))
    crop = frame[y1:y2,x1:x2]
    # Bright glyph pixels, spatially distributed across the whole reviewed name.
    if args.kind=='role':
        mask=np.min(crop,axis=2)>190
    else:
        # Keep solid ink, excluding background-dependent antialiased edges.
        # Saved roles reorder when selected, changing each tile's background.
        mask=np.max(np.abs(crop.astype(np.int16)-np.array([96,47,41])),axis=2)<=4
    pixels = np.column_stack(np.where(mask))[:,::-1]
    if len(pixels)<24:
        raise ValueError('Insufficient readable name pixels')
    chosen = [0]
    for _ in range(23):
        distance = np.min(np.sum((pixels[:,None]-pixels[chosen][None,:])**2,axis=2),axis=1)
        chosen.append(int(np.argmax(distance)))
    ax,ay = pixels[chosen[0]] + [x1,y1]
    def color(x,y):
        b,g,r = map(int,frame[y,x]); return r*65536+g*256+b
    points = [(int(x+x1),int(y+y1)) for x,y in pixels[chosen[1:]]]
    offsets = ','.join(f'{x-ax}|{y-ay}|0x{color(x,y):06x}' for x,y in points)
    height,width = frame.shape[:2]
    region = [170,180,435,230] if args.kind=='role' else [35,270,width-35,height-200]
    feature = 'return {width=%d,height=%d,base=0x%06x,offsets=%s,degree=95,region={%s},tap_offset={%d,%d}}\n' % (
        width,height,color(ax,ay),json.dumps(offsets),','.join(map(str,region)),tx-ax,ty-ay)
    folder = Path.home()/'.my_pocket_automation/accounts'/args.alias
    folder.mkdir(parents=True,exist_ok=True)
    destination=folder/(args.kind+'.lua')
    metadata=folder/(args.kind+'.json')
    previous=None
    if args.append_variant:
        if args.kind!='selector' or not destination.exists() or not metadata.exists():
            raise ValueError('An existing selector is required to append an appearance')
        previous=json.loads(metadata.read_text(encoding='utf-8'))
        feature='local existing=(function()\n'+destination.read_text(encoding='utf-8')+'end)()\nexisting.variants=existing.variants or {}\nexisting.variants[#existing.variants+1]='+feature.removeprefix('return ').strip()+'\nreturn existing\n'
    destination.write_text(feature,encoding='utf-8')
    cv2.imencode('.png',crop)[1].tofile(folder/(args.kind+'.png'))
    metadata.write_text(json.dumps({
        'source':str(args.source.resolve()),'sha256':hashlib.sha256(args.source.read_bytes()).hexdigest(),
        'region':[x1,y1,x2,y2],'previous':previous,'review':'Explicit name rectangle selected after visual review'},indent=2),encoding='utf-8')
    print('Saved reviewed role resource outside repository:',args.alias,args.kind)


if __name__=='__main__': main()

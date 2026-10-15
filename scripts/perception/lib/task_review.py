"""Recover capture rounds and register scrolling content, without inferring answers."""
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np

VIEWPORT = (63, 535, 829, 1410)
ALIGNMENT_METHOD = 'scroll_overlap_mae_v2_bidirectional'

def item_cells(frame):
    edges=cv2.Canny(frame[535:1410,63:829],50,100)
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    anchors=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour);x+=63;y+=535
        if not (137<=w<=142 and 137<=h<=142) or y+h>1405:continue
        column=min(range(5),key=lambda c:abs(x-(64+156*c)))
        if abs(x-(64+156*column))<=4:anchors.append((y,column))
    clusters=[]
    for y,column in sorted(anchors):
        if not clusters or y-np.median([a[0] for a in clusters[-1]])>15:clusters.append([(y,column)])
        else:clusters[-1].append((y,column))
    tops=sorted({int(np.median([a[0] for a in group]))+6 for group in clusters if len({a[1] for a in group})>=2})
    if not tops:return []
    # A clipped outer border does not mean that the item's interior is clipped.
    step=int(round(np.median(np.diff(tops)))) if len(tops)>1 else 156
    if 150<=step<=160:
        top=tops[0]-step
        # The inventory clips at y=527. A row's outer top border can be above
        # the edge detector's crop while its entire 132px interior is visible.
        while top>=527:tops.insert(0,top);top-=step
    return [[70+156*c,y,202+156*c,y+132] for y in tops if y+132<=1405 for c in range(5)]

def compose_rows(pages,image_resolver=None):
    """Merge complete rows only. Every painted row carries its original aliases."""
    from PIL import Image
    from scripts.perception.lib.corpus import image_path
    image_resolver=image_resolver or image_path
    rows=[];records=[];header=None;previous=None
    for page,case in sorted(pages.items()):
        frame=Image.open(image_resolver(case)).convert('RGB')
        if header is None:header=frame
        pixels=np.asarray(frame)
        incoming=[]
        for y in sorted({box[1] for box in item_cells(pixels)}):
            sample=cv2.resize(pixels[y:y+132,70:826],(126,24)).astype(np.float32)
            incoming.append({'sample':sample,'image':Path(case['image']).name,'source':[63,y-3,829,y+135],
                             'shifted_samples':[cv2.resize(pixels[y+shift:y+shift+132,70:826],(126,24)).astype(np.float32)
                                                for shift in (-2,-1,1,2) if y+shift>=535 and y+shift+132<=1405],
                             'aliases':[{'image':Path(case['image']).name,'source':[63,y-3,829,y+135]}],
                             'crop':frame.crop((63,y-3,829,y+135))})
        best=None
        for i in range(len(rows)):
            for j in range(len(incoming)):
                length=0
                while i+length<len(rows) and j+length<len(incoming) and matching_row(rows[i+length],incoming[j+length]):
                    length+=1
                if length and (best is None or length>best[0]):best=(length,i,j)
        # A single full row contains five independent icons; matching all five
        # is necessary. Never infer overlap from uniform borders or empty space.
        if best:
            length,i,j=best
            for offset in range(length):rows[i+offset]['aliases'].extend(incoming[j+offset]['aliases'])
            prefix=incoming[:j];suffix=incoming[j+length:]
            if prefix and i==0:rows[:0]=prefix
            elif prefix:
                # Back-scroll can reveal an omitted complete row immediately
                # before an already-known run, as in the wine failure capture.
                rows[i:i]=prefix
            if suffix and i+length==len(rows)-len(prefix):rows.extend(suffix)
            elif suffix:rows[i+len(prefix)+length:i+len(prefix)+length]=suffix
            added=len(prefix)+len(suffix)
        else:
            added=len(incoming);rows.extend(incoming)
        alignment=None if previous is None else {'accepted':True,'method':'complete_rows'} if best else scroll_offset(previous,frame.crop(VIEWPORT))
        records.append({'page':page,'case_id':case['id'],'alignment':alignment,
                        'redundant_capture':added==0,'added_pixel_rows':added*138,'viewport':list(VIEWPORT)})
        previous=frame.crop(VIEWPORT)
    if header is None:return None
    if not rows:raise ValueError('No complete inventory rows; inspect original images')
    strip=Image.new('RGB',(766,len(rows)*138));layers=[]
    for i,row in enumerate(rows):
        y=i*138;strip.paste(row['crop'],(0,y))
        layers.append({'image':row['image'],'source':row['source'],'aliases':row['aliases'],'destination':[0,y,766,y+138]})
    return strip,records,header,layers

def row_matches(left,right):
    # Each column must agree; a different item cannot be hidden by averaging
    # the other four cells. Empty loading rows are not overlap evidence.
    columns=np.array_split(left,5,axis=1)
    return sum(p.std()>12 for p in columns)>=2 and _matching_columns(columns,right)


def _matching_columns(columns,right):
    return all(np.abs(a-b).mean()<8 for a,b in zip(columns,np.array_split(right,5,axis=1)))

def matching_row(left,right):
    # The left row is unchanged across all vertical-shift candidates.
    columns=np.array_split(left['sample'],5,axis=1)
    if sum(p.std()>12 for p in columns)<2:return False
    return any(_matching_columns(columns,sample) for sample in (right['sample'],*right['shifted_samples']))


def rounds(cases):
    groups = defaultdict(dict)
    for case in cases:
        if case['capture']['origin'] != 'device':
            continue
        folder = str(Path(case['image']).parent).replace(chr(92), '/')
        page=case['truth'].get('page',{}).get('value')
        if page!='find' and not (page is None and '/寻物/' in folder):continue
        groups[folder][len(groups[folder])+1] = case
    return groups


def scroll_offset(previous, current):
    """Estimate vertical scroll; compare content over overlap, not fixed UI or timer.

    Negative shifts also cover scroll rebound at the bottom. At least 32 shared pixel rows
    and a normalized mean absolute error below 18 are required for stitching.
    """
    previous = cv2.resize(np.asarray(previous), (96, previous.height)).astype(np.float32)
    current = cv2.resize(np.asarray(current), (96, current.height)).astype(np.float32)
    height = min(len(previous), len(current))
    candidates = []
    # Reuse scratch pixels across every candidate; keep the same float32
    # subtraction, absolute value and mean without allocating two images each time.
    difference = np.empty((max(0,height-12),previous.shape[1]-8)+previous.shape[2:],dtype=np.float32)
    for offset in range(-height + 32, height - 32):
        begin = max(0, offset)
        end = min(height, height + offset)
        # Exclude the clipping edges: the UI fades partially visible tiles.
        if end - begin < 32:
            continue
        left = previous[begin + 6:end - 6, 4:-4]
        right = current[begin - offset + 6:end - offset - 6, 4:-4]
        scratch=difference[:len(left)]
        np.subtract(left,right,out=scratch)
        np.abs(scratch,out=scratch)
        error = float(np.mean(scratch))
        candidates.append((error, offset, end - begin))
    error, offset, overlap = min(candidates)
    return {'offset': offset, 'overlap': overlap, 'error': round(error, 4),
            'accepted': error < 18, 'method': ALIGNMENT_METHOD}

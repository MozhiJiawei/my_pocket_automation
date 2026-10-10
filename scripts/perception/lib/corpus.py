"""Load evidence and independent annotations, never infer truth from predictions."""
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3] / 'testdata'
VERIFIED = {'reviewed', 'device_verified', 'user_verified'}


def load_cases(task=None):
    paths = [ROOT / task / 'cases.json'] if task else sorted(ROOT.glob('*/cases.json'))
    return [case for path in paths for case in json.loads(path.read_text(encoding='utf-8'))['cases']]


def image_path(case):
    folder = (ROOT / case['task']).resolve()
    path = (folder / case['image']).resolve()
    if not path.is_relative_to(folder):
        raise ValueError('Image must remain inside its task corpus')
    return path


def annotation(value, status, source):
    return {'value': value, 'status': status, 'source': source}


def validate(case):
    path = image_path(case)
    if hashlib.sha256(path.read_bytes()).hexdigest() != case['sha256']:
        raise ValueError(f"Image checksum changed: {case['id']}")
    for field in case['truth'].values():
        if field['status'] not in VERIFIED | {'pending', 'proposed'}:
            raise ValueError('Unknown annotation status')
        if field['status'] in VERIFIED and (field['value'] is None or not field['source']):
            raise ValueError('Verified annotations need a value and evidence')
    if not set(case['expected']['checks']).issubset(case['truth']):
        raise ValueError('Every expected check needs an independent annotation')
    width,height=case['capture']['size']
    for field in ('target_regions', 'negative_regions'):
        for x1,y1,x2,y2 in case['truth'].get(field,{}).get('value') or []:
            if not (0<=x1<x2<=width and 0<=y1<y2<=height):
                raise ValueError('Annotated region outside frame')
    rectangles=case['capture'].get('retained_rectangles')
    if rectangles is not None:
        frame=cv2.imdecode(np.fromfile(path,dtype=np.uint8),1)
        outside=frame.copy()
        for x1,y1,x2,y2 in rectangles: outside[y1:y2,x1:x2]=0
        if np.any(outside): raise ValueError('Pixels outside the retained public regions')
    return path


def audit(cases):
    fields = ['page', 'question', 'count', 'target_regions']
    return {task: {
        'frames': len(group),
        'labels': {name: {
            'verified': sum(c['truth'].get(name, {}).get('status') in VERIFIED for c in group),
            'pending': sum(c['truth'].get(name, {}).get('status') in {'pending', 'proposed'} for c in group),
        } for name in fields},
    } for task in sorted({c['task'] for c in cases})
        for group in [[c for c in cases if c['task'] == task]]}

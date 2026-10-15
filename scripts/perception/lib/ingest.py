"""Import public pixels without inferring or overwriting answers."""
import json
import hashlib
from pathlib import Path
import cv2
import numpy as np
from scripts.perception.lib import corpus


def import_frames(sources, case, rectangles, split='holdout'):
    folder=(corpus.ROOT/case).resolve()
    if not folder.is_relative_to(corpus.ROOT.resolve()) or Path(case).parts[0] not in corpus.TASKS.values():
        raise ValueError('Case must be a named directory within a supported task')
    if folder.exists():raise ValueError('Case already exists; approved data will not be overwritten')
    prepared=[]
    for source in sources:
        if not source.is_absolute():raise ValueError('Source must be an absolute path')
        image=cv2.imdecode(np.fromfile(source,dtype=np.uint8),1)
        if image is None:raise ValueError('Unreadable source image')
        height,width=image.shape[:2];frame=np.zeros_like(image)
        for x1,y1,x2,y2 in rectangles:
            if not 0<=x1<x2<=width or not 0<=y1<y2<=height:raise ValueError('Invalid retained rectangle')
            frame[y1:y2,x1:x2]=image[y1:y2,x1:x2]
        prepared.append(cv2.imencode('.png',frame)[1].tobytes())
    if not prepared:raise ValueError('At least one image is required')
    folder.mkdir(parents=True)
    expected={}
    for index,data in enumerate(prepared,1):
        name='画面.png' if len(prepared)==1 else f'第{index:02d}页.png'
        (folder/name).write_bytes(data)
        pending={key:None for key in corpus.directory_truth(Path(case))}
        pending.setdefault('page',None)
        if Path(case).parts[0]=='抓鬼':pending.update(question=None,target_regions=None)
        pending['用途']=split
        expected[name]=pending
    (folder/'答案.json').write_text(json.dumps({'预期':expected},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return folder


def approve(case, proposal, reviewer, evidence):
    """Replace reviewed coordinates, never union stale answers after a correction."""
    from copy import deepcopy
    folder=(corpus.ROOT/case).resolve()
    if not folder.is_relative_to(corpus.ROOT.resolve()) or not folder.is_dir():raise ValueError('Unknown case')
    if not reviewer.strip() or not evidence.strip():raise ValueError('Explicit reviewer and approval evidence required')
    document=deepcopy(proposal)
    if set(document)-{'正确','反例','预期'}:raise ValueError('Unsupported answer sections')
    for section in ('正确','反例'):
        for locations in document.get(section,{}).values():
            for name,box in locations.items():
                image=folder/name
                if image.parent!=folder or not image.is_file():raise ValueError('Answer references an unknown image')
                frame=cv2.imdecode(np.fromfile(image,dtype=np.uint8),1)
                height,width=frame.shape[:2]
                for x1,y1,x2,y2 in corpus.regions(box):
                    if not 0<=x1<x2<=width or not 0<=y1<y2<=height:raise ValueError('Answer outside image')
    for name,expected in document.get('预期',{}).items():
        if Path(name).name!=name or not (folder/name).is_file():raise ValueError('Expected fields reference an unknown image')
        if expected.get('target_regions') not in (None,[]):raise ValueError('Approved positions belong in 正确')
        if expected.get('negative_regions') not in (None,[]):raise ValueError('Approved negatives belong in 反例')
    # A holdout remains a holdout after annotation; approval is not permission to train.
    for name,old in corpus.read_answers(folder).get('预期',{}).items():
        if '用途' in old:document.setdefault('预期',{}).setdefault(name,{})['用途']=old['用途']
    previous=corpus.read_answers(folder)
    if previous!=document and (previous.get('正确') or previous.get('反例') or
            any(all(value is not None for key,value in entry.items() if key!='用途')
                for entry in previous.get('预期',{}).values())):
        content=(folder/'答案.json').read_bytes()
        backup=corpus.ROOT.parent/'debug-runs/annotation-corrections'/case/(hashlib.sha256(content).hexdigest()+'.json')
        backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():backup.write_bytes(content)
    (folder/'答案.json').write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

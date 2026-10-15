"""Capture coverage feedback is independent of confirmed answer correctness."""
import hashlib
import json
from pathlib import Path
import warnings
import tempfile
from PIL import Image
from scripts.perception.lib.task_review import compose_rows

FILENAME='采集反馈.json'
MIN_INVENTORY_HEIGHT=2760
MIN_PUZZLE_HEIGHT=1600
VERIFICATION_METHOD='image_height_v1'
STATUSES={'complete','incomplete','unverified','verification_failed'}


def manifest(folder):
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(folder).glob('第*页.png'))}


def inspect(folder,task,kind):
    """Judge deduplicated inventory strips, or puzzle originals, by height only."""
    folder=Path(folder);files=sorted(folder.glob('第*页.png'))
    report={'status':'verification_failed','can_use_as_complete':False,'pages':len(files),
            'reasons':[],'recoverable':None,'verification_method':VERIFICATION_METHOD}
    try:
        if not files:raise ValueError('没有采集原图。')
        if kind in ('寻物','找鬼'):
            strip,_,_,_=compose_rows({i:{'id':p.name,'image':p.name} for i,p in enumerate(files)},lambda c:folder/c['image'])
            height=strip.height;minimum=MIN_INVENTORY_HEIGHT
        elif kind=='拼图':
            heights=[]
            for path in files:
                with Image.open(path) as image:heights.append(image.height)
            height=min(heights);minimum=MIN_PUZZLE_HEIGHT
        else:raise ValueError('此图片类型没有高度校验规则。')
    except (ValueError,OSError) as exc:
        report['reasons'].append(f'无法读取图片高度：{exc}')
        return report
    report.update(image_height=height,minimum_height=minimum)
    report['status']='complete' if height>=minimum else 'incomplete'
    report['can_use_as_complete']=report['status']=='complete'
    report['evidence']=f'图片高度{height}像素，完整阈值{minimum}像素。'
    if height<minimum:report['reasons'].append(f'图片高度{height}像素，低于完整阈值{minimum}像素。')
    return report


def write(folder,report):
    folder=Path(folder)
    document={**report,'images':manifest(folder)}
    if document['status'] not in STATUSES:
        raise ValueError('无效采集反馈状态')
    if document['status']=='complete' and not document.get('evidence'):
        raise ValueError('完整采集须有独立核验依据')
    document['can_use_as_complete']=document['status']=='complete'
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=folder,prefix='.capture_',delete=False) as pending:
        pending.write(json.dumps(document,ensure_ascii=False,indent=2)+'\n')
        temporary=Path(pending.name)
    try:temporary.replace(folder/FILENAME)
    finally:temporary.unlink(missing_ok=True)
    return document


def read(folder,verify=True):
    folder=Path(folder);path=folder/FILENAME
    if not path.exists():
        return {'status':'unverified','can_use_as_complete':False,'reasons':['未记录采集完整性核验；人类确认答案不代表输入完整。']}
    try:
        report=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(report,dict) or report.get('status') not in STATUSES:
            raise ValueError('无效采集反馈')
        if not isinstance(report.get('reasons'),list) or any(not isinstance(reason,str) for reason in report['reasons']):
            raise ValueError('无效采集反馈原因')
        if verify and report.get('images')!=manifest(folder):
            raise ValueError('原图集合或像素已改变，旧采集核验失效')
        if report['status']=='complete' and not report.get('evidence'):
            raise ValueError('完整采集缺少核验依据')
        report['can_use_as_complete']=report['status']=='complete'
        return report
    except (ValueError,OSError) as exc:
        return {'status':'unverified','can_use_as_complete':False,'reasons':[str(exc)]}


def warn(identity,report):
    if report['status']!='complete':
        warnings.warn(f'采集负反馈 [{identity}] {report["status"]}: '+
                      '；'.join(report['reasons'])+' 不得作为完整题目归档。',UserWarning,stacklevel=2)


def summary(folder):
    return {k:v for k,v in read(folder,verify=False).items() if k!='images'}


def verify(folder,task,kind):
    """Recheck legacy or changed inputs on open; keep confirmed answers untouched."""
    folder=Path(folder);previous=read(folder)
    if previous['status']!='unverified' and previous.get('verification_method')==VERIFICATION_METHOD:return previous
    report=inspect(folder,task,kind)
    if (folder/FILENAME).exists():
        stored=read(folder,verify=False)
        report['previous_feedback']=stored
        report['recoverable']=stored.get('recoverable')
    return write(folder,report)

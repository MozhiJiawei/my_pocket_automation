"""File-based annotation handoff. No database, index or replay of old captures."""
from pathlib import Path
import json
import tempfile
from datetime import datetime
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'annotation-web'
PENDING=BASE/'未完成'
CONFIRMED=BASE/'已完成'

def resolve(stage,identity):
    base={'pending':PENDING,'confirmed':CONFIRMED}.get(stage)
    if base is None:raise ValueError('未知管道')
    path=(base/identity).resolve()
    if not path.is_relative_to(base.resolve()) or path==base.resolve():raise ValueError('无效项目路径')
    if not path.is_dir() or not list(path.glob('第*页.png')):raise ValueError('项目已移走或删除')
    if stage=='confirmed' and not (path/'答案.json').is_file():raise ValueError('已确认文件已删除')
    return path

def items(stage):
    base={'pending':PENDING,'confirmed':CONFIRMED}[stage]
    folders={p.parent for p in base.rglob('第*页.png')}
    result=[]
    for path in folders:
        if path.relative_to(base).parts[0].startswith('.入队_'):continue
        if stage=='confirmed' and not (path/'答案.json').is_file():continue
        relative=path.relative_to(base);parts=relative.parts
        result.append({'id':relative.as_posix(),'task':parts[0],'kind':parts[1],'topic':parts[2],
                       'name':parts[-1],'pages':len(list(path.glob('第*页.png')))})
    return sorted(result,key=lambda item:(item['topic']!='酒',item['task'],item['kind'],item['topic'],item['name']))

def enqueue(source,task,kind,topic,name,suggestions=None,draft=None):
    """Called once by a producer after a complete capture, never by the website."""
    identity=Path(task)/kind/topic/name
    for component in identity.parts:
        if component in ('.','..') or '/' in component or '\\' in component:raise ValueError('无效分类')
    target=(PENDING/identity).resolve()
    if not target.is_relative_to(PENDING.resolve()):raise ValueError('无效入队路径')
    if target.exists() or (CONFIRMED/identity).exists():return identity.as_posix()
    files=sorted(Path(source).glob('第*页.png'))
    if not files:raise ValueError('采集输入为空')
    PENDING.mkdir(parents=True,exist_ok=True)
    cv2.setNumThreads(1)
    with tempfile.TemporaryDirectory(dir=PENDING,prefix='.入队_') as working:
        folder=Path(working)/'item';folder.mkdir()
        for index,path in enumerate(files,1):
            image=cv2.imdecode(np.fromfile(path,np.uint8),1)
            if image is None or image.shape[:2]!=(1600,900):raise ValueError('无效采集原图')
            redacted=np.zeros_like(image);redacted[174:1435,15:887]=image[174:1435,15:887]
            (folder/f'第{index:02d}页.png').write_bytes(cv2.imencode('.png',redacted)[1].tobytes())
        (folder/'来源.txt').write_text(Path(source).resolve().relative_to(ROOT).as_posix()+'\n',encoding='utf-8')
        for filename,document in [('建议.json',suggestions),('草稿.json',draft)]:
            if document is not None:(folder/filename).write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        target.parent.mkdir(parents=True,exist_ok=True);folder.rename(target)
    return identity.as_posix()

def confirm(identity,document):
    source=resolve('pending',identity)
    target=(CONFIRMED/identity).resolve()
    if not target.is_relative_to(CONFIRMED.resolve()) or target.exists():raise ValueError('项目已确认，不能覆盖归档')
    (source/'答案.json').write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (source/'审核.md').write_text('用户在本地标注网页点击“确认并下一项”，确认本项目的“是／否”选择。\n'
        f'确认时间：{datetime.now().isoformat(timespec="seconds")}。坐标以原图为准；尚未写入正式测试真值。\n',encoding='utf-8')
    (source/'草稿.json').unlink(missing_ok=True)
    target.parent.mkdir(parents=True,exist_ok=True);source.rename(target)
    return target

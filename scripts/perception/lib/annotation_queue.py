"""File-based annotation handoff. No database, index or replay of old captures."""
from pathlib import Path
import json
import tempfile
from datetime import datetime
import cv2
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'annotation-web'
PENDING=BASE/'未完成'
CONFIRMED=BASE/'已完成'
PUZZLE_FIELDS={'师门':'puzzle_locations','抓鬼':'puzzle_order'}

def puzzle_layout(task,images):
    """Read the task's existing source-image geometry; never infer piece order."""
    field=PUZZLE_FIELDS.get(task)
    if field is None:raise ValueError('当前不支持此任务的拼图标注')
    path=ROOT/'testdata'/task/'拼图'/'格位.json'
    try:cells=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:raise ValueError('拼图格位配置不可用') from exc
    if not isinstance(cells,list) or len(cells)!=4 or any(
        not isinstance(box,list) or len(box)!=4 or any(type(v)!=int for v in box)
        or not (0<=box[0]<box[2]<=900 and 0<=box[1]<box[3]<=1600) for box in cells):
        raise ValueError('拼图格位须为原图中的四个完整框')
    top_left,top_right,bottom_left,bottom_right=cells
    if len({(box[2]-box[0],box[3]-box[1]) for box in cells})!=1 or not (
        top_left[0]==bottom_left[0] and top_right[0]==bottom_right[0]
        and top_left[1]==top_right[1] and bottom_left[1]==bottom_right[1]
        and top_left[2]<=top_right[0] and top_left[3]<=bottom_left[1]):
        raise ValueError('拼图格位须为等尺寸、互不重叠的2×2行优先排列')
    if any(value['size']!=[900,1600] for value in images.values()):
        raise ValueError('当前拼图标注只支持900×1600完整原图')
    return {'cells':cells,'field':field}

def validate_puzzle_document(document,images,task,complete=False):
    """Partial drafts may omit pages; confirmation requires every source page."""
    if not isinstance(document,dict) or set(document)!={'预期'} or not isinstance(document['预期'],dict):
        raise ValueError('拼图答案须使用预期格式')
    expected=document['预期'];field=PUZZLE_FIELDS.get(task)
    if set(expected)-set(images):raise ValueError('未知原图')
    if expected and field is None:raise ValueError('当前不支持此任务的拼图标注')
    for entry in expected.values():
        if not isinstance(entry,dict) or set(entry)!={field}:raise ValueError('拼图答案字段与任务不匹配')
        order=entry[field]
        if field=='puzzle_locations':
            valid=isinstance(order,list) and len(order)==4 and all(type(v)==int for v in order) and set(order)=={1,2,3,4}
        else:valid=isinstance(order,str) and len(order)==4 and set(order)==set('ABCD')
        if not valid:raise ValueError('拼图答案须为四个原图格的完整排列')
    if complete:
        puzzle_layout(task,images)
        if set(expected)!=set(images):raise ValueError('每张原图都须确认完整拼图排列')
    return document

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
    """Handoff recognition answers; agents review workflow captures directly."""
    if kind not in ('寻物','找鬼','拼图'):
        raise ValueError('流程页面不进入标注队列，由 AGENT 自主核对并固化')
    identity=Path(task)/kind/topic/name
    for component in identity.parts:
        if component in ('.','..') or '/' in component or '\\' in component:raise ValueError('无效分类')
    target=(PENDING/identity).resolve()
    if not target.is_relative_to(PENDING.resolve()):raise ValueError('无效入队路径')
    if target.exists() or (CONFIRMED/identity).exists():return identity.as_posix()
    files=sorted(Path(source).glob('第*页.png'))
    if not files:raise ValueError('采集输入为空')
    if kind=='拼图':
        image_names={f'第{index:02d}页.png':{} for index in range(1,len(files)+1)}
        for document in (suggestions,draft):
            if document is not None:validate_puzzle_document(document,image_names,task)
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

def confirm(identity,document,*,evidence=None):
    if evidence is not None and (not isinstance(evidence,str) or not evidence.strip()):
        raise ValueError('会话确认须提供用户明确确认的审核依据')
    source=resolve('pending',identity)
    target=(CONFIRMED/identity).resolve()
    if not target.is_relative_to(CONFIRMED.resolve()) or target.exists():raise ValueError('项目已确认，不能覆盖归档')
    parts=Path(identity).parts
    puzzle=len(parts)>1 and parts[1]=='拼图'
    if puzzle:
        images={}
        for path in source.glob('第*页.png'):
            with Image.open(path) as image:images[path.name]={'size':list(image.size)}
        validate_puzzle_document(document,images,parts[0],complete=True)
    (source/'答案.json').write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    approval=('用户在本地标注网页点击“确认并下一项”，确认每张原图的四格拖动恢复顺序。\n'
        '预期排列按恢复图左上、右上、左下、右下记录所使用的原图格；'
        '师门以1至4表示原图格，抓鬼以A至D表示原图格，原图格均按行优先排列。\n' if puzzle else
        '用户在本地标注网页点击“确认并下一项”，确认本项目的“是／否”选择。\n')
    if evidence is not None:
        approval='用户在会话中明确确认答案。审核依据：'+evidence.strip()+'\n'
    (source/'审核.md').write_text(approval+
        f'确认时间：{datetime.now().isoformat(timespec="seconds")}。坐标以原图为准；尚未写入正式测试真值。\n',encoding='utf-8')
    (source/'草稿.json').unlink(missing_ok=True)
    target.parent.mkdir(parents=True,exist_ok=True);source.rename(target)
    return target

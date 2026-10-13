"""Local annotation queue. Queue directories are the only queue state."""
import argparse
import json
from pathlib import Path
import secrets
import sys
import threading
import cv2
import numpy as np
from PIL import Image
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib import annotation_queue as queue
from scripts.perception.lib.corpus import validate_truth
from scripts.perception.lib.task_review import item_cells,compose_rows

REFERENCES=Path(__file__).parent/'图标参考'

def reference_catalog(identity):
    folder=(REFERENCES/Path(*Path(identity).parts[:3])).resolve()
    if not folder.is_relative_to(REFERENCES.resolve()):raise ValueError('无效参考分类')
    path=folder/'参考.json'
    if not path.is_file():return folder,{'说明':'此题目暂无图标参考。','图标':[]}
    document=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(document,dict) or not isinstance(document.get('图标',[]),list):raise ValueError('无效参考格式')
    icons=[]
    for entry in document.get('图标',[]):
        if not isinstance(entry,dict) or not all(isinstance(entry.get(k),str) and entry[k] for k in ('名称','图片','来源')):raise ValueError('参考缺少名称、图片或来源')
        name=entry['图片'];source=entry['来源']
        if name in {icon['图片'] for icon in icons}:raise ValueError('参考图片名称重复，请按类别区分同名图标')
        image_path=(folder/name).resolve()
        if Path(name).name!=name or not image_path.is_relative_to(folder) or not image_path.is_file():raise ValueError('无效参考图片')
        if urlsplit(source).scheme not in ('http','https') or not urlsplit(source).netloc:raise ValueError('无效参考来源')
        icons.append(dict(entry))
    return folder,{'说明':document.get('说明',''),'图标':icons}

def with_question(strip,original,layers):
    """Keep the original prompt visible without changing source coordinates."""
    question=original.crop((63,245,829,450))
    combined=Image.new('RGB',(strip.width,question.height+strip.height))
    combined.paste(question,(0,0));combined.paste(strip,(0,question.height))
    shifted=[]
    for layer in layers:
        x1,y1,x2,y2=layer['destination']
        shifted.append({**layer,'destination':[x1,y1+question.height,x2,y2+question.height]})
    return combined,shifted

def validate_document(document,images,topic):
    if not isinstance(document,dict) or '正确' not in document or set(document)-{'正确','反例'}:raise ValueError('无效答案格式')
    for section in ('正确','反例'):
        groups=document.get(section,{})
        if not isinstance(groups,dict) or set(groups)-{topic}:raise ValueError('答案类别不匹配')
        for locations in groups.values():
            if not isinstance(locations,dict):raise ValueError('无效答案位置')
            for name,boxes in locations.items():
                if name not in images:raise ValueError('未知原图')
                if not isinstance(boxes,list) or not boxes:raise ValueError('答案框不能为空')
                for box in boxes:
                    if not isinstance(box,list) or len(box)!=4 or any(type(v)!=int for v in box):raise ValueError('坐标须为四个整数')
                width,height=images[name]['size']
                validate_truth({'truth':{'target_regions':{'status':'proposed','value':boxes}},'expected':{'checks':[]}},width,height)
    for name in images:
        yes=document['正确'].get(topic,{}).get(name,[])
        no=document.get('反例',{}).get(topic,{}).get(name,[])
        if any(max(a[0],b[0])<min(a[2],b[2]) and max(a[1],b[1])<min(a[3],b[3]) for a in yes for b in no):
            raise ValueError('同一位置不能同时为是和否')
    return document

class Item:
    def __init__(self,stage,identity,output):
        self.directory=queue.resolve(stage,identity);self.stage=stage;self.id=identity
        self.task,self.kind,self.topic=Path(identity).parts[:3];self.token=secrets.token_urlsafe(24)
        files=sorted(self.directory.glob('第*页.png'))
        self.images={}
        for path in files:
            try:
                with Image.open(path) as image:self.images[path.name]={'size':list(image.size),'path':path}
            except OSError as exc:raise ValueError('无效原图') from exc
        limitation='';puzzle=None;records=[];layers=[];cells=[]
        if self.kind=='拼图':
            puzzle={'cells':[],'field':queue.PUZZLE_FIELDS.get(self.task)}
            try:puzzle=queue.puzzle_layout(self.task,self.images)
            except ValueError as exc:limitation=f'仅查看原图：{exc}。此输入不能确认。'
            # Puzzle pieces always come directly from the original source image.
            self.strip=files[0];strip_size=self.images[files[0].name]['size']
        else:
            cases={i:{'image':p.name,'id':p.name} for i,p in enumerate(files,1)}
            try:
                if self.kind not in ('寻物','找鬼'):raise ValueError('当前只支持寻物物品格或拼图标注')
                strip,records,original,layers=compose_rows(cases,image_resolver=lambda c:self.images[c['image']]['path'])
                strip,layers=with_question(strip,original,layers)
            except ValueError as exc:
                # Unsupported failure scenes stay reviewable, without creating truth.
                with Image.open(files[0]) as image:strip=image.convert('RGB')
                limitation=f'仅查看原图：{exc}。此输入不能确认。'
            target=output/stage/identity;target.mkdir(parents=True,exist_ok=True)
            self.strip=target/'长图.png';strip.save(self.strip);strip_size=list(strip.size)
            if not limitation:
                cells=[{'image':name,'box':box} for name,value in self.images.items()
                       for box in item_cells(cv2.imdecode(np.fromfile(value['path'],np.uint8),1))]
        suggestions={'预期':{}} if self.kind=='拼图' else self.read('建议.json')
        self.data={'id':identity,'stage':stage,'kind':self.kind,'topic':self.topic,'token':self.token,'cells':cells,
                   'images':[{'name':name,'size':value['size']} for name,value in self.images.items()],
                   'strip':{'size':strip_size,'layers':layers,'records':records},'suggestions':suggestions,
                   'annotatable':not limitation,'limitation':limitation}
        if puzzle is not None:
            self.data['puzzle']=puzzle
            self.puzzle_documents()
    def read(self,name):
        path=self.directory/name
        if self.kind=='拼图':
            document=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'预期':{}}
            return queue.validate_puzzle_document(document,self.images,self.task,complete=name=='答案.json')
        document=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'正确':{self.topic:{}}}
        return validate_document(document,self.images,self.topic)
    def puzzle_documents(self):
        """Invalid handoff files stay inspectable without adopting their labels."""
        initial_name='答案.json' if self.stage=='confirmed' else '草稿.json'
        documents={};errors=[]
        for name in ('建议.json',initial_name):
            try:documents[name]=self.read(name)
            except (ValueError,OSError) as exc:errors.append(f'{name}：{exc}')
        if errors:
            self.data['annotatable']=False
            warning='仅查看原图：拼图标注文件无效（'+'；'.join(errors)+'）。未加载已核对排列，不能确认。'
            if warning not in self.data['limitation']:
                self.data['limitation']=' '.join(filter(None,(self.data['limitation'],warning)))
        if not self.data['annotatable']:
            self.data['suggestions']={'预期':{}}
            return {'预期':{}},{'预期':{}}
        suggestions=documents['建议.json'];self.data['suggestions']=suggestions
        initial=documents[initial_name] if (self.directory/initial_name).exists() else suggestions
        return initial,suggestions
    def save(self,document):
        if self.stage!='pending':raise ValueError('已完成归档只读')
        if self.kind=='拼图':self.puzzle_documents()
        if not self.data.get('annotatable',True):raise ValueError('此输入尚不支持标注，不能确认')
        if self.kind=='拼图':queue.validate_puzzle_document(document,self.images,self.task,complete=True)
        else:validate_document(document,self.images,self.topic)
        return queue.confirm(self.id,document)

class Review:
    def __init__(self):
        self.cache={};self.lock=threading.Lock()
        self.output=ROOT/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'annotation-web'
    def get(self,stage,identity):
        queue.resolve(stage,identity)  # Deleted files invalidate even cached items.
        key=(stage,identity)
        with self.lock:
            if key not in self.cache:self.cache[key]=Item(stage,identity,self.output)
            return self.cache[key]

def handler(review):
    class Handler(BaseHTTPRequestHandler):
        def respond(self,status,body,kind='application/json; charset=utf-8'):
            if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
            self.end_headers();self.wfile.write(body)
        def do_GET(self):
            url=urlsplit(self.path);args=parse_qs(url.query)
            if url.path=='/api/queue':return self.respond(200,{stage:queue.items(stage) for stage in ('pending','confirmed')})
            if url.path.startswith('/api/'):
                try:item=review.get(args.get('stage',['pending'])[0],args.get('id',[''])[0])
                except ValueError as exc:return self.respond(404,{'error':str(exc)})
            if url.path=='/api/item':
                if item.kind=='拼图':initial,suggestions=item.puzzle_documents()
                else:
                    try:
                        initial=item.read('答案.json' if item.stage=='confirmed' else '草稿.json')
                        suggestions=item.read('建议.json')
                    except ValueError as exc:return self.respond(400,{'error':str(exc)})
                    if not (item.directory/('答案.json' if item.stage=='confirmed' else '草稿.json')).exists():initial=suggestions
                try:_,references=reference_catalog(item.id)
                except (ValueError,KeyError):references={'说明':'参考资料格式无效，请检查该题目的参考.json。','图标':[]}
                note=item.directory/'建议说明.md'
                return self.respond(200,{**item.data,'suggestions':suggestions,'initial':initial,
                    'references':references,'proposal_note':note.read_text(encoding='utf-8') if note.is_file() else ''})
            if url.path=='/api/reference':
                try:folder,catalog=reference_catalog(item.id)
                except (ValueError,KeyError) as exc:return self.respond(404,{'error':str(exc)})
                name=args.get('name',[''])[0]
                if name not in {entry['图片'] for entry in catalog['图标']}:return self.respond(404,{'error':'未知参考图片'})
                with Image.open(folder/name) as reference:kind=Image.MIME.get(reference.format,'application/octet-stream')
                return self.respond(200,(folder/name).read_bytes(),kind)
            if url.path=='/api/image':
                name=args.get('name',[''])[0]
                if name not in item.images:return self.respond(404,{'error':'未知原图'})
                return self.respond(200,item.images[name]['path'].read_bytes(),'image/png')
            if url.path=='/api/strip':return self.respond(200,item.strip.read_bytes(),'image/png')
            assets={'/':'index.html','/app.js':'app.js','/puzzle.js':'puzzle.js','/style.css':'style.css'}
            if url.path not in assets:return self.respond(404,{'error':'未找到'})
            name=assets[url.path];kind={'html':'text/html','js':'text/javascript','css':'text/css'}[name.rsplit('.',1)[1]]
            return self.respond(200,(Path(__file__).parent/name).read_bytes(),kind+'; charset=utf-8')
        def do_POST(self):
            url=urlsplit(self.path);args=parse_qs(url.query)
            if url.path!='/api/confirm':return self.respond(404,{'error':'未找到'})
            try:item=review.get('pending',args.get('id',[''])[0])
            except ValueError as exc:return self.respond(404,{'error':str(exc)})
            if self.headers.get('X-Annotation-Token')!=item.token:return self.respond(403,{'error':'页面验证失败，请刷新'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=262144:raise ValueError('请求大小无效')
                document=json.loads(self.rfile.read(length))
                with review.lock:target=item.save(document)
            except (ValueError,TypeError,OSError) as exc:return self.respond(400,{'error':str(exc)})
            return self.respond(200,{'confirmed':True,'archive':target.relative_to(ROOT).as_posix()})
        def log_message(self,format,*args):pass
    return Handler

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args();cv2.setNumThreads(1);review=Review()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(review))
    print(f'http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

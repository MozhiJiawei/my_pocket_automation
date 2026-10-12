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
        self.topic=Path(identity).parts[2];self.token=secrets.token_urlsafe(24)
        files=sorted(self.directory.glob('第*页.png'))
        self.images={p.name:{'size':[900,1600],'path':p} for p in files}
        cases={i:{'image':p.name,'id':p.name} for i,p in enumerate(files,1)}
        # Reuse the same composition code, supplying only this item's images.
        try:
            if Path(identity).parts[1] not in ('寻物','找鬼'):raise ValueError('当前只支持寻物物品格标注')
            strip,records,original,layers=compose_rows(cases,image_resolver=lambda c:self.images[c['image']]['path'])
            strip,layers=with_question(strip,original,layers)
            limitation=''
        except ValueError as exc:
            # Unsupported failure scenes stay reviewable, without creating truth.
            strip=Image.open(files[0]).convert('RGB');records=[];layers=[]
            limitation=f'仅查看原图：{exc}。此输入保留在未完成队列，不能确认。'
        target=output/stage/identity;target.mkdir(parents=True,exist_ok=True)
        self.strip=target/'长图.png';strip.save(self.strip)
        cells=[{'image':name,'box':box} for name,value in self.images.items()
               for box in item_cells(cv2.imdecode(np.fromfile(value['path'],np.uint8),1))] if not limitation else []
        suggestions=self.read('建议.json')
        validate_document(suggestions,self.images,self.topic)
        self.data={'id':identity,'stage':stage,'topic':self.topic,'token':self.token,'cells':cells,
                   'images':[{'name':name,'size':value['size']} for name,value in self.images.items()],
                   'strip':{'size':list(strip.size),'layers':layers,'records':records},'suggestions':suggestions,
                   'annotatable':not limitation,'limitation':limitation}
    def read(self,name):
        path=self.directory/name
        document=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'正确':{self.topic:{}}}
        return validate_document(document,self.images,self.topic)
    def save(self,document):
        if not self.data.get('annotatable',True):raise ValueError('此输入尚不支持标注，不能确认')
        validate_document(document,self.images,self.topic)
        if self.stage!='pending':raise ValueError('已完成归档只读')
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
                initial=item.read('答案.json' if item.stage=='confirmed' else '草稿.json')
                has_initial=(item.directory/('答案.json' if item.stage=='confirmed' else '草稿.json')).exists()
                suggestions=item.read('建议.json')
                return self.respond(200,{**item.data,'suggestions':suggestions,'initial':initial if has_initial else suggestions})
            if url.path=='/api/image':
                name=args.get('name',[''])[0]
                if name not in item.images:return self.respond(404,{'error':'未知原图'})
                return self.respond(200,item.images[name]['path'].read_bytes(),'image/png')
            if url.path=='/api/strip':return self.respond(200,item.strip.read_bytes(),'image/png')
            assets={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
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

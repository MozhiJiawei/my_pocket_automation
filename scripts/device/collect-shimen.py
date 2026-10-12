"""Bounded host-assisted Shimen exploration; screenshots are evidence, not truth."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import cv2
import numpy as np
from rapidocr import RapidOCR
from dfx_device import Device

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.shimen_collection import Novelty,question,saturated
from scripts.perception.lib.annotation_queue import enqueue

cv2.setNumThreads(1)

class Explorer:
    def __init__(self,device):
        self.device=Device(device)
        self.folder=ROOT/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')
        (self.folder/'res').mkdir(parents=True);(self.folder/'log').mkdir()
        (self.folder/'collector-source.py').write_text(Path(__file__).read_text(encoding='utf-8'),encoding='utf-8')
        self.engine=RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads':2,
                                    'EngineConfig.onnxruntime.inter_op_num_threads':1})
        self.serial=0
        self.device.authorize()
        self.note(event='start',device=device,account='current',task='shimen',max_tasks=20)
    def note(self,**values):
        with (self.folder/'log/exploration.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(values,ensure_ascii=False)+'\n')
        display={k:v for k,v in values.items() if k!='words'}
        if 'words' in values:display['text']=[w['text'] for w in values['words'] if 170<np.asarray(w['box'])[:,1].mean()<1440]
        print(json.dumps(display,ensure_ascii=False),flush=True)
    def frame(self):
        result=subprocess.run([self.device.adb,'-s',self.device.device,'exec-out','screencap','-p'],
                              capture_output=True,timeout=30,check=True)
        image=cv2.imdecode(np.frombuffer(result.stdout,np.uint8),1)
        if image is None or image.shape[:2]!=(1600,900):raise RuntimeError('Unsupported frame')
        return result.stdout,image
    def words(self,image):
        result=self.engine(image)
        return [] if result.txts is None else [{'text':str(t),'score':float(s),'box':np.asarray(b).tolist()}
                 for t,s,b in zip(result.txts,result.scores,result.boxes)]
    def capture(self,label='观察'):
        raw,image=self.frame();words=self.words(image)
        self.serial+=1;path=self.folder/'res'/f'{self.serial:04d}_{label}.png';path.write_bytes(raw)
        self.note(event='capture',path=str(path),words=words)
        return image,words,path
    def command(self,command):
        action=command['action']
        if action=='observe':return self.capture(command.get('label','观察'))
        if action=='tap':
            if self.device.status()!='f00':raise RuntimeError('Device script is not idle')
            _,words,path=self.capture('操作前')
            expected=command['expect'];point=command['point']
            if not expected or not any(expected in w['text'] and w['score']>.8 for w in words):
                raise RuntimeError('Expected page absent; no input sent')
            if len(point)!=2 or not (0<=point[0]<900 and 0<=point[1]<1600):raise ValueError('Invalid point')
            paid=[w for w in words if w['text'].strip()=='领取任务' and w['score']>.9]
            if any(np.min(w['box'],axis=0)[0]-100<point[0]<np.max(w['box'],axis=0)[0]+100 and
                   1300<point[1]<1430 for w in paid):
                texts=[w['text'] for w in words if w['score']>.9]
                count=next((int(m[1]) for t in texts if (m:=re.search(r'(\d+)/20',t))),None)
                if '师门任务' not in texts or '当前未进行任务' not in texts or count is None or count>=20:
                    raise RuntimeError('Paid task guard failed')
                if not any('完成任务消耗2' in t for t in texts):raise RuntimeError('Unexpected energy cost')
                ledger=self.folder/'log/师门进度.json'
                previous=json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else {'attempts':count}
                if previous['attempts']!=count:raise RuntimeError('Shimen count and ledger mismatch')
                ledger.write_text(json.dumps({'account':'current','date':datetime.now().strftime('%Y%m%d'),
                    'attempts':count+1,'energy_cap':40,'stage':'accept_reserved','evidence':str(path)},ensure_ascii=False),encoding='utf-8')
                self.note(event='accept_reserved',attempt=count+1,energy_cap=40)
            self.device.adb_call('shell','input','tap',str(point[0]),str(point[1]))
            self.note(event='tap',expect=expected,point=point,before=str(path))
            time.sleep(1.2);return self.capture('操作后')
        raise ValueError('Unknown exploration action')

    def collect(self,ownership,max_batches=10,previous=()):
        ledger=json.loads(ownership.read_text(encoding='utf-8'))
        if ledger.get('account')!='current' or ledger.get('date')!=datetime.now().strftime('%Y%m%d'):
            raise RuntimeError('Collection ownership mismatch')
        attempt=ledger['attempts'];novelty=Novelty();kind=None
        for archive in previous:
            for line in (archive/'log/exploration.jsonl').read_text(encoding='utf-8').splitlines():
                event=json.loads(line)
                if event.get('event')=='round' and event.get('kind')=='寻物':
                    novelty.questions.add(event['topic'])
            for path in sorted((archive/'res/拼图').glob('*/第*轮/第01页.png')):
                image=cv2.imdecode(np.fromfile(path,np.uint8),1)
                cells=((146,556,438,926),(448,556,740,926),(146,938,438,1308),(448,938,740,1308))
                novelty.puzzle([image[y1:y2,x1:x2] for x1,y1,x2,y2 in cells])
        self.note(event='seeded',topics=len(novelty.questions),puzzles=len(novelty.puzzles),novelty='categories_only')
        self.note(event='collection_start',attempt=attempt,selection_taps=0,new_accepts=0)
        for batch in range(1,max_batches+1):
            additions=0
            for cycle in range(1,11):
                if ledger['date']!=datetime.now().strftime('%Y%m%d'):raise RuntimeError('Business date changed')
                deadline=time.monotonic()+90
                while time.monotonic()<deadline:
                    raw,frame=self.frame();words=self.words(frame);texts=[w['text'] for w in words if w['score']>.8]
                    if '找东西' in texts or '拼图' in texts:break
                    counts=[int(m[1]) for t in texts if (m:=re.search(r'(\d+)/20',t))]
                    if not any('师门任务' in t for t in texts) or counts!=[attempt]:
                        raise RuntimeError('Active Shimen identity/count changed')
                    if '当前未进行任务' in texts:raise RuntimeError('Collection must not accept a new task')
                    if any('确定要认输' in text for text in texts):
                        buttons=[w for w in words if w['text'].strip()=='确定' and w['score']>.9]
                        if len(buttons)!=1 or self.device.status()!='f00':
                            raise RuntimeError('Interrupted concede dialog not verified')
                        x,y=np.asarray(buttons[0]['box']).mean(axis=0).astype(int)
                        self.device.adb_call('shell','input','tap',str(x),str(y));time.sleep(.6)
                        self.note(event='resume_concede',attempt=attempt)
                        continue
                    buttons=[w for w in words if w['text'].strip() in ('再来一次','我来整理','我准备好了','再试试') and
                             w['score']>.9 and 1300<np.asarray(w['box'])[:,1].mean()<1430]
                    if len(buttons)==1:
                        if self.device.status()!='f00':raise RuntimeError('Device is not idle')
                        x,y=np.asarray(buttons[0]['box']).mean(axis=0).astype(int)
                        self.device.adb_call('shell','input','tap',str(x),str(y));time.sleep(.8)
                    else:time.sleep(.6)
                else:raise RuntimeError('No recognized free retry within bound')
                this_kind='寻物' if '找东西' in texts else '拼图'
                if kind and this_kind!=kind:raise RuntimeError('Opportunity changed type')
                kind=this_kind;topic=question(words) if kind=='寻物' else None
                if kind=='寻物' and topic is None:raise RuntimeError('Question not readable')
                category=topic[0] if topic else '未命名图案'
                target=self.folder/'res'/kind/category/f'第{(batch-1)*10+cycle:02d}轮';target.mkdir(parents=True)
                before=additions
                for page in range(1,8 if kind=='寻物' else 2):
                    if page>1:raw,frame=self.frame()
                    (target/f'第{page:02d}页.png').write_bytes(raw)
                    if kind=='寻物' and page==1:
                        additions+=novelty.items(category)
                    elif kind=='拼图':
                        cells=((146,556,438,926),(448,556,740,926),(146,938,438,1308),(448,938,740,1308))
                        additions+=novelty.puzzle([frame[y1:y2,x1:x2] for x1,y1,x2,y2 in cells])
                    if kind=='寻物' and page<7:
                        self.device.adb_call('shell','input','swipe','800','1260','800','800','240');time.sleep(.25)
                self.note(event='round',attempt=attempt,batch=batch,round=cycle,kind=kind,topic=category,
                          required=topic[1] if topic else None,new_material=additions-before,folder=str(target))
                queued=enqueue(target,'师门',kind,category,f'{self.folder.name}_{target.name}')
                self.note(event='annotation_queued',item=queued)
                # Concede only this minigame, never cancel the owned Shimen job.
                _,live=self.frame();current=self.words(live)
                if any(w['text'] in ('找东西','拼图') for w in current):
                    self.device.adb_call('shell','input','tap','48','1510');time.sleep(.4)
                    _,dialog=self.frame();dialog_words=self.words(dialog)
                    if any('确定要认输' in w['text'] for w in dialog_words):
                        buttons=[w for w in dialog_words if w['text'].strip()=='确定' and w['score']>.9]
                        if len(buttons)!=1:raise RuntimeError('Concede button not verified')
                        x,y=np.asarray(buttons[0]['box']).mean(axis=0).astype(int)
                        self.device.adb_call('shell','input','tap',str(x),str(y));time.sleep(.4)
                    elif any(w['text'] in ('找东西','拼图') for w in dialog_words):
                        raise RuntimeError('Minigame exit not verified')
                # Verify the owned job remains available after conceding/timeout.
                until=time.monotonic()+50
                while time.monotonic()<until:
                    _,image=self.frame();exit_words=self.words(image);current=[w['text'] for w in exit_words]
                    if any('确定要认输' in text for text in current):
                        buttons=[w for w in exit_words if w['text'].strip()=='确定' and w['score']>.9]
                        if len(buttons)!=1:raise RuntimeError('Delayed concede button not verified')
                        x,y=np.asarray(buttons[0]['box']).mean(axis=0).astype(int)
                        self.device.adb_call('shell','input','tap',str(x),str(y));time.sleep(.6)
                        continue
                    if '找东西' not in current and '拼图' not in current:
                        counts=[int(m[1]) for text in current if (m:=re.search(r'(\d+)/20',text))]
                        if not any('师门任务' in text for text in current) or counts!=[attempt] or '当前未进行任务' in current:
                            raise RuntimeError('Owned task changed after free retry')
                        break
                    time.sleep(1)
                else:raise RuntimeError('Board did not expire')
            self.note(event='batch',attempt=attempt,batch=batch,new_material=additions,
                      topics=len(novelty.questions),puzzles=len(novelty.puzzles))
            if saturated(10,additions):
                self.note(event='saturated',attempt=attempt,batches=batch,rounds=batch*10,selection_taps=0,new_accepts=0)
                return
        raise RuntimeError('Batch bound reached without saturation; collection is incomplete')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--device',required=True)
    p.add_argument('--collect',action='store_true');p.add_argument('--ownership',type=Path)
    p.add_argument('--previous',type=Path,nargs='*',default=[])
    args=p.parse_args();explorer=Explorer(args.device)
    try:
        explorer.note(event='ready',archive=str(explorer.folder))
        if args.collect:
            if not args.ownership or not args.ownership.is_absolute():raise ValueError('External owned progress path required')
            explorer.collect(args.ownership,previous=args.previous);return
        for line in sys.stdin:
            if not line.strip():continue
            try:
                command=json.loads(line)
                if command['action']=='exit':break
                explorer.command(command)
            except Exception as exc:explorer.note(event='error',type=type(exc).__name__,reason=str(exc))
    except Exception as exc:
        explorer.note(event='error',type=type(exc).__name__,reason=str(exc),collection_complete=False)
        try:explorer.capture('错误现场')
        except Exception:pass
        raise
    finally:explorer.device.close()

if __name__=='__main__':main()

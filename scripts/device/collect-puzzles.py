"""Collect an owned failed puzzle through its free Continue dialogue; no tile taps."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import time

import cv2
import numpy as np
from rapidocr import RapidOCR
from dfx_device import Device

ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--device',required=True)
    p.add_argument('--account',default='current')
    p.add_argument('--rounds',type=int,default=10)
    args=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.account) or not 1<=args.rounds<=20:
        raise ValueError('Invalid account or bounded rounds')
    run_id=datetime.now().strftime('%Y%m%d_%H%M%S')
    folder=ROOT/'debug-runs'/run_id
    (folder/'res').mkdir(parents=True)
    (folder/'log').mkdir()
    device=Device(args.device)
    engine=RapidOCR()
    progress_path=f'/storage/emulated/0/TouchSprite/res/daily_progress_{datetime.now():%Y%m%d}_{args.account}_zhuagui.lua'
    records=[]
    def ledger():
        text=device.adb_call('shell','cat',progress_path)
        if 'status="running"' not in text:raise RuntimeError('No owned active task')
        values={k:int(v) for k,v in re.findall(r'(attempts|completed_count|reserved_energy)=(\d+)',text)}
        if values.get('attempts')!=values.get('completed_count',-2)+1:raise RuntimeError('Unverified ownership')
        return values
    def frame():
        result=subprocess.run([device.adb,'-s',args.device,'exec-out','screencap','-p'],capture_output=True,timeout=30,check=True)
        image=cv2.imdecode(np.frombuffer(result.stdout,np.uint8),1)
        if image is None or image.shape[:2]!=(1600,900):raise RuntimeError('Unexpected capture dimensions')
        return result.stdout,image
    def words(image):
        output=engine(image)
        if output.txts is None:return []
        return [(str(t),float(s),np.asarray(b)) for t,s,b in zip(output.txts,output.scores,output.boxes)]
    def note(item):
        records.append(item)
        (folder/'log/capture.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(item,ensure_ascii=False),flush=True)
    try:
        device.authorize()
        if device.status()!='f00':raise RuntimeError('Device script is not idle')
        original=ledger()
        captured=0
        for round_number in range(1,args.rounds+1):
            deadline=time.monotonic()+75
            opened=False
            while time.monotonic()<deadline:
                raw,image=frame();text=words(image)
                puzzle=any('拼图' in t and float(b[:,1].mean())<270 for t,s,b in text if s>.8)
                if puzzle and (opened or round_number==1):
                    path=folder/'res'/f'daily_{run_id}_puzzle_r{round_number:02d}.png'
                    path.write_bytes(raw)
                    captured+=1;note({'round':round_number,'image':str(path.relative_to(folder)),
                                     'tile_taps':0,'new_accepts':0})
                    break
                # Only this owned NPC failure dialogue; never an Accept/paid page.
                header=any('抓鬼任务' in t for t,s,b in text if s>.8)
                body=any('再试试' in t for t,s,b in text if s>.8)
                buttons=[b for t,s,b in text if t.strip()=='继续' and s>.9 and
                         320<float(b[:,0].mean())<875 and 1300<float(b[:,1].mean())<1430]
                if header and body and len(buttons)==1:
                    if device.status()!='f00' or ledger()!=original:raise RuntimeError('Ownership/state changed before Continue')
                    # Revalidate the same free failure prompt immediately before input.
                    _,current=frame();check=words(current)
                    if not any('再试试' in t for t,s,b in check if s>.8):raise RuntimeError('Failure dialogue changed')
                    target=next((b for t,s,b in check if t.strip()=='继续' and s>.9 and
                                 320<float(b[:,0].mean())<875 and 1300<float(b[:,1].mean())<1430),None)
                    if target is None:raise RuntimeError('Continue target disappeared')
                    x,y=map(lambda v:str(int(v)),target.mean(axis=0))
                    device.adb_call('shell','input','tap',x,y)
                    opened=True
                    time.sleep(1)
                else:time.sleep(1)
            else:raise RuntimeError('Puzzle did not appear within bounded wait')
            if round_number<args.rounds:
                # Let this board expire; do not save redundant countdown frames.
                time.sleep(20)
        if ledger()!=original:raise RuntimeError('Collection changed task progress')
        note({'finished':True,'captured':captured,'attempts':original['attempts'],
              'completed_count':original['completed_count'],'reserved_energy':original['reserved_energy'],
              'tile_taps':0,'new_accepts':0})
    except Exception as exc:
        note({'finished':False,'error_type':type(exc).__name__})
        raise
    finally:device.close()
    print('ARCHIVE:',folder,flush=True)

if __name__=='__main__':main()

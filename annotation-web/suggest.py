"""Generate unapproved wine suggestions using the production color detector."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.support.lua_runtime import Runtime
from tests.support.touchsprite_adapter import Screen
from tests.support.opencl_colors import GpuScreen
from scripts.perception.lib import annotation_queue as queue

def main():
    backend=GpuScreen if GpuScreen.available() else Screen
    for item in queue.items('pending'):
        if item['topic']!='酒' or item['kind']!='寻物':continue
        folder=queue.resolve('pending',item['id'])
        answers={}
        for image in sorted(folder.glob('*.png')):
            runtime=Runtime(backend.read(image));points=[]
            for feature in runtime.require('tasks.zhuagui.assets.catalog')['酒'].values():
                found=runtime.require('common.detector').find(feature)
                if found:
                    x=int(found['x']+feature['tap_offset'][1]);y=int(found['y']+feature['tap_offset'][2])
                    if not any(abs(x-px)<60 and abs(y-py)<60 for px,py in points):points.append((x,y))
            if points:answers[image.name]=[[x-55,y-55,x+55,y+55] for x,y in points]
        target=folder/'建议.json'
        target.write_text(json.dumps({'正确':{'酒':answers}},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(f'{folder.name}: {sum(map(len,answers.values()))} candidates',flush=True)

if __name__=='__main__':main()

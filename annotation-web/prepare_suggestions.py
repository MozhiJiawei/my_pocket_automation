"""Prepare numbered full-round review sheets; save only unapproved suggestions."""
from pathlib import Path
import json
import sys
from datetime import datetime
import cv2
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.perception.lib import annotation_queue as queue
from scripts.perception.lib.task_review import compose_rows,item_cells
import numpy as np

def prepare(topic):
    cv2.setNumThreads(1)
    output=ROOT/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'AI标注'/topic
    output.mkdir(parents=True,exist_ok=True);result={}
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',16)
    for entry in queue.items('pending'):
        if entry['topic']!=topic or entry['kind'] not in ('寻物','找鬼'):continue
        folder=queue.resolve('pending',entry['id']);files=sorted(folder.glob('第*页.png'))
        strip,_,original,layers=compose_rows({i:{'id':p.name,'image':p.name} for i,p in enumerate(files)},image_resolver=lambda c:folder/c['image'])
        cells=[]
        for layer in layers:
            source=Image.open(folder/layer['image']).convert('RGB')
            for box in item_cells(np.asarray(source)):
                x1,y1,x2,y2=layer['source']
                if x1<=box[0]<box[2]<=x2 and y1<=box[1]<box[3]<=y2:
                    cells.append({'image':layer['image'],'box':box})
        sheet=Image.new('RGB',(600,180+((len(cells)+4)//5)*136),'white')
        sheet.paste(original.crop((63,245,829,450)).resize((600,160)),(0,0));draw=ImageDraw.Draw(sheet)
        for i,cell in enumerate(cells):
            x=(i%5)*120;y=180+(i//5)*136
            tile=Image.open(folder/cell['image']).convert('RGB').crop(cell['box']).resize((116,116))
            sheet.paste(tile,(x,y+20));draw.text((x+4,y),str(i+1),font=font,fill='black')
        path=output/(entry['name']+'.jpg');sheet.save(path,quality=92)
        result[entry['name']]={'id':entry['id'],'sheet':str(path),'cells':cells}
    index=output/'物品映射.json';index.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    return index

def write(index,selections,note):
    mapping=json.loads(Path(index).read_text(encoding='utf-8'))
    if set(selections)!=set(mapping):raise ValueError('Must review every round of this category')
    for name,indices in selections.items():
        item=mapping[name];folder=queue.resolve('pending',item['id']);topic=Path(item['id']).parts[2]
        positives={}
        for i in sorted(set(indices)):
            if type(i)!=int or not 1<=i<=len(item['cells']):raise ValueError('Invalid candidate number')
            cell=item['cells'][i-1];positives.setdefault(cell['image'],[]).append(cell['box'])
        (folder/'建议.json').write_text(json.dumps({'正确':{topic:positives}},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (folder/'建议说明.md').write_text(note+'\nAI 建议，尚未经用户确认；未选位置不是已确认反例。\n',encoding='utf-8')

if __name__=='__main__':print(prepare(sys.argv[1]))

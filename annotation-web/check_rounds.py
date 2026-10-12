"""Check all wine strips against their original pixels and clickable cells."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from datetime import datetime
import json
import time
from PIL import Image
from server import ROOT,item_cells,compose_rows
from scripts.perception.lib import annotation_queue as queue
import numpy as np

def contains(outer,box):return outer[0]<=box[0]<box[2]<=outer[2] and outer[1]<=box[1]<box[3]<=outer[3]

def check(job):
    stage,name,output=job
    folder=queue.resolve(stage,name)
    files={p.name:p for p in sorted(folder.glob('*.png'))}
    sources={name:Image.open(path).convert('RGB') for name,path in files.items()}
    cases={i:{'image':filename,'id':filename} for i,filename in enumerate(files,1)}
    strip,_,_,layers=compose_rows(cases,image_resolver=lambda c:files[c['image']])
    target=Path(output)/stage/name;target.mkdir(parents=True,exist_ok=True);strip.save(target/'长图.png')
    answer=folder/('答案.json' if stage=='confirmed' else '建议.json')
    suggestions=json.loads(answer.read_text(encoding='utf-8')) if answer.exists() else {}
    data={'cells':[{'image':name,'box':box} for name,image in sources.items() for box in item_cells(np.asarray(image))],'suggestions':suggestions}
    for layer in layers:
        x,y,_,end=layer['destination']
        assert strip.crop((x,y,766,end)).tobytes()==sources[layer['image']].crop(layer['source']).tobytes(),'Painted pixels differ'
    for cell in data['cells']:
        matches=[layer for layer in layers for alias in layer['aliases'] if alias['image']==cell['image'] and contains(alias['source'],cell['box'])]
        assert len(matches)==1,f'Cell mapped {len(matches)} times: {cell}'
    missing=[]
    for image,boxes in data['suggestions'].get('正确',{}).get('酒',{}).items():
        for box in boxes:
            if not any(alias['image']==image and contains(alias['source'],box) for layer in layers for alias in layer['aliases']):missing.append({'image':image,'box':box})
    return {'round':name,'pages':len(sources),'rows':len(layers),'clickable_cells':len(layers)*5,
            'original_cell_instances':len(data['cells']),'suggestions_without_complete_row':missing,'passed':not missing}

if __name__=='__main__':
    start=time.perf_counter();output=ROOT/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'annotation-web'
    output.mkdir(parents=True,exist_ok=True)
    jobs=[(stage,item['id'],str(output)) for stage in ('pending','confirmed') for item in queue.items(stage) if item['topic']=='酒']
    with ProcessPoolExecutor(max_workers=3) as pool:results=list(pool.map(check,jobs))
    report={'rounds':results,'seconds':round(time.perf_counter()-start,3)}
    (output/'拼接检查.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True);print(output,flush=True)
    raise SystemExit(0 if all(r['passed'] for r in results) else 1)

"""Add collector evidence without overwriting reviewed truth or accepting predictions."""
import hashlib
import json
import re
from pathlib import Path
from scripts.perception.lib.corpus import ROOT, annotation


def sync_catalog():
    folder=ROOT/'zhuagui'
    index=folder/'images/catalog/manifest.json'
    document=json.loads((folder/'cases.json').read_text(encoding='utf-8'))
    captures=json.loads(index.read_text(encoding='utf-8'))
    known={c['sha256'] for c in document['cases']}
    added=0
    for record in captures['cases']:
        for item in record['frames']:
            path=folder/'images/catalog'/item['image']
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            if digest!=item['sha256']: raise ValueError('Collector frame hash changed')
            if digest in known: continue
            match=re.search(r'_r(\d+)_',item['image'])
            run=item['source'].split('/')[1] if item['source'].startswith('debug-runs/') else record['source_run']
            truth={'page':annotation('find' if item['hint_visible'] else 'not_find','proposed','Machine visibility flag; requires independent review'),
                   'target_regions':annotation(None,'pending','Object position not annotated')}
            if item['hint_visible']:
                truth['question']=annotation({'text':record['question'],'target':record['topic']},'proposed','Reviewed round label inherited; confirm this frame')
            document['cases'].append({'id':'zhuagui_'+digest[:16],'task':'zhuagui',
                'image':path.relative_to(folder).as_posix(),'sha256':digest,
                'capture':{'size':[900,1600],'game_version':None,'group':run,
                           'split':'calibration','origin':'device','retained_rectangles':[[15,174,887,1435]]},
                'truth':truth,'expected':{'checks':list(truth),'on_unknown':'abstain'},
                'provenance':[{'source':item['source'],'run':run,'round':int(match[1]) if match else record['source_round']}]})
            known.add(digest); added+=1
    (folder/'cases.json').write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Added {added} pending evidence cases; existing reviewed labels preserved')

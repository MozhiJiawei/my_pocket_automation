"""Apply explicitly approved human review entries; evaluation never calls this tool."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.corpus import annotation, validate


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--approve',nargs='+',required=True,help='Exact topic names explicitly confirmed by the user')
    parser.add_argument('--reviewer',required=True)
    parser.add_argument('--evidence',required=True,help='Human message/date or reviewed document reference')
    args=parser.parse_args()
    folder=ROOT/'testdata/zhuagui'
    proposals_file=ROOT/'.tmp/annotation/zhuagui/proposals.json'
    proposals=json.loads(proposals_file.read_text(encoding='utf-8'))
    index={p['topic']:p for p in proposals}
    if any(name not in index or not index[name]['region'] for name in args.approve):
        parser.error('Every approved topic must have an explicit proposed region')
    document=json.loads((folder/'cases.json').read_text(encoding='utf-8'))
    cases={c['id']:c for c in document['cases']}
    evidence=f'{args.reviewer}: {args.evidence}'
    for name in args.approve:
        proposal=index[name]; case=cases[proposal['case_id']]
        validate(case)
        x1,y1,x2,y2=proposal['region']
        width,height=case['capture']['size']
        if not (0<=x1<x2<=width and 0<=y1<y2<=height): parser.error('Proposed region outside frame')
        objects=case['truth'].setdefault('objects',annotation([],'user_verified',evidence))
        item={'label':name,'region':proposal['region'],'source':evidence}
        if not any(v['label']==name and v['region']==item['region'] for v in objects['value']): objects['value'].append(item)
        if (case['truth'].get('question',{}).get('value') or {}).get('target')==name:
            case['truth']['target_regions']=annotation([proposal['region']],'user_verified',evidence)
            if 'target_regions' not in case['expected']['checks']: case['expected']['checks'].append('target_regions')
        proposal.update(status='user_verified',reviewer=args.reviewer,evidence=args.evidence)
    (folder/'cases.json').write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    proposals_file.write_text(json.dumps(proposals,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__': main()

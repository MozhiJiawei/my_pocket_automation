"""Check image heights; a nonzero exit means insufficient or unreadable input."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.perception.lib import annotation_queue as queue
from scripts.perception.lib import capture_feedback


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=['pending','confirmed'],default='pending')
    parser.add_argument('--id',action='append',help='Only inspect these queue identities')
    parser.add_argument('--record',action='store_true',help='Save feedback alongside original images')
    parser.add_argument('--unrecoverable',action='store_true',help='The original attempt can no longer be recaptured')
    parser.add_argument('--evidence',help='Independent inspection or user feedback')
    args=parser.parse_args();results=[]
    items=queue.items(args.stage)
    if args.id:
        found={item['id']:item for item in items}
        missing=set(args.id)-set(found)
        if missing:parser.error('Unknown queue item: '+', '.join(sorted(missing)))
        items=[found[identity] for identity in args.id]
    for item in items:
        folder=queue.resolve(args.stage,item['id'])
        report=capture_feedback.verify(folder,item['task'],item['kind'])
        if args.evidence:report['evidence']=args.evidence
        if args.unrecoverable:report['recoverable']=False
        if args.record:report=capture_feedback.write(folder,report)
        results.append({'id':item['id'],**report})
    print(json.dumps({'items':results,'passed':all(r['status']=='complete' for r in results)},ensure_ascii=False,indent=2))
    return 0 if all(r['status']=='complete' for r in results) else 1


if __name__=='__main__':sys.exit(main())

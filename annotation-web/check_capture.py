"""Check image heights; a nonzero exit means insufficient or unreadable input."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.perception.lib import annotation_queue as queue
from scripts.perception.lib import capture_height


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=['pending','confirmed'],default='pending')
    parser.add_argument('--id',action='append',help='Only inspect these queue identities')
    args=parser.parse_args();results=[]
    items=queue.items(args.stage)
    if args.id:
        found={item['id']:item for item in items}
        missing=set(args.id)-set(found)
        if missing:parser.error('Unknown queue item: '+', '.join(sorted(missing)))
        items=[found[identity] for identity in args.id]
    for item in items:
        folder=queue.resolve(args.stage,item['id'])
        try:pixel_height=capture_height.height(folder,item['kind'])
        except (ValueError,OSError):pixel_height=0
        results.append({'id':item['id'],'height':pixel_height,'minimum':1600 if item['kind']=='拼图' else 2760,
                        'complete':capture_height.complete(pixel_height,item['kind'])})
    passed=all(item['complete'] for item in results)
    print(json.dumps({'items':results,'passed':passed},ensure_ascii=False,indent=2))
    return 0 if passed else 1


if __name__=='__main__':sys.exit(main())

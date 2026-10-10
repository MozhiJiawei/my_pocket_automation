"""Offline evaluation. Never connects to ADB, APIs or credentials."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.corpus import load_cases
from scripts.perception.lib.evaluation import evaluate_case, write_report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--task',choices=['zhuagui','dungeon'])
    parser.add_argument('--case',help='Exact case id')
    parser.add_argument('--split',choices=['calibration','holdout','regression'])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--baseline',type=Path,help='Previous results.json for regression and annotation-change comparison')
    args=parser.parse_args()
    cases=[c for c in load_cases(args.task) if (not args.case or c['id']==args.case) and (not args.split or c['capture']['split']==args.split)]
    if not cases: parser.error('No cases selected')
    results=[evaluate_case(case) for case in cases]
    output=args.output or ROOT/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'offline-evaluation'
    summary=write_report(cases,results,output.resolve(),args.baseline)
    print(json.dumps({'frames':summary['frames'],'failed_frames':summary['failed_frames'],
                      'checks':summary['checks'],'rounds':summary['rounds'],
                      'report':str(output.resolve()/'README.md')},ensure_ascii=False))
    return 1 if summary['failed_frames'] or summary['rounds']['status']['failed'] else 0

if __name__=='__main__': sys.exit(main())

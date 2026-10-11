"""Import one or more public frames into a named pending case."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.ingest import import_frames


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,nargs='+',required=True)
    parser.add_argument('--case',required=True,help='Readable directory relative to testdata')
    parser.add_argument('--retain',action='append',required=True,help='Public x1,y1,x2,y2 rectangle')
    parser.add_argument('--split',choices=['calibration','holdout'],default='holdout')
    args=parser.parse_args()
    folder=import_frames(args.source,args.case,[list(map(int,v.split(','))) for v in args.retain],args.split)
    print(f'Imported pending evidence: {folder}')

if __name__=='__main__':main()

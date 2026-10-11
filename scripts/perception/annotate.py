"""Apply a explicitly approved proposal expressed in original image coordinates."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.ingest import approve


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',required=True)
    parser.add_argument('--proposal',type=Path,required=True)
    parser.add_argument('--reviewer',required=True)
    parser.add_argument('--evidence',required=True)
    args=parser.parse_args()
    approve(args.case,json.loads(args.proposal.read_text(encoding='utf-8')),args.reviewer,args.evidence)

if __name__=='__main__':main()

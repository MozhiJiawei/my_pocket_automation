"""Apply a human's explicit approval of the current review, never algorithm outputs."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.perception.lib.round_truth import approve_rounds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reviewer', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    folder = ROOT/'testdata/zhuagui'
    review_folder = ROOT/'.tmp/annotation/zhuagui/tasks'
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    document, rounds = approve_rounds(read(folder/'cases.json'), read(review_folder/'rounds.json'),
                                     read(folder/'annotation-history/gold_review.json')['rejected_annotations'],
                                     args.reviewer, args.evidence)
    for path, value in [(folder/'cases.json', document), (folder/'rounds.json', rounds)]:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'rounds':len(rounds['rounds']),
                      'answers':sum(len(r['answer_set']['item_ids']) for r in rounds['rounds'])}))


if __name__ == '__main__':
    main()

"""Run reviewed semantic expectations, not feature names or fake click success."""
import unittest
import json
from pathlib import Path
from datetime import datetime
from scripts.perception.lib.corpus import load_cases, validate
from scripts.perception.lib.evaluation import evaluate_case, write_report


class CorpusTest(unittest.TestCase):
    def test_annotations_and_evidence_are_consistent(self):
        cases=load_cases()
        self.assertEqual(len({c['id'] for c in cases}),len(cases))
        for case in cases:
            with self.subTest(case=case['id']): validate(case)

    def test_reviewed_recognition_and_planned_coordinates(self):
        cases=load_cases()
        baseline=json.loads((Path(__file__).resolve().parents[2]/'testdata/regression_baseline.json').read_text(encoding='utf-8'))
        successful={r['id']:r['checks'] for r in baseline['results']}
        results=[]
        for case in cases:
            with self.subTest(case=case['id']):
                result=evaluate_case(case)
                results.append(result)
                # Existing successful checks remain regressions. Newly reviewed
                # answers are capability evaluations and may expose unsupported solvers.
                regression=successful.get(case['id'],{})
                for field, expected in regression.items():
                    self.assertEqual(case['truth'][field]['value'],expected, 'Baseline truth changed; review it explicitly')
                failures=[c for c in result['checks'] if c['status']!='passed' and c['field'] in regression
                          and case['truth'][c['field']]['status'] in {'reviewed','user_verified','device_verified'}]
                self.assertFalse(failures,failures)
        output=Path(__file__).resolve().parents[2]/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'offline-evaluation'
        write_report(cases,results,output)

    def test_required_topics_are_not_filled_with_unreviewed_objects(self):
        coverage=json.loads((Path(__file__).resolve().parents[2]/'testdata/zhuagui/coverage.json').read_text(encoding='utf-8'))
        present={c['truth']['question']['value']['target'] for c in load_cases('zhuagui')
                 if c['truth'].get('question',{}).get('status') in {'reviewed','user_verified','device_verified'}}
        self.assertEqual(coverage['missing_topics'],[t for t in coverage['required_topics'] if t not in present])

if __name__=='__main__': unittest.main()

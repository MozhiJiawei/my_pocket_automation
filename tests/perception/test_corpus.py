"""Run reviewed semantic expectations, not feature names or fake click success."""
import unittest
import json
from pathlib import Path
from datetime import datetime
from scripts.perception.lib.corpus import load_cases, validate_truth
from scripts.perception.lib.evaluation import evaluate_inputs, write_report


class CorpusTest(unittest.TestCase):
    def test_annotations_and_evidence_are_consistent(self):
        seen=set()
        for case in load_cases():
            self.assertNotIn(case['id'],seen)
            seen.add(case['id'])
            with self.subTest(case=case['id']): validate_truth(case,*case['capture']['size'])

    def test_reviewed_recognition_and_planned_coordinates(self):
        cases,results=evaluate_inputs(load_cases())
        for family in {c['truth']['puzzle_family']['value'] for c in cases if 'puzzle_family' in c['truth']}:
            self.assertEqual(sum(c['truth'].get('puzzle_family',{}).get('value')==family for c in cases),24,family)
        seen=set()
        for result in results:
            with self.subTest(case=result['id']):
                self.assertNotIn(result['id'],seen)
                seen.add(result['id'])
                failures=[c for c in result['checks'] if c['status']=='failed']
                self.assertFalse(failures,failures)
        output=Path(__file__).resolve().parents[2]/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'offline-evaluation'
        write_report(cases,results,output)

    def test_required_topics_are_not_filled_with_unreviewed_objects(self):
        required={'梅花酒','虎骨酒','蛇胆酒','珍露酒','黄金','黄纸','书籍','书画','香','蜡烛','野鬼','牛头','马面','僵尸'}
        present={c['truth']['question']['value']['target'] for c in load_cases('zhuagui')
                 if c['truth'].get('question',{}).get('status') in {'reviewed','user_verified','device_verified'}}
        self.assertFalse(required-present, required-present)

if __name__=='__main__': unittest.main()

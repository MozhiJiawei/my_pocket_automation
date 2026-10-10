"""Unknown labels and diagnostic failures must remain visible to algorithm authors."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from scripts.perception.lib.corpus import load_cases, validate
from scripts.perception.lib.evaluation import evaluate_case, write_report
from tests.support.lua_runtime import semantic_target


class TruthContractTest(unittest.TestCase):
    def setUp(self):
        self.case=deepcopy(next(c for c in load_cases('zhuagui') if c['truth'].get('target_regions',{}).get('source','').startswith('20261010_093606:')))

    def test_proposed_position_cannot_count_as_a_pass(self):
        self.case['truth']['target_regions']['status']='proposed'
        self.case['expected']['checks']=['target_regions']
        result=evaluate_case(self.case)
        self.assertEqual(result['status'],'unscored')
        self.assertEqual(result['actions'],[])

    def test_changed_evidence_is_rejected(self):
        self.case['sha256']='0'*64
        with self.assertRaises(ValueError): validate(self.case)

    def test_wrong_coordinate_produces_failure_overlay_and_trace(self):
        self.case['truth']['target_regions']['value']=[[10,10,20,20]]
        self.case['expected']['checks']=['target_regions']
        result=evaluate_case(self.case)
        self.assertEqual(result['status'],'failed')
        self.assertTrue(result['matches'])
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)
            summary=write_report([self.case],[result],output)
            self.assertEqual(summary['checks']['failed'],1)
            self.assertTrue((output/f"{self.case['id']}.png").exists())
            self.assertFalse(summary['backend']['device_equivalent'])
            self.assertEqual(len(summary['harness_sha256']),64)
            self.assertTrue(json.loads((output/'results.json').read_text(encoding='utf-8'))['results'][0]['actions'])

    def test_no_capture_group_leaks_between_splits(self):
        groups={}
        for case in load_cases():
            group=(case['task'],case['capture']['group'])
            groups.setdefault(group,set()).add(case['capture']['split'])
        self.assertTrue(all(len(splits)==1 for splits in groups.values()))

    def test_strategy_names_do_not_become_game_truth(self):
        self.assertEqual(semantic_target('legacy','香炉'),'香')
        self.assertEqual(semantic_target('legacy','书籍'),'书籍')
        self.assertEqual(semantic_target('snake_wine','酒'),'蛇胆酒')

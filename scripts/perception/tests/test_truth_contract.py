"""Unknown answers, bounds and failure evidence retain their meaning."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from scripts.perception.lib.corpus import load_cases,validate
from scripts.perception.lib.evaluation import evaluate_case,write_report
from tests.support.lua_runtime import semantic_target


class TruthContractTest(unittest.TestCase):
    def setUp(self):
        self.case=deepcopy(next(c for c in load_cases('zhuagui') if '/蛇胆酒/' in c['id'] and c['truth'].get('target_regions',{}).get('value')))

    def test_proposed_position_cannot_count_as_pass(self):
        self.case['truth']['target_regions']['status']='proposed'
        self.case['expected']['checks']=['target_regions']
        result=evaluate_case(self.case)
        self.assertEqual(result['status'],'unscored');self.assertEqual(result['actions'],[])

    def test_region_outside_image_is_rejected(self):
        self.case['truth']['target_regions']['value']=[[-1,10,20,20]]
        with self.assertRaises(ValueError):validate(self.case)

    def test_wrong_coordinate_produces_failure_overlay(self):
        self.case['truth']['target_regions']['value']=[[10,10,20,20]]
        self.case['truth']['target_regions_complete']={'value':True,'status':'reviewed','source':'independent test mutation'}
        self.case['expected']['checks']=['target_regions']
        result=evaluate_case(self.case);self.assertEqual(result['status'],'failed')
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder);summary=write_report([self.case],[result],output)
            self.assertEqual(summary['checks']['failed'],1)
            self.assertTrue((output/'failures'/self.case['id']).exists())
            self.assertFalse(summary['backend']['device_equivalent'])

    def test_strategy_names_do_not_become_game_truth(self):
        self.assertEqual(semantic_target('legacy','香炉'),'香')
        self.assertEqual(semantic_target('snake_wine','酒'),'蛇胆酒')

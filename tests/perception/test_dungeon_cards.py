"""Locate independently reviewed unselected cards using production features."""
import unittest
from scripts.perception.lib.corpus import load_cases, validate
from tests.support.lua_runtime import Runtime
from tests.support.touchsprite_adapter import Screen


class DungeonCardsTest(unittest.TestCase):
    def test_unselected_wuji_card(self):
        self.check_unselected_card('wuji')

    def test_unselected_chechi_card(self):
        self.check_unselected_card('chechi')

    def check_unselected_card(self, dungeon):
        field=dungeon+'_card'
        case=next(c for c in load_cases('dungeon') if field in c['truth'])
        self.assertEqual(case['truth'][field]['status'], 'reviewed')
        runtime=Runtime(Screen.read(validate(case)))
        feature=runtime.require('tasks.dungeon.'+dungeon+'.assets.card')
        feature.region=runtime.lua.table_from([15,1140,870,1260])
        found=runtime.require('common.detector').find(feature)
        self.assertIsNotNone(found)
        x1,y1,x2,y2=case['truth'][field]['value']
        offset=found['tap_offset'] or feature['tap_offset']
        self.assertTrue(x1<=found['x']+offset[1]<=x2 and y1<=found['y']+offset[2]<=y2)

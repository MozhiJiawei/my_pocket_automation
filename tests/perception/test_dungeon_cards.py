"""Locate independently reviewed unselected cards using production features."""
import unittest
from scripts.perception.lib.corpus import load_cases, validate
from tests.support.lua_runtime import Runtime
from tests.support.touchsprite_adapter import Screen


class DungeonCardsTest(unittest.TestCase):
    def test_list_marks_verify_both_claimed_dungeons_from_the_same_frame(self):
        case=next(c for c in load_cases('dungeon') if '/葫芦已领取/' in c['id'])
        runtime=Runtime(Screen.read(validate(case)))
        pages=runtime.require('tasks.dungeon.pages')
        self.assertEqual(pages.state(),'list_wuji')
        self.assertTrue(pages.reward_claimed('wuji'))
        self.assertTrue(pages.reward_claimed('chechi'))
        runtime.close()

    def test_unclaimed_and_ready_pages_cannot_match_claimed_list_marks(self):
        for case in load_cases('dungeon'):
            if not any('/'+name+'/' in case['id'] for name in ('副本列表','准备开始','葫芦未领取')):continue
            with self.subTest(case=case['id']):
                runtime=Runtime(Screen.read(validate(case)))
                pages=runtime.require('tasks.dungeon.pages')
                self.assertFalse(pages.reward_claimed('wuji'))
                self.assertFalse(pages.reward_claimed('chechi'))
                runtime.close()

    def test_receipt_close_targets_blank_area_below_both_entry_buttons(self):
        case=next(c for c in load_cases('dungeon') if c['truth'].get('page',{}).get('value')=='wuji_claim_receipt')
        runtime=Runtime(Screen.read(validate(case)))
        feature=runtime.require('tasks.dungeon.assets.claim_receipt_close')
        found=runtime.require('common.detector').find(feature)
        self.assertIsNotNone(found)
        offset=found['tap_offset'] or feature['tap_offset']
        x,y=found['x']+offset[1],found['y']+offset[2]
        self.assertTrue(300<=x<=600 and 1460<=y<=1540)
        self.assertGreater(y,1448)
        runtime.close()
    def test_unselected_wuji_card(self):
        self.check_unselected_card('wuji')

    def test_unselected_chechi_card(self):
        self.check_unselected_card('chechi')

    def check_unselected_card(self, dungeon):
        field=dungeon+'_card'
        cases=[c for c in load_cases('dungeon') if field in c['truth']]
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case=case['id']):
                self.assertEqual(case['truth'][field]['status'], 'reviewed')
                runtime=Runtime(Screen.read(validate(case)))
                try:
                    feature=runtime.require('tasks.dungeon.'+dungeon+'.assets.card')
                    feature.region=runtime.lua.table_from([15,1140,870,1260])
                    found=runtime.require('common.detector').find(feature)
                    self.assertIsNotNone(found)
                    x1,y1,x2,y2=case['truth'][field]['value']
                    offset=found['tap_offset'] or feature['tap_offset']
                    self.assertTrue(x1<=found['x']+offset[1]<=x2 and y1<=found['y']+offset[2]<=y2)
                finally:runtime.close()

"""Locate independently reviewed unselected cards using production features."""
import unittest
from scripts.perception.lib.corpus import DUNGEON_IDS, load_cases, validate
from tests.support.lua_runtime import Runtime
from tests.support.touchsprite_adapter import Screen


class DungeonCardsTest(unittest.TestCase):
    def test_list_marks_verify_both_claimed_dungeons_from_the_same_frame(self):
        case=next(c for c in load_cases('dungeon') if c['id']=='副本/乌鸡国/葫芦已领取/场景01/画面.png')
        runtime=Runtime(Screen.read(validate(case)))
        pages=runtime.require('tasks.dungeon.pages')
        self.assertEqual(pages.state(),'list_wuji')
        self.assertTrue(pages.reward_claimed('wuji'))
        self.assertTrue(pages.reward_claimed('chechi'))
        runtime.close()

    def test_ended_marker_credits_only_the_dungeon_named_in_the_current_list(self):
        for name in ('车迟国', '黑风山', '水陆大会', '平顶山'):
            target=DUNGEON_IDS[name]
            case=next(c for c in load_cases('dungeon') if c['id'].startswith(f'副本/{name}/葫芦已领取/场景01/'))
            with self.subTest(case=case['id']):
                runtime=Runtime(Screen.read(validate(case)))
                try:
                    pages=runtime.require('tasks.dungeon.pages')
                    self.assertEqual(pages.state(), 'list_' + target)
                    if target=='chechi':
                        detector=runtime.require('common.detector')
                        self.assertFalse(detector.present(pages.definitions.chechi.claimed_card))
                    for dungeon in DUNGEON_IDS.values():
                        self.assertEqual(pages.reward_claimed(dungeon), dungeon==target, dungeon)
                finally:
                    runtime.close()

    def test_current_chechi_green_marker_works_with_wuji_selected(self):
        case=next(c for c in load_cases('dungeon') if c['id']=='副本/车迟国/葫芦已领取/场景02/画面.png')
        runtime=Runtime(Screen.read(validate(case)))
        self.addCleanup(runtime.close)
        pages=runtime.require('tasks.dungeon.pages')
        self.assertEqual(pages.state(), 'list_wuji')
        self.assertTrue(pages.reward_claimed('chechi'))
        self.assertFalse(pages.reward_claimed('heifeng'))

    def test_current_chechi_receipt_requires_list_confirmation(self):
        case=next(c for c in load_cases('dungeon') if c['id']=='副本/车迟国/领取成功/场景02/画面.png')
        runtime=Runtime(Screen.read(validate(case)))
        self.addCleanup(runtime.close)
        pages=runtime.require('tasks.dungeon.pages')
        self.assertEqual(pages.state(), 'chechi_claim_receipt')
        self.assertFalse(pages.reward_claimed('chechi'))

    def test_relocated_claimed_cards_bind_the_green_mark_to_each_card_name(self):
        cases={c['id']:c for c in load_cases('dungeon')}
        for scene, visible in [('场景02', {'heifeng'}), ('场景03', {'heifeng', 'shuilu', 'pingding'})]:
            case=cases[f'副本/平顶山/葫芦已领取/{scene}/画面.png']
            with self.subTest(case=case['id']):
                runtime=Runtime(Screen.read(validate(case)))
                try:
                    pages=runtime.require('tasks.dungeon.pages')
                    detector=runtime.require('common.detector')
                    for dungeon in ('heifeng', 'shuilu', 'pingding'):
                        self.assertEqual(detector.present(pages.definitions[dungeon].claimed_card), dungeon in visible, dungeon)
                finally:
                    runtime.close()

    def test_unclaimed_and_ready_pages_cannot_match_claimed_list_marks(self):
        for case in load_cases('dungeon'):
            if not any('/'+name+'/' in case['id'] for name in ('副本列表','准备开始','葫芦未领取')):continue
            with self.subTest(case=case['id']):
                runtime=Runtime(Screen.read(validate(case)))
                try:
                    pages=runtime.require('tasks.dungeon.pages')
                    for dungeon in DUNGEON_IDS.values():
                        self.assertFalse(pages.reward_claimed(dungeon), dungeon)
                finally:
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

    def test_switch_dialog_has_independent_confirm_and_cancel_targets(self):
        for case in load_cases('dungeon'):
            if '/副本切换/' not in case['id']:continue
            with self.subTest(case=case['id']):
                runtime=Runtime(Screen.read(validate(case)))
                try:
                    pages=runtime.require('tasks.dungeon.pages')
                    state=pages.state()
                    self.assertEqual(state, case['truth']['page']['value'])
                    detector=runtime.require('common.detector')
                    for feature, bounds in ((pages.switch_feature(state), (471, 816)),
                                            (pages.features.switch_cancel, (82, 428))):
                        found=detector.find(feature)
                        self.assertIsNotNone(found)
                        offset=found['tap_offset'] or feature['tap_offset']
                        self.assertTrue(bounds[0]<found['x']+offset[1]<bounds[1])
                        self.assertTrue(1128<found['y']+offset[2]<1210)
                finally:
                    runtime.close()

    def test_unselected_wuji_card(self):
        self.check_unselected_card('wuji')

    def test_unselected_chechi_card(self):
        self.check_unselected_card('chechi')

    def test_unselected_cards_for_the_three_additional_dungeons(self):
        for dungeon in ('heifeng', 'shuilu', 'pingding'):
            with self.subTest(dungeon=dungeon):
                self.check_unselected_card(dungeon)

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
                    self.assertTrue(x1<=found['x']+offset[1]<x2 and y1<=found['y']+offset[2]<y2)
                finally:runtime.close()

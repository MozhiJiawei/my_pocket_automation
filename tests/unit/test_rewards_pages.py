"""Frozen reward screens exercise production flow-page recognition."""
import json
import struct
from pathlib import Path
import unittest

from tests.support.lua_runtime import Runtime
from tests.support.touchsprite_adapter import Screen


ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / 'testdata' / '收尾' / '葫芦'


def load_case(name):
    directory = CASES / name
    expected = json.loads((directory / '预期.json').read_text(encoding='utf-8'))
    return directory, expected


class RewardsPagesTest(unittest.TestCase):
    def runtime(self, name):
        directory, case = load_case(name)
        runtime = Runtime(Screen.read(directory / '画面.png'))
        self.addCleanup(runtime.close)
        return runtime, case['expected']

    def test_frozen_cases_contain_only_business_expectations(self):
        cases = sorted(CASES.glob('*/预期.json'))
        self.assertEqual(len(cases), 17)
        for path in cases:
            with self.subTest(case=path.parent.name):
                case = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(set(case), {'expected'})
                self.assertTrue(case['expected'])
                original = path.parent / '画面.png'
                with original.open('rb') as stream:
                    header = stream.read(24)
                self.assertEqual(header[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II', header[16:24]), (900, 1600))

    def test_reviewed_pages_categories_and_bounded_cards(self):
        for path in sorted(CASES.glob('*/预期.json')):
            with self.subTest(case=path.parent.name):
                runtime, expected = self.runtime(path.parent.name)
                pages = runtime.require('tasks.rewards.pages')
                detector = runtime.require('common.detector')
                self.assertEqual(runtime.screen.frame.shape[:2], (1600, 900))
                self.assertEqual(pages.state(), expected['state'])
                self.assertEqual(pages.empty_category(), expected['empty_category'])
                if expected['state'] == 'detail':
                    self.assertIsNotNone(detector.find(pages.features.detail_title))
                if expected.get('detail_title_variant') == 'long':
                    self.assertIsNotNone(detector.find(
                        runtime.require('tasks.rewards.assets.detail_title_long')))
                cards = pages.cards()
                if expected['card_icon_regions'] is None:
                    self.assertIsNone(cards)
                else:
                    self.assertEqual(len(cards), len(expected['card_icon_regions']))
                    self.assertIsNone(detector.find(pages.features.detail_title))
                    for category in ('task', 'dungeon', 'special'):
                        self.assertEqual(
                            detector.present(pages.features[category + '_tab_selected']),
                            category == expected['selected_category'],
                        )
                    for index, region in enumerate(expected['card_icon_regions'], 1):
                        found = detector.find(cards[index])
                        self.assertIsNotNone(found)
                        offset = found['tap_offset'] or cards[index]['tap_offset']
                        x, y = found['x'] + offset[1], found['y'] + offset[2]
                        self.assertTrue(region[0] <= x <= region[2] and
                                        region[1] <= y <= region[3], (index, x, y, region))

    def test_bonus_receipt_returns_with_left_button_and_verifies_destination(self):
        for closes in (True, False):
            with self.subTest(closes=closes):
                runtime, _ = self.runtime('额外奖励收据')
                def tap(x, y, options=None):
                    runtime.actions.append((x, y))
                    if closes:
                        runtime.screen = Screen.read(CASES / '副本空库存' / '画面.png')
                runtime.lua.globals().tap = tap
                pages = runtime.require('tasks.rewards.pages')
                self.assertEqual(pages.close_receipt(runtime.lua.table()), closes)
                self.assertEqual(len(runtime.actions), 1)
                x, y = runtime.actions[0]
                self.assertTrue(34 <= x <= 420 and 1334 <= y <= 1433, (x, y))
                self.assertEqual(pages.state(), 'inventory' if closes else 'bonus_receipt')

    def test_receipt_close_does_not_tap_normal_inventory(self):
        runtime, _ = self.runtime('副本空库存')
        self.assertTrue(runtime.require('tasks.rewards.pages').close_receipt(runtime.lua.table()))
        self.assertEqual(runtime.actions, [])

    def test_fragment_notice_closes_with_acknowledge_without_navigation_or_preferences(self):
        runtime, _ = self.runtime('树苗碎片提示')
        pages = runtime.require('tasks.rewards.pages')
        self.assertEqual(pages.state(), 'bonus_receipt')
        def tap(x, y, options=None):
            runtime.actions.append((x, y))
            runtime.screen = Screen.read(CASES / '副本空库存' / '画面.png')
        runtime.lua.globals().tap = tap
        self.assertTrue(pages.close_receipt(runtime.lua.table()))
        self.assertEqual(len(runtime.actions), 1)
        x, y = runtime.actions[0]
        self.assertTrue(27 <= x <= 281 and 1325 <= y <= 1425, (x, y))
        self.assertEqual(pages.state(), 'inventory')

    def test_detail_title_geometry_allows_two_pixels_of_match_tolerance(self):
        title_y = []
        for count in (6, 5, 4, 3, 2):
            runtime, _ = self.runtime(f'抓鬼详情{count}')
            pages = runtime.require('tasks.rewards.pages')
            found = runtime.require('common.detector').find(pages.features.detail_title)
            self.assertIsNotNone(found)
            title_y.append(found['y'])
        for found_y in title_y:
            self.assertLessEqual(abs(found_y - title_y[0]), 2)
        runtime, expected = self.runtime('烟花详情2')
        pages = runtime.require('tasks.rewards.pages')
        found = runtime.require('common.detector').find(pages.features.detail_title)
        self.assertIsNotNone(found)
        self.assertLessEqual(abs(found['y'] - title_y[0] - expected['detail_title_shift_y']), 2)

    def test_ghost_gourd_count_accepts_only_supported_ghost_details(self):
        cases = ('抓鬼详情2', '抓鬼详情3', '抓鬼详情4', '抓鬼详情5', '抓鬼详情6', '烟花详情2')
        for name in cases:
            with self.subTest(case=name):
                runtime, expected = self.runtime(name)
                count = expected['ghost_gourd_count']
                actual = runtime.require('tasks.rewards.pages').ghost_gourd_count()
                self.assertEqual(actual, None if count is False else count)
                self.assertEqual(runtime.actions, [])

    def test_ghost_gourd_count_requires_detail_page(self):
        runtime, _ = self.runtime('任务空库存')
        self.assertIsNone(runtime.require('tasks.rewards.pages').ghost_gourd_count())
        self.assertEqual(runtime.actions, [])

    def test_ghost_gourd_inventory_checks_role_and_business_date_before_input(self):
        runtime, _ = self.runtime('任务空库存')
        runtime.lua.execute('''
            package.loaded['common.navigation']={home_identity_matches=function() return false end}
            ctx={identity_verified=true,config={business_date='20000101'}}
        ''')
        ctx = runtime.lua.globals().ctx
        count = runtime.require('tasks.rewards.inventory').ghost_count
        self.assertEqual(count(ctx), (None, 'ghost_gourd_business_date_not_verified'))
        ctx.config.business_date = runtime.lua.eval("os.date('%Y%m%d')")
        self.assertEqual(count(ctx), (None, 'ghost_gourd_identity_not_verified'))
        self.assertEqual(runtime.actions, [])

    def test_ghost_gourd_inventory_stops_on_empty_task_tab(self):
        runtime, _ = self.runtime('任务空库存')
        runtime.lua.execute('''
            package.loaded['common.navigation']={home_identity_matches=function() return true end}
            require('tasks.rewards.pages').open_treasury=function() return true end
            ctx={identity_verified=true,config={business_date=os.date('%Y%m%d')}}
        ''')
        outcome = runtime.require('tasks.rewards.inventory').ghost_count(runtime.lua.globals().ctx)
        self.assertEqual(outcome, (None, 'ghost_gourd_missing'))
        self.assertEqual(len(runtime.actions), 1)
        x, y = runtime.actions[0]['point']
        self.assertTrue(160 <= x <= 320 and 1315 <= y <= 1415, (x, y))

    def test_discard_confirmation_variants_target_the_reviewed_buttons(self):
        for name in ('丢弃三按钮确认', '佳节祝福单个丢弃确认', '良辰佳期单个丢弃确认'):
            with self.subTest(case=name):
                runtime, expected = self.runtime(name)
                detector = runtime.require('common.detector')
                self.assertEqual(runtime.require('tasks.rewards.pages').state(), 'discard_confirm')
                points = {}
                for button, target in expected['button_targets'].items():
                    feature = runtime.require('tasks.rewards.assets.' + button)
                    found = detector.find(feature)
                    self.assertIsNotNone(found, button)
                    # Variants have different button locations and must supply their own offset.
                    offset = found['tap_offset'] or feature['tap_offset']
                    x, y = found['x'] + offset[1], found['y'] + offset[2]
                    points[button] = (x, y)
                    region = target['region']
                    self.assertTrue(region[0] - 2 <= x <= region[2] + 2 and
                                    region[1] - 2 <= y <= region[3] + 2, (button, x, y))
                    self.assertLessEqual(abs(x - target['point'][0]), 2, button)
                    self.assertLessEqual(abs(y - target['point'][1]), 2, button)
                x, y = points['discard_cancel']
                for region in expected['cancel_forbidden_regions']:
                    self.assertFalse(region[0] <= x <= region[2] and
                                     region[1] <= y <= region[3], (x, y, region))


if __name__ == '__main__':
    unittest.main()

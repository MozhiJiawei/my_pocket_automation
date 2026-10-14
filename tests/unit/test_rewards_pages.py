"""Frozen reward screens exercise production flow-page recognition."""
import hashlib
import json
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

    def test_frozen_originals_retain_independent_review_evidence(self):
        cases = sorted(CASES.glob('*/预期.json'))
        self.assertEqual(len(cases), 14)
        for path in cases:
            with self.subTest(case=path.parent.name):
                case = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(case['review']['status'], 'reviewed')
                self.assertEqual(case['review']['kind'], 'flow_controls')
                original = path.parent / '画面.png'
                self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),
                                 case['source_sha256'])
                audit = (path.parent / '审核.md').read_text(encoding='utf-8')
                self.assertIn(case['source'], audit)
                self.assertIn(case['source_sha256'], audit)
                self.assertIn('主 Agent 独立目视核验', audit)

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

    def test_discard_confirmation_variants_target_the_reviewed_buttons(self):
        for name in ('丢弃三按钮确认', '佳节祝福单个丢弃确认'):
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

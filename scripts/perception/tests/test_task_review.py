import unittest
import json
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.perception.lib.task_review import rounds, scroll_offset
from scripts.perception.lib.corpus import load_cases
from scripts.perception.render_task_review import compose


class TaskReviewTest(unittest.TestCase):
    def test_scroll_registration_recovers_shared_content(self):
        scene = np.random.default_rng(7).integers(0, 256, (1400, 250, 3), dtype=np.uint8)
        result = scroll_offset(Image.fromarray(scene[:875]), Image.fromarray(scene[450:1325]))
        self.assertTrue(result['accepted'])
        self.assertEqual(result['offset'], 450)

    def test_bottom_jitter_does_not_look_like_another_page(self):
        scene = np.random.default_rng(8).integers(0, 256, (900, 250, 3), dtype=np.uint8)
        result = scroll_offset(Image.fromarray(scene[:875]), Image.fromarray(scene[7:882]))
        self.assertTrue(result['accepted'])
        self.assertEqual(result['offset'], 7)

    def test_unrelated_layout_is_not_stitched_as_overlap(self):
        scene = np.random.default_rng(9).integers(0, 256, (1750, 250, 3), dtype=np.uint8)
        result = scroll_offset(Image.fromarray(scene[:875]), Image.fromarray(scene[875:]))
        self.assertFalse(result['accepted'])

    def test_bottom_rebound_is_registered_without_duplicate_tail(self):
        scene = np.random.default_rng(10).integers(0, 256, (1000, 250, 3), dtype=np.uint8)
        result = scroll_offset(Image.fromarray(scene[85:960]), Image.fromarray(scene[:875]))
        self.assertTrue(result['accepted'])
        self.assertEqual(result['offset'], -85)

    def test_existing_weapon_rounds_preserved_and_bottom_deduplicated(self):
        groups = rounds(load_cases('zhuagui'))
        weapons = [pages for pages in groups.values() if any(
            (case['truth'].get('question', {}).get('value') or {}).get('target') == '兵器'
            for case in pages.values())]
        self.assertEqual(len(weapons), 15)
        strip, captures, _ = compose(groups[('20261010_105320', 1)])
        self.assertEqual(len(captures), 7)
        self.assertEqual(sum(c['redundant_capture'] for c in captures), 2)
        self.assertLess(strip.height, 4 * 875)
        self.assertTrue(all(c['alignment'] is None or c['alignment']['accepted'] for c in captures))

    def test_answer_proposals_are_sets_with_original_frame_coordinates(self):
        path = Path(__file__).resolve().parents[3]/'testdata/zhuagui/rounds.json'
        categories = {}
        for entry in json.loads(path.read_text(encoding='utf-8'))['rounds']:
            categories.setdefault(entry['topic'],[]).append(entry)
        weapon_rounds = categories['兵器']
        all_rounds = [r for entries in categories.values() for r in entries]
        self.assertEqual(len({r['id'] for r in all_rounds}),len(all_rounds))
        cases = {case['id']:case for case in load_cases('zhuagui')}
        self.assertTrue(any(len(r['answer_set']['item_ids']) > 1 for r in weapon_rounds))
        self.assertTrue(any(not r['answer_set']['item_ids'] for r in weapon_rounds))
        for round_case in all_rounds:
            self.assertEqual(round_case['visual_review'], 'ai_reviewed')
            self.assertFalse(round_case['answer_set']['exhaustive'])
            items = {c['id']:c for c in round_case['candidate_annotations']}
            self.assertEqual(set(round_case['answer_set']['item_ids']),
                             {c['id'] for c in items.values() if c['status'] != 'uncertain'})
            self.assertEqual(len(items), len(round_case['candidate_annotations']))
            for candidate in items.values():
                case = cases[candidate['case_id']]
                x1,y1,x2,y2 = candidate['region']
                self.assertTrue(0 <= x1 < x2 <= case['capture']['size'][0])
                self.assertTrue(535 <= y1 < y2 <= 1410)
                capture = next(c for c in round_case['captures'] if c['page']==candidate['source_page'])
                self.assertEqual(candidate['stitched_region'],
                    [x1-63,y1-535+capture['list_origin_y'],x2-63,y2-535+capture['list_origin_y']])


if __name__ == '__main__':
    unittest.main()

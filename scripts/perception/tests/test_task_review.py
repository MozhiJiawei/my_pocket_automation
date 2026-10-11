"""Review strips remove redundant scrolling without replacing original truth."""
import importlib.util
from pathlib import Path
import unittest
from scripts.perception.lib.corpus import load_cases
from scripts.perception.lib.task_review import rounds

spec=importlib.util.spec_from_file_location('review',Path(__file__).parents[1]/'render_task_review.py')
review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)


class TaskReviewTest(unittest.TestCase):
    def test_repeated_bottom_pages_do_not_repeat_in_long_strip(self):
        pages=rounds(load_cases('zhuagui'))['抓鬼/寻物/上好的兵器/第02轮']
        strip,records,_=review.compose(pages)
        self.assertGreater(len(records),1)
        self.assertTrue(any(r['redundant_capture'] for r in records))
        self.assertLess(strip.height,len(records)*875)
        self.assertTrue(all(r['alignment'] is None or r['alignment']['accepted'] for r in records))

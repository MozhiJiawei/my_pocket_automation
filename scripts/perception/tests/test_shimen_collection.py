"""First collection pass counts new question categories, not item variants."""
import unittest
import numpy as np
from scripts.perception.lib.shimen_collection import Novelty,question,saturated

class ShimenCollectionTest(unittest.TestCase):
    def test_only_new_question_categories_count(self):
        novelty=Novelty()
        self.assertEqual(novelty.items('酒'),1)
        for _ in range(10):self.assertEqual(novelty.items('酒'),0)
        self.assertEqual(novelty.items('乐器'),1)
        self.assertEqual(novelty.questions,{'酒','乐器'})
    def test_puzzle_rearrangement_is_not_a_new_category(self):
        parts=[np.full((40,30,3),color,np.uint8) for color in (0,50,150,250)]
        novelty=Novelty();self.assertEqual(novelty.puzzle(parts),1)
        self.assertEqual(novelty.puzzle(parts[::-1]),0)
        self.assertEqual(novelty.puzzle([np.zeros((40,30,3),np.uint8) for _ in range(4)]),1)
    def test_question_keeps_required_count(self):
        self.assertEqual(question([{'text':'请找到精魄灵石X2'}]),('精魄灵石',2))
        self.assertIsNone(question([{'text':'未识别的页面'}]))
    def test_only_a_complete_quiet_batch_is_saturated(self):
        self.assertTrue(saturated(10,0));self.assertFalse(saturated(10,1))
        with self.assertRaises(ValueError):saturated(9,0)

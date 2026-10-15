"""A round may accept several answers, while unlabelled objects remain unknown."""
import unittest
from scripts.perception.lib.corpus import load_rounds,read_answers,ROOT
from scripts.perception.lib.round_truth import evaluate_rounds


class RoundTruthTest(unittest.TestCase):
    def setUp(self):
        self.round={'id':'兵器/第01轮','topic':'兵器','frames':['第01页.png'],
                    'answers':{'长剑':{'第01页.png':[10,10,30,30]},'短剑':{'第01页.png':[50,10,70,30]}}}

    def score(self,point=None,negative=None):
        return evaluate_rounds([self.round],[{'id':'第01页.png','actions':[] if point is None else [{'kind':'tap','point':point}],
            'known_negative_regions':negative or []}])[0]

    def test_any_approved_answer_can_be_selected(self):
        for point in ([20,20],[60,20]):
            result=self.score(point);self.assertEqual(result['status'],'passed')
            self.assertEqual(len(result['unselected_answers']),1)

    def test_two_historical_boundaries_remain_one_answer(self):
        self.round['answers']['长剑']['第01页.png']=[[10,10,30,30],[10,8,29,30]]
        result=self.score([20,9])
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['selected_answers'],['长剑'])
        self.assertEqual(len(result['expected_answers']),2)

    def test_partial_truth_does_not_make_unknown_object_negative(self):
        self.assertEqual(self.score([100,100])['status'],'unscored')

    def test_explicit_negative_click_fails_even_with_other_answers(self):
        self.assertEqual(self.score([100,100],[[90,90,110,110]])['status'],'failed')

    def test_abstention_with_visible_answers_fails(self):
        self.assertEqual(self.score()['status'],'failed')

    def test_empty_answer_set_is_unscored(self):
        self.round['answers']={};self.assertEqual(self.score()['status'],'unscored')

    def test_empty_positive_group_is_unknown_and_explicit_negative_still_fails(self):
        self.round['answers']={'长剑':{}}
        result=self.score()
        self.assertEqual(result['expected_answers'],[])
        self.assertEqual(result['status'],'unscored')
        self.assertEqual(self.score([100,100],[[90,90,110,110]])['status'],'failed')

    def test_all_existing_rounds_keep_multi_answer_truth(self):
        rounds=load_rounds();self.assertEqual(len(rounds),97)
        for item in rounds:
            document=read_answers(ROOT/item['id'])
            self.assertTrue(any(locations for section in ('正确','反例') for locations in document.get(section,{}).values()),
                '没有批准正反例的采集轮次不能留在正式测试集：'+item['id'])
        self.assertTrue(any(len(r['answers'])>1 for r in rounds))

    def test_shimen_requires_every_positive_and_keeps_negative_failures(self):
        self.round['id']='师门/寻物/酒/第01轮'
        self.round['answers']={'酒':{'第01页.png':[[10,10,30,30],[50,10,70,30]]}}
        frame={'id':'第01页.png','actions':[{'kind':'tap','point':[20,20]}],'status':'passed'}
        self.assertEqual(evaluate_rounds([self.round],[frame])[0]['status'],'failed')
        frame['actions'].append({'kind':'tap','point':[60,20]})
        self.assertEqual(evaluate_rounds([self.round],[frame])[0]['status'],'passed')
        frame['status']='failed'
        self.assertEqual(evaluate_rounds([self.round],[frame])[0]['status'],'failed')

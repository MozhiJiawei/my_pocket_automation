"""Multi-answer truth, partial captures and known negatives must stay independent."""
from copy import deepcopy
import unittest

from scripts.perception.lib.round_truth import approve_rounds, evaluate_rounds, project_region
from scripts.perception.lib.corpus import load_cases, validate


class RoundTruthTest(unittest.TestCase):
    def setUp(self):
        self.capture={'case_id':'frame','sha256':'digest','viewport':[63,535,829,1410],
                      'list_origin_y':0,'page':1}
        self.candidate={'id':'A1','status':'proposed','stitched_region':[10,10,100,100],
                        'label':'weapon'}
        self.round={'id':'round','topic':'weapon','captures':[self.capture],
                    'candidate_annotations':[self.candidate],
                    'answer_set':{'item_ids':['A1'],'exhaustive':False},
                    'collection_status':'extent_unconfirmed'}
        self.document={'cases':[{'id':'frame','sha256':'digest','truth':{
            'target_regions':{'value':None,'status':'pending','source':'not annotated'}},
            'expected':{'checks':['target_regions']}}]}

    def approve(self, entry=None):
        return approve_rounds(self.document, {'categories':{'weapon':[entry or self.round]}},
                              [], 'user','explicit approval')

    def test_full_visible_answer_projects_to_every_overlapping_capture(self):
        later={**self.capture,'list_origin_y':40}
        self.assertEqual(project_region([10,50,100,150],later),[73,545,163,645])
        self.assertIsNone(project_region([10,10,100,100],later))

    def test_approval_preserves_uncertainty_and_does_not_make_empty_frames_negative(self):
        entry=deepcopy(self.round)
        entry['candidate_annotations'][0]['status']='uncertain'
        document, frozen=self.approve(entry)
        self.assertEqual(document['cases'][0]['truth']['target_regions']['status'],'pending')
        self.assertEqual(frozen['rounds'][0]['answer_set']['item_ids'],[])
        self.assertFalse(frozen['rounds'][0]['answer_set']['exhaustive'])

    def test_approval_is_idempotent_and_cannot_accept_changed_screenshot(self):
        document, frozen=self.approve()
        again,_=approve_rounds(document,{'categories':{'weapon':[self.round]}},[], 'user','explicit approval')
        self.assertEqual(document,again)
        changed=deepcopy(self.round); changed['captures'][0]['sha256']='wrong'
        with self.assertRaises(ValueError): self.approve(changed)

    def test_any_correct_answer_is_usable_without_faking_all_object_recall(self):
        _, frozen=self.approve()
        entry=frozen['rounds'][0]
        entry['candidate_annotations'].append({'id':'A2','status':'user_verified','stitched_region':[110,10,200,100]})
        entry['answer_set']['item_ids'].append('A2')
        results=[{'id':'frame','actions':[{'kind':'tap','point':[193,555]}]}]
        result=evaluate_rounds([entry],results)[0]
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['selected_answers'],['A2'])
        self.assertEqual(result['unselected_answers'],['A1'])
        results[0]['actions'][0]['point']=[500,555]
        self.assertEqual(evaluate_rounds([entry],results)[0]['status'],'unscored')
        results[0]['known_negative_regions']=[[490,540,510,570]]
        self.assertEqual(evaluate_rounds([entry],results)[0]['status'],'failed')

    def test_excluded_gold_mineral_is_a_known_negative_with_provenance(self):
        rejection={'round_id':'round','label':'mineral','stitched_region':[110,10,200,100]}
        document,_=approve_rounds(self.document,{'categories':{'weapon':[self.round]}},
                                  [rejection],'user','explicit approval')
        truth=document['cases'][0]['truth']
        self.assertEqual(truth['negative_regions']['value'],[[173,545,263,635]])
        self.assertEqual(truth['negative_regions']['status'],'user_verified')
        self.assertNotIn('regression_checks',document['cases'][0]['expected'])

    def test_later_correction_removes_stale_positive_without_claiming_absence(self):
        document,_=self.approve()
        entry=deepcopy(self.round); entry['candidate_annotations']=[]
        corrected,_=approve_rounds(document,{'categories':{'weapon':[entry]}},[], 'user','later correction')
        field=corrected['cases'][0]['truth']['target_regions']
        self.assertIsNone(field['value'])
        self.assertEqual(field['status'],'pending')

    def test_approved_corpus_keeps_valid_regions_and_round_refs(self):
        for case in load_cases('zhuagui'):
            validate(case)
            if case.get('round_answer_refs'):
                self.assertEqual(case['truth']['target_regions']['status'],'user_verified')
                self.assertIn('target_regions',case['expected']['checks'])


if __name__=='__main__':
    unittest.main()

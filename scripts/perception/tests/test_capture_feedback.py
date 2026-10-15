"""Answer confirmation cannot erase missing-capture evidence."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
import cv2
import numpy as np
from unittest.mock import patch
from PIL import Image
from scripts.perception.lib import annotation_queue as queue,capture_feedback as feedback


class CaptureVerificationTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=queue.ROOT/'.tmp');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.write_frames([0,624,1248,1872,2245,2245])

    def write_frames(self,offsets,thumb=True):
        for path in self.folder.glob('第*页.png'):path.unlink()
        for page,offset in enumerate(offsets,1):
            frame=np.full((1600,900,3),(229,180,164),np.uint8)
            cv2.putText(frame,'FIND THE WINE',(80,385),cv2.FONT_HERSHEY_SIMPLEX,1,(20,20,20),3)
            body=frame.copy()
            for row in range(20):
                top=537+row*156-offset
                for column in range(5):
                    left=64+column*156
                    cv2.rectangle(body,(left,top),(left+138,top+138),(245,220,205),1)
                    if 0<=top+20 and top+120<=1600:
                        texture=np.random.default_rng(row*5+column).integers(0,220,(8,8,3),dtype=np.uint8)
                        body[top+20:top+120,left+20:left+120]=cv2.resize(texture,(100,100),interpolation=cv2.INTER_NEAREST)
            frame[527:1402,63:826]=body[527:1402,63:826]
            if thumb:
                start=round(527+offset*(875-246)/2245)
                frame[max(527,start):min(1402,start+246),828:832]=(184,140,108)
            cv2.imencode('.png',frame,[cv2.IMWRITE_PNG_COMPRESSION,1])[1].tofile(self.folder/f'第{page:02d}页.png')

    def verify(self):return feedback.verify(self.folder,'抓鬼','寻物')

    def test_complete_strip_passes_and_repeated_bottom_page_adds_no_height(self):
        result=self.verify()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['image_height'],2760)
        self.assertEqual(result['minimum_height'],2760)
        self.assertTrue(feedback.read(self.folder)['can_use_as_complete'])

    def test_missing_middle_page_produces_a_short_strip(self):
        self.write_frames([0,624,1872,2245,2245])
        result=self.verify()
        self.assertEqual(result['status'],'incomplete')
        self.assertEqual(result['image_height'],2346)
        self.assertIn('2346',result['reasons'][0])

    def test_complete_strip_does_not_require_a_scrollbar(self):
        self.write_frames([0,624,1248,1872,2245,2245],thumb=False)
        result=self.verify()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['image_height'],2760)

    def test_prompt_pixels_do_not_affect_height_check(self):
        path=self.folder/'第03页.png';frame=cv2.imdecode(np.fromfile(path,np.uint8),1)
        frame[325:425,63:610]=(0,0,0);cv2.imencode('.png',frame)[1].tofile(path)
        result=self.verify()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['image_height'],2760)

    def test_changed_pixels_trigger_reverification_instead_of_cached_complete(self):
        self.assertEqual(self.verify()['status'],'complete')
        Image.new('RGB',(900,1600),'blue').save(self.folder/'第03页.png')
        result=self.verify()
        self.assertEqual(result['status'],'incomplete')
        self.assertLess(result['image_height'],2760)
        self.assertFalse(result['can_use_as_complete'])

    def test_old_feedback_is_reassessed_by_height_and_retained_in_history(self):
        feedback.write(self.folder,{'status':'incomplete','reasons':['用户指出缺少原始页。']})
        result=self.verify()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['previous_feedback']['reasons'],['用户指出缺少原始页。'])

    def test_puzzle_originals_are_judged_only_by_height(self):
        self.write_frames([])
        for height,status in [(1599,'incomplete'),(1600,'complete'),(1601,'complete')]:
            with self.subTest(height=height):
                Image.new('RGB',(900,height),'blue').save(self.folder/'第01页.png')
                result=feedback.verify(self.folder,'师门','拼图')
                self.assertEqual(result['status'],status)
                self.assertEqual(result['image_height'],height)

    def test_failed_open_keeps_the_prior_unknown_feedback_for_audit(self):
        feedback.write(self.folder,{'status':'unverified','reasons':['历史覆盖未记录。']})
        (self.folder/'第01页.png').write_bytes(b'broken png')
        result=self.verify()
        self.assertEqual(result['status'],'verification_failed')
        self.assertEqual(result['previous_feedback']['reasons'],['历史覆盖未记录。'])

    def test_repeating_one_page_does_not_meet_height_threshold(self):
        self.write_frames([0]*7)
        result=self.verify()
        self.assertEqual(result['status'],'incomplete')
        self.assertEqual(result['image_height'],690)

    def test_unchanged_images_reuse_height_result(self):
        with patch.object(feedback,'compose_rows',wraps=feedback.compose_rows) as compose:
            first=self.verify();second=self.verify()
            self.assertEqual(first,second)
            self.assertEqual(compose.call_count,1)

    def test_shortest_puzzle_original_controls_completeness(self):
        self.write_frames([])
        for index,height in enumerate((1600,1599),1):
            Image.new('RGB',(900,height),'blue').save(self.folder/f'第{index:02d}页.png')
        result=feedback.verify(self.folder,'师门','拼图')
        self.assertEqual(result['status'],'incomplete')
        self.assertEqual(result['image_height'],1599)


class CaptureFeedbackTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=queue.ROOT/'.tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        Image.new('RGB',(900,1600),'blue').save(self.source/'第01页.png')

    def test_inventory_height_boundary_is_shared_by_tasks(self):
        for task,kind in [('师门','寻物'),('抓鬼','寻物'),('抓鬼','找鬼')]:
            for height,status in [(2759,'incomplete'),(2760,'complete'),(2761,'complete')]:
                with self.subTest(task=task,kind=kind,height=height),patch.object(feedback,'compose_rows',return_value=(Image.new('RGB',(766,height)),[],None,[])):
                    report=feedback.inspect(self.source,task,kind)
                    self.assertEqual(report['status'],status)
                    self.assertEqual(report['can_use_as_complete'],status=='complete')
                    self.assertEqual(report['image_height'],height)

    def test_missing_images_resolve_to_a_failure_instead_of_unknown(self):
        with tempfile.TemporaryDirectory(dir=self.root) as empty:
            for kind in ['寻物','拼图']:
                report=feedback.verify(empty,'师门',kind)
                self.assertEqual(report['status'],'verification_failed')
                self.assertTrue(report['reasons'])

    def test_new_intake_warns_ai_and_confirmation_keeps_negative_feedback(self):
        with patch.object(queue,'PENDING',self.root/'pending'),patch.object(queue,'CONFIRMED',self.root/'confirmed'):
            with self.assertWarnsRegex(UserWarning,'采集负反馈'):
                identity=queue.enqueue(self.source,'师门','寻物','酒','输入')
            folder=queue.resolve('pending',identity)
            report=feedback.read(folder);self.assertEqual(report['status'],'verification_failed')
            target=queue.confirm(identity,{'正确':{'酒':{}}})
            self.assertEqual(feedback.read(target),report)
            self.assertEqual(queue.items('confirmed')[0]['capture_feedback']['status'],'verification_failed')
            self.assertTrue((target/'答案.json').is_file())

    def test_pixels_or_page_set_changes_invalidate_previous_complete_review(self):
        report={'status':'complete','reasons':[],'evidence':'独立核对完整原图、连续滚动和触底。'}
        feedback.write(self.source,report)
        self.assertTrue(feedback.read(self.source)['can_use_as_complete'])
        Image.new('RGB',(900,1600),'red').save(self.source/'第01页.png')
        self.assertFalse(feedback.read(self.source)['can_use_as_complete'])
        feedback.write(self.source,report)
        Image.new('RGB',(900,1600),'blue').save(self.source/'第02页.png')
        self.assertEqual(feedback.read(self.source)['status'],'unverified')

    def test_complete_feedback_requires_evidence_and_malformed_feedback_is_negative(self):
        with self.assertRaisesRegex(ValueError,'核验依据'):
            feedback.write(self.source,{'status':'complete','reasons':[]})
        (self.source/feedback.FILENAME).write_text('{broken',encoding='utf-8')
        self.assertFalse(feedback.read(self.source)['can_use_as_complete'])

    def test_freeze_rejects_incomplete_capture_and_preserves_confirmed_local_answers(self):
        identity='师门/寻物/酒/输入'
        folder=self.root/'confirmed'/identity;folder.mkdir(parents=True)
        Image.new('RGB',(900,1600),'blue').save(folder/'第01页.png')
        document={'正确':{'酒':{'第01页.png':[[70,543,202,675]]}},'反例':{'酒':{}}}
        (folder/'答案.json').write_text(json.dumps(document,ensure_ascii=False),encoding='utf-8')
        (folder/'审核.md').write_text('用户确认可见答案。',encoding='utf-8')
        feedback.write(folder,{'status':'incomplete','reasons':['只有局部原图，无法补采。'],'recoverable':False})
        spec=importlib.util.spec_from_file_location('freeze_with_feedback',queue.ROOT/'scripts/perception/freeze-annotations.py')
        freeze=importlib.util.module_from_spec(spec);spec.loader.exec_module(freeze)
        before=(folder/'答案.json').read_bytes()
        with patch.object(queue,'CONFIRMED',self.root/'confirmed'),self.assertWarnsRegex(UserWarning,'采集负反馈'):
            with self.assertRaisesRegex(ValueError,'采集不完整.*'+identity):freeze.prepare(identity)
            with patch.object(freeze,'compose_rows',return_value=(None,[],None,[])):
                result=freeze.prepare(identity,allow_partial=True)
        self.assertEqual(result[1],document)
        self.assertEqual(result[3]['status'],'verification_failed')
        self.assertEqual(result[3]['previous_feedback']['status'],'incomplete')
        self.assertFalse(result[3]['can_use_as_complete'])
        self.assertEqual((folder/'答案.json').read_bytes(),before)

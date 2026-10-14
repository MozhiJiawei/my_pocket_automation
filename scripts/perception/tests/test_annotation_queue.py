"""Capture handoff and deletion must not depend on persistent queue indexes."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
import subprocess
from contextlib import ExitStack
from unittest.mock import patch
from PIL import Image
from scripts.perception.lib import annotation_queue as queue

class AnnotationQueueTest(unittest.TestCase):
    def test_queue_contents_are_ignored_but_directory_placeholders_are_not(self):
        for name in ('未完成','已完成'):
            folder=queue.ROOT/'annotation-web'/name
            self.assertTrue((folder/'.gitkeep').is_file())
            for path,ignored in [(folder/'师门/寻物/酒/输入/答案.json',True),(folder/'.gitkeep',False)]:
                result=subprocess.run(['git','check-ignore','--no-index','-q',str(path)],cwd=queue.ROOT)
                self.assertEqual(result.returncode,0 if ignored else 1)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=queue.ROOT/'.tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name,value in [('BASE',self.root/'工作'),('PENDING',self.root/'工作/未完成'),('CONFIRMED',self.root/'工作/已完成')]:
            self.stack.enter_context(patch.object(queue,name,value))
        self.source=self.root/'source';self.source.mkdir()
        Image.new('RGB',(900,1600),(40,80,120)).save(self.source/'第01页.png')
    def test_capture_enters_pending_with_public_pixels_only(self):
        identity=queue.enqueue(self.source,'师门','寻物','酒','输入')
        self.assertEqual(queue.items('pending')[0]['id'],identity)
        image=Image.open(queue.resolve('pending',identity)/'第01页.png')
        self.assertEqual(image.getpixel((0,0)),(0,0,0))
        self.assertEqual(image.getpixel((300,800)),(40,80,120))
        self.assertFalse((queue.resolve('pending',identity)/'答案.json').exists())
    def test_partial_enqueue_is_not_visible(self):
        working=queue.PENDING/'.入队_test/item';working.mkdir(parents=True)
        Image.new('RGB',(900,1600)).save(working/'第01页.png')
        self.assertEqual(queue.items('pending'),[])
    def test_workflow_inputs_never_enter_human_confirmation_queue(self):
        for kind in ('页面','流程','未知类型'):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError,'流程页面不进入标注队列'):
                    queue.enqueue(self.source,'师门',kind,'测试','输入')
                self.assertEqual(queue.items('pending'),[])
                self.assertTrue((self.source/'第01页.png').is_file())
    def test_conversation_confirmation_preserves_user_evidence(self):
        identity=queue.enqueue(self.source,'师门','拼图','香炉','输入')
        document={'预期':{'第01页.png':{'puzzle_locations':[3,2,1,4]}}}
        folder=queue.resolve('pending',identity)
        for evidence in ('', '  ', 123):
            with self.assertRaisesRegex(ValueError,'用户明确确认'):
                queue.confirm(identity,document,evidence=evidence)
            self.assertFalse((folder/'答案.json').exists())
        target=queue.confirm(identity,document,evidence='用户确认：本张顺序为3、2、1、4。')
        note=(target/'审核.md').read_text(encoding='utf-8')
        self.assertIn('用户确认：本张顺序为3、2、1、4。',note)
        self.assertNotIn('点击',note)
        self.assertEqual(json.loads((target/'答案.json').read_text(encoding='utf-8')),document)
    def test_confirmation_deletion_does_not_replay_source(self):
        identity=queue.enqueue(self.source,'师门','寻物','酒','输入')
        target=queue.confirm(identity,{'正确':{'酒':{}}})
        self.assertEqual(queue.items('pending'),[])
        (target/'答案.json').unlink()
        self.assertEqual(queue.items('confirmed'),[])
        self.assertEqual(queue.items('pending'),[])
        self.assertTrue((self.source/'第01页.png').exists())
    def test_unsafe_paths_and_duplicate_confirmation_are_rejected(self):
        with self.assertRaises(ValueError):queue.enqueue(self.source,'../outside','寻物','酒','输入')
        identity=queue.enqueue(self.source,'师门','寻物','酒','输入')
        queue.confirm(identity,{'正确':{'酒':{}}})
        with self.assertRaises(ValueError):queue.confirm(identity,{'正确':{'酒':{}}})
        with self.assertRaises(ValueError):queue.resolve('pending','../../source')
    def test_puzzle_enqueue_defaults_are_empty_and_source_geometry_is_preserved(self):
        identity=queue.enqueue(self.source,'师门','拼图','香炉','输入')
        folder=queue.resolve('pending',identity)
        for name in ('建议.json','草稿.json'):
            self.assertFalse((folder/name).exists())
        with Image.open(folder/'第01页.png') as image,Image.open(self.source/'第01页.png') as original:
            for box in queue.puzzle_layout('师门',{'第01页.png':{'size':list(image.size)}})['cells']:
                self.assertEqual(image.crop(box).tobytes(),original.crop(box).tobytes())
        self.assertFalse((folder/'答案.json').exists())
    def test_puzzle_layout_requires_equal_nonoverlapping_row_major_cells(self):
        root=self.root/'geometry';path=root/'testdata/师门/拼图/格位.json';path.parent.mkdir(parents=True)
        images={'第01页.png':{'size':[900,1600]}}
        valid=[[10,20,30,50],[40,20,60,50],[10,60,30,90],[40,60,60,90]]
        unequal=[valid[0],valid[1],valid[2],[40,60,61,90]]
        overlapping=[[10,20,30,50],[25,20,45,50],[10,60,30,90],[25,60,45,90]]
        vertical_overlap=[[10,20,30,50],[40,20,60,50],[10,45,30,75],[40,45,60,75]]
        wrong_order=[valid[0],valid[2],valid[1],valid[3]]
        misaligned=[valid[0],valid[1],[11,60,31,90],valid[3]]
        with patch.object(queue,'ROOT',root):
            path.write_text(json.dumps(valid),encoding='utf-8')
            self.assertEqual(queue.puzzle_layout('师门',images)['cells'],valid)
            for cells in [unequal,overlapping,vertical_overlap,wrong_order,misaligned,[valid[0]]*4]:
                with self.subTest(cells=cells):
                    path.write_text(json.dumps(cells),encoding='utf-8')
                    with self.assertRaises(ValueError):queue.puzzle_layout('师门',images)
    def test_puzzle_enqueue_rejects_invalid_proposals_before_creating_queue_item(self):
        for document in [{'正确':{}},{'预期':{'第01页.png':{'puzzle_locations':[1,1,3,4]}}},
                         {'预期':{'第02页.png':{'puzzle_locations':[1,2,3,4]}}}]:
            with self.assertRaises(ValueError):queue.enqueue(self.source,'师门','拼图','香炉','输入',suggestions=document)
            with self.assertRaises(ValueError):queue.enqueue(self.source,'师门','拼图','香炉','输入',draft=document)
            self.assertEqual(queue.items('pending'),[])
    def test_puzzle_confirmation_validates_all_pages_before_writing_approval(self):
        Image.new('RGB',(900,1600),(50,90,130)).save(self.source/'第02页.png')
        for task,field,order in [('师门','puzzle_locations',[3,2,1,4]),('抓鬼','puzzle_order','CBAD')]:
            identity=queue.enqueue(self.source,task,'拼图','香炉','输入');folder=queue.resolve('pending',identity)
            expected={'第01页.png':{field:order}}
            with self.assertRaises(ValueError):queue.confirm(identity,{'预期':expected})
            self.assertFalse((folder/'答案.json').exists());self.assertFalse((folder/'审核.md').exists())
            expected['第02页.png']={field:order}
            original={p.name:p.read_bytes() for p in folder.glob('第*页.png')}
            target=queue.confirm(identity,{'预期':expected})
            self.assertEqual(json.loads((target/'答案.json').read_text(encoding='utf-8')),{'预期':expected})
            for name,pixels in original.items():self.assertEqual((target/name).read_bytes(),pixels)
            note=(target/'审核.md').read_text(encoding='utf-8')
            self.assertIn('恢复图左上、右上、左下、右下',note);self.assertIn('尚未写入正式测试真值',note)
            self.assertTrue((self.source/'第01页.png').is_file())
    def test_puzzle_partial_documents_are_strict_and_task_specific(self):
        images={'第01页.png':{'size':[900,1600]},'第02页.png':{'size':[900,1600]}}
        self.assertEqual(queue.validate_puzzle_document({'预期':{}},images,'师门'),{'预期':{}})
        for task,field,valid,invalid in [
            ('师门','puzzle_locations',[3,2,1,4],[[1,1,3,4],[True,2,3,4],[1.0,2,3,4],(1,2,3,4),'1234',[1,2,3,5],None]),
            ('抓鬼','puzzle_order','CBAD',['AACD','abcd','ABCDE','ABC',[1,2,3,4],1234,None])]:
            document={'预期':{'第01页.png':{field:valid}}}
            self.assertEqual(queue.validate_puzzle_document(document,images,task),document)
            with self.assertRaises(ValueError):queue.validate_puzzle_document(document,images,task,complete=True)
            for order in invalid:
                with self.subTest(task=task,order=order):
                    with self.assertRaises(ValueError):queue.validate_puzzle_document({'预期':{'第01页.png':{field:order}}},images,task)
            wrong='puzzle_order' if field=='puzzle_locations' else 'puzzle_locations'
            with self.assertRaises(ValueError):queue.validate_puzzle_document({'预期':{'第01页.png':{wrong:valid}}},images,task)
    def test_freeze_tool_filters_other_tasks_and_puzzles(self):
        spec=importlib.util.spec_from_file_location('freeze_annotations',queue.ROOT/'scripts/perception/freeze-annotations.py')
        freeze=importlib.util.module_from_spec(spec);spec.loader.exec_module(freeze)
        unsupported='师门/拼图/香炉/输入'
        with self.assertRaisesRegex(ValueError,'Unsupported annotation type'):freeze.prepare(unsupported)
        items=[{'task':'师门','kind':'寻物','id':'师门/寻物/酒/输入'},
               {'task':'师门','kind':'拼图','id':unsupported},
               {'task':'抓鬼','kind':'找鬼','id':'抓鬼/找鬼/鬼/输入'}]
        with patch.object(freeze,'ROOT',self.root),patch.object(freeze.queue,'items',return_value=items),\
             patch.object(freeze,'ProcessPoolExecutor') as executor,patch('sys.argv',['freeze-annotations.py']),patch('builtins.print'):
            executor.return_value.__enter__.return_value.map.return_value=[]
            freeze.main()
            executor.return_value.__enter__.return_value.map.assert_called_once_with(freeze.prepare,['师门/寻物/酒/输入'])

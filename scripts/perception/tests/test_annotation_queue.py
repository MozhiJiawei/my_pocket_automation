"""Capture handoff and deletion must not depend on persistent queue indexes."""
from pathlib import Path
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

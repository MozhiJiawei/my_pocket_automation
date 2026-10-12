"""Draft isolation and HTTP boundaries of the local annotation tool."""
import importlib.util
import json
from pathlib import Path
import tempfile
import cv2
import numpy as np
import threading
import sys
import unittest
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from PIL import Image

spec=importlib.util.spec_from_file_location('annotation_server',Path(__file__).with_name('server.py'))
web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)

class QueueTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=web.ROOT/'.tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name,value in [('PENDING',self.root/'未完成'),('CONFIRMED',self.root/'已完成')]:
            patcher=patch.object(web.queue,name,value);patcher.start();self.addCleanup(patcher.stop)
        self.identity='师门/寻物/酒/测试输入'
        self.directory=web.queue.PENDING/self.identity;self.directory.mkdir(parents=True)
        Image.new('RGB',(900,1600),'blue').save(self.directory/'第01页.png')
        self.item=object.__new__(web.Item);self.item.topic='酒';self.item.token='test-token'
        self.item.directory=self.directory;self.item.id=self.identity;self.item.stage='pending'
        self.item.images={'第01页.png':{'size':[900,1600],'path':self.directory/'第01页.png'}}
        self.item.strip=self.directory/'第01页.png';self.item.data={'id':self.identity}
        self.review=web.Review();self.review.cache[('pending',self.identity)]=self.item
        self.doc={'正确':{'酒':{'第01页.png':[[100,600,220,720]]}},'反例':{'酒':{'第01页.png':[[250,600,370,720]]}}}
    def test_confirmation_moves_input_and_preserves_original_pixels(self):
        original=(self.directory/'第01页.png').read_bytes();target=self.item.save(self.doc)
        self.assertFalse(self.directory.exists())
        self.assertEqual((target/'第01页.png').read_bytes(),original)
        self.assertEqual(json.loads((target/'答案.json').read_text(encoding='utf-8')),self.doc)
        self.assertEqual(web.queue.items('pending'),[])
        self.assertEqual(len(web.queue.items('confirmed')),1)
    def test_external_answer_deletion_removes_archive_and_never_requeues(self):
        target=self.item.save(self.doc);(target/'答案.json').unlink()
        self.assertEqual(web.queue.items('confirmed'),[])
        self.assertEqual(web.queue.items('pending'),[])
        with self.assertRaises(ValueError):self.review.get('confirmed',self.identity)
    def test_invalid_answers_do_not_move_input(self):
        for name,box in [('第01页.png',[-1,0,10,10]),('第01页.png',[0,0,901,10]),('第01页.png',[10,0,1,10]),
                         ('第01页.png',[False,0,10,10]),('../原图.png',[0,0,10,10])]:
            with self.assertRaises(ValueError):self.item.save({'正确':{'酒':{name:[box]}}})
        self.assertTrue(self.directory.exists());self.assertEqual(web.queue.items('confirmed'),[])
    def test_http_scopes_images_and_confirmations(self):
        from urllib.parse import quote
        server=ThreadingHTTPServer(('127.0.0.1',0),web.handler(self.review))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}';query='?id='+quote(self.identity)
        try:
            for path in ['/api/image'+query+'&name=../outside.png','/../AGENTS.md','/api/item?id=../../outside']:
                with self.assertRaises(HTTPError) as failure:urlopen(base+path)
                self.assertEqual(failure.exception.code,404)
            with self.assertRaises(HTTPError) as failure:
                urlopen(Request(base+'/api/confirm'+query,data=json.dumps(self.doc).encode(),method='POST'))
            self.assertEqual(failure.exception.code,403)
            req=Request(base+'/api/confirm'+query,data=json.dumps(self.doc).encode(),headers={'X-Annotation-Token':'test-token'},method='POST')
            with urlopen(req) as response:self.assertTrue(json.load(response)['confirmed'])
            with urlopen(base+'/api/queue') as response:state=json.load(response)
            self.assertEqual(state['pending'],[]);self.assertEqual(len(state['confirmed']),1)
            with self.assertRaises(HTTPError):urlopen(req)
        finally:server.shutdown();server.server_close();thread.join()
    def test_all_no_is_valid_and_conflicting_states_are_rejected(self):
        doc={'正确':{'酒':{}},'反例':{'酒':{'第01页.png':[[100,600,220,720]]}}}
        web.validate_document(doc,self.item.images,'酒')
        with self.assertRaises(ValueError):web.validate_document({'正确':doc['反例'],'反例':doc['反例']},self.item.images,'酒')
    def test_unsupported_scene_keeps_original_visible_and_cannot_confirm(self):
        identity='师门/拼图/香炉/测试输入'
        folder=web.queue.PENDING/identity;folder.mkdir(parents=True)
        Image.new('RGB',(900,1600),'blue').save(folder/'第01页.png')
        item=web.Item('pending',identity,self.root/'output')
        self.assertFalse(item.data['annotatable'])
        self.assertEqual(item.data['strip']['size'],[900,1600])
        self.assertEqual(item.data['cells'],[])
        self.assertIn('仅查看原图',item.data['limitation'])
        with self.assertRaises(ValueError):item.save({'正确':{'香炉':{}}})
        self.assertTrue(folder.exists());self.assertFalse((folder/'答案.json').exists())
    def test_strip_check_fails_when_suggestion_has_no_source_mapping(self):
        spec=importlib.util.spec_from_file_location('strip_check',Path(__file__).with_name('check_rounds.py'))
        check=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'server':web}):spec.loader.exec_module(check)
        (self.directory/'建议.json').write_text(json.dumps({'正确':{'酒':{'第01页.png':[[70,800,202,932]]}}}),encoding='utf-8')
        original=Image.open(self.directory/'第01页.png').convert('RGB')
        layer={'image':'第01页.png','source':[63,540,829,678],
               'aliases':[{'image':'第01页.png','source':[63,540,829,678]}],'destination':[0,0,766,138]}
        with patch.object(check,'compose_rows',return_value=(original.crop(layer['source']),[],original,[layer])):
            result=check.check(('pending',self.identity,str(self.root/'output')))
        self.assertFalse(result['passed']);self.assertEqual(len(result['suggestions_without_complete_row']),1)

class ProvenanceTest(unittest.TestCase):
    def test_original_question_prepend_preserves_source_and_click_mapping(self):
        original=Image.fromarray(np.arange(1600*900*3,dtype=np.uint8).reshape(1600,900,3))
        strip=Image.new('RGB',(766,138),'blue')
        layer={'image':'第01页.png','source':[63,540,829,678],
               'aliases':[{'image':'第02页.png','source':[63,600,829,738]}],
               'destination':[0,0,766,138]}
        combined,layers=web.with_question(strip,original,[layer])
        self.assertEqual(combined.size,(766,343))
        self.assertEqual(combined.crop((0,0,766,205)).tobytes(),original.crop((63,245,829,450)).tobytes())
        self.assertEqual(combined.crop((0,205,766,343)).tobytes(),strip.tobytes())
        self.assertEqual(layers[0]['destination'],[0,205,766,343])
        self.assertEqual(layer['destination'],[0,0,766,138])
        self.assertEqual(layers[0]['source'],layer['source'])
        self.assertEqual(layers[0]['aliases'],layer['aliases'])
        # A click on an aliased item still maps to exactly the same original pixel.
        for row in (layer,layers[0]):
            source=row['aliases'][0]['source'];destination=row['destination']
            projected_y=620+destination[1]-source[1]
            self.assertEqual(projected_y-destination[1]+source[1],620)

    def test_one_pixel_detection_shift_does_not_duplicate_rows(self):
        frame=np.random.default_rng(17).integers(0,256,(1600,900,3),dtype=np.uint8)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'画面.png';Image.fromarray(frame).save(path)
            pages={i:{'id':str(i),'image':f'第{i:02d}页.png'} for i in (1,2)}
            with patch('scripts.perception.lib.task_review.item_cells',side_effect=[[[70,543,202,675]],[[70,544,202,676]]]):
                strip,records,_,layers=web.compose_rows(pages,image_resolver=lambda c:path)
            self.assertEqual(len(layers),1)
            self.assertTrue(records[-1]['redundant_capture'])
            self.assertEqual([a['source'][1] for a in layers[0]['aliases']],[540,541])
            self.assertEqual(strip.tobytes(),Image.fromarray(frame).crop(layers[0]['source']).tobytes())
    def test_clipped_border_keeps_complete_top_row_clickable(self):
        frame=np.full((1600,900,3),240,np.uint8)
        for row in range(6):
            for column in range(5):
                x,y=64+156*column,531+156*row
                cv2.rectangle(frame,(x,y),(x+138,y+138),(180,190,205),2)
        cells=web.item_cells(frame)
        self.assertEqual(len(cells),25)
        self.assertEqual(min(b[1] for b in cells),535)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'画面.png';Image.fromarray(frame).save(path)
            strip,_,_,layers=web.compose_rows({1:{'id':'1','image':path.name}},image_resolver=lambda c:path)
            for box in cells:
                self.assertEqual(sum(a['source'][0]<=box[0]<box[2]<=a['source'][2] and a['source'][1]<=box[1]<box[3]<=a['source'][3]
                                     for l in layers for a in l['aliases']),1)
            for layer in layers:
                _,dy,_,end=layer['destination']
                self.assertEqual(strip.crop((0,dy,766,end)).tobytes(),Image.fromarray(frame).crop(layer['source']).tobytes())
    def test_complete_item_grid_has_all_clickable_cells(self):
        frame=np.full((1600,900,3),240,np.uint8)
        for row in range(6):
            for column in range(5):
                x,y=64+156*column,537+156*row
                cv2.rectangle(frame,(x,y),(x+138,y+138),(180,190,205),2)
        cells=web.item_cells(frame)
        self.assertEqual(len(cells),25)
        self.assertTrue(all(b[3]<=1405 for b in cells))
    def test_painted_row_sources_match_strip_pixels(self):
        spec=importlib.util.spec_from_file_location('review_map',web.ROOT/'scripts/perception/render_task_review.py')
        review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)
        with tempfile.TemporaryDirectory() as folder:
            paths={};images={}
            for i,color in enumerate(('red','blue'),1):
                name=f'{i}.png';image=Image.new('RGB',(900,1600),color)
                images[name]=image;paths[name]=Path(folder)/name;image.save(paths[name])
            pages={i:{'image':f'{i}.png','id':f'{i}.png'} for i in (1,2)}
            alignment={'accepted':True,'offset':156,'overlap':719,'error':0}
            with patch.object(review,'image_path',side_effect=lambda c:paths[c['image']]),patch.object(review,'scroll_offset',return_value=alignment):
                strip,records,_,layers=review.compose(pages,with_sources=True)
            self.assertGreater(len(layers),len(records))
            for y in range(10,strip.height-10,20):
                layer=next(l for l in reversed(layers) if l['destination'][1]<=y<l['destination'][3])
                x=100;sx=x+layer['source'][0]-layer['destination'][0];sy=y+layer['source'][1]-layer['destination'][1]
                self.assertEqual(strip.getpixel((x,y)),images[layer['image']].getpixel((sx,sy)))

if __name__=='__main__':unittest.main()

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
        self.item.task='师门';self.item.kind='寻物'
        self.item.directory=self.directory;self.item.id=self.identity;self.item.stage='pending'
        self.item.images={'第01页.png':{'size':[900,1600],'path':self.directory/'第01页.png'}}
        self.item.strip=self.directory/'第01页.png';self.item.data={'id':self.identity}
        self.review=web.Review();self.review.cache[('pending',self.identity)]=self.item
        self.doc={'正确':{'酒':{'第01页.png':[[100,600,220,720]]}},'反例':{'酒':{'第01页.png':[[250,600,370,720]]}}}
    def test_capture_negative_feedback_is_returned_without_clearing_confirmed_answers(self):
        web.capture_feedback.write(self.directory,{'status':'incomplete','reasons':['缺少后续页面。'],'recoverable':False})
        target=self.item.save(self.doc)
        self.assertEqual(json.loads((target/'答案.json').read_text(encoding='utf-8')),self.doc)
        server=ThreadingHTTPServer(('127.0.0.1',0),web.handler(self.review))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        from urllib.parse import quote
        try:
            url=f'http://127.0.0.1:{server.server_port}/api/item?stage=confirmed&id='+quote(self.identity)
            with urlopen(url) as response:record=json.load(response)
            self.assertEqual(record['capture_feedback']['status'],'verification_failed')
            self.assertEqual(record['capture_feedback']['previous_feedback']['reasons'],['缺少后续页面。'])
            self.assertFalse(record['capture_feedback']['recoverable'])
            self.assertEqual(record['initial'],self.doc)
            Image.new('RGB',(900,1600),'red').save(target/'第01页.png')
            with urlopen(url) as response:changed=json.load(response)
            self.assertEqual(changed['capture_feedback']['status'],'verification_failed')
            self.assertTrue(changed['capture_feedback']['reasons'])
        finally:server.shutdown();server.server_close();thread.join()

    def test_opening_unknown_capture_runs_verification_and_persists_the_result(self):
        web.capture_feedback.write(self.directory,{'status':'unverified','reasons':['尚未运行检查。']})
        with patch.object(web.capture_feedback,'verify',wraps=web.capture_feedback.verify) as verify:
            item=self.review.get('pending',self.identity)
            verify.assert_called_once_with(self.directory,'师门','寻物')
        result=item.data['capture_feedback']
        self.assertNotEqual(result['status'],'unverified')
        self.assertTrue(result['reasons'])
        self.assertEqual(web.capture_feedback.read(self.directory)['status'],result['status'])
        self.assertEqual(result['previous_feedback']['reasons'],['尚未运行检查。'])
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
        identity='师门/其它/香炉/测试输入'
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
    def test_reference_catalog_is_scoped_and_rejects_unsafe_sources(self):
        references=self.root/'references';folder=references/'师门/寻物/酒';folder.mkdir(parents=True)
        Image.new('RGB',(40,40),'red').save(folder/'酒.png')
        document={'说明':'酒类参考，尚非真值','图标':[{'名称':'酒','图片':'酒.png','来源':'https://example.com/items'}]}
        path=folder/'参考.json';path.write_text(json.dumps(document),encoding='utf-8')
        with patch.object(web,'REFERENCES',references):
            resolved,catalog=web.reference_catalog(self.identity)
            self.assertEqual(resolved,folder.resolve());self.assertEqual(catalog,document)
            _,missing=web.reference_catalog('师门/寻物/其它/输入')
            self.assertEqual(missing['图标'],[])
            with self.assertRaises(ValueError):web.reference_catalog('../../outside')
            for field,value in [('图片','../酒.png'),('来源','javascript:alert(1)')]:
                invalid=json.loads(json.dumps(document));invalid['图标'][0][field]=value
                path.write_text(json.dumps(invalid),encoding='utf-8')
                with self.assertRaises(ValueError):web.reference_catalog(self.identity)
    def test_reference_http_only_serves_images_listed_for_current_topic(self):
        from urllib.parse import quote
        references=self.root/'references';folder=references/'师门/寻物/酒';folder.mkdir(parents=True)
        Image.new('RGB',(40,40),'red').save(folder/'酒.png')
        (folder/'参考.json').write_text(json.dumps({'图标':[{'名称':'酒','图片':'酒.png','来源':'https://example.com/items','功效':'示例'}]}),encoding='utf-8')
        server=ThreadingHTTPServer(('127.0.0.1',0),web.handler(self.review))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}';query='?id='+quote(self.identity)
        try:
            with patch.object(web,'REFERENCES',references):
                with urlopen(base+'/api/item'+query) as response:
                    self.assertEqual(json.load(response)['references']['图标'][0]['功效'],'示例')
                with urlopen(base+'/api/reference'+query+'&name='+quote('酒.png')) as response:
                    self.assertEqual(response.headers['Content-Type'],'image/png')
                    self.assertEqual(response.read(),(folder/'酒.png').read_bytes())
                for name in ('../酒.png','未知.png'):
                    with self.assertRaises(HTTPError):urlopen(base+'/api/reference'+query+'&name='+quote(name))
        finally:server.shutdown();server.server_close();thread.join()

    def test_same_name_references_require_distinct_image_files(self):
        references=self.root/'references';folder=references/'师门/寻物/酒';folder.mkdir(parents=True)
        Image.new('RGB',(40,40),'red').save(folder/'月光.jpg')
        entries=[{'名称':'月光','图片':'月光.jpg','来源':'https://example.com/'+kind,'类别':kind}
                 for kind in ('双短剑','刃环')]
        path=folder/'参考.json';path.write_text(json.dumps({'图标':entries}),encoding='utf-8')
        with patch.object(web,'REFERENCES',references):
            with self.assertRaisesRegex(ValueError,'参考图片名称重复'):web.reference_catalog(self.identity)
            for entry in entries:
                entry['图片']='月光-'+entry['类别']+'.jpg'
                Image.new('RGB',(40,40),'blue').save(folder/entry['图片'])
            path.write_text(json.dumps({'图标':entries}),encoding='utf-8')
            self.assertEqual(web.reference_catalog(self.identity)[1]['图标'],entries)

class PuzzleTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=web.ROOT/'.tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name,value in [('PENDING',self.root/'未完成'),('CONFIRMED',self.root/'已完成')]:
            patcher=patch.object(web.queue,name,value);patcher.start();self.addCleanup(patcher.stop)
        self.review=web.Review();self.review.output=self.root/'output'
        self.server=ThreadingHTTPServer(('127.0.0.1',0),web.handler(self.review))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close_server)
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def close_server(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def create(self,task='师门',pages=2,size=(900,1600)):
        identity=f'{task}/拼图/香炉/测试输入';folder=web.queue.PENDING/identity;folder.mkdir(parents=True)
        colors=('red','green','blue','yellow')
        for index in range(1,pages+1):
            image=Image.new('RGB',size,(index*20,30,40))
            if task in web.queue.PUZZLE_FIELDS and size==(900,1600):
                boxes=json.loads((web.ROOT/'testdata'/task/'拼图/格位.json').read_text(encoding='utf-8'))
                for box,color in zip(boxes,colors):image.paste(color,box)
            image.save(folder/f'第{index:02d}页.png')
        return identity,folder
    def get(self,identity,stage='pending'):
        from urllib.parse import urlencode
        with urlopen(self.base+'/api/item?'+urlencode({'id':identity,'stage':stage})) as response:return json.load(response)
    def post(self,identity,document,token):
        from urllib.parse import urlencode
        request=Request(self.base+'/api/confirm?'+urlencode({'id':identity}),
            data=json.dumps(document).encode(),headers={'X-Annotation-Token':token},method='POST')
        with urlopen(request) as response:return json.load(response)
    def test_both_tasks_load_original_geometry_and_pixels_without_item_detection(self):
        from urllib.parse import urlencode
        for task,field,order in [('师门','puzzle_locations',[3,2,1,4]),('抓鬼','puzzle_order','CBAD')]:
            identity,folder=self.create(task)
            with patch.object(web,'compose_rows',side_effect=AssertionError('拼图不得拼物品长图')),patch.object(web,'item_cells',side_effect=AssertionError('拼图不得识别物品格')):
                item=self.get(identity)
            self.assertEqual(item['kind'],'拼图');self.assertTrue(item['annotatable'])
            self.assertEqual(item['puzzle']['field'],field)
            boxes=json.loads((web.ROOT/'testdata'/task/'拼图/格位.json').read_text(encoding='utf-8'))
            self.assertEqual(item['puzzle']['cells'],boxes)
            self.assertEqual(item['images'],[{'name':f'第{i:02d}页.png','size':[900,1600]} for i in (1,2)])
            self.assertEqual(item['suggestions'],{'预期':{}});self.assertEqual(item['initial'],{'预期':{}})
            self.assertEqual(item['cells'],[]);self.assertEqual(item['strip']['layers'],[])
            self.assertFalse((self.root/'output').exists())
            for endpoint in ('strip','image'):
                with urlopen(self.base+'/api/'+endpoint+'?'+urlencode({'id':identity,'name':'第01页.png'})) as response:
                    self.assertEqual(response.read(),(folder/'第01页.png').read_bytes())
            # Restored target positions refer to these exact original-image crops.
            with Image.open(folder/'第01页.png') as source:
                restored=[source.crop(boxes[i-1]).getpixel((5,5)) for i in ([3,2,1,4] if isinstance(order,list) else [ord(c)-64 for c in order])]
            self.assertEqual(restored,[(0,0,255),(0,128,0),(255,0,0),(255,255,0)])
    def test_partial_suggestions_and_drafts_keep_unmarked_pages_unknown(self):
        identity,folder=self.create()
        suggestion={'预期':{'第01页.png':{'puzzle_locations':[3,2,1,4]}}}
        draft={'预期':{'第02页.png':{'puzzle_locations':[1,2,3,4]}}}
        for name,document in [('建议.json',suggestion),('草稿.json',draft)]:
            (folder/name).write_text(json.dumps(document),encoding='utf-8')
        item=self.get(identity)
        self.assertEqual(item['suggestions'],suggestion);self.assertEqual(item['initial'],draft)
        self.assertNotIn('第01页.png',item['initial']['预期'])
        with self.assertRaises(HTTPError) as failure:self.post(identity,draft,item['token'])
        self.assertEqual(failure.exception.code,400);self.assertTrue(folder.exists())
    def test_enqueued_suggestion_is_initial_when_no_explicit_draft_exists(self):
        _,source=self.create()
        suggestion={'预期':{'第01页.png':{'puzzle_locations':[3,2,1,4]}}}
        identity=web.queue.enqueue(source,'师门','拼图','香炉','仅建议',suggestions=suggestion)
        folder=web.queue.resolve('pending',identity)
        self.assertFalse((folder/'草稿.json').exists())
        item=self.get(identity)
        self.assertEqual(item['suggestions'],suggestion);self.assertEqual(item['initial'],suggestion)
        self.assertNotIn('第02页.png',item['initial']['预期'])
    def test_invalid_or_missing_page_answers_never_write_or_move_input(self):
        identity,folder=self.create();token=self.get(identity)['token']
        valid={'预期':{f'第{i:02d}页.png':{'puzzle_locations':[3,2,1,4]} for i in (1,2)}}
        invalid=[{}, {'预期':{}}, {'预期':{'第01页.png':valid['预期']['第01页.png']}},
            {'预期':{**valid['预期'],'未知.png':{'puzzle_locations':[1,2,3,4]}}},
            {**valid,'正确':{}}]
        for entry in [{'puzzle_order':'CBAD'}, {'puzzle_locations':[1,1,3,4]}, {'puzzle_locations':[True,2,3,4]},
                      {'puzzle_locations':[1.0,2,3,4]}, {'puzzle_locations':'1234'}, {'puzzle_locations':[1,2,3]},
                      {'puzzle_locations':[0,2,3,4]}, {'puzzle_locations':[1,2,3,4],'puzzle_order':'ABCD'}, [], None]:
            invalid.append({'预期':{**valid['预期'],'第01页.png':entry}})
        for document in invalid:
            with self.subTest(document=document):
                with self.assertRaises(HTTPError) as failure:self.post(identity,document,token)
                self.assertEqual(failure.exception.code,400)
                self.assertTrue(folder.exists());self.assertFalse((folder/'答案.json').exists())
                self.assertFalse((folder/'审核.md').exists())
        self.assertEqual(web.queue.items('confirmed'),[])
    def test_confirmed_archive_is_read_only_and_deletion_never_requeues(self):
        for task,field,order in [('师门','puzzle_locations',[3,2,1,4]),('抓鬼','puzzle_order','CBAD')]:
            identity,folder=self.create(task);originals={p.name:p.read_bytes() for p in folder.glob('第*页.png')}
            document={'预期':{name:{field:order} for name in originals}}
            (folder/'草稿.json').write_text(json.dumps(document),encoding='utf-8')
            self.assertTrue(self.post(identity,document,self.get(identity)['token'])['confirmed'])
            target=web.queue.CONFIRMED/identity;self.assertFalse(folder.exists())
            for name,pixels in originals.items():self.assertEqual((target/name).read_bytes(),pixels)
            self.assertEqual(json.loads((target/'答案.json').read_text(encoding='utf-8')),document)
            self.assertFalse((target/'草稿.json').exists())
            self.assertIn('四格拖动恢复顺序',(target/'审核.md').read_text(encoding='utf-8'))
            self.assertEqual(self.get(identity,'confirmed')['initial'],document)
            with self.assertRaisesRegex(ValueError,'只读'):self.review.get('confirmed',identity).save(document)
            with self.assertRaises(HTTPError) as failure:self.post(identity,document,'old-token')
            self.assertEqual(failure.exception.code,404)
            (target/'答案.json').unlink()
            self.assertNotIn(identity,{item['id'] for item in web.queue.items('confirmed')})
            self.assertEqual(web.queue.items('pending'),[])
            with self.assertRaises(HTTPError):self.get(identity,'confirmed')
            self.assertTrue(all((target/name).is_file() for name in originals))
    def test_unsupported_size_task_or_geometry_remains_original_only(self):
        for task,size in [('师门',(720,1280)),('副本',(900,1600))]:
            identity,folder=self.create(task,pages=1,size=size);item=self.get(identity)
            self.assertFalse(item['annotatable']);self.assertEqual(item['images'][0]['size'],list(size))
            self.assertEqual(item['strip']['size'],list(size));self.assertEqual(item['puzzle']['cells'],[])
            self.assertIn('仅查看原图',item['limitation'])
            with self.assertRaises(HTTPError):self.post(identity,{'预期':{}},item['token'])
            self.assertTrue(folder.exists());self.assertFalse((folder/'答案.json').exists())
        identity,folder=self.create('抓鬼',pages=1)
        geometry=self.root/'geometry';path=geometry/'testdata/抓鬼/拼图/格位.json';path.parent.mkdir(parents=True)
        for cells in [[[0,0,901,20]]*4,[[0,0,20,20]]*4,
                      [[0,0,20,20],[30,0,50,20],[0,30,20,50],[30,30,51,50]]]:
            path.write_text(json.dumps(cells),encoding='utf-8')
            with patch.object(web.queue,'ROOT',geometry):item=web.Item('pending',identity,self.root/'output')
            self.assertFalse(item.data['annotatable']);self.assertEqual(item.data['puzzle']['cells'],[])
            self.assertEqual(item.strip,folder/'第01页.png')
    def test_invalid_suggestion_and_unknown_archive_image_remain_inspectable(self):
        from urllib.parse import urlencode
        identity,folder=self.create(pages=1)
        (folder/'建议.json').write_text(json.dumps({'说明':'无效建议格式，未经网页标注'}),encoding='utf-8')
        answer={'预期':{'画面.png':{'puzzle_locations':[3,2,1,4]}}}
        (folder/'答案.json').write_text(json.dumps(answer),encoding='utf-8')
        target=web.queue.CONFIRMED/identity;target.parent.mkdir(parents=True);folder.rename(target)
        originals={p.name:p.read_bytes() for p in target.iterdir() if p.is_file()}
        # Image access must work even before /api/item has read the invalid files.
        with urlopen(self.base+'/api/image?'+urlencode({'id':identity,'stage':'confirmed','name':'第01页.png'})) as response:
            self.assertEqual(response.read(),originals['第01页.png'])
        item=self.get(identity,'confirmed')
        self.assertFalse(item['annotatable']);self.assertEqual(item['initial'],{'预期':{}})
        self.assertEqual(item['suggestions'],{'预期':{}})
        self.assertIn('建议.json',item['limitation']);self.assertIn('答案.json',item['limitation'])
        self.assertIn('未知原图',item['limitation']);self.assertIn('未加载已核对排列',item['limitation'])
        self.assertEqual(item['images'],[{'name':'第01页.png','size':[900,1600]}])
        with self.assertRaisesRegex(ValueError,'只读'):self.review.get('confirmed',identity).save(answer)
        for name,content in originals.items():self.assertEqual((target/name).read_bytes(),content)
    def test_invalid_pending_files_disable_server_side_confirmation(self):
        identity,folder=self.create(pages=1)
        valid={'预期':{'第01页.png':{'puzzle_locations':[3,2,1,4]}}}
        item=self.review.get('pending',identity);self.assertTrue(item.data['annotatable'])
        # A direct POST after external draft corruption must also be refused.
        (folder/'草稿.json').write_text('{broken json',encoding='utf-8')
        with self.assertRaises(HTTPError) as failure:self.post(identity,valid,item.token)
        self.assertEqual(failure.exception.code,400);self.assertFalse(item.data['annotatable'])
        self.assertFalse((folder/'答案.json').exists());self.assertFalse((folder/'审核.md').exists())
        result=self.get(identity)
        self.assertFalse(result['annotatable']);self.assertEqual(result['initial'],{'预期':{}})
        self.assertIn('草稿.json',result['limitation']);self.assertTrue(folder.exists())
        # Invalid suggestions at first load must preserve the same read-only fallback.
        other_identity,other_folder=self.create('抓鬼',pages=1)
        (other_folder/'建议.json').write_text(json.dumps({'说明':'仅说明'}),encoding='utf-8')
        other=self.get(other_identity);self.assertFalse(other['annotatable'])
        self.assertEqual(other['initial'],{'预期':{}});self.assertIn('建议.json',other['limitation'])
        with self.assertRaises(HTTPError) as failure:
            self.post(other_identity,{'预期':{'第01页.png':{'puzzle_order':'CBAD'}}},other['token'])
        self.assertEqual(failure.exception.code,400);self.assertTrue(other_folder.exists())

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

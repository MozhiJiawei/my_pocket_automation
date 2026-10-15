"""Shared production search preserves first-match behavior and enumerates icons."""
import unittest
import weakref
import gc
import numpy as np
from tests.support.lua_runtime import Runtime
from tests.support.touchsprite_adapter import Screen

class FindItemsTest(unittest.TestCase):
    def test_shimen_defaults_to_two_answers_across_pages(self):
        runtime=Runtime(Screen(np.zeros((1600,900,3),dtype=np.uint8)))
        runtime.lua.execute("""
            local visible=true
            local taps,page=0,1
            package.preload['common.detector']=function() return {
                present=function(f) return f.title and visible or false end} end
            package.preload['tasks.shimen.assets.questions']=function() return {
                title={title=true},topics={}} end
            package.preload['tasks.shimen.assets.catalog']=function() return {
                test=function() return {} end} end
            package.preload['common.find_items']=function() return {
                scan=function(features,title,expired,all,limit)
                    assert(all and limit==3-page)
                    return {{x=100,y=700,feature={region={100,700,100,700}}}}
                end} end
            package.preload['common.device']=function() return {
                tap=function() taps=taps+1;visible=taps<2;return true end,
                swipe=function(ctx,title,label,from,to,options)
                    assert(taps==1 and visible and options==nil)
                    page=page+1;return true
                end,
                wait=function(predicate)
                    assert(taps==2);return predicate()
                end
            } end
        """)
        module=runtime.require('tasks.shimen.find')
        module.identify=runtime.lua.eval("function() return 'test' end")
        ok,reason=module.solve(runtime.lua.eval('{config={}}'))
        self.assertTrue(ok)
        self.assertEqual(reason,'find_completed')
        runtime.close()

    def test_shimen_early_exit_cannot_complete_two_answer_task(self):
        runtime=Runtime(Screen(np.zeros((1600,900,3),dtype=np.uint8)))
        runtime.lua.execute("""
            local visible=true
            package.preload['common.detector']=function() return {
                present=function(f) return f.title and visible or false end} end
            package.preload['tasks.shimen.assets.questions']=function() return {
                title={title=true},topics={}} end
            package.preload['tasks.shimen.assets.catalog']=function() return {
                test=function() return {} end} end
            package.preload['common.find_items']=function() return {
                scan=function(features,title,expired,all,limit)
                    assert(all and limit==2)
                    return {{x=100,y=700,feature={region={100,700,100,700}}}}
                end} end
            package.preload['common.device']=function() return {
                tap=function(ctx,f)
                    assert(f.region[1]==96 and f.region[3]==104)
                    visible=false; return true
                end,
                wait=function() error('Incomplete exit must not wait for success') end
            } end
        """)
        module=runtime.require('tasks.shimen.find')
        module.identify=runtime.lua.eval("function() return 'test' end")
        ok,reason=module.solve(runtime.lua.eval('{config={shimen_needed=2}}'))
        self.assertFalse(ok)
        self.assertEqual(reason,'find_incomplete_exit')
        runtime.close()

    def test_shimen_device_step_refuses_unrecognized_page(self):
        runtime=Runtime(Screen(np.zeros((1600,900,3),dtype=np.uint8)),planning=True)
        runtime.lua.execute("package.preload['progress']=function() return {read=function() return nil end} end")
        outcome=runtime.require('tasks.shimen.task').run(runtime.lua.eval('{config={step="advance"},account={alias="current"}}'))
        self.assertEqual(outcome['status'],'blocked')
        self.assertEqual(outcome['reason'],'shimen_task_page_not_verified')
        self.assertEqual(runtime.actions,[])
        runtime.close()
    def test_closed_runtime_releases_its_frame(self):
        frame=np.zeros((1600,900,3),dtype=np.uint8)
        reference=weakref.ref(frame)
        runtime=Runtime(Screen(frame))
        runtime.question('shimen')
        runtime.close()
        del runtime,frame
        gc.collect()
        self.assertIsNone(reference())

    def test_first_all_and_capture_release(self):
        frame=np.zeros((1600,900,3),dtype=np.uint8)
        frame[450,50]=[255,255,255]
        for x,y in [(100,700),(400,1000)]:frame[y,x]=[10,30,210]
        runtime=Runtime(Screen(frame));held=[];runtime.lua.globals().keepScreen=lambda value:held.append(value)
        feature=runtime.lua.eval('{width=900,height=1600,base=0xd21e0a,offsets="1|0|0x000000",region={65,535,829,1410},tap_offset={0,0}}')
        title=runtime.lua.eval('{width=900,height=1600,base=0xffffff,offsets="1|0|0x000000",region={50,450,50,450}}')
        matcher=runtime.require('common.find_items');features=runtime.lua.table_from([feature])
        first,reason=matcher.scan(features,title,None,False)
        self.assertIsNone(reason);self.assertEqual(first['base'],feature['base'])
        points,reason=matcher.scan(features,title,None,True)
        self.assertIsNone(reason);self.assertEqual({(p['x'],p['y']) for p in points.values()},{(100,700),(400,1000)})
        for point in points.values():
            self.assertEqual(list(point['feature']['region'].values()),[point['x'],point['y'],point['x'],point['y']])
        limited,reason=matcher.scan(features,title,None,True,1)
        self.assertIsNone(reason)
        self.assertEqual(len(limited),1)
        frame[450,50]=0
        runtime.screen=Screen(frame)
        result,reason=matcher.scan(features,title,None,True)
        self.assertIsNone(result);self.assertEqual(reason,'find_page_changed')
        self.assertEqual(held,[True,False]*4)

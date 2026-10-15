"""Actual solver releases its held frame on every exit before sending actions."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


class FindFrameGuardTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            held=false; captures=0; actions=0; swipes=0; shots={}; logs={}
            fail_search=false; page_disappears=false; timeout=false; state='find'
            function keepScreen(value)
                held=value
                if value then captures=captures+1 end
            end
            local title={title=true}; local expired={expired=true}
            package.preload['tasks.zhuagui.assets.find_title']=function() return title end
            package.preload['tasks.zhuagui.assets.find_time_expired']=function() return expired end
            package.preload['common.detector']=function() return {present=function(feature)
                if feature.title then return held or not page_disappears end
                if feature.expired then return timeout end
                assert(held,'search features must share the held frame')
                if fail_search then error('native_match_failure') end
                return feature.rotation==3 and feature.mirror==true and (not match_after_swipe or swipes>0)
            end} end
            package.preload['common.device']=function() return {
                tap=function() assert(not held,'no action on held frame'); actions=actions+1; return true end,
                swipe=function()
                    assert(not held); swipes=swipes+1
                    if expire_on_scroll then state='retry';return false end
                    return true
                end,
                wait=function() return true end
            } end
            package.preload['dfx.log']=function() return {write=function(c,event,detail) logs[event]=detail end} end
            package.preload['dfx.snapshot']=function() return {capture=function(c,label)
                assert(not held);table.insert(shots,label)
            end} end
            package.preload['tasks.zhuagui.pages']=function() return {
                state=function() return state end,features={find_title=title}
            } end
            package.preload['tasks.zhuagui.legacy']=function() return {items=function() return {} end} end
            package.preload['tasks.zhuagui.assets.catalog']=function()
                local features={}
                for _,mirror in ipairs({false,true}) do
                    for turn=0,3 do features[#features+1]={rotation=turn,mirror=mirror} end
                end
                return {wine=features,['酒']=features}
            end
            solver=require('tasks.zhuagui.find')
            solver.identify=function() return 'wine','wine' end
        ''')

    def test_many_signatures_use_one_frame_and_release_before_click(self):
        result=self.lua.execute('return solver.solve({})')
        self.assertEqual(result,(True,'find_clicked'))
        self.assertEqual(self.lua.globals().captures,1)
        self.assertEqual(self.lua.globals().actions,1)
        self.assertFalse(self.lua.globals().held)

    def test_native_error_releases_frame_and_sends_no_action(self):
        ok,error=self.lua.execute('fail_search=true; return pcall(solver.solve,{})')
        self.assertFalse(ok)
        self.assertIn('native_match_failure',error)
        self.assertFalse(self.lua.globals().held)
        self.assertEqual(self.lua.globals().actions,0)

    def test_page_change_after_release_blocks_click(self):
        result=self.lua.execute('page_disappears=true; return solver.solve({})')
        self.assertEqual(result[:2],(False,'find_page_changed'))
        self.assertFalse(self.lua.globals().held)
        self.assertEqual(self.lua.globals().actions,0)

    def test_expired_question_releases_frame_and_blocks_click(self):
        result=self.lua.execute('timeout=true; return solver.solve({})')
        self.assertEqual(result[:2],(False,'find_time_expired'))
        self.assertFalse(self.lua.globals().held)
        self.assertEqual(self.lua.globals().actions,0)

    def test_named_wine_without_approved_bank_collects_instead_of_matching_generic_wine(self):
        self.lua.execute("solver.identify=function() return 'tiger_wine','酒' end")
        self.assertEqual(self.lua.execute('return solver.solve({})'),
                         (False,'find_target_requires_calibration','酒'))
        self.assertEqual(self.lua.globals().captures,0)
        self.assertEqual(self.lua.globals().actions,0)
        self.assertEqual(self.lua.globals().swipes,6)
        self.assertEqual(list(self.lua.globals().shots.values()),
                         [f'find_unmatched_p{i:02}' for i in range(1,8)])
        self.assertIn('matching_started=false',self.lua.globals().logs.find_collection)
        self.assertIn('target=tiger_wine',self.lua.globals().logs.find_collection)

    def test_approved_named_wine_enters_matcher_and_scrolls_after_a_miss(self):
        self.lua.execute("""
            local bank=require('tasks.zhuagui.assets.catalog')
            bank.tiger_wine=bank.wine;bank['酒']=nil;bank.wine=nil
            solver.identify=function() return 'tiger_wine','酒' end
            match_after_swipe=true
        """)
        self.assertEqual(self.lua.execute('return solver.solve({})'),(True,'find_clicked'))
        self.assertEqual(self.lua.globals().captures,2)
        self.assertEqual(self.lua.globals().swipes,1)
        self.assertEqual(self.lua.globals().actions,1)
        self.assertIn('target=tiger_wine',self.lua.globals().logs.find_search)

    def test_unknown_target_uses_the_same_candidate_collector(self):
        self.lua.execute('solver.identify=function() return nil end')
        self.assertEqual(self.lua.execute('return solver.solve({})'),(False,'find_target_unknown',None))
        self.assertEqual(self.lua.globals().swipes,6)
        self.assertEqual(self.lua.globals().actions,0)

    def test_collection_page_expiry_stops_without_retry_or_candidate_click(self):
        self.lua.execute("solver.identify=function() return 'tiger_wine','酒' end;expire_on_scroll=true")
        self.assertEqual(self.lua.execute('return solver.solve({})'),(False,'catalog_page_changed','酒'))
        self.assertEqual(self.lua.globals().swipes,1)
        self.assertEqual(self.lua.globals().actions,0)
        self.assertEqual(list(self.lua.globals().shots.values()),['find_unmatched_p01','find_unmatched_incomplete'])

    def test_find_page_missing_does_not_start_collection(self):
        self.lua.execute("solver.identify=function() return nil,nil,'not_find_page' end")
        self.assertEqual(self.lua.execute('return solver.solve({})'),(False,'not_find_page'))
        self.assertEqual(self.lua.globals().swipes,0)
        self.assertEqual(len(self.lua.globals().shots),0)

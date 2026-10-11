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
            held=false; captures=0; actions=0; fail_search=false; page_disappears=false; timeout=false
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
                return feature.rotation==3 and feature.mirror==true
            end} end
            package.preload['common.device']=function() return {
                tap=function() assert(not held,'no action on held frame'); actions=actions+1; return true end,
                swipe=function() assert(not held); return false end,
                wait=function() return true end
            } end
            package.preload['dfx.log']=function() return {write=function() end} end
            package.preload['dfx.snapshot']=function() return {capture=function() assert(not held) end} end
            package.preload['tasks.zhuagui.legacy']=function() return {items=function() return {} end} end
            package.preload['tasks.zhuagui.assets.catalog']=function()
                local features={}
                for _,mirror in ipairs({false,true}) do
                    for turn=0,3 do features[#features+1]={rotation=turn,mirror=mirror} end
                end
                return {wine=features}
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

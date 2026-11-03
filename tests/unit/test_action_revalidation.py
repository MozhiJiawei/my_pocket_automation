"""UI transitions during evidence capture must not leave stale actions."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]

class ActionRevalidationTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            captures=0; actions=0; vanished=false; unavailable=false; clicked=nil; tap_options=nil
            package.preload['common.detector']=function() return {
                find=function() if unavailable or (captures>0 and vanished) then return nil end
                    return {x=captures>0 and 40 or 10,y=20} end,
                present=function() return captures==0 or not vanished end
            } end
            package.preload['dfx.snapshot']=function() return {capture=function() captures=captures+1 end} end
            package.preload['dfx.log']=function() return {write=function() end} end
            mSleep=function() end
            tap=function(x,y,options) actions=actions+1; clicked={x,y};tap_options=options end
            touchDown=function() actions=actions+1 end
            touchMove=function() end; touchUp=function() end
            feature={tap_offset={2,3}}
        ''')
        self.device=self.lua.eval("require('common.device')")[0]

    def test_target_disappears_during_screenshot_no_tap(self):
        self.lua.execute('vanished=true')
        self.assertFalse(self.device.tap(self.lua.table(),self.lua.globals().feature,'test'))
        self.assertEqual(self.lua.globals().actions,0)

    def test_missing_target_never_captures_or_sends_native_input(self):
        self.lua.execute('unavailable=true')
        self.assertFalse(self.device.tap(self.lua.table(),self.lua.globals().feature,'test'))
        self.assertEqual(self.lua.globals().captures,0)
        self.assertEqual(self.lua.globals().actions,0)

    def test_moved_target_uses_latest_coordinates(self):
        self.assertTrue(self.device.tap(self.lua.table(),self.lua.globals().feature,'test'))
        self.assertEqual(list(self.lua.globals().clicked.values()),[42,23])
        self.assertEqual(self.lua.globals().actions,1)
        self.assertEqual(dict(self.lua.globals().tap_options.items()),{'ms':50,'index':1})

    def test_initial_failed_business_guard_sends_no_native_input(self):
        guard=self.lua.eval('function() return false end')
        self.assertFalse(self.device.tap(self.lua.table(),self.lua.globals().feature,'test',guard))
        self.assertEqual(self.lua.globals().captures,0)
        self.assertEqual(self.lua.globals().actions,0)

    def test_business_precondition_changes_during_capture_no_tap(self):
        guard=self.lua.eval('function() return captures==0 end')
        self.assertFalse(self.device.tap(self.lua.table(),self.lua.globals().feature,'test',guard))
        self.assertEqual(self.lua.globals().actions,0)

    def test_page_changes_during_screenshot_no_swipe(self):
        self.lua.execute('vanished=true')
        self.assertFalse(self.device.swipe(self.lua.table(),self.lua.globals().feature,'test',self.lua.table_from([1,2]),self.lua.table_from([3,4])))
        self.assertEqual(self.lua.globals().actions,0)

if __name__=='__main__': unittest.main()

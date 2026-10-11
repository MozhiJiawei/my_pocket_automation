"""Selected/unselected appearances retain their own click geometry."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]

class DetectorVariantTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            getScreenSize=function() return 900,1600 end
            hits={}; taps={}; mSleep=function() end
            findMultiColorInRegionFuzzy=function(base)
                local hit=hits[base]; if hit then return hit[1],hit[2] end;return -1,-1
            end
            tap=function(x,y) taps[#taps+1]={x,y} end
            package.preload['dfx.log']=function() return {write=function() end} end
            package.preload['dfx.snapshot']=function() return {capture=function() end} end
            primary={width=900,height=1600,base=1,offsets='',region={0,0,900,1600},tap_offset={5,10}}
            variant={width=900,height=1600,base=2,offsets='',region={0,0,900,1600},tap_offset={-50,-90}}
            primary.variants={variant}
            detector=require('common.detector');device=require('common.device')
        ''')

    def test_primary_is_preferred_when_present(self):
        self.lua.execute('hits={[1]={200,500},[2]={700,600}}')
        self.assertEqual(self.lua.eval('detector.find(primary).x'),200)

    def test_alternative_recognizes_other_appearance_and_uses_its_offset(self):
        self.lua.execute('hits={[2]={700,600}}')
        self.assertTrue(self.lua.eval("device.tap({},primary,'select')"))
        self.assertEqual((self.lua.globals().taps[1][1],self.lua.globals().taps[1][2]),(650,510))

    def test_unknown_appearance_never_clicks(self):
        self.assertFalse(self.lua.eval("device.tap({},primary,'select')"))
        self.assertEqual(len(self.lua.globals().taps),0)

    def test_resolution_mismatch_cannot_use_variant(self):
        self.lua.execute('hits={[2]={700,600}};primary.width=1600')
        self.assertIsNone(self.lua.eval('detector.find(primary)'))

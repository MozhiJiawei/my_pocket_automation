"""Exercise the shared production scanner with bounded scrolling and frame changes."""
from pathlib import Path
import unittest

from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]


class ListNavigationTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute('''
            position=3; lower=0; upper=6; target=1; valid=true
            frozen=false; frames=0; reads=0; taps=0; clock=0; swipes={}; logs={}
            keepScreen=function(value) frozen=value;if value then frames=frames+1 end end
            getColor=function() assert(frozen);return (position+200)*0x001010 end
            mSleep=function(ms) clock=clock+ms end
            package.preload['dfx.log']=function() return {write=function(c,kind,detail)
                logs[#logs+1]={kind=kind,detail=detail} end} end
            package.preload['dfx.snapshot']=function() return {capture=function() end} end
            package.preload['common.device']=function() return {
                swipe=function(c,feature,label,from,to,options)
                    assert(feature=='list' and options.settle_ms==350)
                    local forward=from[1]>to[1] or from[2]>to[2]
                    position=math.max(lower,math.min(upper,position+(forward and 1 or -1)))
                    swipes[#swipes+1]={from=from,to=to,forward=forward}
                    return true
                end,
                tap=function(c,feature,label,guard)
                    if invalidate_on_tap then valid=false end
                    if guard and not guard() then return false end
                    taps=taps+1;return true
                end
            } end
            spec={name='test',page='list',valid=function() return valid end,
                inspect=function()
                    reads=reads+1
                    if position==target then return {kind='target',feature='target'} end
                end}
            ctx={}
        ''')
        self.module=self.lua.eval("require('common.list_navigation')")[0]

    def find(self):
        value=self.module.find(self.lua.globals().ctx,self.lua.globals().spec)
        return value if isinstance(value,tuple) else (value,None)

    def test_retained_position_searches_both_directions(self):
        match,reason=self.find()
        self.assertIsNone(reason)
        self.assertEqual(match['kind'],'target')
        self.assertEqual(self.lua.globals().position,1)
        directions=[entry['forward'] for entry in self.lua.globals().swipes.values()]
        self.assertIn(True,directions)
        self.assertIn(False,directions)
        self.assertEqual(self.lua.globals().taps,0)

    def test_boundary_and_missing_target_never_infer_completion(self):
        self.lua.execute('target=100')
        self.assertEqual(self.find(),(None,'target_not_found'))
        self.assertLessEqual(len(self.lua.globals().swipes),24)
        self.assertEqual(self.lua.globals().taps,0)
        self.assertEqual(self.lua.globals().position,0)
        self.assertEqual(sum(log['kind']=='list_boundary' for log in self.lua.globals().logs.values()),2)

    def test_list_without_a_boundary_stops_at_shared_limit(self):
        self.lua.execute('target=200;lower=-100;upper=100')
        self.assertEqual(self.find(),(None,'target_not_found'))
        self.assertEqual(len(self.lua.globals().swipes),24)

    def test_drag_in_a_gap_retries_a_distinct_start_before_declaring_boundary(self):
        self.lua.execute('''
            target=4
            local original=require('common.device').swipe
            require('common.device').swipe=function(c,feature,label,from,to,options)
                if #swipes==0 then
                    swipes[#swipes+1]={from=from,to=to,forward=true};return true
                end
                return original(c,feature,label,from,to,options)
            end
        ''')
        match,reason=self.find()
        self.assertIsNone(reason)
        self.assertEqual(match['kind'],'target')
        self.assertEqual(len(self.lua.globals().swipes),2)
        first,second=list(self.lua.globals().swipes.values())
        self.assertNotEqual(first['from'][2],second['from'][2])

    def test_horizontal_list_uses_the_same_search_and_footer(self):
        self.lua.execute("spec.axis='horizontal';spec.view={15,1140,870,1260}")
        match,reason=self.find()
        self.assertIsNone(reason)
        self.assertEqual(match['kind'],'target')
        for swipe in self.lua.globals().swipes.values():
            self.assertEqual(swipe['from'][2],1200)
            self.assertEqual(swipe['to'][2],1200)

    def test_repeating_carousel_stops_in_both_directions(self):
        self.lua.execute('''
            target=100;position=0
            require('common.device').swipe=function(c,feature,label,from,to,options)
                local forward=from[1]>to[1] or from[2]>to[2]
                position=(position+(forward and 1 or -1))%3
                swipes[#swipes+1]={forward=forward};return true
            end
        ''')
        self.assertEqual(self.find(),(None,'target_not_found'))
        self.assertEqual(len(self.lua.globals().swipes),6)

    def test_unstable_frames_do_not_probe_or_send_input(self):
        self.lua.execute('getColor=function() return frames*0x001010 end')
        self.assertEqual(self.find(),(None,'list_not_stable'))
        self.assertEqual(self.lua.globals().reads,0)
        self.assertEqual(len(self.lua.globals().swipes),0)
        self.assertFalse(self.lua.globals().frozen)

    def test_page_change_during_stabilization_stops(self):
        self.lua.execute('mSleep=function() valid=false end')
        self.assertEqual(self.find(),(None,'list_changed'))
        self.assertEqual(self.lua.globals().reads,0)
        self.assertEqual(len(self.lua.globals().swipes),0)

    def test_page_change_after_swipe_stops_without_more_input(self):
        self.lua.execute('''
            require('common.device').swipe=function()
                swipes[#swipes+1]={};valid=false;return true
            end
        ''')
        self.assertEqual(self.find(),(None,'list_changed'))
        self.assertEqual(len(self.lua.globals().swipes),1)

    def test_target_is_rechecked_at_activation(self):
        match,_=self.find()
        self.lua.execute('invalidate_on_tap=true')
        self.assertFalse(self.module.activate(self.lua.globals().ctx,self.lua.globals().spec,match,'open'))
        self.assertEqual(self.lua.globals().taps,0)

    def test_completion_appearing_before_activation_prevents_entry_click(self):
        match,_=self.find()
        self.lua.execute("spec.inspect=function() return {kind='completed'} end")
        self.assertFalse(self.module.activate(self.lua.globals().ctx,self.lua.globals().spec,match,'open'))
        self.assertEqual(self.lua.globals().taps,0)

    def test_sampling_failure_releases_the_frozen_screen(self):
        self.lua.execute("getColor=function() error('pixel_failure') end")
        with self.assertRaisesRegex(Exception,'pixel_failure'):
            self.find()
        self.assertFalse(self.lua.globals().frozen)
